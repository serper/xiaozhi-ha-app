# Xiaozhi MCP - Open-Meteo (0.1.1)

App de Home Assistant OS probada en Raspberry Pi 5 (aarch64).

## Instalación desde GitHub

Añade `https://github.com/serper/xiaozhi-ha-app` en los repositorios de la tienda de aplicaciones de Home Assistant. Instala la aplicación e introduce tu endpoint privado `wss://...` de Xiaozhi.

## Instalación local

Copia `xiaozhi_mcp` a `/addons/xiaozhi_mcp`, recarga las aplicaciones locales e instala. Configura `mcp_endpoint` y opcionalmente `country_code` (por defecto `ES`), y activa el arranque automático.

La conexión registra `Conectado a Xiaozhi` y luego `ListToolsRequest` y `PingRequest`. Las consultas registran `CallToolRequest`.

La aplicación inicia exclusivamente conexiones salientes. No solicita acceso a la API de Home Assistant y no puede modificar entidades ni configuración.

**Seguridad:** no publiques el token del endpoint MCP. El arranque lee `/data/options.json` protegido, abandona privilegios y ejecuta el servicio con el usuario `app`.

La versión 0.1.1 corrige los permisos de lectura de las opciones de Supervisor de la v0.1.0.

## Próximas versiones

Catálogo de luces autorizado por zona, primero de consulta y después con órdenes opcionales de encendido/apagado. Sin llamadas genéricas a servicios ni acceso a la configuración de Home Assistant.
