"""Diagnostics support for the VW EU Data Act integration.

Dumps the in-memory coordinator state so the dataset structure can be inspected
WITHOUT a portal re-login. Reveals, per dataset UUID slot:
  * ``timestamp_utc`` (None or a value) -> confirms whether soc/mileage points
    carry per-item freshness,
  * every duplicate ``field_name`` slot side by side (e.g. 4x soc, 3x mileage)
    with the value ``find_by_field`` currently picks,
  * the untouched raw ``Data`` array (``latest_raw``) preserving per-item fields
    (message_id, car_captured_time, grouping) that ``Dataset.from_json`` drops.

VIN, user_id and credentials are redacted.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import EudaConfigEntry
from .const import (
    CONF_EMAIL,
    CONF_IDENTIFIER,
    CONF_NICKNAME,
    CONF_PASSWORD,
    CONF_VIN,
)
from .data import find_by_field

# Config-entry keys to redact (credentials + identifying values).
TO_REDACT = {
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_VIN,
    CONF_IDENTIFIER,
    CONF_NICKNAME,
}

# Per-item / top-level keys in the raw dataset that can carry identifying info.
RAW_REDACT = {"vin", "user_id", "userId"}


def _safe(fn):
    """Never let a property error abort the whole diagnostics dump."""
    try:
        return fn()
    except Exception as err:  # noqa: BLE001 - diagnostics must not crash
        return f"<error: {err}>"


def _point_dump(dp) -> dict[str, Any]:
    """One merged DataPoint -> plain dict (drops nothing the bug needs)."""
    return {
        "key": dp.key,
        "field_name": dp.field_name,
        "raw_value": dp.raw_value,
        "value": _safe(lambda: dp.value),
        "type_hint": dp.type_hint,
        "unit": dp.unit,
        "cluster": dp.cluster,
        # The crux of the bug: is per-item freshness present, or None?
        "timestamp_utc": dp.timestamp_utc,
        "timestamp_parsed": _safe(
            lambda: dp.timestamp.isoformat() if dp.timestamp else None
        ),
    }


def _redact_raw(payload: dict | None) -> dict | None:
    """Redact top-level + per-item VIN/user_id from the untouched payload."""
    if not isinstance(payload, dict):
        return payload
    out = async_redact_data(payload, RAW_REDACT)
    data = out.get("Data")
    if isinstance(data, list):
        out["Data"] = [
            async_redact_data(item, RAW_REDACT) if isinstance(item, dict) else item
            for item in data
        ]
    return out


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EudaConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator
    points = coordinator.data or {}

    # All merged points, sorted so duplicate field_names sit next to each other.
    all_points = [
        _point_dump(dp)
        for dp in sorted(points.values(), key=lambda d: (d.field_name, d.key))
    ]

    # field_name -> how many UUID slots it occupies (the smoking gun: soc=4,
    # mileage.value=3, ...). Only the duplicated ones are interesting.
    field_counts = Counter(dp.field_name for dp in points.values())
    duplicate_fields = {
        name: count for name, count in field_counts.items() if count > 1
    }

    # For each duplicated field, list every slot and flag which one
    # find_by_field currently selects (the possibly-stale winner).
    duplicate_slots: dict[str, Any] = {}
    for name in duplicate_fields:
        picked = find_by_field(points, name)
        picked_key = picked.key if picked else None
        duplicate_slots[name] = {
            "picked_key": picked_key,
            "slots": [
                {
                    "key": dp.key,
                    "raw_value": dp.raw_value,
                    "timestamp_utc": dp.timestamp_utc,
                    "is_picked": dp.key == picked_key,
                }
                for dp in sorted(
                    (d for d in points.values() if d.field_name == name),
                    key=lambda d: d.key,
                )
            ],
        }

    return {
        "entry_data": async_redact_data(entry.data, TO_REDACT),
        "coordinator": {
            "update_interval": str(coordinator.update_interval),
            "dataset_created_at": (
                coordinator.dataset_created_at.isoformat()
                if coordinator.dataset_created_at
                else None
            ),
            "last_update_success": coordinator.last_update_success,
            "point_count": len(points),
        },
        # (b) every duplicated field with all its slots + the current winner
        "duplicate_field_summary": duplicate_fields,
        "duplicate_slots": duplicate_slots,
        # (a) full merged point list incl. timestamp_utc per slot
        "merged_points": all_points,
        # (c) untouched single-dataset Data array (preserves message_id /
        # car_captured_time / grouping that from_json discards). Populates on the
        # first successful download after this module is loaded.
        "latest_raw_dataset": _redact_raw(coordinator.latest_raw),
    }
