"""Coordinator tests: authentication failures surface as ConfigEntryAuthFailed.

An expired/invalid login must trigger Home Assistant's reauth flow, not be
swallowed as a transient polling error. AuthError is a subclass of ApiError, so
the coordinator has to catch it *before* the generic ApiError handling in both
the dataset-listing and dataset-download paths.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vw_eu_data_act.api import ApiError, AuthError
from custom_components.vw_eu_data_act.const import (
    CONF_IDENTIFIER,
    CONF_VIN,
    DATASET_INTERVAL,
    DOMAIN,
    MAX_DATASET_INTERVAL,
    MIN_DATASET_INTERVAL,
    RETRY_INTERVAL,
)
from custom_components.vw_eu_data_act.coordinator import (
    EudaCoordinator,
    _infer_dataset_interval,
)


def _make_coordinator(hass, client) -> EudaCoordinator:
    """Build a coordinator the way async_setup_entry does."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_VIN: "WVWZZZTESTVIN0001", CONF_IDENTIFIER: "ident-1"},
        unique_id="WVWZZZTESTVIN0001",
    )
    entry.add_to_hass(hass)
    return EudaCoordinator(hass, entry, client)


async def test_auth_error_while_listing_raises_reauth(hass) -> None:
    client = MagicMock()
    client.async_list_datasets = AsyncMock(side_effect=AuthError("invalid token"))
    coordinator = _make_coordinator(hass, client)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_auth_error_while_downloading_raises_reauth(hass) -> None:
    # Listing succeeds, but the download leg hits an expired session. Because
    # AuthError subclasses ApiError, this previously fell into the retry/skip
    # branch instead of triggering reauth.
    client = MagicMock()
    client.async_list_datasets = AsyncMock(
        return_value=[
            {"name": "WVWZZZTESTVIN0001_20260101000000.zip", "createdOn": "2026-01-01T00:00:00Z"}
        ]
    )
    client.async_download_dataset = AsyncMock(side_effect=AuthError("session expired"))
    coordinator = _make_coordinator(hass, client)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


def _times(start: datetime, step: timedelta, count: int) -> list[datetime]:
    return [start + i * step for i in range(count)]


def test_infer_interval_median_of_gaps() -> None:
    # Hourly drops with one outlier gap (a skipped delivery): the median must
    # stay at one hour rather than being dragged up by the outlier.
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    ts = _times(base, timedelta(hours=1), 5)
    ts.append(ts[-1] + timedelta(hours=4))  # outlier
    assert _infer_dataset_interval(ts) == timedelta(hours=1)


def test_infer_interval_fallback_when_too_few() -> None:
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert _infer_dataset_interval([]) == DATASET_INTERVAL
    assert _infer_dataset_interval([base, base + timedelta(hours=1)]) == DATASET_INTERVAL
    # all-identical timestamps leave no positive gaps to infer from
    assert _infer_dataset_interval([base, base, base]) == DATASET_INTERVAL


def test_infer_interval_clamped() -> None:
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    fast = _times(base, timedelta(seconds=10), 5)
    assert _infer_dataset_interval(fast) == MIN_DATASET_INTERVAL
    slow = _times(base, timedelta(days=3), 5)
    assert _infer_dataset_interval(slow) == MAX_DATASET_INTERVAL


async def test_reschedule_respects_slow_user_cadence(hass) -> None:
    # An hourly continuous request: right after a drop, the next one is ~an
    # hour away. The old hardcoded 15-min assumption made this look overdue
    # and degraded to 1-minute retry polling for most of every hour.
    coordinator = _make_coordinator(hass, MagicMock())
    now = dt_util.utcnow()
    listing = [
        {"name": f"VIN_{i}.zip", "createdOn": (now - i * timedelta(hours=1)).isoformat()}
        for i in range(5, 0, -1)  # newest is 1 h old -> next drop in ~0 min...
    ]
    # newest drop just happened
    listing.append({"name": "VIN_0.zip", "createdOn": now.isoformat()})
    coordinator._reschedule(listing)
    assert coordinator.update_interval > timedelta(minutes=45)


async def test_reschedule_overdue_uses_retry_interval(hass) -> None:
    # Newest dataset is far older than the cadence: the next drop is overdue,
    # so keep polling at the short retry interval until it appears.
    coordinator = _make_coordinator(hass, MagicMock())
    now = dt_util.utcnow()
    listing = [
        {
            "name": f"VIN_{i}.zip",
            "createdOn": (now - timedelta(hours=2) - i * timedelta(minutes=15)).isoformat(),
        }
        for i in range(5)
    ]
    coordinator._reschedule(listing)
    assert coordinator.update_interval == RETRY_INTERVAL


async def test_plain_api_error_does_not_raise_reauth(hass) -> None:
    # A generic (non-auth) failure on first load must surface as a normal
    # UpdateFailed, never as a reauth trigger. A 400 ("data delivery not ready")
    # is not retried, so this stays fast and deterministic.
    client = MagicMock()
    client.async_list_datasets = AsyncMock(side_effect=ApiError("HTTP 400", status=400))
    client.async_get_metadata = AsyncMock(side_effect=ApiError("no metadata", status=400))
    coordinator = _make_coordinator(hass, client)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
