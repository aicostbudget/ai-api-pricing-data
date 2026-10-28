import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_MODELS = ROOT / "data" / "canonical" / "models.json"
CANONICAL_PROVIDERS = ROOT / "data" / "canonical" / "providers.json"
PROJECTION = ROOT / "data" / "pricing-v2-preview" / "generated" / "model-pricing.v2.json"
HF_EXPORT = ROOT / "huggingface" / "prices.json"
PROVIDER = "meta"

# Standard-mode Model API prices, USD per 1M tokens: (input, cached_input, output).
EXPECTED = {
    "muse-wonder-1.0": ("4", "0.2", "20"),
    "muse-spark-1.3": ("1.25", "0.15", "4.25"),
}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class MetaMuseOnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.providers = {row["provider_id"]: row for row in read_json(CANONICAL_PROVIDERS)}
        cls.canonical = {
            (row["provider_id"], row["model_id"]): row for row in read_json(CANONICAL_MODELS)
        }
        cls.projection = {
            (row["provider"], row["id"]): row for row in read_json(PROJECTION)["models"]
        }
        cls.hf_records = {
            (row["provider_id"], row["model_id"]) for row in read_json(HF_EXPORT)["records"]
        }

    def test_provider_and_models_exist(self):
        provider = self.providers[PROVIDER]
        self.assertEqual(provider["display_name"], "Meta")
        self.assertTrue(provider["pricing_url"].startswith("https://dev.meta.ai/"))
        self.assertEqual(
            {model_id for provider_id, model_id in self.canonical if provider_id == PROVIDER},
            set(EXPECTED),
        )

    def test_standard_mode_prices_only(self):
        for model_id, values in EXPECTED.items():
            model = self.canonical[(PROVIDER, model_id)]
            self.assertEqual(model["context_window_tokens"], 1048576)
            self.assertEqual(len(model["price_records"]), 1, model_id)
            record = model["price_records"][0]
            self.assertEqual(record["processing_mode"], "standard")
            charges = {c["component"]: c["amount"] for c in record["charges"]}
            self.assertEqual((charges["input"], charges["cached_input"], charges["output"]), values, model_id)
        # Contributor mode trades training use of content for a lower price: noted, never a default row.
        self.assertNotIn((PROVIDER, "muse-spark-1.3-contributor"), self.canonical)
        self.assertIn("Contributor mode", self.canonical[(PROVIDER, "muse-spark-1.3")]["price_records"][0]["billing_note"])

    def test_wonder_is_preview_and_spark_is_active(self):
        wonder = self.canonical[(PROVIDER, "muse-wonder-1.0")]
        self.assertEqual((wonder["status"], wonder["release_stage"]), ("preview", "preview"))
        self.assertIn("South Korea", wonder["notes"])
        self.assertEqual(self.canonical[(PROVIDER, "muse-spark-1.3")]["status"], "active")

    def test_projection_and_hf_export(self):
        for model_id, values in EXPECTED.items():
            row = self.projection[(PROVIDER, model_id)]
            self.assertTrue(row["defaultSafe"], model_id)
            self.assertEqual(
                (row["inputPrice"], row["cachedInputPrice"], row["outputPrice"]),
                tuple(float(value) for value in values),
            )
            self.assertIn((PROVIDER, model_id), self.hf_records)


if __name__ == "__main__":
    unittest.main()
