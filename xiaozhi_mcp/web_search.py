"""Optional bounded Tavily search. No Home Assistant data is passed to the provider."""
import json
import sqlite3
import time
from collections import OrderedDict
from datetime import datetime, timezone
from threading import Lock
from typing import Protocol
from urllib.error import HTTPError
from urllib.request import Request, HTTPRedirectHandler, build_opener


class SearchProvider(Protocol):
    def search(self, query: str, topic: str, time_range: str | None) -> dict: ...


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class TavilyProvider:
    def __init__(self, api_key, depth="basic", max_results=5):
        self.api_key = api_key
        self.depth = depth
        self.max_results = max_results
        self.cost = 1 if depth == "basic" else 2

    def search(self, query, topic, time_range):
        payload = {
            "query": query, "topic": topic, "search_depth": self.depth,
            "max_results": self.max_results, "auto_parameters": False,
            "include_answer": True, "include_raw_content": False,
            "include_images": False,
        }
        if time_range:
            payload["time_range"] = time_range
        request = Request(
            "https://api.tavily.com/search",
            data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + self.api_key,
                     "Content-Type": "application/json"},
            method="POST",
        )
        with build_opener(NoRedirect()).open(request, timeout=8) as response:
            raw = response.read(512 * 1024 + 1)
        if len(raw) > 512 * 1024:
            raise ValueError("Response too large")
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise ValueError("Invalid response")

        def clip(value, length):
            return value[:length] if isinstance(value, str) else ""

        results = [
            {"title": clip(item.get("title"), 200),
             "url": clip(item.get("url"), 1000),
             "content": clip(item.get("content"), 1000)}
            for item in data["results"][:self.max_results]
            if isinstance(item, dict)
        ]
        return {"source": "Tavily", "untrusted_external_content": True,
                "answer": clip(data.get("answer"), 1500), "results": results}


class CreditBudget:
    """Reserve before sending; uncertain/failed requests are not refunded."""
    def __init__(self, path, limit):
        self.path = path
        self.limit = limit

    def reserve(self, cost):
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        with sqlite3.connect(self.path, timeout=3) as db:
            db.execute("CREATE TABLE IF NOT EXISTS credits "
                       "(month TEXT PRIMARY KEY, used INTEGER NOT NULL)")
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT used FROM credits WHERE month=?", (month,)).fetchone()
            used = row[0] if row else 0
            if used + cost > self.limit:
                return False
            db.execute("INSERT INTO credits VALUES (?, ?) "
                       "ON CONFLICT(month) DO UPDATE SET used=excluded.used",
                       (month, used + cost))
            return True


class WebSearch:
    def __init__(self, provider, budget, ttl=300):
        self.provider = provider
        self.budget = budget
        self.ttl = ttl
        self.cache = OrderedDict()
        self.lock = Lock()

    def search(self, query, topic="general", time_range=None):
        query = query.strip()
        if not 2 <= len(query) <= 400 or any(ord(c) < 32 for c in query):
            return {"error": "Consulta no válida"}
        if topic not in ("general", "news") or time_range not in (None, "day", "week", "month", "year"):
            return {"error": "Filtro de búsqueda no válido"}
        key = (query, topic, time_range)
        # Avoid parallel requests and duplicate charges in this MCP process.
        if not self.lock.acquire(blocking=False):
            return {"error": "Hay otra búsqueda en curso"}
        try:
            now = time.monotonic()
            entry = self.cache.get(key)
            if entry and entry[0] > now:
                self.cache.move_to_end(key)
                return entry[1]
            if not self.budget.reserve(self.provider.cost):
                return {"error": "Límite mensual local de búsqueda alcanzado"}
            result = self.provider.search(query, topic, time_range)
            self.cache[key] = (time.monotonic() + self.ttl, result)
            self.cache.move_to_end(key)
            while len(self.cache) > 64:
                self.cache.popitem(last=False)
            return result
        except HTTPError as exc:
            if exc.code in (401, 403):
                return {"error": "Tavily: credenciales o permisos no válidos"}
            if exc.code in (429, 432, 433):
                return {"error": "Tavily: cuota o frecuencia de consultas excedida"}
            return {"error": "Tavily no disponible"}
        except Exception:
            # Do not serialize exceptions, queries, response bodies or credentials.
            return {"error": "No se pudo completar la búsqueda"}
        finally:
            self.lock.release()
