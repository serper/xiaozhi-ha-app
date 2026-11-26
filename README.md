# Xiaozhi MCP for Home Assistant

Home Assistant App providing MCP tools to **Xiaozhi AI**. Version 0.3.0 adds a persistent SQLite scheduler for delayed light on/off operations, while retaining editable lighting zones and Open-Meteo.

**Status:** v0.1.1 has been validated on a real Raspberry Pi 5; v0.3.0 requires CI, GHCR image publication and a Home Assistant integration test before being considered production-ready.

## Install

1. Home Assistant → **Settings → Apps → App Store → Repositories**.
2. Add `https://github.com/serper/xiaozhi-ha-app`.
3. Install **Xiaozhi MCP - Open-Meteo**.
4. Configure `mcp_endpoint` with your personal `wss://...` endpoint from the Xiaozhi console.
5. Start the app. Check for `Conectado a Xiaozhi` and `ListToolsRequest` in logs, then ask Xiaozhi about the weather.

If migrating from a local app, stop the local installation first. A repository app is a separate Supervisor installation; copy your endpoint privately to the new app and avoid running duplicate tools.

## Features

- MCP tool `weather_spain(ciudad)` with Open-Meteo; default country `ES`
- Outbound-only WebSocket connection and automatic reconnect
- Runs unprivileged after loading protected Supervisor options
- Optional non-administrator Home Assistant long-lived token for explicitly allowlisted lights
- Fixed read/turn_on/turn_off endpoints only; no Supervisor API permissions
- No incoming TCP listeners, no exposure of Home Assistant configuration

## Security

**Never upload your MCP endpoint, tokens or `/data/options.json`.** The endpoint is secret and must remain in app options. Version 0.2.0 never exposes a generic Home Assistant API and will not access any entity unless you configure it. For lights, create a dedicated non-administrator Home Assistant user and put its long-lived access token in the private app options. All allow_control switches are off by default.

## Roadmap

- v0.2: Editable light zones, voice aliases, optional read and on/off permissions
- v0.3: One-shot persistent delayed lighting actions, task listing and cancellation
- v0.2: Native ARM64/AMD64 GHCR image workflow
- Next: Physical HA integration checks, finer UX and additional tools

See [app documentation](xiaozhi_mcp/README.md).

Licensed under [MIT](LICENSE).

### Optional web search (0.4.0)

Tavily public web search, disabled by default, with local persistent credit limits and a short-lived in-memory cache. See the [add-on documentation](xiaozhi_mcp/README.md).

Version 0.4.1 adds persistent local Tavily usage statistics, available by voice and in add-on logs, without consuming search credits.
