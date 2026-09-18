from flask import Flask, request, jsonify, render_template, Response, send_file
import json
import os
import uuid
import datetime
import threading
import time
import calendar
import requests
import websocket
from zoneinfo import ZoneInfo

import settings as settings_module
import mqtt_client
import reports
import mail
import images as images_module

app = Flask(__name__)

# Opgehoogd bij elke wijziging in static/*.js of static/*.css, en als
# querystring achter die bestanden geplakt (zie templates), zodat browsers
# (en de Home Assistant ingress-iframe) na een update niet een verouderde,
# gecachte versie van die bestanden blijven gebruiken.
STATIC_VERSION = "1.7.5"

DATA_DIR = "/data"
DATA_FILE = os.path.join(DATA_DIR, "tariffs.json")

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN")
LOCAL_TZ = ZoneInfo("Europe/Amsterdam")


# ---------------------------------------------------------------------------
# Tarieven: opslag en logica
# ---------------------------------------------------------------------------

def load_tariffs():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_tariffs(tariffs):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(tariffs, f, indent=2)


def get_active_tariff(tariffs):
    today = datetime.date.today().isoformat()
    active = None
    for t in sorted(tariffs, key=lambda t: t["valid_from"]):
        if t["valid_from"] <= today:
            active = t
        else:
            break
    return active


def get_tariff_for_date(tariffs, date_iso):
    applicable = [t for t in tariffs if t["valid_from"] <= date_iso]
    if not applicable:
        return None
    return max(applicable, key=lambda t: t["valid_from"])


def validate_payload(data):
    errors = []

    valid_from = data.get("valid_from", "")
    try:
        datetime.date.fromisoformat(valid_from)
    except (ValueError, TypeError):
        errors.append("Ongeldige ingangsdatum (verwacht formaat JJJJ-MM-DD).")

    try:
        price = float(data.get("price"))
        if price < 0:
            errors.append("Tarief mag niet negatief zijn.")
    except (ValueError, TypeError):
        errors.append("Ongeldig tarief.")

    return errors


# ---------------------------------------------------------------------------
# Home Assistant Core API: geschiedenis ophalen
# ---------------------------------------------------------------------------

def fetch_daily_last_values(entity_id, start_date, end_date):
    """Geeft per kalenderdag de laatst bekende waarde van entity_id terug,
    ook als de sensor 's nachts 'unavailable' wordt (de laatste geldige
    waarde vóór het offline gaan telt als eindwaarde van die dag)."""
    if not SUPERVISOR_TOKEN:
        return {}

    start_iso = f"{start_date}T00:00:00"
    end_iso = f"{end_date}T23:59:59"
    url = (
        f"http://supervisor/core/api/history/period/{start_iso}"
        f"?filter_entity_id={entity_id}&end_time={end_iso}&minimal_response"
    )

    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"},
            timeout=20,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[solar-reporter] Kon geschiedenis van {entity_id} niet ophalen: {e}", flush=True)
        return {}

    data = resp.json()
    if not data or not data[0]:
        return {}

    per_day = {}
    for entry in data[0]:
        state = entry.get("state")
        timestamp = entry.get("last_changed") or entry.get("last_updated")
        if state in (None, "unknown", "unavailable") or not timestamp:
            continue
        try:
            value = float(state)
        except (TypeError, ValueError):
            continue

        dt = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        day = dt.astimezone(LOCAL_TZ).date().isoformat()
        per_day[day] = value

    return per_day


def _ws_request(payload, timeout=15):
    """Stuurt één commando naar de Home Assistant WebSocket-API (via de
    Supervisor-proxy) en geeft het 'result' terug, of None bij een fout.
    Nodig omdat langetermijn-statistieken (in tegenstelling tot states-
    geschiedenis) niet via de gewone REST-API beschikbaar zijn."""
    if not SUPERVISOR_TOKEN:
        return None

    try:
        ws = websocket.create_connection("ws://supervisor/core/websocket", timeout=timeout)
    except Exception as e:  # noqa: BLE001 - verbindingsfouten willen we allemaal afvangen
        print(f"[solar-reporter] Kon geen WebSocket-verbinding maken: {e}", flush=True)
        return None

    try:
        hello = json.loads(ws.recv())
        if hello.get("type") != "auth_required":
            print(f"[solar-reporter] Onverwacht WebSocket-antwoord: {hello}", flush=True)
            return None

        ws.send(json.dumps({"type": "auth", "access_token": SUPERVISOR_TOKEN}))
        auth_result = json.loads(ws.recv())
        if auth_result.get("type") != "auth_ok":
            print(f"[solar-reporter] WebSocket-authenticatie mislukt: {auth_result}", flush=True)
            return None

        message = dict(payload, id=1)
        ws.send(json.dumps(message))
        while True:
            response = json.loads(ws.recv())
            if response.get("id") != 1:
                continue
            if not response.get("success"):
                print(f"[solar-reporter] WebSocket-commando mislukt: {response.get('error')}", flush=True)
                return None
            return response.get("result")
    except Exception as e:  # noqa: BLE001
        print(f"[solar-reporter] WebSocket-fout: {e}", flush=True)
        return None
    finally:
        try:
            ws.close()
        except Exception:  # noqa: BLE001
            pass


def fetch_daily_statistics(entity_id, start_date, end_date):
    """Geeft per kalenderdag de laatste 'state'-waarde uit de langetermijn-
    statistieken (recorder/statistics_during_period), die — in tegenstelling
    tot de states-tabel — niet na een paar dagen wordt opgeruimd. Voor een
    dagelijks-resettende opbrengstsensor is dat exact de opbrengst van die
    dag. Alleen 'vandaag' loopt hierin vaak achter (statistieken worden
    periodiek herberekend, niet live), zie fetch_daily_energy_totals."""
    result = _ws_request({
        "type": "recorder/statistics_during_period",
        "start_time": f"{start_date}T00:00:00+00:00",
        "end_time": f"{(datetime.date.fromisoformat(end_date) + datetime.timedelta(days=1)).isoformat()}T00:00:00+00:00",
        "statistic_ids": [entity_id],
        "period": "day",
        "types": ["state", "max"],
    })
    if not result:
        return {}

    per_day = {}
    for entry in result.get(entity_id, []):
        start_ms = entry.get("start")
        value = entry.get("state")
        if value is None:
            value = entry.get("max")
        if value is None or start_ms is None:
            continue
        dt = datetime.datetime.fromtimestamp(start_ms / 1000, tz=datetime.timezone.utc).astimezone(LOCAL_TZ)
        per_day[dt.date().isoformat()] = round(float(value), 3)

    return per_day


def fetch_daily_energy_totals(entity_id, start_date, end_date):
    """Combineert langetermijn-statistieken (voor alle dagen — de states-
    tabel bewaart doorgaans maar een beperkt aantal dagen) met de live
    states-geschiedenis voor vandaag (de statistieken van vandaag lopen
    daarvoor te veel achter)."""
    per_day = fetch_daily_statistics(entity_id, start_date, end_date)

    today = datetime.date.today().isoformat()
    if start_date <= today <= end_date:
        today_values = fetch_daily_last_values(entity_id, today, today)
        if today in today_values:
            per_day[today] = today_values[today]
        else:
            per_day.pop(today, None)

    return per_day


def fetch_hourly_kwh_for_day(power_entity, date_iso):
    """Berekent per uur (0-23) de geschatte opbrengst in kWh, op basis van
    het gemiddelde vermogen (in Watt) tijdens dat uur."""
    if not SUPERVISOR_TOKEN:
        return [0.0] * 24

    start_iso = f"{date_iso}T00:00:00"
    next_day = (datetime.date.fromisoformat(date_iso) + datetime.timedelta(days=1)).isoformat()
    end_iso = f"{next_day}T00:00:00"
    url = (
        f"http://supervisor/core/api/history/period/{start_iso}"
        f"?filter_entity_id={power_entity}&end_time={end_iso}"
    )

    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"},
            timeout=20,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[solar-reporter] Kon vermogensgeschiedenis niet ophalen: {e}", flush=True)
        return [0.0] * 24

    data = resp.json()
    if not data or not data[0]:
        return [0.0] * 24

    buckets = [[] for _ in range(24)]
    for entry in data[0]:
        state = entry.get("state")
        timestamp = entry.get("last_changed") or entry.get("last_updated")
        if state in (None, "unknown", "unavailable") or not timestamp:
            continue
        try:
            value = float(state)
        except (TypeError, ValueError):
            continue

        dt = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
        if dt.date().isoformat() != date_iso:
            continue
        buckets[dt.hour].append(value)

    hourly_kwh = []
    for hour_values in buckets:
        if not hour_values:
            hourly_kwh.append(0.0)
        else:
            avg_watt = sum(hour_values) / len(hour_values)
            hourly_kwh.append(round(avg_watt / 1000.0, 3))
    return hourly_kwh


# ---------------------------------------------------------------------------
# Besparing
# ---------------------------------------------------------------------------

def calculate_savings():
    settings = settings_module.load_settings()
    energy_entity = settings["entities"]["energy_today"]

    tariffs = sorted(load_tariffs(), key=lambda t: t["valid_from"])
    if not tariffs:
        return False, "Geen tarieven ingevoerd.", None

    earliest = tariffs[0]["valid_from"]
    today = datetime.date.today().isoformat()

    per_day = fetch_daily_energy_totals(energy_entity, earliest, today)
    if not per_day:
        return False, f"Geen (bruikbare) gegevens gevonden voor {energy_entity}.", None

    total_kwh = 0.0
    total_euro = 0.0
    for day, kwh in per_day.items():
        tariff = get_tariff_for_date(tariffs, day)
        if tariff is None:
            continue
        total_kwh += kwh
        total_euro += kwh * tariff["price"]

    today_kwh = per_day.get(today, 0.0)
    today_tariff = get_active_tariff(tariffs)
    today_euro = today_kwh * today_tariff["price"] if today_tariff else 0.0

    result = {
        "today_kwh": round(today_kwh, 3),
        "today_euro": round(today_euro, 2),
        "total_kwh": round(total_kwh, 3),
        "total_euro": round(total_euro, 2),
        "vanaf": earliest,
        "dagen_meegeteld": len(per_day),
    }
    return True, "OK", result


# ---------------------------------------------------------------------------
# Home Assistant sensoren bijwerken (via MQTT-apparaat of via de Core API)
# ---------------------------------------------------------------------------

def _publish_entity(entity_key, ha_entity_id, state, attributes, mqtt_settings):
    if mqtt_client.ensure_connected(mqtt_settings):
        mqtt_client.publish_state(entity_key, state, attributes)
        return True, f"Bijgewerkt via MQTT ({entity_key})."

    if not SUPERVISOR_TOKEN:
        message = (
            "SUPERVISOR_TOKEN ontbreekt. Controleer of 'homeassistant_api: true' "
            "in config.yaml staat en herbouw de addon."
        )
        print(f"[solar-reporter] {message}", flush=True)
        return False, message

    try:
        resp = requests.post(
            f"http://supervisor/core/api/states/{ha_entity_id}",
            headers={
                "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
                "Content-Type": "application/json",
            },
            json={"state": state, "attributes": attributes},
            timeout=5,
        )
        if resp.status_code >= 300:
            message = f"Home Assistant gaf HTTP {resp.status_code} terug: {resp.text}"
            print(f"[solar-reporter] {message}", flush=True)
            return False, message
        return True, f"Sensor {ha_entity_id} bijgewerkt naar {state}."
    except requests.RequestException as e:
        message = f"Kon Home Assistant niet bereiken: {e}"
        print(f"[solar-reporter] {message}", flush=True)
        return False, message


def push_state_to_ha():
    settings = settings_module.load_settings()
    tariffs = sorted(load_tariffs(), key=lambda t: t["valid_from"])
    active = get_active_tariff(tariffs)
    today = datetime.date.today().isoformat()

    alle_tarieven = [
        {
            "ingangsdatum": t["valid_from"],
            "tarief": t["price"],
        }
        for t in tariffs
    ]

    attributes = {
        "friendly_name": "Stroomtarief (actief)",
        "unit_of_measurement": "EUR/kWh",
        "tarieven": alle_tarieven,
    }

    if active is None:
        state = "unknown"
    else:
        upcoming = [t for t in tariffs if t["valid_from"] > today]
        state = active["price"]
        attributes.update({
            "device_class": "monetary",
            "state_class": "measurement",
            "ingangsdatum": active["valid_from"],
            "eerstvolgende_wijziging": upcoming[0]["valid_from"] if upcoming else None,
            "eerstvolgend_tarief": upcoming[0]["price"] if upcoming else None,
        })

    return _publish_entity("actief_tarief", "sensor.stroomtarief_actief", state, attributes, settings["mqtt"])


def push_savings_to_ha():
    settings = settings_module.load_settings()
    success, message, result = calculate_savings()
    if not success:
        print(f"[solar-reporter] Besparing niet bijgewerkt: {message}", flush=True)
        return False, message

    _publish_entity(
        "besparing_vandaag", "sensor.stroombesparing_vandaag", result["today_euro"],
        {
            "friendly_name": "Stroombesparing vandaag",
            "unit_of_measurement": "EUR",
            "device_class": "monetary",
            "state_class": "measurement",
            "kwh": result["today_kwh"],
        },
        settings["mqtt"],
    )
    _publish_entity(
        "besparing_totaal", "sensor.stroombesparing_totaal", result["total_euro"],
        {
            "friendly_name": "Stroombesparing totaal",
            "unit_of_measurement": "EUR",
            "device_class": "monetary",
            "state_class": "measurement",
            "kwh_totaal": result["total_kwh"],
            "berekend_vanaf": result["vanaf"],
            "dagen_meegeteld": result["dagen_meegeteld"],
        },
        settings["mqtt"],
    )
    _publish_entity(
        "opbrengst_vandaag", "sensor.stroomopbrengst_vandaag", result["today_kwh"],
        {
            "friendly_name": "Opbrengst vandaag",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "state_class": "measurement",
        },
        settings["mqtt"],
    )
    _publish_entity(
        "opbrengst_totaal", "sensor.stroomopbrengst_totaal", result["total_kwh"],
        {
            "friendly_name": "Opbrengst totaal",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "state_class": "measurement",
            "berekend_vanaf": result["vanaf"],
            "dagen_meegeteld": result["dagen_meegeteld"],
        },
        settings["mqtt"],
    )
    return True, message


# ---------------------------------------------------------------------------
# Rapportages
# ---------------------------------------------------------------------------

def build_daily_report_data(date_iso, settings):
    entities = settings["entities"]
    tariffs = sorted(load_tariffs(), key=lambda t: t["valid_from"])

    hourly_kwh = fetch_hourly_kwh_for_day(entities["power"], date_iso)

    per_day_energy = fetch_daily_energy_totals(entities["energy_today"], date_iso, date_iso)
    total_kwh = per_day_energy.get(date_iso, sum(hourly_kwh))

    tariff = get_tariff_for_date(tariffs, date_iso)
    total_euro = total_kwh * tariff["price"] if tariff else 0.0

    ok, _, savings = calculate_savings()
    savings_kwh = savings["total_kwh"] if ok else 0.0
    savings_euro = savings["total_euro"] if ok else 0.0

    return hourly_kwh, total_kwh, total_euro, savings_kwh, savings_euro


def build_monthly_report_data(year, month, settings):
    entities = settings["entities"]
    tariffs = sorted(load_tariffs(), key=lambda t: t["valid_from"])

    start_date = datetime.date(year, month, 1).isoformat()
    last_day = calendar.monthrange(year, month)[1]
    end_date = datetime.date(year, month, last_day).isoformat()

    per_day_energy = fetch_daily_energy_totals(entities["energy_today"], start_date, end_date)

    daily_kwh = {}
    daily_euro = {}
    total_kwh = 0.0
    total_euro = 0.0
    for day_str, kwh in per_day_energy.items():
        d = datetime.date.fromisoformat(day_str)
        if d.year == year and d.month == month:
            tariff = get_tariff_for_date(tariffs, day_str)
            euro = kwh * tariff["price"] if tariff else 0.0
            daily_kwh[d.day] = kwh
            daily_euro[d.day] = euro
            total_kwh += kwh
            total_euro += euro

    ok, _, savings = calculate_savings()
    savings_kwh = savings["total_kwh"] if ok else 0.0
    savings_euro = savings["total_euro"] if ok else 0.0

    return daily_kwh, daily_euro, total_kwh, total_euro, savings_kwh, savings_euro


_WEEKDAGEN = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
_MAANDEN = [
    "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
]


def _dutch_full_date(d):
    """Nederlandse datum zonder afhankelijkheid van systeemlocale (die in
    de Alpine-container niet beschikbaar is), bijv. 'woensdag 16 september 2026'."""
    return f"{_WEEKDAGEN[d.weekday()]} {d.day} {_MAANDEN[d.month - 1]} {d.year}"


def _dutch_month_year(year, month):
    return f"{_MAANDEN[month - 1]} {year}"


def _report_context(report_title, period_label, total_kwh, total_euro, savings_kwh, savings_euro):
    """Bouwt de tag-waarden op die in PDF-tekstelementen gebruikt kunnen
    worden (zie reports.AVAILABLE_TAGS)."""
    now = datetime.datetime.now(LOCAL_TZ)
    return {
        "report_title": report_title,
        "period_label": period_label,
        "opbrengst_kwh": f"{total_kwh:.2f}",
        "opbrengst_euro": f"{total_euro:.2f}",
        "besparing_totaal_kwh": f"{savings_kwh:.1f}",
        "besparing_totaal_euro": f"{savings_euro:.2f}",
        "gegenereerd_op": now.strftime("%d-%m-%Y %H:%M"),
    }


def send_daily_report(date_iso, settings):
    hourly_kwh, total_kwh, total_euro, sav_kwh, sav_euro = build_daily_report_data(date_iso, settings)
    report_date = datetime.date.fromisoformat(date_iso)
    context = _report_context(
        "Dagrapport stroomopbrengst", _dutch_full_date(report_date),
        total_kwh, total_euro, sav_kwh, sav_euro,
    )
    labels = [f"{h:02d}" for h in range(24)]
    pdf_bytes = reports.render_report_pdf(
        settings["branding"]["pdf_template"]["daily"]["elements"], context, labels, hourly_kwh, "kWh per uur",
    )
    subject = settings["branding"]["daily_subject"].format(datum=date_iso)
    body = settings["branding"]["daily_body"].format(
        datum=date_iso, opbrengst_kwh=f"{total_kwh:.2f}", besparing_euro=f"{total_euro:.2f}"
    )
    recipients = settings["reports"]["daily"]["recipients"]
    ok, message = mail.send_report_email(
        settings["email"], recipients, subject,
        body, pdf_bytes, f"dagrapport-{date_iso}.pdf",
    )
    print(f"[solar-reporter] Dagrapport {date_iso}: {message}", flush=True)
    return ok, message


def send_monthly_report(year, month, settings):
    daily_kwh, daily_euro, total_kwh, total_euro, sav_kwh, sav_euro = build_monthly_report_data(
        year, month, settings
    )
    days_in_month = calendar.monthrange(year, month)[1]
    labels = [str(d) for d in range(1, days_in_month + 1)]
    values = [daily_kwh.get(d, 0.0) for d in range(1, days_in_month + 1)]
    maand_label = _dutch_month_year(year, month)
    context = _report_context(
        "Maandrapport stroomopbrengst", maand_label, total_kwh, total_euro, sav_kwh, sav_euro,
    )
    pdf_bytes = reports.render_report_pdf(
        settings["branding"]["pdf_template"]["monthly"]["elements"], context, labels, values, "kWh per dag",
    )
    subject = settings["branding"]["monthly_subject"].format(maand=maand_label)
    body = settings["branding"]["monthly_body"].format(
        maand=maand_label, opbrengst_kwh=f"{total_kwh:.2f}", besparing_euro=f"{total_euro:.2f}"
    )
    recipients = settings["reports"]["monthly"]["recipients"]
    ok, message = mail.send_report_email(
        settings["email"], recipients, subject,
        body, pdf_bytes, f"maandrapport-{year}-{month:02d}.pdf",
    )
    print(f"[solar-reporter] Maandrapport {year}-{month:02d}: {message}", flush=True)
    return ok, message


def check_and_send_reports():
    settings = settings_module.load_settings()
    now = datetime.datetime.now(LOCAL_TZ)
    today_iso = now.date().isoformat()
    current_hm = now.strftime("%H:%M")

    daily_cfg = settings["reports"]["daily"]
    if (
        daily_cfg["enabled"]
        and current_hm == daily_cfg["send_time"]
        and settings["reports"]["last_sent"]["daily"] != today_iso
    ):
        send_daily_report(today_iso, settings)
        settings_module.update_settings({"reports": {"last_sent": {"daily": today_iso}}})

    monthly_cfg = settings["reports"]["monthly"]
    month_iso = now.strftime("%Y-%m")
    if (
        monthly_cfg["enabled"]
        and now.day == int(monthly_cfg["send_day"])
        and current_hm == monthly_cfg["send_time"]
        and settings["reports"]["last_sent"]["monthly"] != month_iso
    ):
        prev_month_last_day = now.date().replace(day=1) - datetime.timedelta(days=1)
        send_monthly_report(prev_month_last_day.year, prev_month_last_day.month, settings)
        settings_module.update_settings({"reports": {"last_sent": {"monthly": month_iso}}})


# ---------------------------------------------------------------------------
# Achtergrondtaak
# ---------------------------------------------------------------------------

def background_refresh():
    while True:
        settings = settings_module.load_settings()
        push_state_to_ha()
        push_savings_to_ha()
        try:
            check_and_send_reports()
        except Exception as e:  # noqa: BLE001
            print(f"[solar-reporter] Fout bij rapportcontrole: {e}", flush=True)

        interval = max(5, int(settings.get("refresh_interval_seconds", 10)))
        time.sleep(interval)


# ---------------------------------------------------------------------------
# Routes: pagina's
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", v=STATIC_VERSION)


@app.route("/settings")
def settings_page():
    return render_template("settings.html", v=STATIC_VERSION)


# ---------------------------------------------------------------------------
# Routes: tarieven
# ---------------------------------------------------------------------------

@app.route("/api/tariffs", methods=["GET"])
def get_tariffs():
    tariffs = load_tariffs()
    tariffs.sort(key=lambda t: t["valid_from"])

    today = datetime.date.today().isoformat()
    active_id = None
    for t in tariffs:
        if t["valid_from"] <= today:
            active_id = t["id"]
        else:
            break

    return jsonify({"tariffs": tariffs, "active_id": active_id})


@app.route("/api/tariffs", methods=["POST"])
def create_tariff():
    data = request.get_json(silent=True) or {}
    errors = validate_payload(data)
    if errors:
        return jsonify({"errors": errors}), 400

    tariffs = load_tariffs()
    new_tariff = {
        "id": uuid.uuid4().hex,
        "valid_from": data["valid_from"],
        "price": round(float(data["price"]), 7),
    }
    tariffs.append(new_tariff)
    save_tariffs(tariffs)
    push_state_to_ha()
    push_savings_to_ha()
    return jsonify(new_tariff), 201


@app.route("/api/tariffs/<tariff_id>", methods=["PUT"])
def update_tariff(tariff_id):
    data = request.get_json(silent=True) or {}
    errors = validate_payload(data)
    if errors:
        return jsonify({"errors": errors}), 400

    tariffs = load_tariffs()
    for t in tariffs:
        if t["id"] == tariff_id:
            t["valid_from"] = data["valid_from"]
            t["price"] = round(float(data["price"]), 7)
            save_tariffs(tariffs)
            push_state_to_ha()
            push_savings_to_ha()
            return jsonify(t)

    return jsonify({"errors": ["Tarief niet gevonden."]}), 404


@app.route("/api/tariffs/<tariff_id>", methods=["DELETE"])
def delete_tariff(tariff_id):
    tariffs = load_tariffs()
    remaining = [t for t in tariffs if t["id"] != tariff_id]
    if len(remaining) == len(tariffs):
        return jsonify({"errors": ["Tarief niet gevonden."]}), 404

    save_tariffs(remaining)
    push_state_to_ha()
    push_savings_to_ha()
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Routes: besparing (voor de widget op de hoofdpagina)
# ---------------------------------------------------------------------------

@app.route("/api/savings", methods=["GET"])
def get_savings():
    success, message, result = calculate_savings()
    if not success:
        return jsonify({"success": False, "message": message}), 200
    return jsonify({"success": True, **result})


# ---------------------------------------------------------------------------
# Routes: instellingen
# ---------------------------------------------------------------------------

@app.route("/api/ha/entities", methods=["GET"])
def get_ha_entities():
    """Geeft entiteiten terug uit Home Assistant, optioneel gefilterd op
    eenheid (bijv. 'W' of 'kWh'), voor de zoekbare dropdowns bij Entiteiten."""
    unit = request.args.get("unit", "")
    if not SUPERVISOR_TOKEN:
        return jsonify([])

    try:
        resp = requests.get(
            "http://supervisor/core/api/states",
            headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[solar-reporter] Kon entiteitenlijst niet ophalen: {e}", flush=True)
        return jsonify([])

    result = []
    for state in resp.json():
        attributes = state.get("attributes", {})
        if unit and attributes.get("unit_of_measurement") != unit:
            continue
        result.append({
            "entity_id": state.get("entity_id"),
            "friendly_name": attributes.get("friendly_name", state.get("entity_id")),
        })
    result.sort(key=lambda e: e["friendly_name"].lower())
    return jsonify(result)


@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(settings_module.load_settings())


@app.route("/api/settings", methods=["POST"])
def post_settings():
    partial = request.get_json(silent=True) or {}
    merged = settings_module.update_settings(partial)
    return jsonify(merged)


# ---------------------------------------------------------------------------
# Routes: afbeeldingen (voor afbeelding-elementen in de PDF-opmaak)
# ---------------------------------------------------------------------------

@app.route("/api/images", methods=["GET"])
def list_images():
    return jsonify(images_module.list_images())


@app.route("/api/images", methods=["POST"])
def upload_image():
    file = request.files.get("image")
    if not file:
        return jsonify({"success": False, "message": "Geen bestand ontvangen."}), 400
    image_id = images_module.save_image(file)
    return jsonify({"success": True, "id": image_id})


@app.route("/api/images/<image_id>", methods=["DELETE"])
def delete_image(image_id):
    ok = images_module.delete_image(image_id)
    return jsonify({"success": ok})


@app.route("/api/images/<image_id>/file", methods=["GET"])
def get_image_file(image_id):
    path = images_module.image_path(image_id)
    if not path:
        return "", 404
    return send_file(path)


# ---------------------------------------------------------------------------
# Routes: rapportages handmatig testen
# ---------------------------------------------------------------------------

@app.route("/api/reports/test-send/daily", methods=["POST"])
def test_send_daily():
    settings = settings_module.load_settings()
    today_iso = datetime.date.today().isoformat()
    ok, message = send_daily_report(today_iso, settings)
    return jsonify({"success": ok, "message": message})


@app.route("/api/reports/test-send/monthly", methods=["POST"])
def test_send_monthly():
    settings = settings_module.load_settings()
    today = datetime.date.today()
    ok, message = send_monthly_report(today.year, today.month, settings)
    return jsonify({"success": ok, "message": message})


# ---------------------------------------------------------------------------
# Routes: PDF-opmaak (editor)
# ---------------------------------------------------------------------------

@app.route("/api/reports/tags", methods=["GET"])
def get_report_tags():
    return jsonify(reports.AVAILABLE_TAGS)


@app.route("/api/settings/pdf-template/default", methods=["GET"])
def get_default_pdf_template():
    import copy
    kind = request.args.get("kind", "daily")
    if kind not in ("daily", "monthly"):
        kind = "daily"
    return jsonify(copy.deepcopy(settings_module.DEFAULTS["branding"]["pdf_template"][kind]))


@app.route("/api/reports/preview/<kind>", methods=["POST"])
def preview_report(kind):
    if kind not in ("daily", "monthly"):
        return jsonify({"success": False, "message": "Onbekend rapporttype."}), 400

    settings = settings_module.load_settings()
    payload = request.get_json(silent=True) or {}
    elements = payload.get("elements")
    if elements is None:
        elements = settings["branding"]["pdf_template"][kind]["elements"]

    today = datetime.date.today()
    if kind == "daily":
        hourly_kwh, total_kwh, total_euro, sav_kwh, sav_euro = build_daily_report_data(
            today.isoformat(), settings
        )
        context = _report_context(
            "Dagrapport stroomopbrengst", _dutch_full_date(today),
            total_kwh, total_euro, sav_kwh, sav_euro,
        )
        labels = [f"{h:02d}" for h in range(24)]
        pdf_bytes = reports.render_report_pdf(elements, context, labels, hourly_kwh, "kWh per uur")
    else:
        daily_kwh, daily_euro, total_kwh, total_euro, sav_kwh, sav_euro = build_monthly_report_data(
            today.year, today.month, settings
        )
        days_in_month = calendar.monthrange(today.year, today.month)[1]
        labels = [str(d) for d in range(1, days_in_month + 1)]
        values = [daily_kwh.get(d, 0.0) for d in range(1, days_in_month + 1)]
        maand_label = _dutch_month_year(today.year, today.month)
        context = _report_context(
            "Maandrapport stroomopbrengst", maand_label, total_kwh, total_euro, sav_kwh, sav_euro,
        )
        pdf_bytes = reports.render_report_pdf(elements, context, labels, values, "kWh per dag")

    return Response(pdf_bytes, mimetype="application/pdf")


if __name__ == "__main__":
    threading.Thread(target=background_refresh, daemon=True).start()
    app.run(host="0.0.0.0", port=8099)
