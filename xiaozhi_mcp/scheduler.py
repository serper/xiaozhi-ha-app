"""Persistent, restricted, one-shot light scheduler.

The database stores *zone names*, not entity IDs. Execution consults the current
local allowlist. An interrupted job is marked uncertain, never blindly replayed.
"""
import asyncio
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone

from ha_lights import HALights

LOG = logging.getLogger("scheduler")
DB_PATH = os.environ.get("SCHEDULER_DB", "/data/scheduler/tasks.sqlite3")
MAX_DELAY_SECONDS = 86400
MIN_DELAY_SECONDS = 1
MAX_PENDING = 50


def connect():
    db = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=10000")
    return db


def initialize():
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS jobs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          zone TEXT NOT NULL,
          action TEXT NOT NULL CHECK(action IN ('encender','apagar')),
          due_at REAL NOT NULL,
          created_at REAL NOT NULL,
          finished_at REAL,
          state TEXT NOT NULL CHECK(state IN ('pending','running','done','failed','cancelled','interrupted')),
          outcome TEXT NOT NULL DEFAULT ''
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS ix_jobs_due ON jobs(state,due_at)")
        # At-most-once invocation policy: after an unexpected process exit, a
        # running job may already have affected the real device. Do not replay.
        interrupted = db.execute(
            "UPDATE jobs SET state='interrupted', finished_at=?, outcome='Interrumpida: ejecución incierta' WHERE state='running'",
            (time.time(),),
        ).rowcount
        if interrupted:
            LOG.warning("%d tarea(s) interrumpidas; no se reejecutan automáticamente", interrupted)


def format_utc(timestamp):
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(timespec="seconds")


class Scheduler:
    def __init__(self, lights):
        self.lights = lights

    def programar_luz(self, zona, accion, retraso_segundos):
        if type(retraso_segundos) is not int or not MIN_DELAY_SECONDS <= retraso_segundos <= MAX_DELAY_SECONDS:
            return {"error": "Retraso permitido: 1 a 86400 segundos (24 horas)"}
        if accion not in ("encender", "apagar"):
            return {"error": "Solo se permite encender o apagar"}
        canonical, entities = self.lights.resolve(zona)
        if not entities or not all(e["control"] for e in entities):
            return {"error": "Zona desconocida o sin permiso de control"}
        now = time.time()
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute("SELECT COUNT(*) FROM jobs WHERE state='pending'").fetchone()[0]
            if count >= MAX_PENDING:
                db.execute("ROLLBACK")
                return {"error": "Límite de 50 tareas pendientes alcanzado"}
            cursor = db.execute(
                "INSERT INTO jobs(zone,action,due_at,created_at,state) VALUES(?,?,?,?, 'pending')",
                (canonical, accion, now + retraso_segundos, now),
            )
            db.execute("COMMIT")
        LOG.info("Tarea #%s programada: zona=%s, accion=%s, retraso=%ss", cursor.lastrowid, canonical, accion, retraso_segundos)
        return {"id_tarea": cursor.lastrowid, "zona": canonical, "accion": accion,
                "ejecucion_utc": format_utc(now + retraso_segundos), "estado": "programada"}

    def listar_tareas(self):
        with connect() as db:
            rows = db.execute(
                "SELECT id,zone,action,due_at FROM jobs WHERE state='pending' ORDER BY due_at,id LIMIT 50"
            ).fetchall()
        return {"tareas": [
            {"id_tarea": r["id"], "zona": r["zone"], "accion": r["action"],
             "ejecucion_utc": format_utc(r["due_at"])} for r in rows
        ]}

    def cancelar_tarea(self, id_tarea):
        if type(id_tarea) is not int or id_tarea < 1:
            return {"error": "Identificador de tarea inválido"}
        with connect() as db:
            changed = db.execute(
                "UPDATE jobs SET state='cancelled', finished_at=?, outcome='Cancelada por petición del usuario' WHERE id=? AND state='pending'",
                (time.time(), id_tarea),
            ).rowcount
        return {"id_tarea": id_tarea, "cancelada": bool(changed)}

    def claim_due(self):
        now = time.time()
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT id,zone,action FROM jobs WHERE state='pending' AND due_at<=? ORDER BY due_at,id LIMIT 1",
                (now,),
            ).fetchone()
            if not row:
                db.execute("COMMIT")
                return None
            db.execute("UPDATE jobs SET state='running' WHERE id=? AND state='pending'", (row["id"],))
            db.execute("COMMIT")
            return dict(row)

    def finish(self, job_id, state, outcome):
        with connect() as db:
            db.execute(
                "UPDATE jobs SET state=?, finished_at=?, outcome=? WHERE id=? AND state='running'",
                (state, time.time(), outcome[:250], job_id),
            )

    async def worker(self):
        initialize()
        while True:
            job = self.claim_due()
            if job is None:
                await asyncio.sleep(1.0)
                continue
            # Revalidate the *current* allowlist before execution. On app restart
            # a new catalog is loaded; removed permissions invalidate old jobs.
            zone, entities = self.lights.resolve(job["zone"])
            if not entities or not all(e["control"] for e in entities):
                self.finish(job["id"], "failed", "Permiso revocado o zona eliminada")
                LOG.warning("Tarea #%s denegada: permisos cambiados", job["id"])
                continue
            try:
                result = await asyncio.to_thread(self.lights.controlar_luz, zone, job["action"])
                outcomes = result.get("resultados", [])
                ok = bool(outcomes) and all(x["resultado"] == "solicitado" for x in outcomes)
                self.finish(job["id"], "done" if ok else "failed", "Solicitada a HA" if ok else "Error de servicio o permisos")
                LOG.info("Tarea #%s: %s", job["id"], "ejecutada" if ok else "fallida")
            except Exception as exc:
                # Do not leak tokens or request details in log.
                self.finish(job["id"], "failed", "Excepción de ejecución")
                LOG.warning("Tarea #%s falló (%s)", job["id"], type(exc).__name__)
