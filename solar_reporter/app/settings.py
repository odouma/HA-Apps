import json
import os
import threading

import images as images_module

SETTINGS_FILE = "/data/settings.json"
LOGO_FILE = "/data/logo.png"  # pad van het oude, ene gedeelde logo (voor migratie)

_lock = threading.Lock()

DEFAULTS = {
    "refresh_interval_seconds": 10,
    "entities": {
        "power": "sensor.solplanet_power",
        "energy_today": "sensor.solplanet_energy_produced_today",
    },
    "mqtt": {
        "enabled": False,
        "host": "core-mosquitto",
        "port": 1883,
        "username": "",
        "password": "",
    },
    "email": {
        "smtp_host": "",
        "smtp_port": 587,
        "encryption": "starttls",  # none | starttls | ssl
        "username": "",
        "password": "",
        "from_address": "",
    },
    "reports": {
        "daily": {
            "enabled": False,
            "send_time": "22:00",
            "recipients": [],
        },
        "monthly": {
            "enabled": False,
            "send_day": 1,
            "send_time": "08:00",
            "recipients": [],
        },
        "last_sent": {
            "daily": None,   # laatst verzonden datum (YYYY-MM-DD)
            "monthly": None,  # laatst verzonden maand (YYYY-MM)
        },
    },
    "branding": {
        "daily_subject": "Dagrapport stroomopbrengst {datum}",
        "monthly_subject": "Maandrapport stroomopbrengst {maand}",
        "daily_body": (
            "Hierbij het dagrapport van {datum}.\n\n"
            "Opbrengst: {opbrengst_kwh} kWh\n"
            "Besparing: € {besparing_euro}"
        ),
        "monthly_body": (
            "Hierbij het maandrapport van {maand}.\n\n"
            "Opbrengst: {opbrengst_kwh} kWh\n"
            "Besparing: € {besparing_euro}"
        ),
        # Layout van de PDF-rapporten — een apart sjabloon voor het dag- en
        # het maandrapport. Elk element staat in procenten (0-100) van de
        # paginabreedte/-hoogte, gemeten vanaf de linkerbovenhoek. De
        # volgorde in de lijst bepaalt de stapelvolgorde (laatste = boven).
        "pdf_template": {
            "daily": {"elements": [
                {
                    "id": "logo",
                    "type": "image",
                    "x": 5, "y": 3, "width": 25, "height": 10,
                    "image_id": None,
                },
                {
                    "id": "title",
                    "type": "text",
                    "x": 5, "y": 15, "width": 90, "height": 9,
                    "text": "{report_title}",
                    "font_size": 22,
                    "font_family": "sans-serif",
                    "font_weight": "bold",
                    "font_style": "normal",
                    "underline": False,
                    "align": "left",
                    "color": "#111111",
                },
                {
                    "id": "subtitle",
                    "type": "text",
                    "x": 5, "y": 24, "width": 90, "height": 5,
                    "text": "{period_label}",
                    "font_size": 11,
                    "font_family": "sans-serif",
                    "font_weight": "normal",
                    "font_style": "normal",
                    "underline": False,
                    "align": "left",
                    "color": "#555555",
                },
                {
                    "id": "stat_opbrengst",
                    "type": "text",
                    "x": 5, "y": 30, "width": 90, "height": 6,
                    "text": "Opbrengst: {opbrengst_kwh} kWh — € {opbrengst_euro}",
                    "font_size": 13,
                    "font_family": "sans-serif",
                    "font_weight": "bold",
                    "font_style": "normal",
                    "underline": False,
                    "align": "left",
                    "color": "#111111",
                },
                {
                    "id": "stat_besparing",
                    "type": "text",
                    "x": 5, "y": 37, "width": 90, "height": 6,
                    "text": "Totale besparing tot nu toe: € {besparing_totaal_euro} ({besparing_totaal_kwh} kWh)",
                    "font_size": 11,
                    "font_family": "sans-serif",
                    "font_weight": "normal",
                    "font_style": "normal",
                    "underline": False,
                    "align": "left",
                    "color": "#111111",
                },
                {
                    "id": "chart",
                    "type": "chart",
                    "x": 5, "y": 46, "width": 90, "height": 48,
                    "chart_type": "bar",  # bar | line | area
                    "chart_color": "#03a9f4",
                    "show_grid": True,
                    "show_values": False,
                    "value_decimals": 2,
                    "show_markers": True,
                    "line_width": 2.5,
                },
            ]},
            "monthly": {"elements": [
                {
                    "id": "logo",
                    "type": "image",
                    "x": 5, "y": 3, "width": 25, "height": 10,
                    "image_id": None,
                },
                {
                    "id": "title",
                    "type": "text",
                    "x": 5, "y": 15, "width": 90, "height": 9,
                    "text": "{report_title}",
                    "font_size": 22,
                    "font_family": "sans-serif",
                    "font_weight": "bold",
                    "font_style": "normal",
                    "underline": False,
                    "align": "left",
                    "color": "#111111",
                },
                {
                    "id": "subtitle",
                    "type": "text",
                    "x": 5, "y": 24, "width": 90, "height": 5,
                    "text": "{period_label}",
                    "font_size": 11,
                    "font_family": "sans-serif",
                    "font_weight": "normal",
                    "font_style": "normal",
                    "underline": False,
                    "align": "left",
                    "color": "#555555",
                },
                {
                    "id": "stat_opbrengst",
                    "type": "text",
                    "x": 5, "y": 30, "width": 90, "height": 6,
                    "text": "Opbrengst: {opbrengst_kwh} kWh — € {opbrengst_euro}",
                    "font_size": 13,
                    "font_family": "sans-serif",
                    "font_weight": "bold",
                    "font_style": "normal",
                    "underline": False,
                    "align": "left",
                    "color": "#111111",
                },
                {
                    "id": "stat_besparing",
                    "type": "text",
                    "x": 5, "y": 37, "width": 90, "height": 6,
                    "text": "Totale besparing tot nu toe: € {besparing_totaal_euro} ({besparing_totaal_kwh} kWh)",
                    "font_size": 11,
                    "font_family": "sans-serif",
                    "font_weight": "normal",
                    "font_style": "normal",
                    "underline": False,
                    "align": "left",
                    "color": "#111111",
                },
                {
                    "id": "chart",
                    "type": "chart",
                    "x": 5, "y": 46, "width": 90, "height": 48,
                    "chart_type": "bar",  # bar | line | area
                    "chart_color": "#03a9f4",
                    "show_grid": True,
                    "show_values": False,
                    "value_decimals": 2,
                    "show_markers": True,
                    "line_width": 2.5,
                },
            ]},
        },
    },
}


def _deep_merge(defaults, overrides):
    result = dict(defaults)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _migrate_stored(stored):
    """Migreert oudere instellingen naar het huidige schema. Retourneert
    (stored, changed) — changed is True als er iets is aangepast, zodat de
    aanroeper dit direct kan wegschrijven (anders gebeurt de migratie bij
    elke load opnieuw, zonder dat die ooit duurzaam wordt)."""
    changed = False
    branding = stored.get("branding")
    if not isinstance(branding, dict):
        return stored, changed

    if branding.pop("has_logo", None) is not None:
        changed = True

    pdf_template = branding.get("pdf_template")
    if not isinstance(pdf_template, dict):
        return stored, changed

    # Vóór de per-rapport PDF-opmaak was er nog één gedeeld sjabloon
    # (`pdf_template.elements`) in plaats van een apart sjabloon per
    # rapporttype (`pdf_template.daily`/`.monthly`).
    if "elements" in pdf_template and "daily" not in pdf_template and "monthly" not in pdf_template:
        legacy_elements = pdf_template.pop("elements")
        pdf_template["daily"] = {"elements": legacy_elements}
        pdf_template["monthly"] = {"elements": json.loads(json.dumps(legacy_elements))}
        changed = True

    # Vóór afbeeldingen per element was er maar één, gedeeld logo.png.
    # Registreer dat (eenmalig) als gewone afbeelding en koppel bestaande
    # afbeelding-elementen zonder image_id daaraan, zodat een bestaande
    # PDF-opmaak niet plots leeg komt te staan.
    legacy_id = images_module.import_legacy_logo(LOGO_FILE)
    if legacy_id:
        for kind in ("daily", "monthly"):
            for el in pdf_template.get(kind, {}).get("elements", []):
                if el.get("type") == "image" and not el.get("image_id"):
                    el["image_id"] = legacy_id
                    changed = True

    return stored, changed


def load_settings():
    with _lock:
        if not os.path.exists(SETTINGS_FILE):
            return json.loads(json.dumps(DEFAULTS))
        try:
            with open(SETTINGS_FILE, "r") as f:
                stored = json.load(f)
        except (json.JSONDecodeError, OSError):
            stored = {}
        stored, changed = _migrate_stored(stored)
        merged = _deep_merge(DEFAULTS, stored)
        if changed:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(merged, f, indent=2)
        return merged


def save_settings(settings):
    with _lock:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)


def update_settings(partial):
    current = load_settings()
    merged = _deep_merge(current, partial)
    save_settings(merged)
    return merged
