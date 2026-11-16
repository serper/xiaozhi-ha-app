"""Restricted Home Assistant lighting tools for Xiaozhi MCP.

All entity IDs come from local Supervisor settings, never from model input.
Use a dedicated non-administrator Home Assistant account and its long-lived
access token, plus local explicit allowlists and fixed permitted endpoints.
"""
import json
import logging
import os
import re
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

LOGGER = logging.getLogger("lights")
ENTITY_RE = re.compile(r"^(light|switch)\.[a-z0-9_]+$")
BLOCKED_SWITCH_PARTS = ("desconectar_rele", "modo_turbo", "led_de_red", "engineering_mode")
API_ROOT = "http://homeassistant:8123/api"


def normalize(s):
    s = unicodedata.normalize("NFKD", s.strip())
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).lower().split())


def validate_zones(entries):
    if not isinstance(entries, list) or len(entries) > 100:
        raise ValueError("light_zones debe ser una lista de máximo 100 entradas")
    zones = {}
    aliases = {}
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("Entrada de zona inválida")
        zone = normalize(str(item.get("zone", "")))
        if not zone or len(zone) > 80:
            raise ValueError("Nombre de zona inválido")
        eid = str(item.get("entity_id", "")).strip()
        match = ENTITY_RE.fullmatch(eid)
        if not match or (match.group(1) == "switch" and any(x in eid for x in BLOCKED_SWITCH_PARTS)):
            raise ValueError("Entidad no permitida en catálogo")
        if type(item.get("allow_read", True)) is not bool or type(item.get("allow_control", False)) is not bool:
            raise ValueError("Permisos de zona inválidos")
        read = item.get("allow_read", True)
        control = item.get("allow_control", False)
        if control and not read:
            raise ValueError("El control requiere permiso de consulta")
        entries_for_zone = zones.setdefault(zone, [])
        if any(e["id"] == eid for e in entries_for_zone):
            raise ValueError("Entidad duplicada en la zona")
        entries_for_zone.append({"id": eid, "read": read, "control": control})
        names = [zone, *(x for x in str(item.get("aliases", "")).split(","))]
        for name in names:
            normalized = normalize(name)
            if not normalized:
                continue
            if len(normalized) > 80:
                raise ValueError("Alias demasiado largo")
            previous = aliases.setdefault(normalized, zone)
            if previous != zone:
                raise ValueError("Alias ambiguo entre zonas")
    return {"zones": zones, "aliases": aliases}


class HALights:
    def __init__(self, entries, token, url=API_ROOT):
        catalog = validate_zones(entries)
        self.zones = catalog["zones"]
        self.aliases = catalog["aliases"]
        self.token = token
        self.url = url.rstrip("/")

    def resolve(self, zona):
        if not isinstance(zona, str) or len(zona) > 100:
            return None, None
        canonical = self.aliases.get(normalize(zona))
        return canonical, self.zones.get(canonical) if canonical else None

    def request(self, method, path, payload=None):
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/json"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        req = Request(self.url + path, data=data, headers=headers, method=method)
        with urlopen(req, timeout=8) as response:
            return json.load(response)

    def consultar_luz(self, zona):
        canonical, entries = self.resolve(zona)
        if not entries:
            return {"error": "Zona no autorizada o desconocida"}
        readable = [x for x in entries if x["read"]]
        if not readable:
            return {"error": "Consulta no autorizada para esta zona"}
        result = []
        for item in readable:
            try:
                state = self.request("GET", "/states/" + quote(item["id"], safe="."))
                result.append({"entidad": item["id"], "estado": state.get("state", "unknown")})
            except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
                LOGGER.warning("Error consultando luz (%s)", type(exc).__name__)
                result.append({"entidad": item["id"], "estado": "error"})
        return {"zona": canonical, "luces": result}

    def controlar_luz(self, zona, accion):
        if accion not in ("encender", "apagar"):
            return {"error": "Acción no autorizada"}
        canonical, entries = self.resolve(zona)
        if not entries:
            return {"error": "Zona no autorizada o desconocida"}
        if not all(x["control"] for x in entries):
            return {"error": "Control no autorizado para toda la zona"}
        # Switches are permitted only if explicitly configured, never by discovery.
        action = "turn_on" if accion == "encender" else "turn_off"
        result = []
        for item in entries:
            domain = item["id"].split(".", 1)[0]
            try:
                self.request("POST", f"/services/{domain}/{action}", {"entity_id": item["id"]})
                result.append({"entidad": item["id"], "resultado": "solicitado"})
                LOGGER.info("Control autorizado: zona=%s accion=%s entidad=%s", canonical, accion, item["id"])
            except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
                LOGGER.warning("Error en control de luz (%s)", type(exc).__name__)
                result.append({"entidad": item["id"], "resultado": "error"})
        return {"zona": canonical, "accion": accion, "resultados": result}
