# Xiaozhi MCP for Home Assistant

Home Assistant App providing MCP tools to **Xiaozhi AI**. The initial release uses Open-Meteo for weather reports.

**Status:** v0.1.1 has been tested with Raspberry Pi 5 / Home Assistant OS (aarch64). No Home Assistant entity access is implemented yet.

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
- No Home Assistant API token or Supervisor permissions
- No incoming TCP listeners, no exposure of Home Assistant configuration

## Security

**Never upload your MCP endpoint, tokens or `/data/options.json`.** The endpoint is secret and must remain in app options. Version 0.1.1 cannot turn on lights or alter any Home Assistant settings.

## Roadmap

- Editable mapping of friendly voice zones to Home Assistant lights
- Read-only state queries
- Optional allowlisted on/off control, never generic service execution
- Additional MCP tools, CI and prebuilt release images

See [app documentation](xiaozhi_mcp/README.md).

Licensed under [MIT](LICENSE).
