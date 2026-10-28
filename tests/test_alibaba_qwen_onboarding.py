import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_MODELS = ROOT / "data" / "canonical" / "models.json"
CANONICAL_PROVIDERS = ROOT / "data" / "canonical" / "providers.json"
PROJECTION = ROOT / "data" / "pricing-v2-preview" / "generated" / "model-pricing.v2.json"
HF_EXPORT = ROOT / "huggingface" / "prices.json"
PROVIDER = "alibaba-qwen"

# International (Singapore) list prices, USD per 1M tokens: (input, cached_input, output) per tier.
EXPECTED = {
    "qwen3.8-max": {"short": ("2", "0.25", "6")},
    "qwen3.8-flash": {"short": ("0.15", "0.016", "0.47")},
    "qwen3.7-plus": {"short": ("0.4", "0.08", "1.6"), "long": ("1.2", "0.24", "4.8")},
    "qwen-flash": {"short": ("0.05", "0.01", "0.4"), "long": ("0.25", "0.05", "2")},
}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class AlibabaQwenOnboardingTests(unittest.TestCase):
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
        self.assertEqual(provider["display_name"], "Alibaba Qwen")
        self.assertTrue(provider["pricing_url"].startswith("https://www.alibabacloud.com/help/en/model-studio/"))
        self.assertEqual(
            {model_id for provider_id, model_id in self.canonical if provider_id == PROVIDER},
            set(EXPECTED),
        )

    def test_international_list_prices_and_request_tiers(self):
        for model_id, tiers in EXPECTED.items():
            model = self.canonical[(PROVIDER, model_id)]
            self.assertEqual(model["context_window_tokens"], 1000000)
            records = {r["context_class"]: r for r in model["price_records"]}
            self.assertEqual(set(records), set(tiers), model_id)
            for context_class, values in tiers.items():
                record = records[context_class]
                charges = {c["component"]: c["amount"] for c in record["charges"]}
                self.assertEqual(set(charges), {"input", "cached_input", "output"}, model_id)
                self.assertEqual((charges["input"], charges["cached_input"], charges["output"]), values, model_id)
                self.assertEqual(record["region_policy"]["pricing_geography"], "region_specific")
                self.assertEqual(record["region_policy"]["endpoint_geographies"], ["ap-southeast-1"])
                if len(tiers) == 2:
                    self.assertEqual(record["prompt_token_threshold"], 256000)
                    self.assertTrue(record["tier_selection"]["whole_request_pricing"])
                else:
                    self.assertIsNone(record["prompt_token_threshold"])
            self.assertIsNone(model["pricing"]["batch_input"])

    def test_qwen37_plus_keeps_list_price_and_notes_the_promotion(self):
        model = self.canonical[(PROVIDER, "qwen3.7-plus")]
        self.assertIn("limited-time 20% discount", model["notes"])
        self.assertEqual(model["pricing"]["input"], 0.4)

    def test_projection_and_hf_export(self):
        for model_id, tiers in EXPECTED.items():
            row = self.projection[(PROVIDER, model_id)]
            self.assertTrue(row["defaultSafe"], model_id)
            self.assertEqual(
                (row["inputPrice"], row["cachedInputPrice"], row["outputPrice"]),
                tuple(float(value) for value in tiers["short"]),
            )
            self.assertIn((PROVIDER, model_id), self.hf_records)


if __name__ == "__main__":
    unittest.main()
