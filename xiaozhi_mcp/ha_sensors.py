"""Read-only, explicitly allowlisted Home Assistant sensors."""
import json
import logging
import re
from urllib.request import Request, HTTPRedirectHandler, ProxyHandler, build_opener

from ha_lights import normalize, API_ROOT

LOGGER = logging.getLogger("sensors")
ENTITY_RE = re.compile(r"(sensor|binary_sensor)\.[a-z0-9_]+", re.ASCII)
MAX_RESPONSE = 256 * 1024


def validate_sensors(entries):
    if not isinstance(entries, list) or len(entries) > 100:
        raise ValueError("sensor_catalog debe ser una lista de máximo 100 entradas")
    sensors, aliases, entities = {}, {}, set()
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("Entrada de sensor inválida")
        name = item.get("name")
        eid = item.get("entity_id")
        alias_text = item.get("aliases", "")
        read = item.get("allow_read")
        if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 80
                or any(ord(ch) < 32 for ch in name) or not normalize(name)):
            raise ValueError("Nombre de sensor inválido")
        if not isinstance(eid, str) or len(eid) > 255 or not ENTITY_RE.fullmatch(eid):
            raise ValueError("Solo se permiten entidades sensor y binary_sensor")
        if not isinstance(alias_text, str) or len(alias_text) > 1000 or any(ord(ch) < 32 for ch in alias_text):
            raise ValueError("Alias de sensor inválido")
        if type(read) is not bool:
            raise ValueError("Permiso de consulta explícito requerido")
        canonical = normalize(name)
        if canonical in sensors or eid in entities:
            raise ValueError("Nombre o entidad de sensor duplicado")
        entities.add(eid)
        sensors[canonical] = {"name": name.strip(), "entity_id": eid, "allow_read": read}
        for alias in [name, *alias_text.split(",")]:
            normalized = normalize(alias)
            if not normalized:
                continue
            if len(normalized) > 80:
                raise ValueError("Alias demasiado largo")
            if aliases.setdefault(normalized, canonical) != canonical:
                raise ValueError("Alias ambiguo entre sensores")
    return sensors, aliases


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class HASensors:
    def __init__(self, entries, token):
        self.sensors, self.aliases = validate_sensors(entries)
        self.token = token

    def listar_sensores(self):
        return {"sensores": [entry["name"] for entry in self.sensors.values()
                             if entry["allow_read"]]}

    def consultar_sensor(self, nombre):
        if not isinstance(nombre, str) or len(nombre) > 100:
            return {"error": "Sensor no autorizado o desconocido"}
        entry = self.sensors.get(self.aliases.get(normalize(nombre)))
        if not entry or not entry["allow_read"]:
            return {"error": "Sensor no autorizado o desconocido"}
        try:
            req = Request(API_ROOT + "/states/" + entry["entity_id"],
                          headers={"Authorization": "Bearer " + self.token,
                                   "Accept": "application/json"}, method="GET")
            # Fixed internal destination; never forward credentials to redirects or proxies.
            with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=8) as response:
                raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ValueError("Respuesta demasiado grande")
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get("entity_id") != entry["entity_id"]:
                raise ValueError("Respuesta no válida")
            state = data.get("state")
            attrs = data.get("attributes")
            if not isinstance(state, str) or len(state) > 255 or not isinstance(attrs, dict):
                raise ValueError("Estado no válido")
            def scalar(value, max_length=100):
                return value if isinstance(value, str) and len(value) <= max_length else None
            domain = entry["entity_id"].split(".", 1)[0]
            return {"sensor": entry["name"], "tipo": domain, "estado": state,
                    "disponible": state not in ("unknown", "unavailable"),
                    "unidad": scalar(attrs.get("unit_of_measurement")),
                    "device_class": scalar(attrs.get("device_class")),
                    "ultimo_cambio": scalar(data.get("last_changed")),
                    "ultima_actualizacion": scalar(data.get("last_updated"))}
        except (OSError, ValueError, TypeError) as exc:
            LOGGER.warning("Error consultando sensor (%s)", type(exc).__name__)
            return {"error": "No se pudo consultar el sensor"}
