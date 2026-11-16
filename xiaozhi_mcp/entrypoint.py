"""Read private Supervisor options and drop root privileges before running MCP."""
import json
import os
import pwd

from ha_lights import validate_zones


def main():
    try:
        with open("/data/options.json", encoding="utf-8") as file:
            options = json.load(file)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"No se pudieron leer opciones: {type(exc).__name__}")
    endpoint = str(options.get("mcp_endpoint", "")).strip()
    if not endpoint.startswith("wss://"):
        raise SystemExit("Configura un mcp_endpoint wss:// válido en la aplicación.")
    country = str(options.get("country_code", "ES")).strip().upper()
    if len(country) != 2 or not country.isalpha():
        raise SystemExit("country_code debe contener dos letras ISO.")
    entries = options.get("light_zones", [])
    try:
        validate_zones(entries)
    except ValueError as exc:
        raise SystemExit(f"Catálogo de luces no válido: {exc}")
    token = str(options.get("ha_access_token", "")).strip()
    if entries and not token:
        raise SystemExit("Configura ha_access_token de un usuario HA no administrador")
    os.environ["MCP_ENDPOINT"] = endpoint
    os.environ["WEATHER_COUNTRY"] = country
    if token:
        os.environ["HA_ACCESS_TOKEN"] = token
    # Avoid environmental serialization of user settings; options are read from
    # protected Supervisor file once. Pass only the validated catalog to child.
    os.environ["LIGHT_ZONES_JSON"] = json.dumps(entries, ensure_ascii=False)
    if os.geteuid() == 0:
        account = pwd.getpwnam("app")
        os.setgroups([])
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
    from bridge import main as start
    start()


if __name__ == "__main__":
    main()
