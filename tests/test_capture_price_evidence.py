import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.capture_price_evidence import EVIDENCE_DIR, page_lines, price_passages, run

PAGE = """<html><head><style>.x{color:red}</style><script>var price="$99";</script></head><body>
<h1>Voxtral TTS 3</h1><div>Pricing</div><span>USD</span><span>$13</span><span>/M Chars</span>
<p>Released 2026-10-20</p></body></html>"""


def fetcher(pages):
    return lambda url: (200, pages[url])


class CapturePriceEvidenceTests(unittest.TestCase):
    def test_passages_keep_split_prices_together_and_skip_scripts(self):
        lines = page_lines(PAGE)
        self.assertNotIn('var price="$99";', lines)
        passages = price_passages(lines)
        self.assertTrue(any("$13" in passage and "/M Chars" in passage for passage in passages))
        self.assertFalse(any("$99" in passage for passage in passages))

    def test_capture_records_pages_and_reports_changes_since_the_previous_capture(self):
        url = "https://docs.example/tts"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = run("mistral-ai/tts", [url], ["$13"], root, fetcher({url: PAGE}), datetime(2026, 10, 23, tzinfo=timezone.utc))
            self.assertEqual(first["previous_capture"], None)
            self.assertEqual(first["pages"][0]["missing_expected"], [])
            stored = root / EVIDENCE_DIR / "mistral-ai/tts/20261023T000000Z.json"
            self.assertEqual(json.loads(stored.read_text(encoding="utf-8"))["pages"][0]["url"], url)

            changed = PAGE.replace("$13", "$16")
            second = run("mistral-ai/tts", [url], ["$13"], root, fetcher({url: changed}), datetime(2026, 10, 24, tzinfo=timezone.utc))
            self.assertEqual(second["previous_capture"], "20261023T000000Z")
            self.assertEqual(second["pages"][0]["missing_expected"], ["$13"])
            change = second["changes_since_previous"][0]
            self.assertTrue(any("$16" in passage for passage in change["added"]))
            self.assertTrue(any("$13" in passage for passage in change["removed"]))

    def test_model_must_name_its_provider(self):
        with self.assertRaises(SystemExit):
            run("tts", ["https://docs.example"], [], Path("."), fetcher({}))


if __name__ == "__main__":
    unittest.main()
