"""Generate the entity translation sections of strings.json / en.json / de.json.

Reads the curated registries from data.py (single source of truth for fields,
English names and enum members) and writes the ``entity`` section into:

  custom_components/vw_eu_data_act/strings.json
  custom_components/vw_eu_data_act/translations/en.json
  custom_components/vw_eu_data_act/translations/de.json

The existing ``config`` sections are preserved. Translation keys and enum state
keys are derived with the same functions the entity platforms use
(entity_translation_key / enum_option_key), so they cannot drift.

Run from the repo root after changing the curated registries or translations:

    python tools/gen_translations.py
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG_DIR = ROOT / "custom_components" / "vw_eu_data_act"


def _load_data():
    pkg = types.ModuleType("vw_eu_data_act")
    pkg.__path__ = [str(PKG_DIR)]
    sys.modules["vw_eu_data_act"] = pkg
    spec = importlib.util.spec_from_file_location(
        "vw_eu_data_act.data", PKG_DIR / "data.py"
    )
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "vw_eu_data_act"
    sys.modules["vw_eu_data_act.data"] = mod
    spec.loader.exec_module(mod)
    return mod


# --- German entity names (English source name -> German) -------------------

NAME_DE: dict[str, str] = {
    "Battery": "Batterie",
    "Target charge level": "Ziel-Ladestand",
    "Charge bulk threshold": "Schwelle Hauptladephase",
    "Charge power": "Ladeleistung",
    "Charge rate": "Ladegeschwindigkeit",
    "Charged energy": "Geladene Energie",
    "Remaining charging time": "Restladezeit",
    "Remaining time to bulk": "Restzeit Hauptladephase",
    "Mileage": "Kilometerstand",
    "Electric range": "Elektrische Reichweite",
    "Remaining climate time": "Restzeit Klimatisierung",
    "Residual energy": "Restenergie",
    "Battery min temperature": "Batterietemperatur min.",
    "Battery max temperature": "Batterietemperatur max.",
    "Last connected": "Zuletzt verbunden",
    "Charge state": "Ladestatus",
    "Charge mode": "Lademodus",
    "Charge type": "Ladeart",
    "Charging scenario": "Ladeszenario",
    "Charging action state": "Ladeaktion",
    "Charge mode selection": "Lademodus-Auswahl",
    "Max AC charge current": "Max. AC-Ladestrom",
    "Window heating": "Scheibenheizung",
    "Window heating front": "Scheibenheizung vorne",
    "Window heating rear": "Scheibenheizung hinten",
    "Plug state": "Steckerstatus",
    "Plug connection": "Steckerverbindung",
    "Plug lock": "Steckerverriegelung",
    "BEM level": "BEM-Level",
    "Range (combined)": "Reichweite (kombiniert)",
    "Range (primary)": "Reichweite (primär)",
    "Range (secondary)": "Reichweite (sekundär)",
    "SCR range": "SCR-Reichweite",
    "Fuel level": "Tankfüllstand",
    "Fuel level accuracy": "Tankfüllstand (Genauigkeit)",
    "CNG gas level": "CNG-Füllstand",
    "Outside temperature": "Außentemperatur",
    "Tire pressure FL": "Reifendruck vorne links",
    "Tire pressure FR": "Reifendruck vorne rechts",
    "Tire pressure RL": "Reifendruck hinten links",
    "Tire pressure RR": "Reifendruck hinten rechts",
    "Tire pressure spare": "Reifendruck Reserverad",
    "Tire pressure diff FL": "Reifendruck-Differenz vorne links",
    "Tire pressure diff FR": "Reifendruck-Differenz vorne rechts",
    "Tire pressure diff RL": "Reifendruck-Differenz hinten links",
    "Tire pressure diff RR": "Reifendruck-Differenz hinten rechts",
    "Tire pressure diff spare": "Reifendruck-Differenz Reserverad",
    "Front left window position": "Fensterposition vorne links",
    "Front right window position": "Fensterposition vorne rechts",
    "Rear left window position": "Fensterposition hinten links",
    "Rear right window position": "Fensterposition hinten rechts",
    "Sunroof position": "Schiebedachposition",
    "Inspection interval": "Zeit bis Inspektion",
    "Oil change interval": "Zeit bis Ölwechsel",
    "Inspection distance": "Strecke bis Inspektion",
    "Oil change distance": "Strecke bis Ölwechsel",
    "Trip distance (long)": "Fahrstrecke (Langzeit)",
    "Trip start mileage (long)": "Start-Kilometerstand (Langzeit)",
    "Avg fuel consumption (long)": "Ø Verbrauch (Langzeit)",
    "Avg speed (long)": "Ø Geschwindigkeit (Langzeit)",
    "Travel time (long)": "Fahrzeit (Langzeit)",
    "Trip distance (short)": "Fahrstrecke (Kurzzeit)",
    "Trip start mileage (short)": "Start-Kilometerstand (Kurzzeit)",
    "Avg fuel consumption (short)": "Ø Verbrauch (Kurzzeit)",
    "Travel time (short)": "Fahrzeit (Kurzzeit)",
    "Oil level": "Ölstand",
    "Additional oil level": "Zusätzlicher Ölstand",
    "Max oil level": "Max. Ölstand",
    "Oil dipstick indicator": "Ölmessstab-Anzeige",
    # binary sensors
    "Vehicle locked": "Fahrzeug verriegelt",
    "Front left door lock": "Schloss vorne links",
    "Front right door lock": "Schloss vorne rechts",
    "Rear left door lock": "Schloss hinten links",
    "Rear right door lock": "Schloss hinten rechts",
    "Tailgate lock": "Schloss Heckklappe",
    "Hood lock": "Schloss Motorhaube",
    "Front left door": "Tür vorne links",
    "Front right door": "Tür vorne rechts",
    "Rear left door": "Tür hinten links",
    "Rear right door": "Tür hinten rechts",
    "Tailgate": "Heckklappe",
    "Hood": "Motorhaube",
    "Front right door safe": "Safe vorne rechts",
    "Rear left door safe": "Safe hinten links",
    "Rear right door safe": "Safe hinten rechts",
    "Tailgate safe": "Safe Heckklappe",
    "Hood safe": "Safe Motorhaube",
    "Front left window": "Fenster vorne links",
    "Front right window": "Fenster vorne rechts",
    "Rear left window": "Fenster hinten links",
    "Rear right window": "Fenster hinten rechts",
    "Sunroof": "Schiebedach",
    "Sunroof motor 3": "Schiebedachmotor 3",
    "Parking brake": "Parkbremse",
    "Parking lights": "Parklicht",
    "Hood state": "Motorhaubenstatus",
    "Service hatch": "Serviceklappe",
    "Spoiler": "Spoiler",
    # dataset-level freshness sensors
    "Last vehicle update": "Letzte Fahrzeugmeldung",
    "Dataset generated": "Datensatz erstellt",
}

# --- Enum state labels ------------------------------------------------------
# Per translation key: state key -> (English, German). State keys are the
# shortened, lowercased member labels (enum_option_key). Where live values are
# known to differ from the documented members, both spellings get an entry.

STATES: dict[str, dict[str, tuple[str, str]]] = {
    "charging_state_report_current_charge_state": {
        "not_ready_for_charging": ("Not ready for charging", "Nicht ladebereit"),
        "ready_for_charging": ("Ready for charging", "Ladebereit"),
        "charging_hv_battery": ("Charging HV battery", "Lädt HV-Batterie"),
        "discharging": ("Discharging", "Entladen"),
        "charge_purpose_reached_and_not_conservation_charging": (
            "Charge target reached",
            "Ladeziel erreicht",
        ),
        "charge_purpose_reached_and_conservation": (
            "Charge target reached (conservation)",
            "Ladeziel erreicht (Erhaltung)",
        ),
        "conservation_charging": ("Conservation charging", "Erhaltungsladen"),
        "charging_error": ("Charging error", "Ladefehler"),
    },
    "charging_state_report_charge_mode": {
        "immediately_stopped": ("Immediate charging stopped", "Sofortladen gestoppt"),
        "immediately_default": ("Immediate charging", "Sofortladen"),
        "immediately_profile": ("Immediate charging (profile)", "Sofortladen (Profil)"),
        "extended_profile": ("Extended (profile)", "Erweitert (Profil)"),
        "extended_stopped": ("Extended stopped", "Erweitert gestoppt"),
    },
    "charging_state_report_charge_type": {
        "off": ("Off", "Aus"),
        "ac": ("AC", "AC"),
        "dc": ("DC", "DC"),
    },
    "charging_state_report_charging_scenario": {
        "off": ("Off", "Aus"),
        "charging_to_departure_time_finished": (
            "Charging to departure time finished",
            "Laden bis Abfahrtszeit abgeschlossen",
        ),
        "immediately_charging_finished": (
            "Immediate charging finished",
            "Sofortladen abgeschlossen",
        ),
        "optimised_charging_finished": (
            "Optimised charging finished",
            "Optimiertes Laden abgeschlossen",
        ),
        "charging_to_departure_time_active": (
            "Charging to departure time active",
            "Laden bis Abfahrtszeit aktiv",
        ),
        "immediately_charging_active": (
            "Immediate charging active",
            "Sofortladen aktiv",
        ),
        "optimised_charging_ac": ("Optimised AC charging", "Optimiertes AC-Laden"),
    },
    "charging_state_report_immediate_action_state": {
        "invalid": ("Invalid", "Ungültig"),
        "immediate_action_time": ("Immediate action: time", "Sofortaktion: Zeit"),
        "immediate_charging": ("Immediate charging", "Sofortladen"),
        "immediate_action_stopped": (
            "Immediate action stopped",
            "Sofortaktion gestoppt",
        ),
        "immediate_action_range": (
            "Immediate action: range",
            "Sofortaktion: Reichweite",
        ),
        "immediate_action_soc": ("Immediate action: SOC", "Sofortaktion: Ladestand"),
        "charge_mode_selection": ("Charge mode selection", "Lademodus-Auswahl"),
    },
    "settings_charge_mode_selection": {
        "invalid": ("Invalid", "Ungültig"),
        "timercharging": ("Timer charging", "Timer-Laden"),
        "immediatecharging": ("Immediate charging", "Sofortladen"),
        "timer_charging_climatization": (
            "Timer charging + climatisation",
            "Timer-Laden + Klimatisierung",
        ),
        "preferred_charging_times": (
            "Preferred charging times",
            "Bevorzugte Ladezeiten",
        ),
        "only_own_current": ("Only own current", "Nur eigener Strom"),
        "immediate_discharging": ("Immediate discharging", "Sofort-Entladen"),
        "home_storage_charging": ("Home storage charging", "Heimspeicher-Laden"),
    },
    "settings_max_charge_current_ac": {
        # documented members keep their full prefix after shortening ...
        "max_charge_current_invalid": ("Invalid", "Ungültig"),
        "max_charge_current_reduced": ("Reduced", "Reduziert"),
        "max_charge_current_maximum": ("Maximum", "Maximum"),
        # ... while live values carry an extra _AC_ and shorten fully
        "invalid": ("Invalid", "Ungültig"),
        "reduced": ("Reduced", "Reduziert"),
        "maximum": ("Maximum", "Maximum"),
    },
    "window_heating_state": {
        "off": ("Off", "Aus"),
        "on": ("On", "Ein"),
    },
}


def main() -> int:
    data = _load_data()

    sensors: dict[str, dict] = {}
    binaries: dict[str, dict] = {}

    for curated in data.CURATED_SENSORS_DOTTED + data.CURATED_SENSORS_FLAT:
        key = data.entity_translation_key(curated.field_name)
        entry = sensors.setdefault(key, {"_en_name": curated.name})
        if curated.device_class == "enum":
            documented = set(data.enum_options_for_field(curated.field_name))
            declared = set(STATES.get(key, {}))
            missing = documented - declared
            if missing:
                print(f"WARNING: {key}: undeclared enum states {sorted(missing)}")
            entry["_states"] = STATES.get(key, {})

    for curated in data.CURATED_BINARY_DOTTED + data.CURATED_BINARY_FLAT:
        key = data.entity_translation_key(curated.field_name)
        binaries.setdefault(key, {"_en_name": curated.name})

    # dataset-level freshness sensors (translation keys set in sensor.py)
    sensors["last_vehicle_update"] = {"_en_name": "Last vehicle update"}
    sensors["dataset_generated"] = {"_en_name": "Dataset generated"}

    def build(lang: str) -> dict:
        sensor_section: dict[str, dict] = {}
        for key in sorted(sensors):
            en_name = sensors[key]["_en_name"]
            name = en_name if lang == "en" else NAME_DE.get(en_name, en_name)
            if lang == "de" and en_name not in NAME_DE:
                print(f"WARNING: no German name for {en_name!r}")
            block: dict = {"name": name}
            states = sensors[key].get("_states")
            if states:
                block["state"] = {
                    s: (en if lang == "en" else de)
                    for s, (en, de) in sorted(states.items())
                }
            sensor_section[key] = block
        binary_section = {}
        for key in sorted(binaries):
            en_name = binaries[key]["_en_name"]
            binary_section[key] = {
                "name": en_name if lang == "en" else NAME_DE.get(en_name, en_name)
            }
        return {"sensor": sensor_section, "binary_sensor": binary_section}

    targets = [
        (PKG_DIR / "strings.json", "en"),
        (PKG_DIR / "translations" / "en.json", "en"),
        (PKG_DIR / "translations" / "de.json", "de"),
    ]
    for path, lang in targets:
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["entity"] = build(lang)
        path.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
