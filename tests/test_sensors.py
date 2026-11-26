"""Offline sensor catalog tests."""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "xiaozhi_mcp"))
from ha_sensors import HASensors, validate_sensors, NoRedirect, MAX_RESPONSE


def entry(name="Temperatura salón", entity_id="sensor.fake_temperature",
          aliases="temperatura sala", allow_read=True):
    return dict(name=name, entity_id=entity_id, aliases=aliases, allow_read=allow_read)


class SensorTests(unittest.TestCase):
    def setUp(self):
        self.app = HASensors([entry(), entry("Presencia", "binary_sensor.fake_presence", "", True),
                              entry("Privado", "sensor.private", "secreto", False)], "FAKE-TOKEN")

    def response(self, opener, eid="sensor.fake_temperature", state="21.5", attrs=None):
        data = {"entity_id": eid, "state": state,
                "attributes": attrs if attrs is not None else {
                    "unit_of_measurement": "°C", "device_class": "temperature",
                    "secret": "never return"},
                "last_changed": "2026-11-26T12:00:00Z",
                "last_updated": "2026-11-26T12:01:00Z"}
        opener.return_value.open.return_value.__enter__.return_value = io.BytesIO(json.dumps(data).encode())

    @patch("ha_sensors.build_opener")
    def test_read_alias_and_fixed_get(self, opener):
        self.response(opener)
        result = self.app.consultar_sensor(" TEMPERATURA SALON ")
        self.assertEqual(result["estado"], "21.5")
        self.assertEqual(result["unidad"], "°C")
        self.assertTrue(result["disponible"])
        self.assertNotIn("secret", str(result))
        self.assertNotIn("FAKE-TOKEN", str(result))
        self.assertEqual(result["ultimo_cambio"], "2026-11-26T12:00:00Z")
        req = opener.return_value.open.call_args.args[0]
        self.assertEqual(req.get_method(), "GET")
        self.assertEqual(req.full_url, "http://homeassistant:8123/api/states/sensor.fake_temperature")
        self.assertEqual(req.get_header("Authorization"), "Bearer FAKE-TOKEN")
        self.assertIsNone(req.data)

    @patch("ha_sensors.build_opener")
    def test_unknown_denied_and_listing_never_access_network(self, opener):
        for name in ("secreto", "Privado", "sensor.private", "sensor.fake_temperature", "../../config", None):
            self.assertIn("error", self.app.consultar_sensor(name))
        self.assertEqual(self.app.listar_sensores(), {"sensores": ["Temperatura salón", "Presencia"]})
        opener.assert_not_called()

    @patch("ha_sensors.build_opener")
    def test_binary_and_unavailable(self, opener):
        for state, available in [("on", True), ("off", True), ("unknown", False), ("unavailable", False)]:
            self.response(opener, "binary_sensor.fake_presence", state, {"device_class": "occupancy"})
            result = self.app.consultar_sensor("presencia")
            self.assertEqual(result["estado"], state)
            self.assertEqual(result["disponible"], available)
            self.assertEqual(result["device_class"], "occupancy")

    @patch("ha_sensors.build_opener")
    def test_bad_response_and_http_errors(self, opener):
        self.response(opener, "sensor.other")
        self.assertIn("error", self.app.consultar_sensor("temperatura sala"))
        opener.return_value.open.return_value.__enter__.return_value = io.BytesIO(b"x" * (MAX_RESPONSE + 1))
        self.assertIn("error", self.app.consultar_sensor("temperatura sala"))
        for code in (401, 403, 404, 500):
            opener.return_value.open.side_effect = HTTPError("http://example.org", code, "FAKE-TOKEN", {}, None)
            result = self.app.consultar_sensor("temperatura sala")
            self.assertIn("error", result)
            self.assertNotIn("FAKE-TOKEN", str(result))

    def test_redirect_denied(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "http://example.org"))

    def test_catalog_validation(self):
        for eid in ("light.test", "switch.test", "automation.test", "sensor.x/../../config", "sensor.x?foo", "sensor.x\n"):
            with self.assertRaises(ValueError):
                validate_sensors([entry(entity_id=eid)])
        for invalid in ([entry(allow_read="true")], [entry(), entry("otro")],
                        [entry(), entry("otro", "sensor.other", "temperatura sala")],
                        [entry(), entry("TEMPERATURA SALON", "sensor.other", "")],
                        [dict(name="x", entity_id="sensor.x")], [entry(name="\n")],
                        [entry(aliases="a"*81)], [entry()]*101):
            with self.assertRaises(ValueError):
                validate_sensors(invalid)
        self.assertEqual(validate_sensors([]), ({}, {}))


if __name__ == "__main__":
    unittest.main()
