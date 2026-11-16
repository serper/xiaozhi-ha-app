"""MCP stdio: weather lookups only. No Home Assistant API access."""
import json
import logging
import os
import unicodedata
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger('weather')
mcp = FastMCP('XiaozhiOpenMeteo')
COUNTRY = os.getenv('WEATHER_COUNTRY', 'ES')
CODES = {
    0: 'despejado', 1: 'mayormente despejado', 2: 'parcialmente nuboso',
    3: 'cubierto', 45: 'niebla', 48: 'niebla con escarcha',
    51: 'llovizna ligera', 53: 'llovizna', 55: 'llovizna intensa',
    61: 'lluvia ligera', 63: 'lluvia', 65: 'lluvia intensa',
    71: 'nieve ligera', 73: 'nieve', 75: 'nieve intensa',
    80: 'chubascos ligeros', 81: 'chubascos', 82: 'chubascos intensos',
    95: 'tormenta', 96: 'tormenta con granizo', 99: 'tormenta con granizo intenso',
}


def fetch_json(url, parameters):
    request = Request(f'{url}?{urlencode(parameters)}', headers={'User-Agent': 'XiaozhiMCPHomeAssistant/0.1'})
    with urlopen(request, timeout=12) as response:
        return json.load(response)


def normalize(value):
    value = unicodedata.normalize('NFKD', value)
    return ''.join(c for c in value if not unicodedata.combining(c)).casefold()


@mcp.tool()
def weather_spain(ciudad: str) -> dict:
    """Consulta tiempo actual y previsión de hoy en una ciudad española; elige ciudades de España, nunca homónimos extranjeros. Responde brevemente en español."""
    ciudad = ciudad.strip()
    if not 2 <= len(ciudad) <= 100 or any(ord(c) < 32 for c in ciudad):
        return {'error': 'Nombre de ciudad no válido'}
    try:
        places = fetch_json('https://geocoding-api.open-meteo.com/v1/search', {
            'name': ciudad, 'count': 100, 'language': 'es', 'format': 'json',
        })
        candidates = [r for r in places.get('results', []) if r.get('country_code') == COUNTRY]
        if not candidates:
            return {'error': f'No se encontró {ciudad} en {COUNTRY}'}
        candidates.sort(key=lambda r: (
            normalize(r.get('name', '')) == normalize(ciudad),
            r.get('population') or 0,
        ), reverse=True)
        place = candidates[0]
        forecast = fetch_json('https://api.open-meteo.com/v1/forecast', {
            'latitude': place['latitude'], 'longitude': place['longitude'],
            'current': 'temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m',
            'daily': 'temperature_2m_max,temperature_2m_min,precipitation_probability_max',
            'forecast_days': 1, 'timezone': 'auto',
        })
        current, daily = forecast['current'], forecast['daily']
        return {
            'ciudad': place['name'], 'provincia': place.get('admin2'),
            'pais': place.get('country', COUNTRY), 'observacion': current['time'],
            'temperatura_c': current['temperature_2m'],
            'sensacion_c': current['apparent_temperature'],
            'humedad_pct': current['relative_humidity_2m'],
            'viento_kmh': current['wind_speed_10m'],
            'estado': CODES.get(current['weather_code'], 'sin clasificar'),
            'maxima_hoy_c': daily['temperature_2m_max'][0],
            'minima_hoy_c': daily['temperature_2m_min'][0],
            'probabilidad_lluvia_pct': daily['precipitation_probability_max'][0],
            'fuente': 'Open-Meteo',
        }
    except Exception as exc:
        logger.exception('Error de consulta meteorológica')
        return {'error': 'No se pudo consultar Open-Meteo', 'tipo': type(exc).__name__}


# Register HA tools only when the administrator explicitly configures zones.
# Xiaozhi discovers exactly these two named operations; it has no generic API.
from ha_lights import HALights

_zone_entries = json.loads(os.environ.get("LIGHT_ZONES_JSON", "[]"))
if _zone_entries:
    _ha = HALights(_zone_entries, os.environ["SUPERVISOR_TOKEN"])

    @mcp.tool()
    def consultar_luz(zona: str) -> dict:
        """Consulta estado de la luz de una zona autorizada (ej. salón o cocina). No permite modificar nada."""
        return _ha.consultar_luz(zona)

    @mcp.tool()
    def controlar_luz(zona: str, accion: str) -> dict:
        """Enciende o apaga las luces de una zona autorizada. accion: 'encender' o 'apagar'. No permite otras acciones."""
        return _ha.controlar_luz(zona, accion)


if __name__ == '__main__':
    mcp.run(transport='stdio')
