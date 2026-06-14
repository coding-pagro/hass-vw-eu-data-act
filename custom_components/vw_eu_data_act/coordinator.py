"""Coordinator: dynamic-interval refresh of the latest dataset."""

from __future__ import annotations

import logging
import asyncio
from datetime import datetime, timedelta, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ApiError, AuthError, EudaApiClient
from .const import (
    CONF_IDENTIFIER,
    CONF_VIN,
    DATASET_INTERVAL,
    DOMAIN,
    MAX_BACKFILL,
    MAX_DATASET_INTERVAL,
    MIN_DATASET_INTERVAL,
    MIN_INTERVAL,
    NO_CONTENT_SUFFIX,
    POST_DATASET_BUFFER,
    RETRY_INTERVAL,
)
from .data import Dataset, DataPoint, merge_points

_LOGGER = logging.getLogger(__name__)

# Transient upstream errors worth retrying / keeping previous data for.
_SERVER_ERROR_CODES = frozenset({500, 502, 503, 504})


def _is_server_error(err: Exception) -> bool:
    """True for transient upstream 5xx failures (carried on ApiError.status)."""
    return getattr(err, "status", None) in _SERVER_ERROR_CODES


def _filename_timestamp(name: str) -> datetime | None:
    """Parse a YYYYMMDDhhmmss segment from a dataset filename.

    Handles both layouts seen in the wild ("TIMESTAMP_VIN.zip" and
    "VIN_TIMESTAMP.zip") by scanning the underscore-separated parts
    right-to-left for the first one that parses as a timestamp.
    """
    stem = name.rsplit(".", 1)[0]
    for part in reversed(stem.split("_")):
        try:
            return datetime.strptime(part, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _infer_dataset_interval(timestamps: list[datetime]) -> timedelta:
    """Infer the dataset cadence from the listed drops' createdOn spacing.

    The portal lets the user choose the delivery frequency of their continuous
    data request, so a hardcoded interval is wrong for anyone not on the
    default: with e.g. an hourly cadence the next dataset would look "overdue"
    right after every drop, degrading to 1-minute retry polling for ~45 min of
    every hour. The median gap between consecutive drops is robust against a
    single outlier (portal hiccup, duplicated timestamp) and is clamped to
    [MIN_DATASET_INTERVAL, MAX_DATASET_INTERVAL].
    """
    if len(timestamps) < 3:
        return DATASET_INTERVAL  # too few drops to infer; assume the default
    ts = sorted(timestamps)
    deltas = sorted(b - a for a, b in zip(ts, ts[1:]) if b > a)
    if not deltas:
        return DATASET_INTERVAL
    median = deltas[len(deltas) // 2]
    return min(max(median, MIN_DATASET_INTERVAL), MAX_DATASET_INTERVAL)


def _created_on(entry: dict) -> datetime | None:
    raw = entry.get("createdOn")
    if not raw:
        return _filename_timestamp(entry.get("name", ""))
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return _filename_timestamp(entry.get("name", ""))


class EudaCoordinator(DataUpdateCoordinator[dict[str, DataPoint]]):
    """Fetches the latest dataset and reschedules adaptively."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: EudaApiClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            # Pass the entry explicitly; relying on the ContextVar is deprecated
            # and breaks in HA 2026.8.
            config_entry=entry,
            name=f"{DOMAIN} {entry.data[CONF_VIN]}",
            update_interval=RETRY_INTERVAL,
        )
        self.entry = entry
        self.client = client
        self.vin: str = entry.data[CONF_VIN]
        self.identifier: str = entry.data[CONF_IDENTIFIER]
        self.latest_dataset: Dataset | None = None
        # Untouched JSON of the most recently downloaded dataset, kept solely
        # for diagnostics: from_json discards per-item fields (message_id, the
        # per-snapshot car_captured_time grouping) that are needed to reason
        # about duplicate-slot freshness. Memory-only; never persisted.
        self.latest_raw: dict | None = None
        # createdOn of the newest successfully downloaded dataset (portal-side
        # freshness, as opposed to Dataset.captured_at = car-side freshness).
        self.dataset_created_at: datetime | None = None
        self._is_initial_setup: bool = True

    async def _async_update_data(self) -> dict[str, DataPoint]:
        listing = await self._async_list_with_refresh()

        # content datasets, oldest -> newest by createdOn
        content = sorted(
            (
                e
                for e in listing
                if e.get("name") and not e["name"].endswith(NO_CONTENT_SUFFIX)
            ),
            key=lambda e: _created_on(e) or datetime.min.replace(tzinfo=timezone.utc),
        )
        _LOGGER.debug("refresh: %d listed, %d with content", len(listing), len(content))

        if not content:
            self._reschedule(listing)
            if self.data:
                # Subsequent refresh: keep previous data
                _LOGGER.debug("No new datasets available, keeping previous data")
                return self.data
            # First load with no data: fail so HA retries setup
            _LOGGER.warning(
                "No datasets available on first load, will retry in %s", RETRY_INTERVAL
            )
            raise UpdateFailed("No datasets available on first load")

        # High-water mark: only download datasets newer than the newest one
        # already merged (dataset_created_at doubles as the mark; it lives in
        # memory only, so the first refresh after a restart seeds from the
        # newest MAX_BACKFILL datasets for fuller entity coverage at setup).
        if self.dataset_created_at is not None and self.data:
            pending = [
                e
                for e in content
                if (ts := _created_on(e)) and ts > self.dataset_created_at
            ]
        else:
            pending = content[-MAX_BACKFILL:]

        if not pending:
            # Nothing new since the last merge: skip the downloads entirely
            # instead of re-fetching a dataset we already processed.
            _LOGGER.debug("No datasets newer than %s", self.dataset_created_at)
            self._reschedule(listing)
            return self.data

        # Download all pending datasets oldest -> newest, merging each one;
        # the timestamp-aware merge guarantees a point never overwrites a
        # strictly newer one. A dataset that keeps failing is skipped (it is
        # retried until a newer dataset succeeds and moves the mark past it).
        merged: dict[str, DataPoint] = dict(self.data) if self.data else {}
        last_error: ApiError | None = None
        success = False

        for dataset_entry in pending:
            # Use fewer, faster retries during initial setup for better UX
            # Full retries kick in after first successful load
            max_retries = 3 if self._is_initial_setup else 5
            retry_delay = 3 if self._is_initial_setup else 5

            for attempt in range(max_retries):
                try:
                    payload = await self.client.async_download_dataset(
                        self.vin, self.identifier, dataset_entry["name"]
                    )
                except AuthError as err:
                    raise ConfigEntryAuthFailed(str(err)) from err
                except ApiError as err:
                    last_error = err
                    if _is_server_error(err) and attempt < max_retries - 1:
                        _LOGGER.debug(
                            "Server error downloading %s (attempt %d/%d): %s, retrying in %ds",
                            dataset_entry["name"],
                            attempt + 1,
                            max_retries,
                            err,
                            retry_delay,
                        )
                        await asyncio.sleep(retry_delay)
                        continue
                    _LOGGER.debug(
                        "Giving up on %s: %s", dataset_entry["name"], err
                    )
                    break
                else:
                    self.latest_raw = payload
                    self.latest_dataset = Dataset.from_json(payload)
                    merged = merge_points(merged, self.latest_dataset.points)
                    # max() keeps the mark monotonic even if the portal lists
                    # entries out of order.
                    created = _created_on(dataset_entry)
                    if created and (
                        self.dataset_created_at is None
                        or created > self.dataset_created_at
                    ):
                        self.dataset_created_at = created
                    self._is_initial_setup = False
                    success = True
                    break

        if success and last_error is None:
            self._reschedule(listing)
            return merged

        if success:
            # Partial catch-up: some datasets merged, the rest still pending.
            # Retry soon rather than waiting a full cadence for the missing one.
            self.update_interval = RETRY_INTERVAL
            return merged

        # Nothing downloaded at all
        self.update_interval = RETRY_INTERVAL
        if self.data:
            _LOGGER.debug(
                "Could not download any dataset (last error: %s), keeping previous data",
                last_error,
            )
            return self.data
        # First load failure: raise so HA retries setup
        _LOGGER.error(
            "Could not download any dataset on first load: %s. Will retry in %s.",
            last_error,
            RETRY_INTERVAL,
        )
        raise UpdateFailed(
            f"Failed to download dataset on first load: {last_error}"
        ) from last_error

    async def _async_list_with_refresh(self) -> list[dict]:
        """List datasets, self-healing a stale identifier once if needed.

        If the user deletes and recreates the continuous data subscription on
        the portal, the backend assigns a new identifier and the stored one
        stops working (the list errors or returns no files). Re-fetch the
        identifier from the metadata endpoint and retry once before giving up —
        so it recovers on the next cycle without needing a manual reload.
        """
        # Use fewer, faster retries during initial setup
        max_retries = 3 if self._is_initial_setup else 5
        retry_delay = 3 if self._is_initial_setup else 5

        for identifier_retry in (False, True):
            last_error = None

            for attempt in range(max_retries):
                try:
                    listing = await self.client.async_list_datasets(
                        self.vin, self.identifier
                    )
                    # Empty listing might mean subscription was recreated
                    if (
                        not listing
                        and not identifier_retry
                        and await self._refresh_identifier()
                    ):
                        _LOGGER.info(
                            "Empty listing, retrying with refreshed identifier"
                        )
                        break  # Break inner loop to retry with new identifier
                    return listing

                except AuthError as err:
                    raise ConfigEntryAuthFailed(str(err)) from err

                except ApiError as err:
                    last_error = err
                    is_server_error = _is_server_error(err)

                    # 4xx etc. won't change on an immediate retry; only
                    # transient 5xx are worth hammering the endpoint for.
                    if not is_server_error:
                        break

                    # Retry server errors with delay
                    if attempt < max_retries - 1:
                        _LOGGER.debug(
                            "Server error listing datasets (attempt %d/%d): %s, retrying in %ds",
                            attempt + 1,
                            max_retries,
                            err,
                            retry_delay,
                        )
                        await asyncio.sleep(retry_delay)
                        continue

            # After all retries, try refreshing identifier once if not already tried
            if last_error and not identifier_retry and await self._refresh_identifier():
                _LOGGER.info("Retrying list with refreshed identifier after failures")
                continue

            # All attempts failed
            if last_error:
                self.update_interval = RETRY_INTERVAL

                # HTTP 400 special case
                if getattr(last_error, "status", None) == 400:
                    raise UpdateFailed(
                        "Data delivery not ready yet (HTTP 400). If you just enabled "
                        "the continuous data request on the portal, it can take a few "
                        "hours to start; will keep retrying."
                    ) from last_error

                # Server errors with existing data - return empty to keep old data
                if _is_server_error(last_error) and self.data:
                    _LOGGER.error(
                        "Failed to list datasets after %d attempts: %s. Keeping previous data.",
                        max_retries,
                        last_error,
                    )
                    return []

                # Other errors or first load: raise UpdateFailed
                raise UpdateFailed(str(last_error)) from last_error

        return []

    async def _refresh_identifier(self) -> bool:
        """Re-fetch the data-request identifier; persist it if it changed.

        Returns True (and updates the config entry) when the portal has handed
        out a new identifier, e.g. after the subscription was recreated.
        """
        try:
            meta = await self.client.async_get_metadata(self.vin)
        except ApiError as err:
            _LOGGER.debug("Could not refresh data-request identifier: %s", err)
            return False
        new_id = meta.get("Identifier") or meta.get("identifier")
        if not new_id or new_id == self.identifier:
            return False
        _LOGGER.warning(
            "Data-request identifier changed (%s -> %s); the portal subscription "
            "was likely recreated. Updating the config entry.",
            self.identifier,
            new_id,
        )
        self.identifier = new_id
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, CONF_IDENTIFIER: new_id}
        )
        return True

    def _reschedule(self, listing: list[dict]) -> None:
        """Schedule the next poll shortly after the next expected dataset drop.

        The drop cadence is inferred from the listing (the portal lets users
        pick the delivery frequency). If the expected time has already passed
        (a new dataset is due but not yet present), poll every minute until it
        appears.
        """
        timestamps = [ts for e in listing if (ts := _created_on(e))]
        newest = max(timestamps) if timestamps else None
        if newest:
            interval = _infer_dataset_interval(timestamps)
            target = newest + interval + POST_DATASET_BUFFER
            delta = target - dt_util.utcnow()
            if delta > MIN_INTERVAL:
                self.update_interval = delta
                _LOGGER.debug(
                    "Next refresh in %s (cadence %s, newest %s)",
                    delta,
                    interval,
                    newest,
                )
                return
        # newest dataset is overdue (or unknown) -> short retry for the next drop
        self.update_interval = RETRY_INTERVAL
        _LOGGER.debug("Next dataset overdue; retrying in %s", RETRY_INTERVAL)
