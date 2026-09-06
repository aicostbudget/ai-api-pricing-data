from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from scripts.generate_pricing_v2_preview import status_parts
from scripts.pricing_contract import normalize_canonical_price_records, select_price_record


ROOT = Path(__file__).resolve().parents[1]
IDS = {
    "grok-4.20-0309-reasoning",
    "grok-4.20-0309-non-reasoning",
    "grok-4.20-multi-agent-0309",
}
EXPECTED = {
    ("standard", "short"): {"input": "1.25", "cached_input": "0.2", "output": "2.5"},
    ("standard", "long"): {"input": "2.5", "cached_input": "0.4", "output": "5"},
    ("batch", "short"): {"input": "1", "cached_input": "0.16", "output": "2"},
    ("batch", "long"): {"input": "2", "cached_input": "0.32", "output": "4"},
}


def read(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


class Grok420OnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        canonical = read("data/canonical/models.json")
        cls.models = {
            row["model_id"]: row
            for row in canonical
            if row["provider_id"] == "xai" and row["model_id"] in IDS
        }

    def test_exact_three_canonical_identities_and_alias_ownership(self):
        self.assertEqual(set(self.models), IDS)
        all_xai = [row for row in read("data/canonical/models.json") if row["provider_id"] == "xai"]
        self.assertNotIn("grok-4.20", {row["model_id"] for row in all_xai})
        reasoning = self.models["grok-4.20-0309-reasoning"]
        self.assertIn("grok-4.20", reasoning["aliases"])
        aliases = [alias for row in self.models.values() for alias in row["aliases"]]
        self.assertEqual(len(aliases), len(set(aliases)))
        self.assertTrue(IDS.isdisjoint(aliases))
        self.assertEqual(self.models["grok-4.20-multi-agent-0309"]["status"], "preview")
        self.assertEqual(self.models["grok-4.20-multi-agent-0309"]["release_stage"], "preview")

    def test_exact_three_models_have_verified_price_record_evidence(self):
        statuses = {
            model_id: status_parts("xai", model_id, model, None)["verificationStatus"]
            for model_id, model in self.models.items()
        }
        self.assertEqual(set(statuses), IDS)
        self.assertEqual(set(statuses.values()), {"verified"})
        print(
            "Grok 4.20 model verification: "
            + ", ".join(f"{model_id}={statuses[model_id]}" for model_id in sorted(statuses))
        )

    def test_200k_whole_request_boundary_and_batch_matrix(self):
        for model_id, model in self.models.items():
            records = normalize_canonical_price_records(f"xai/{model_id}", model["price_records"], lambda value: value)
            self.assertEqual(len(records), 4, model_id)
            for mode in ("standard", "batch"):
                for prompt_tokens, context in ((199_999, "short"), (200_000, "long"), (200_001, "long")):
                    selected = select_price_record(records, processing_mode=mode, prompt_tokens=prompt_tokens)
                    self.assertEqual(selected["selectionStatus"], "available")
                    self.assertEqual(selected["contextClass"], context)
                    self.assertEqual(selected["promptTokenThreshold"], 200_000)
                    self.assertEqual(
                        selected["tierSelection"],
                        {
                            "comparison": "less_than" if context == "short" else "greater_than_or_equal",
                            "tokenBasis": "total_prompt_tokens",
                            "cachedPromptTokensIncluded": True,
                            "wholeRequestPricing": True,
                        },
                    )
                    amounts = {charge["component"]: charge["amount"] for charge in selected["charges"]}
                    self.assertEqual(amounts, EXPECTED[(mode, context)])

    def test_identity_v2_website_hf_and_public_api_parity(self):
        identities = {
            row["internalId"]: row
            for row in read("data/pricing-v2-preview/model-identity-registry.json")
            if row["internalId"].removeprefix("xai/") in IDS
        }
        self.assertEqual(set(identities), {f"xai/{model_id}" for model_id in IDS})
        for row in identities.values():
            self.assertEqual(row["contextWindowTokens"], 1_000_000)
            self.assertTrue(any(item["type"] == "alias" for item in row["officialIds"]))

        rich = read("data/pricing-v2-preview/generated/model-pricing.v2.json")["models"]
        rich_rows = [row for row in rich if row["id"] in IDS]
        self.assertEqual(len(rich_rows), 3)
        for row in rich_rows:
            self.assertEqual(row["contextWindow"], "1M")
            self.assertEqual(row["contextWindowTokens"], 1_000_000)
            self.assertEqual(len(row["pricingTiers"]), 2)
            self.assertEqual(len(row["pricingComponents"]), 12)

        hf = read("huggingface/prices.json")["records"]
        hf_rows = [row for row in hf if row["provider_id"] == "xai" and row["model_id"] in IDS]
        self.assertEqual(len(hf_rows), 3)
        self.assertTrue(all(len(row["pricing_components"]) == 12 for row in hf_rows))

        public = read("api/v1/prices.json")
        public_rows = public["models"] if isinstance(public, dict) else public
        self.assertEqual(
            {row["model_id"] for row in public_rows if row["provider_id"] == "xai" and row["model_id"] in IDS},
            IDS,
        )

    def test_grok_46_canonical_semantics_are_frozen(self):
        grok46 = next(
            row for row in read("data/canonical/models.json")
            if row["provider_id"] == "xai" and row["model_id"] == "grok-4.6"
        )
        digest = hashlib.sha256(
            json.dumps(grok46, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.assertEqual(digest, "43acf46a77f31ba5bcfef9e3feaf6daf99f2c8b77149fac7421f36fb2efa1a44")


if __name__ == "__main__":
    unittest.main()
