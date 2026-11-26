import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "xiaozhi_mcp"))
from web_search import CreditBudget, TavilyProvider, WebSearch


class WebSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "credits.sqlite3")
        self.provider = Mock(cost=1)
        self.provider.search.return_value = {"answer": "test", "results": []}
        self.search = WebSearch(self.provider, CreditBudget(self.path, 2))

    def test_cache_and_persistent_limit(self):
        self.search.search("first")
        self.search.search("first")
        self.assertEqual(self.provider.search.call_count, 1)
        self.search.search("second")
        other = WebSearch(self.provider, CreditBudget(self.path, 2))
        self.assertIn("error", other.search("third"))
        self.assertEqual(self.provider.search.call_count, 2)

    def test_invalid_input_does_not_spend(self):
        for query, topic, period in [("", "general", None),
                                      ("valid", "bad", None),
                                      ("valid", "news", "bad")]:
            self.assertIn("error", self.search.search(query, topic, period))
        self.provider.search.assert_not_called()
        self.assertTrue(CreditBudget(self.path, 2).reserve(2))

    def test_failed_calls_are_counted_and_sanitized(self):
        self.provider.search.side_effect = RuntimeError("secret")
        self.assertNotIn("secret", str(self.search.search("first")))
        self.assertIn("error", self.search.search("second"))
        self.assertIn("error", self.search.search("third"))
        self.assertEqual(self.provider.search.call_count, 2)

    def test_advanced_cost(self):
        self.assertTrue(CreditBudget(self.path, 2).reserve(2))
        self.assertFalse(CreditBudget(self.path, 2).reserve(1))

    @patch("web_search.build_opener")
    def test_http_payload_and_bounded_response(self, opener):
        response = opener.return_value.open.return_value.__enter__.return_value
        response.read.return_value = json.dumps({
            "answer": "a" * 2000, "results": [
                {"title": "title", "url": "https://example.org", "content": "x" * 2000},
                {"title": "second"}], "raw_content": "private"
        }).encode()
        result = TavilyProvider("fake", "basic", 1).search("query", "news", "day")
        request = opener.return_value.open.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.tavily.com/search")
        self.assertEqual(request.get_header("Authorization"), "Bearer fake")
        self.assertFalse(payload["auto_parameters"])
        self.assertEqual(payload["time_range"], "day")
        self.assertEqual(len(result["answer"]), 1500)
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(len(result["results"][0]["content"]), 1000)
        self.assertNotIn("raw_content", result)

    def test_http_error(self):
        self.provider.search.side_effect = HTTPError("https://example.org", 429, "secret", {}, None)
        self.assertIn("cuota", self.search.search("query")["error"])


if __name__ == "__main__":
    unittest.main()
