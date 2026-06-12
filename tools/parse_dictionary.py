#!/usr/bin/env python3
"""One-off dev tool: parse the EU Data Act PDF data dictionary into JSON.

Extracts the table (Key | Data Point Name | Description | Measurement Unit |
Tech. Data Type | Data Cluster) from every page and writes a mapping keyed by
the stable data-point UUID:

    { "<key-uuid>": {"name", "description", "unit", "type", "cluster"}, ... }

The resulting custom_components/vw_eu_data_act/data_dictionary.json is committed
and shipped with the integration; pdfplumber is NOT a runtime dependency.

Usage:
    .venv/bin/python tools/parse_dictionary.py [PDF_PATH] [OUT_PATH]
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

import pdfplumber

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)
HEADER_FIRST_CELL = "key"


def _clean_key(cell: str | None) -> str:
    """UUIDs may wrap across lines; remove all whitespace."""
    return re.sub(r"\s+", "", cell or "")


def _clean_name(cell: str | None) -> str:
    """Join wrapped lines.

    Friendly names ("Remaining Charge Time Complete") legitimately contain
    spaces; code identifiers ("remaining_climate_time", dotted paths) do not.
    Heuristic: if any physical line already contains a space it is a friendly
    name -> join lines with a space; otherwise it is a code identifier whose
    line breaks are artifacts -> join with no separator.
    """
    if not cell:
        return ""
    lines = [ln.strip() for ln in cell.split("\n") if ln.strip()]
    sep = " " if any(" " in ln for ln in lines) else ""
    name = sep.join(lines)
    return re.sub(r"\s+", " ", name).strip()


def _clean_text(cell: str | None) -> str:
    """Collapse wrapped multi-line text (descriptions) into one line."""
    if not cell:
        return ""
    text = re.sub(r"\s+", " ", cell.replace("\n", " "))
    return html.unescape(text).strip()


def _clean_token(cell: str | None) -> str:
    """Single-token columns (unit / type). Treat placeholders as empty."""
    tok = _clean_text(cell)
    if tok in ("", "'-", "-", "'"):
        return ""
    return tok


def parse(pdf_path: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    dupes = 0
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    # Continuous dictionaries have 6 columns; the Historical
                    # Data dictionary omits the trailing "Data Cluster" column.
                    if not row or len(row) < 5:
                        continue
                    key = _clean_key(row[0])
                    if key.lower() == HEADER_FIRST_CELL:
                        continue
                    if not UUID_RE.match(key):
                        continue
                    entry = {
                        "name": _clean_name(row[1]),
                        "description": _clean_text(row[2]),
                        "unit": _clean_token(row[3]),
                        "type": _clean_token(row[4]).lower(),
                        "cluster": _clean_text(row[5]) if len(row) > 5 else "",
                    }
                    if key in out and out[key] != entry:
                        dupes += 1
                    out[key] = entry
    if dupes:
        print(f"  note: {dupes} duplicate keys with differing rows (last wins)")
    return out


def main() -> None:
    here = Path(__file__).resolve().parent.parent
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else next(
        here.glob("*DataDictionary*.pdf")
    )
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else (
        here / "custom_components" / "vw_eu_data_act" / "data_dictionary.json"
    )
    print(f"Parsing {pdf_path.name} ...")
    mapping = parse(pdf_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # encoding matters: Windows' default is cp1252, which cannot represent
    # every character in the PDF and crashes the write.
    out_path.write_text(
        json.dumps(mapping, indent=1, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(f"Wrote {len(mapping)} data points -> {out_path}")

    # sanity check from the plan
    sample = "3c19831c-38b8-3dc5-9ead-bb333616d925"
    if sample in mapping:
        print(f"  check {sample}: {mapping[sample]}")
    else:
        print(f"  WARNING: expected key {sample} not found!")


if __name__ == "__main__":
    main()
