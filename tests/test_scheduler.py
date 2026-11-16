"""No hardware calls: test scheduling, persistence, cancellation and permissions."""
import asyncio
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "xiaozhi_mcp"))
from ha_lights import HALights
import scheduler


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = scheduler.DB_PATH
        scheduler.DB_PATH = os.path.join(self.tmp.name, "tasks.sqlite3")
        scheduler.initialize()
        self.entries = [{"zone": "Cocina", "aliases": "", "entity_id": "light.fake_cocina",
                         "allow_read": True, "allow_control": True}]
        self.lights = HALights(self.entries, "TEST")
        self.jobs = scheduler.Scheduler(self.lights)

    def tearDown(self):
        scheduler.DB_PATH = self.old_db
        self.tmp.cleanup()

    def test_schedule_and_persist(self):
        result = self.jobs.programar_luz("cocina", "apagar", 60)
        self.assertEqual(result["estado"], "programada")
        other = scheduler.Scheduler(self.lights)
        self.assertEqual(other.listar_tareas()["tareas"][0]["id_tarea"], result["id_tarea"])
        self.assertIsNone(other.claim_due())

    def test_reject_invalid_delay_action_zone(self):
        for delay in (0, -10, 86401, True, 1.5, "60"):
            self.assertIn("error", self.jobs.programar_luz("cocina", "apagar", delay))
        self.assertIn("error", self.jobs.programar_luz("cocina", "toggle", 60))
        self.assertIn("error", self.jobs.programar_luz("not-a-zone", "apagar", 60))
        self.assertEqual(self.jobs.listar_tareas()["tareas"], [])

    def test_read_only_cannot_schedule(self):
        entries = [dict(self.entries[0], allow_control=False)]
        ro = scheduler.Scheduler(HALights(entries, "TEST"))
        self.assertIn("error", ro.programar_luz("cocina", "apagar", 60))

    def test_cancel_prevents_claim(self):
        job = self.jobs.programar_luz("cocina", "apagar", 1)
        self.assertTrue(self.jobs.cancelar_tarea(job["id_tarea"])["cancelada"])
        self.assertFalse(self.jobs.cancelar_tarea(job["id_tarea"])["cancelada"])
        with scheduler.connect() as db:
            db.execute("UPDATE jobs SET due_at=? WHERE id=?", (time.time() - 1, job["id_tarea"]))
        self.assertIsNone(self.jobs.claim_due())

    def test_due_claim_is_atomic(self):
        job = self.jobs.programar_luz("cocina", "encender", 1)
        with scheduler.connect() as db:
            db.execute("UPDATE jobs SET due_at=? WHERE id=?", (time.time() - 1, job["id_tarea"]))
        first = self.jobs.claim_due()
        self.assertEqual(first["id"], job["id_tarea"])
        self.assertIsNone(self.jobs.claim_due())
        self.jobs.finish(first["id"], "done", "Solicitada a HA")
        self.assertIsNone(self.jobs.claim_due())

    def test_crash_recovery_at_most_once(self):
        job = self.jobs.programar_luz("cocina", "encender", 1)
        with scheduler.connect() as db:
            db.execute("UPDATE jobs SET state='running' WHERE id=?", (job["id_tarea"],))
        scheduler.initialize()  # app restarted after uncertain execution
        with scheduler.connect() as db:
            row = db.execute("SELECT state FROM jobs WHERE id=?", (job["id_tarea"],)).fetchone()
        self.assertEqual(row["state"], "interrupted")

    def test_limit_pending_jobs(self):
        for _ in range(scheduler.MAX_PENDING):
            self.assertEqual(self.jobs.programar_luz("cocina", "apagar", 60)["estado"], "programada")
        self.assertIn("error", self.jobs.programar_luz("cocina", "apagar", 60))

    def test_worker_revocation_denies_without_call(self):
        job = self.jobs.programar_luz("cocina", "apagar", 1)
        with scheduler.connect() as db:
            db.execute("UPDATE jobs SET due_at=? WHERE id=?", (time.time() - 1, job["id_tarea"]))
        read_only = HALights([dict(self.entries[0], allow_control=False)], "TEST")
        worker = scheduler.Scheduler(read_only)
        async def run():
            with patch.object(read_only, "controlar_luz", side_effect=AssertionError("MUST NOT CALL")):
                task = asyncio.create_task(worker.worker())
                await asyncio.sleep(0.2)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        asyncio.run(run())
        with scheduler.connect() as db:
            state = db.execute("SELECT state FROM jobs WHERE id=?", (job["id_tarea"],)).fetchone()["state"]
        self.assertEqual(state, "failed")

    def test_worker_authorized_executes_once(self):
        job = self.jobs.programar_luz("cocina", "encender", 1)
        with scheduler.connect() as db:
            db.execute("UPDATE jobs SET due_at=? WHERE id=?", (time.time() - 1, job["id_tarea"]))
        async def run():
            with patch.object(self.lights, "controlar_luz", return_value={
                "resultados": [{"entidad": "light.fake_cocina", "resultado": "solicitado"}]}) as call:
                task = asyncio.create_task(self.jobs.worker())
                await asyncio.sleep(0.2)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                self.assertEqual(call.call_count, 1)
        asyncio.run(run())
        with scheduler.connect() as db:
            state = db.execute("SELECT state FROM jobs WHERE id=?", (job["id_tarea"],)).fetchone()["state"]
        self.assertEqual(state, "done")


if __name__ == "__main__":
    unittest.main()
