import json
import unittest

from scripts import update_readme_prices as readme


def model(provider, model_id, input_price, output_price, status="active", unit="1M tokens"):
    return {
        "provider_id": provider, "model_id": model_id, "display_name": model_id.upper(), "status": status,
        "pricing": {"unit": unit, "currency": "USD", "input": input_price, "output": output_price},
    }


class ReadmePriceTableTests(unittest.TestCase):
    def test_committed_readme_matches_published_prices(self):
        dataset = json.loads((readme.ROOT / "api/v1/prices.json").read_text(encoding="utf-8"))
        text = (readme.ROOT / "README.md").read_text(encoding="utf-8")
        self.assertEqual(readme.updated_readme(text, dataset), text, "run python scripts/update_readme_prices.py")

    def test_range_uses_active_token_priced_models_only(self):
        dataset = {"model_count": 5, "last_verified_at": "2026-10-30T08:35:21Z", "models": [
            model("openai", "cheap", 0.1, 0.5),
            model("openai", "dear", 30, 180),
            model("openai", "retired", 0.01, 0.02, status="retired"),
            model("openai", "tts", 1, 2, unit="1M characters"),
            model("openai", "embed", 0.02, None),
        ]}
        table = readme.render(dataset)
        self.assertIn("| 2 | [CHEAP]", table)
        self.assertIn("$0.10 / $0.50 | [DEAR]", table)
        self.assertNotIn("RETIRED", table)
        self.assertNotIn("TTS", table)
        self.assertIn("last verified **2026-10-30**", table)
        self.assertNotIn("Anthropic", table)

    def test_single_model_provider_does_not_repeat_itself(self):
        table = readme.render({"model_count": 1, "last_verified_at": "2026-10-30T00:00:00Z", "models": [model("meta", "muse", 1.25, 4.25)]})
        self.assertIn("| same model |", table)

    def test_missing_markers_fail(self):
        with self.assertRaisesRegex(ValueError, "markers"):
            readme.updated_readme("# no table\n", {"model_count": 0, "last_verified_at": "x", "models": []})


if __name__ == "__main__":
    unittest.main()
