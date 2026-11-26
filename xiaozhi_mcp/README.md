# Xiaozhi MCP — Home Assistant App v0.3.0

Open-Meteo and optionally controlled Home Assistant lights, with friendly names.

## Installation

Add `https://github.com/serper/xiaozhi-ha-app` to **Settings → Apps → App Store → Repositories** in Home Assistant and install **Xiaozhi MCP**. The application downloads prebuilt `aarch64` and `amd64` images from GHCR; the images must be published before installation.

Configure `mcp_endpoint` with the **private** Xiaozhi WebSocket MCP endpoint, and optionally `country_code` (defaults to ES). For lighting, create a dedicated **non-administrator** Home Assistant user and create a long-lived access token in that user's profile. Enter it into `ha_access_token` (password field). The weather tool works without this token.

## Editable zone catalog

The `light_zones` option is a list of rows in the app configuration form. Example (fictional entity IDs):

```yaml
light_zones:
  - zone: Salón
    aliases: "sala, estar"
    entity_id: light.example_living_room
    allow_read: true
    allow_control: false
  - zone: Cocina
    aliases: "cocina"
    entity_id: switch.example_kitchen_lights
    allow_read: true
    allow_control: false
```

**Each row describes one entity.** Repeat a zone with the same aliases to group several entities. Allowed entity domains are `light` and `switch`, specifically configured by the administrator. Dangerous-looking switch entities for relay-disconnection mode, turbo mode and network LEDs are rejected. Avoid adding switches that control appliances.

By default `light_zones: []` means **no access to Home Assistant entities**, and `allow_control: false` means read-only. A zone can only be controlled when **every entity in that zone** has `allow_control: true`. The control tool accepts only `encender` and `apagar`, never toggle, arbitrary service names, automations or settings.

Allowed spoken requests:
- “¿Está encendida la luz del salón?” → `consultar_luz(zona="salón")`
- “Apaga la luz de la cocina” → `controlar_luz(zona="cocina", accion="apagar")` if allowed

You can update the catalog in the Home Assistant application configuration, save it, and restart the app; no Docker rebuild is required.

## Planificador persistente (v0.3.0)

Xiaozhi puede programar, consultar y cancelar órdenes **puntuales** de encendido/apagado:

- «Apaga la luz de la cocina en un minuto» → `programar_luz(zona="cocina", accion="apagar", retraso_segundos=60)`
- «¿Qué órdenes de luces hay pendientes?» → `listar_tareas()`
- «Cancela la tarea 4» → `cancelar_tarea(id_tarea=4)`

**No simules el tiempo transcurrido.** Programar una tarea solo devuelve la confirmación e identificador; la Raspberry Pi ejecuta la orden posteriormente, aunque el ESP32 o Xiaozhi se desconecten.

El planificador admite retrasos de 1 a 86400 segundos y 50 tareas pendientes, y guarda SQLite en `/data/scheduler/tasks.sqlite3`, persistente entre actualizaciones de la misma aplicación. No crea automatizaciones de Home Assistant. No hay recurrencias ni programación por hora absoluta en esta versión.

La autorización se comprueba al programar y **otra vez al ejecutar**, utilizando el catálogo cargado al arrancar la app. Tras cambiar permisos en las opciones, reinicia la aplicación para que la política activa se actualice. Si una tarea estaba ejecutándose al interrumpirse el proceso, se marca `interrupted` en el siguiente inicio y **no se repite automáticamente**, porque podría haber ejecutado ya su acción. La confirmación `Solicitada a HA` significa que la llamada fue aceptada, no que el estado físico se verificó.

La cancelación solo afecta a tareas todavía `pending`; una tarea ya iniciada no se puede cancelar de forma fiable.

## Security warning

The app deliberately does **not** request `homeassistant_api: true`, which would provide an administrator-equivalent Supervisor token. Instead, lighting calls use the dedicated non-admin user's `ha_access_token` against the internal Home Assistant Core API. This account cannot manage Home Assistant settings. Home Assistant's ordinary user roles are **not** a fine-grained per-entity authorization system, so the local explicit allowlist is still essential. The app never exposes a generic service, shell, configuration or automation tool.

Do not share `/data/options.json` , your HA access token or your Xiaozhi endpoint, which embeds a secret token. The connection is outbound only. No inbound ports are needed.

## Release

The `.github/workflows/release.yml` workflow builds ARM64 and AMD64 images with native GitHub runners and publishes a GHCR multi-architecture manifest tagged with the exact `version` in `config.yaml`. Run it on a release ref or via **Actions → Build and publish Home Assistant app → Run workflow** after checks pass. Keep GHCR package visibility public for unauthenticated Home Assistant installations.

## Verification

The automated tests prove zone parsing, ambiguity detection, denied operations, dangerous switches rejection and exact fixed service paths. They do not constitute an integration test of Supervisor or a physical end-to-end Home Assistant deployment.

## Optional web search (Tavily)

Disabled by default. Obtain a key at https://app.tavily.com/ and enter it in the add-on configuration, then enable web search and restart. Never commit or share the key.

```yaml
web_search_enabled: true
web_search_depth: basic
web_search_max_results: 5
web_search_monthly_limit: 900
```

The MCP tool `web_search` accepts a public query, topic (general/news) and optional time_range (day/week/month/year). Weather remains on Open-Meteo. Basic/advanced reserve 1/2 credits respectively. The local UTC calendar-month budget persists in /data/web_search; failed or ambiguous calls are conservatively counted. It does not account for other clients using your Tavily account. Successful results are cached in memory for five minutes (64 entries); reconnects clear the cache. Queries are sent to Tavily; do not include private information. External results are untrusted, and the tool description instructs the model not to follow embedded instructions; this is not a complete prompt-injection defense. No automatic retries. The HTTP socket timeout is eight seconds, not a guaranteed overall wall-clock deadline.

### Local search statistics (0.4.1)

Ask Xiaozhi about Tavily credits or search usage; the new read-only MCP tool `web_search_statistics` returns the current UTC calendar month's local reserved credits, configured limit, remaining local credits, attempts, completed successes/failures, unknown attempts, cache hits, estimated credits saved, budget blocks and mean completed provider latency. The same compact counters are logged on MCP startup/reconnect and after searches, without queries or credentials. Invalid or concurrent-rejected calls are excluded. The existing credit database is migrated in place: earlier reservations are retained and shown separately; historical detailed counts cannot be reconstructed. Statistics calls do not contact Tavily. The local budget is not the actual Tavily account balance, and may differ because failures are conservatively reserved, account billing periods differ or other clients use the key. No Home Assistant entities are created.
