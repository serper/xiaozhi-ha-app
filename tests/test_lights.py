"""Offline tests. Never touch a real Home Assistant installation."""
import unittest
from unittest.mock import patch
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "xiaozhi_mcp"))
from ha_lights import HALights, validate_zones


class FakeResponse:
    def __init__(self, data):
        self.data = data
    def read(self):
        return json.dumps(self.data).encode('utf-8')
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


class LightTests(unittest.TestCase):
    def setUp(self):
        self.entries = [
            {"zone":"Salón", "aliases":"sala, estar", "entity_id":"light.fake_salon", "allow_read": True, "allow_control": True},
            {"zone":"Salón", "aliases":"sala, estar", "entity_id":"light.fake_rincon", "allow_read": True, "allow_control": True},
            {"zone":"Cocina", "aliases":"", "entity_id":"switch.luz_cocina", "allow_read": True, "allow_control": False},
        ]
        self.app = HALights(self.entries, "TEST-TOKEN")

    def test_alias_normalization(self):
        self.assertEqual(self.app.resolve(" SALON ")[0], "salon")
        self.assertEqual(self.app.resolve("la cocina")[0], None)
        self.assertEqual(self.app.resolve("sala")[0], "salon")

    def test_unknown_zone_never_calls_api(self):
        with patch("ha_lights.urlopen") as openurl:
            self.assertIn("error", self.app.controlar_luz("sótano", "encender"))
            openurl.assert_not_called()

    def test_action_allowlist(self):
        with patch("ha_lights.urlopen") as openurl:
            self.assertIn("error", self.app.controlar_luz("salón", "toggle"))
            openurl.assert_not_called()

    def test_read_only_zone(self):
        with patch("ha_lights.urlopen") as openurl:
            self.assertIn("error", self.app.controlar_luz("cocina", "apagar"))
            openurl.assert_not_called()

    def test_all_or_nothing_zone(self):
        entries = [dict(x) for x in self.entries]
        entries[1]["allow_control"] = False
        app = HALights(entries, "TEST-TOKEN")
        with patch("ha_lights.urlopen") as openurl:
            self.assertIn("error", app.controlar_luz("salón", "encender"))
            openurl.assert_not_called()

    def test_calls_only_fixed_service(self):
        called = []
        def mocked(req, timeout):
            called.append((req.get_method(), req.full_url, json.loads(req.data)))
            return FakeResponse([])
        with patch("ha_lights.urlopen", side_effect=mocked):
            result = self.app.controlar_luz("salón", "apagar")
        self.assertEqual(len(result["resultados"]), 2)
        self.assertEqual([x[0] for x in called], ["POST","POST"])
        self.assertTrue(all(x[1].endswith("/services/light/turn_off") for x in called))
        self.assertEqual([x[2]["entity_id"] for x in called], ["light.fake_salon", "light.fake_rincon"])

    def test_query_only_fixed_entity(self):
        called = []
        def mocked(req, timeout):
            called.append((req.get_method(), req.full_url))
            return FakeResponse({"state": "on"})
        with patch("ha_lights.urlopen", side_effect=mocked):
            result = self.app.consultar_luz("cocina")
        self.assertEqual(result["luces"][0]["estado"], "on")
        self.assertEqual(called, [("GET", "http://homeassistant:8123/api/states/switch.luz_cocina")])

    def test_switch_configuration_entity_rejected(self):
        for name in ("switch.sonoff_zbminir2_desconectar_rele_2",
                     "switch.sonoff_zbminir2_modo_turbo_2",
                     "switch.sonoff_zbminir2_led_de_red_2"):
            with self.assertRaises(ValueError):
                validate_zones([{"zone":"cocina", "entity_id":name}])

    def test_reject_config_domain_and_forged_ids(self):
        for entity in ("automation.test", "script.test", "switch.foo/../../config", "light.a?x=1"):
            with self.assertRaises(ValueError):
                validate_zones([{"zone":"x", "entity_id":entity}])

    def test_alias_collision(self):
        with self.assertRaises(ValueError):
            validate_zones([{"zone":"salon", "aliases":"cocina", "entity_id":"light.a"},
                            {"zone":"cocina", "entity_id":"light.b"}])

    def test_default_readonly(self):
        app = HALights([{"zone":"x", "entity_id":"light.x"}], "token")
        self.assertIn("error", app.controlar_luz("x", "encender"))


if __name__ == "__main__":
    unittest.main()
