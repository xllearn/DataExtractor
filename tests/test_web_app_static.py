import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WebAppStaticTests(unittest.TestCase):
    def test_fetch_json_handles_non_json_responses(self):
        source = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn('headers.get("content-type")', source)
        self.assertIn("response.text()", source)
        self.assertIn("application/json", source)
        self.assertIn("Backend returned non-JSON", source)

    def test_article_rendering_uses_safe_dom_api(self):
        source = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")

        self.assertNotIn(".innerHTML", source)
        self.assertIn("document.createElement", source)
        self.assertIn("textContent", source)
        self.assertIn("isSafeHttpUrl", source)

    def test_database_not_ready_disables_query_actions(self):
        source = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")

        self.assertIn("safe_to_query", source)
        self.assertIn("setQueryEnabled", source)
        self.assertIn("searchBtn.disabled", source)
        self.assertIn("extractBtn.disabled", source)


if __name__ == "__main__":
    unittest.main()
