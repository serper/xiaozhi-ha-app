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
    enabled = options.get("web_search_enabled", False)
    key = str(options.get("tavily_api_key", "")).strip()
    depth = options.get("web_search_depth", "basic")
    results = options.get("web_search_max_results", 5)
    limit = options.get("web_search_monthly_limit", 900)
    if enabled and (not key or any(ord(c) < 33 or ord(c) > 126 for c in key)
                    or depth not in ("basic", "advanced")
                    or type(results) is not int or not 1 <= results <= 10
                    or type(limit) is not int or not 1 <= limit <= 100000):
        raise SystemExit("Configuración de búsqueda web no válida")
    os.environ["WEB_SEARCH_ENABLED"] = "1" if enabled else "0"
    os.environ.pop("TAVILY_API_KEY", None)
    if enabled:
        os.environ["TAVILY_API_KEY"] = key
        os.environ["WEB_SEARCH_DEPTH"] = depth
        os.environ["WEB_SEARCH_MAX_RESULTS"] = str(results)
        os.environ["WEB_SEARCH_MONTHLY_LIMIT"] = str(limit)
    os.environ["MCP_ENDPOINT"] = endpoint
    os.environ["WEATHER_COUNTRY"] = country
    if token:
        os.environ["HA_ACCESS_TOKEN"] = token
    # Avoid environmental serialization of user settings; options are read from
    # protected Supervisor file once. Pass only the validated catalog to child.
    os.environ["LIGHT_ZONES_JSON"] = json.dumps(entries, ensure_ascii=False)
    # Supervisor's /data is protected; prepare a private, persistent DB
    # directory before dropping privileges. Never chmod/chown all of /data.
    scheduler_dir = "/data/scheduler"
    if os.geteuid() == 0:
        os.makedirs(scheduler_dir, mode=0o700, exist_ok=True)
        account = pwd.getpwnam("app")
        os.chown(scheduler_dir, account.pw_uid, account.pw_gid)
        os.chmod(scheduler_dir, 0o700)
        for filename in ("tasks.sqlite3", "tasks.sqlite3-wal", "tasks.sqlite3-shm"):
            pathname = os.path.join(scheduler_dir, filename)
            if os.path.exists(pathname):
                os.chown(pathname, account.pw_uid, account.pw_gid)
        
        if enabled:
            search_dir = "/data/web_search"
            os.makedirs(search_dir, mode=0o700, exist_ok=True)
            os.chown(search_dir, account.pw_uid, account.pw_gid)
            os.chmod(search_dir, 0o700)
            for filename in ("credits.sqlite3", "credits.sqlite3-journal"):
                pathname = os.path.join(search_dir, filename)
                if os.path.exists(pathname):
                    os.chown(pathname, account.pw_uid, account.pw_gid)
        os.setgroups([])
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
    from bridge import main as start
    start()


if __name__ == "__main__":
    main()
