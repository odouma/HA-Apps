"""
MQTT Discovery: groepeert onze sensoren onder één apparaat 'Solar Reporter'
in Home Assistant (Instellingen -> Apparaten & services -> MQTT).

Dit vereist een MQTT-broker (bijv. de 'Mosquitto broker' app) en de MQTT-
integratie in Home Assistant. Zonder MQTT-configuratie doet deze module
niets, en blijft de addon werken via de gewone Core API (states), alleen
dan niet gegroepeerd onder één apparaat.
"""
import json
import threading
import time

try:
    import paho.mqtt.client as mqtt
except ImportError:  # zou niet moeten gebeuren, maar voorkomt harde crash
    mqtt = None

DEVICE_ID = "stroomtarieven"  # blijft ongewijzigd: dit is de opgeslagen HA-apparaat-identiteit
DISCOVERY_PREFIX = "homeassistant"

DEVICE_INFO = {
    "identifiers": [DEVICE_ID],
    "name": "Solar Reporter",
    "manufacturer": "Eigen addon",
    "model": "Solar Reporter addon",
}

# entity_key -> (component, config)
ENTITY_DEFS = {
    "actief_tarief": {
        "component": "sensor",
        "name": "Stroomtarief (actief)",
        "unit_of_measurement": "EUR/kWh",
        "device_class": "monetary",
        "state_class": "measurement",
        "icon": "mdi:flash",
    },
    "besparing_vandaag": {
        "component": "sensor",
        "name": "Stroombesparing vandaag",
        "unit_of_measurement": "EUR",
        "device_class": "monetary",
        "state_class": "measurement",
        "icon": "mdi:cash-plus",
    },
    "besparing_totaal": {
        "component": "sensor",
        "name": "Stroombesparing totaal",
        "unit_of_measurement": "EUR",
        "device_class": "monetary",
        "state_class": "measurement",
        "icon": "mdi:cash-multiple",
    },
    "opbrengst_vandaag": {
        "component": "sensor",
        "name": "Stroomopbrengst vandaag",
        "unit_of_measurement": "kWh",
        "device_class": "energy",
        "state_class": "measurement",
        "icon": "mdi:solar-power",
    },
    "opbrengst_totaal": {
        "component": "sensor",
        "name": "Stroomopbrengst totaal",
        "unit_of_measurement": "kWh",
        "device_class": "energy",
        "state_class": "measurement",
        "icon": "mdi:solar-power-variant",
    },
}

_client = None
_client_lock = threading.Lock()
_connected = False


def _on_connect(client, userdata, flags, rc, properties=None):
    global _connected
    _connected = rc == 0
    if _connected:
        _publish_discovery(client)


def _on_disconnect(client, userdata, rc, properties=None):
    global _connected
    _connected = False


def _state_topic(entity_key):
    return f"{DISCOVERY_PREFIX}/sensor/{DEVICE_ID}_{entity_key}/state"


def _attributes_topic(entity_key):
    return f"{DISCOVERY_PREFIX}/sensor/{DEVICE_ID}_{entity_key}/attributes"


def _config_topic(entity_key):
    return f"{DISCOVERY_PREFIX}/sensor/{DEVICE_ID}_{entity_key}/config"


def _publish_discovery(client):
    for entity_key, definition in ENTITY_DEFS.items():
        config = {
            "name": definition["name"],
            "unique_id": f"{DEVICE_ID}_{entity_key}",
            "state_topic": _state_topic(entity_key),
            "json_attributes_topic": _attributes_topic(entity_key),
            "unit_of_measurement": definition.get("unit_of_measurement"),
            "device_class": definition.get("device_class"),
            "state_class": definition.get("state_class"),
            "icon": definition.get("icon"),
            "device": DEVICE_INFO,
        }
        client.publish(_config_topic(entity_key), json.dumps(config), retain=True)


def ensure_connected(mqtt_settings):
    """Zorgt dat er een (herbruikbare) MQTT-verbinding is als MQTT aan staat
    in de instellingen. Retourneert True als de client klaar is voor gebruik."""
    global _client, _connected

    if mqtt is None or not mqtt_settings.get("enabled"):
        return False

    with _client_lock:
        if _client is not None:
            return _connected

        client = mqtt.Client(client_id="ha_stroomtarieven", protocol=mqtt.MQTTv311)
        username = mqtt_settings.get("username") or ""
        password = mqtt_settings.get("password") or ""
        if username:
            client.username_pw_set(username, password)

        client.on_connect = _on_connect
        client.on_disconnect = _on_disconnect

        try:
            client.connect(
                mqtt_settings.get("host", "core-mosquitto"),
                int(mqtt_settings.get("port", 1883)),
                keepalive=60,
            )
            client.loop_start()
        except Exception as e:  # noqa: BLE001 - we willen hier alles vangen
            print(f"[solar-reporter] MQTT-verbinding mislukt: {e}", flush=True)
            _client = None
            return False

        _client = client

        # geef de achtergrondloop even de tijd om te verbinden
        for _ in range(20):
            if _connected:
                break
            time.sleep(0.1)

        return _connected


def publish_state(entity_key, state, attributes=None):
    """Publiceert de state (en attributen) van één van onze entiteiten via
    MQTT. Doet niets als MQTT niet verbonden is."""
    if _client is None or not _connected:
        return False

    _client.publish(_state_topic(entity_key), str(state), retain=True)
    if attributes is not None:
        _client.publish(_attributes_topic(entity_key), json.dumps(attributes), retain=True)
    return True


def disconnect():
    global _client, _connected
    with _client_lock:
        if _client is not None:
            try:
                _client.loop_stop()
                _client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        _client = None
        _connected = False
