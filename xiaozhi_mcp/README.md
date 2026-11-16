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
