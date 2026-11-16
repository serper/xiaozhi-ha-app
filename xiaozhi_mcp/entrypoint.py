"""Read Supervisor options; never print the MCP endpoint/token."""
import json
import os
import pwd


def main():
    try:
        with open('/data/options.json', encoding='utf-8') as file:
            options = json.load(file)
    except (OSError, ValueError) as exc:
        raise SystemExit(f'No se pudieron leer opciones: {type(exc).__name__}')
    endpoint = options.get('mcp_endpoint', '').strip()
    if not endpoint.startswith('wss://'):
        raise SystemExit('Configura un mcp_endpoint wss:// válido en la aplicación.')
    country = options.get('country_code', 'ES').strip().upper()
    if len(country) != 2 or not country.isalpha():
        raise SystemExit('country_code debe contener dos letras ISO, por ejemplo ES.')
    os.environ['MCP_ENDPOINT'] = endpoint
    os.environ['WEATHER_COUNTRY'] = country
    # Supervisor options are protected. Read them first, then permanently drop privileges.
    if os.geteuid() == 0:
        account = pwd.getpwnam('app')
        os.setgroups([])
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
    from bridge import main as start
    start()


if __name__ == '__main__':
    main()
