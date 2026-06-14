#!/usr/bin/env python3
"""Dump the *structure* of real datasets to design the snapshot-grouping fix.

Logs in with the real EudaApiClient, downloads the newest few datasets and
prints how the flat ``Data`` array is shaped: every per-item field key seen,
one full sample item, and — for the fields that jump (soc / mileage) and the
freshness fields (car_captured_time / timestamp) — each occurrence with its
key, value, timestampUtc and array index, so we can see which timestamp a
value point can be tied to.

It never prints the password. Run from the repo root:

    # creds via env (preferred):
    set EUDA_EMAIL=you@example.com
    set EUDA_PASSWORD=secret
    python tools/dump_dataset.py

    # or on the command line:
    python tools/dump_dataset.py you@example.com "secret"

    # how many newest datasets to inspect (default 3):
    python tools/dump_dataset.py --count 3
"""
from __future__ import annotations

import asyncio
import getpass
import importlib.util
import json
import logging
import os
import sys
import types
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG_DIR = ROOT / "custom_components" / "vw_eu_data_act"
PKG = "vw_eu_data_act"

# Fields we care about for the freshness/ordering bug.
VALUE_FIELDS = ("battery_state_report.soc", "mileage.value", "mileage.unit", "range.value")
TIME_FIELDS = ("car_captured_time", "car_captured_utc_timestamp", "timestamp")


def _load():
    try:
        import aiohttp  # noqa: F401
    except ModuleNotFoundError:
        print("ERROR: aiohttp is not installed. Run: pip install aiohttp")
        sys.exit(2)
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [str(PKG_DIR)]
    sys.modules[PKG] = pkg
    mods = {}
    for name in ("const", "data", "api"):
        spec = importlib.util.spec_from_file_location(f"{PKG}.{name}", PKG_DIR / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = PKG
        sys.modules[f"{PKG}.{name}"] = mod
        spec.loader.exec_module(mod)
        mods[name] = mod
    return mods


def _short_field(item: dict) -> str:
    return item.get("dataFieldName") or item.get("key") or "?"


def describe(payload: dict, label: str) -> None:
    print(f"\n{'='*70}\n{label}\n{'='*70}")
    print("top-level keys:", sorted(payload.keys()))
    data = payload.get("Data", [])
    print(f"Data items: {len(data)}")
    if not data:
        return

    # Every per-item field key seen across the array (reveals a grouping/index
    # or per-item timestamp field the parser currently ignores).
    item_keys = Counter()
    for it in data:
        if isinstance(it, dict):
            item_keys.update(it.keys())
    print("per-item field keys (count):", dict(item_keys))

    print("\nfirst raw item (verbatim):")
    print(json.dumps(data[0], indent=2, ensure_ascii=False)[:800])

    # How many items carry a timestampUtc at all?
    with_ts = sum(1 for it in data if it.get("timestampUtc"))
    print(f"\nitems with non-empty timestampUtc: {with_ts}/{len(data)}")

    # Occurrences of the jumpy value fields and the freshness fields, in array
    # order, so we can eyeball whether a value sits next to its captured time.
    print("\noccurrences (idx | dataFieldName | value | timestampUtc | key):")
    for idx, it in enumerate(data):
        if not isinstance(it, dict):
            continue
        fn = _short_field(it)
        if fn in VALUE_FIELDS or fn.rsplit(".", 1)[-1] in TIME_FIELDS:
            print(
                f"  {idx:4d} | {fn:34s} | {str(it.get('value'))[:24]:24s} | "
                f"{str(it.get('timestampUtc'))[:25]:25s} | {it.get('key')}"
            )


async def run(api, email: str, password: str, count: int, brand: str) -> int:
    import aiohttp

    logging.basicConfig(level=logging.WARNING)  # keep the auth flow quiet
    print(f"brand={brand}")
    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar())
    client = api.EudaApiClient(session, email, password, brand)
    try:
        await client.async_login()
        vehicles = await client.async_list_vehicles()
        if not vehicles:
            print("no vehicles returned")
            return 1
        vin = vehicles[0]["vin"]
        meta = await client.async_get_metadata(vin)
        identifier = meta.get("Identifier")
        datasets = await client.async_list_datasets(vin, identifier)
        # newest first; skip no-content stubs
        from vw_eu_data_act.const import NO_CONTENT_SUFFIX

        named = [d for d in datasets if d.get("name") and not d["name"].endswith(NO_CONTENT_SUFFIX)]
        print(f"{len(named)} content datasets; inspecting newest {min(count, len(named))}")
        for d in named[:count]:
            payload = await client.async_download_dataset(vin, identifier, d["name"])
            describe(payload, f"{d.get('name')}  createdOn={d.get('createdOn')}")
        return 0
    except Exception as err:  # noqa: BLE001
        print(f"FAILED: {type(err).__name__}: {err}")
        return 1
    finally:
        await session.close()


def main() -> int:
    mods = _load()
    api = mods["api"]
    argv = sys.argv[1:]
    count = 3
    if "--count" in argv:
        i = argv.index("--count")
        count = int(argv[i + 1])
        del argv[i : i + 2]
    # Brand selects the OIDC client_id. It MUST match the brand the working HA
    # config entry uses (a Cupra account against the default VW client_id is
    # rejected as "user/password don't match"). Valid: volkswagen, audi, skoda,
    # seat, cupra.
    brand = os.environ.get("EUDA_BRAND", "volkswagen")
    email = (argv[0] if len(argv) > 0 else os.environ.get("EUDA_EMAIL")) or input("Email: ")
    password = (
        argv[1] if len(argv) > 1 else os.environ.get("EUDA_PASSWORD")
    ) or getpass.getpass("Password: ")
    return asyncio.run(run(api, email, password, count, brand))


if __name__ == "__main__":
    raise SystemExit(main())
