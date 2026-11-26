"""Optional bounded Tavily search. No Home Assistant data is passed to the provider."""
import json
import logging
from contextlib import closing
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


logger = logging.getLogger("web_search")


class CreditBudget:
    """Reserve before sending; uncertain/failed requests are not refunded."""
    def __init__(self, path, limit):
        self.path = path
        self.limit = limit

    @staticmethod
    def month():
        return datetime.now(timezone.utc).strftime("%Y-%m")

    @staticmethod
    def schema(db):
        db.execute("CREATE TABLE IF NOT EXISTS credits "
                   "(month TEXT PRIMARY KEY, used INTEGER NOT NULL)")
        db.execute("""CREATE TABLE IF NOT EXISTS search_stats (
            month TEXT PRIMARY KEY,
            attempts INTEGER NOT NULL DEFAULT 0,
            success INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            cache_hits INTEGER NOT NULL DEFAULT 0,
            saved_credits INTEGER NOT NULL DEFAULT 0,
            blocked INTEGER NOT NULL DEFAULT 0,
            latency_ms INTEGER NOT NULL DEFAULT 0,
            tracked_credits INTEGER NOT NULL DEFAULT 0
        )""")

    def reserve(self, cost, month=None):
        month = month or self.month()
        with closing(sqlite3.connect(self.path, timeout=3)) as db, db:
            self.schema(db)
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO search_stats(month) VALUES (?)", (month,))
            row = db.execute("SELECT used FROM credits WHERE month=?", (month,)).fetchone()
            used = row[0] if row else 0
            if used + cost > self.limit:
                db.execute("UPDATE search_stats SET blocked=blocked+1 WHERE month=?", (month,))
                return False
            db.execute("INSERT INTO credits VALUES (?, ?) "
                       "ON CONFLICT(month) DO UPDATE SET used=excluded.used",
                       (month, used + cost))
            db.execute("UPDATE search_stats SET attempts=attempts+1, "
                       "tracked_credits=tracked_credits+? WHERE month=?", (cost, month))
            return True

    def record(self, month, event, amount=0):
        with closing(sqlite3.connect(self.path, timeout=3)) as db, db:
            self.schema(db)
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO search_stats(month) VALUES (?)", (month,))
            if event == "cache":
                db.execute("UPDATE search_stats SET cache_hits=cache_hits+1, "
                           "saved_credits=saved_credits+? WHERE month=?", (amount, month))
            elif event in ("success", "failed"):
                # Column chosen only from this fixed allowlist.
                db.execute(f"UPDATE search_stats SET {event}={event}+1, "
                           "latency_ms=latency_ms+? WHERE month=?", (amount, month))
            else:
                raise ValueError("Invalid statistics event")

    def statistics(self, month=None):
        month = month or self.month()
        with closing(sqlite3.connect(self.path, timeout=3)) as db, db:
            self.schema(db)
            db.execute("BEGIN")
            row = db.execute("SELECT used FROM credits WHERE month=?", (month,)).fetchone()
            used = row[0] if row else 0
            row = db.execute("SELECT attempts, success, failed, cache_hits, saved_credits, "
                             "blocked, latency_ms, tracked_credits FROM search_stats WHERE month=?",
                             (month,)).fetchone()
            attempts, success, failed, hits, saved, blocked, latency, tracked = row or (0,) * 8
        completed = success + failed
        return {
            "month_utc": month,
            "source": "local_addon",
            "reserved_credits": used,
            "monthly_limit": self.limit,
            "remaining_local_credits": max(0, self.limit - used),
            "usage_percent": round(100 * used / self.limit, 1),
            "credits_before_statistics": max(0, used - tracked),
            "provider_attempts": attempts,
            "successful_searches": success,
            "failed_searches": failed,
            "unfinished_or_unknown_attempts": max(0, attempts - completed),
            "cache_hits": hits,
            "estimated_credits_saved": saved,
            "blocked_by_budget": blocked,
            "average_provider_latency_ms": round(latency / completed) if completed else None,
            "note": "Créditos reservados locales, no saldo real de la cuenta Tavily. "
                    "Los contadores detallados comienzan en v0.4.1.",
        }


class WebSearch:
    def __init__(self, provider, budget, ttl=300):
        self.provider = provider
        self.budget = budget
        self.ttl = ttl
        self.cache = OrderedDict()
        self.lock = Lock()

    def statistics(self):
        try:
            return self.budget.statistics()
        except Exception:
            return {"error": "No se pudieron leer las estadísticas locales"}

    def log_statistics(self):
        stats = self.statistics()
        if "error" in stats:
            logger.warning("Estadísticas Tavily no disponibles")
        else:
            logger.info("Tavily UTC %s: créditos reservados %d/%d; intentos %d; "
                        "éxitos %d; fallos %d; caché %d; bloqueos %d",
                        stats["month_utc"], stats["reserved_credits"], stats["monthly_limit"],
                        stats["provider_attempts"], stats["successful_searches"],
                        stats["failed_searches"], stats["cache_hits"], stats["blocked_by_budget"])

    def _record(self, month, event, amount):
        try:
            self.budget.record(month, event, amount)
        except Exception:
            logger.warning("No se pudo registrar un evento estadístico de Tavily")

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
        reserved = False
        completed = False
        started = None
        month = None
        try:
            month = self.budget.month()
            now = time.monotonic()
            entry = self.cache.get(key)
            if entry and entry[0] > now:
                self.cache.move_to_end(key)
                self._record(month, "cache", self.provider.cost)
                return entry[1]
            if not self.budget.reserve(self.provider.cost, month):
                return {"error": "Límite mensual local de búsqueda alcanzado"}
            reserved = True
            started = time.monotonic()
            result = self.provider.search(query, topic, time_range)
            completed = True
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
            try:
                if reserved:
                    self._record(month, "success" if completed else "failed",
                                 round((time.monotonic() - started) * 1000))
                self.log_statistics()
            finally:
                self.lock.release()
