import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_MODELS = ROOT / "data" / "canonical" / "models.json"
CANONICAL_PROVIDERS = ROOT / "data" / "canonical" / "providers.json"
PREVIEW = ROOT / "data" / "pricing-v2-preview"
PROJECTION = PREVIEW / "generated" / "model-pricing.v2.json"
HF_EXPORT = ROOT / "huggingface" / "prices.json"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class MoonshotAIOnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.providers = {row["provider_id"]: row for row in read_json(CANONICAL_PROVIDERS)}
        cls.canonical = {
            (row["provider_id"], row["model_id"]): row for row in read_json(CANONICAL_MODELS)
        }
        cls.identities = {
            row["internalId"]: row for row in read_json(PREVIEW / "model-identity-registry.json")
        }
        cls.prices = {
            row["pricingId"]: row for row in read_json(PREVIEW / "prices.json")
        }
        cls.projection = {
            (row["provider"], row["id"]): row for row in read_json(PROJECTION)["models"]
        }
        cls.hf_records = {
            (row["provider_id"], row["model_id"]): row
            for row in read_json(HF_EXPORT)["records"]
        }

    def test_provider_and_current_canonical_models_exist(self):
        provider = self.providers["moonshot-ai"]
        self.assertEqual(provider["display_name"], "Moonshot AI")
        self.assertTrue(provider["pricing_url"].startswith("https://platform.kimi.ai/"))
        expected = {"kimi-k3", "kimi-k2.7-code", "kimi-k2.6"}
        self.assertEqual(
            {model_id for provider_id, model_id in self.canonical if provider_id == "moonshot-ai"},
            expected,
        )
        self.assertTrue(all(self.canonical[("moonshot-ai", model_id)]["status"] == "active" for model_id in expected))

    def test_k2_7_highspeed_is_alias_with_fast_pricing_not_a_fourth_model(self):
        model = self.canonical[("moonshot-ai", "kimi-k2.7-code")]
        self.assertIn("kimi-k2.7-code-highspeed", model["aliases"])
        identity = self.identities["moonshot-ai/kimi-k2.7-code"]
        self.assertIn(
            {"id": "kimi-k2.7-code-highspeed", "type": "alias", "source": "public_dataset"},
            identity["officialIds"],
        )
        self.assertNotIn(("moonshot-ai", "kimi-k2.7-code-highspeed"), self.canonical)
        fast = self.prices["price:moonshot-ai/kimi-k2.7-code:fast:short:current"]
        self.assertFalse(fast["calculationDefault"])
        self.assertEqual(fast["processingMode"], "fast")
        self.assertEqual(
            {charge["component"]: charge["amount"] for charge in fast["charges"]},
            {"input": "1.9", "cached_input": "0.38", "output": "8"},
        )

    def test_verified_standard_cache_and_batch_contracts(self):
        expected_standard = {
            "kimi-k3": {"input": "3", "cached_input": "0.3", "output": "15"},
            "kimi-k2.7-code": {"input": "0.95", "cached_input": "0.19", "output": "4"},
            "kimi-k2.6": {"input": "0.95", "cached_input": "0.16", "output": "4"},
        }
        for model_id, expected in expected_standard.items():
            price = self.prices[f"price:moonshot-ai/{model_id}:standard:short:current"]
            self.assertEqual(price["verificationStatus"], "verified")
            self.assertTrue(all("platform-kimi-ai" in source for source in price["sourceRefs"]))
            self.assertEqual(
                {charge["component"]: charge["amount"] for charge in price["charges"]},
                expected,
            )
        expected_batch = {
            "kimi-k2.7-code": {"input": "0.57", "cached_input": "0.114", "output": "2.4"},
            "kimi-k2.6": {"input": "0.57", "cached_input": "0.096", "output": "2.4"},
        }
        for model_id, expected in expected_batch.items():
            batch = self.prices[f"price:moonshot-ai/{model_id}:batch:short:current"]
            self.assertEqual(
                {charge["component"]: charge["amount"] for charge in batch["charges"]},
                expected,
            )
        self.assertNotIn("price:moonshot-ai/kimi-k3:batch:short:current", self.prices)
        moonshot_charges = [
            charge
            for price in self.prices.values()
            if price["modelInternalId"].startswith("moonshot-ai/")
            for charge in price["charges"]
        ]
        self.assertFalse(any(charge["component"] == "tool_call" for charge in moonshot_charges))

    def test_public_projection_and_hugging_face_include_calculator_rows(self):
        for model_id in ("kimi-k3", "kimi-k2.7-code", "kimi-k2.6"):
            projected = self.projection[("moonshot-ai", model_id)]
            self.assertTrue(projected["defaultSafe"])
            self.assertIsNotNone(projected["inputPrice"])
            self.assertIsNotNone(projected["cachedInputPrice"])
            self.assertIsNotNone(projected["outputPrice"])
            self.assertEqual(projected["verificationStatus"], "verified")
            self.assertIn(("moonshot-ai", model_id), self.hf_records)

    def test_mistral_and_cohere_remain_full_chain_providers(self):
        for provider_id in ("mistral-ai", "cohere"):
            self.assertIn(provider_id, self.providers)
            self.assertTrue(any(key[0] == provider_id for key in self.canonical))
            self.assertTrue(any(key[0] == provider_id for key in self.projection))
            self.assertTrue(any(key[0] == provider_id for key in self.hf_records))


if __name__ == "__main__":
    unittest.main()
