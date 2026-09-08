from __future__ import annotations

import json
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


EXPECTED = {
    "mistral-large": {
        "name": "Mistral Large 3",
        "prices": (0.5, 0.05, 1.5, 0.25, 0.75),
        "context": None,
        "aliases": None,
    },
    "mistral-medium-3-5": {
        "name": "Mistral Medium 3.5",
        "prices": (1.5, 0.15, 7.5, 0.75, 3.75),
        "context": 262144,
        "aliases": ["mistral-medium-latest"],
    },
    "mistral-small-2603": {
        "name": "Mistral Small 4",
        "prices": (0.15, 0.015, 0.6, 0.075, 0.3),
        "context": 262144,
        "aliases": ["mistral-small-latest"],
    },
    "ministral-14b-2512": {
        "name": "Ministral 3 14B",
        "prices": (0.2, 0.02, 0.2, 0.1, 0.1),
        "context": 262144,
        "aliases": ["ministral-14b-latest"],
    },
    "ministral-8b-2512": {
        "name": "Ministral 3 8B",
        "prices": (0.15, 0.015, 0.15, 0.075, 0.075),
        "context": 262144,
        "aliases": ["ministral-8b-latest"],
    },
    "ministral-3b-2512": {
        "name": "Ministral 3 3B",
        "prices": (0.1, 0.01, 0.1, 0.05, 0.05),
        "context": 262144,
        "aliases": ["ministral-3b-latest"],
    },
    "codestral-2508": {
        "name": "Codestral",
        "prices": (0.3, 0.03, 0.9, 0.15, 0.45),
        "context": 131072,
        "aliases": ["codestral-latest"],
    },
}


class MistralCurrentCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.canonical = {
            row["model_id"]: row
            for row in read_json("data/canonical/models.json")
            if row["provider_id"] == "mistral-ai" and row["model_id"] in EXPECTED
        }
        cls.v2 = {
            row["id"]: row
            for row in read_json("data/pricing-v2-preview/generated/model-pricing.v2.json")["models"]
            if row["provider"] == "mistral-ai" and row["id"] in EXPECTED
        }
        cls.hf = {
            row["model_id"]: row
            for row in read_json("huggingface/prices.json")["records"]
            if row["provider_id"] == "mistral-ai" and row["model_id"] in EXPECTED
        }

    def test_required_current_models_are_unique_and_complete(self):
        self.assertEqual(set(self.canonical), set(EXPECTED))
        self.assertEqual(len(self.canonical), len(set(self.canonical)))

    def test_current_models_use_verified_token_contracts(self):
        for model_id, expected in EXPECTED.items():
            with self.subTest(model_id=model_id):
                row = self.canonical[model_id]
                pricing = row["pricing"]
                self.assertEqual(row["provider_id"], "mistral-ai")
                self.assertEqual(row["display_name"], expected["name"])
                self.assertEqual(row["status"], "active")
                self.assertEqual(pricing["unit"], "1M tokens")
                self.assertEqual(
                    (
                        pricing["input"],
                        pricing["cached_input"],
                        pricing["output"],
                        pricing["batch_input"],
                        pricing["batch_output"],
                    ),
                    expected["prices"],
                )
                self.assertIsNone(pricing["cache_write"])
                self.assertIsNone(pricing["cache_write_1h"])
                self.assertNotIn("pricing_components", row)
                self.assertEqual(row.get("context_window_tokens"), expected["context"])
                self.assertEqual(row.get("aliases"), expected["aliases"])

    def test_sources_are_official_and_verification_is_current(self):
        for model_id, row in self.canonical.items():
            with self.subTest(model_id=model_id):
                urls = row.get("official_source_urls", [row["official_source_url"]])
                self.assertIn(row["official_source_url"], urls)
                self.assertTrue(all(urlparse(url).hostname in {"docs.mistral.ai", "mistral.ai"} for url in urls))
                self.assertRegex(row["last_verified_at"], r"^2026-09-0[28]T")

    def test_large_3_baseline_semantics_remain_unchanged(self):
        row = self.canonical["mistral-large"]
        self.assertEqual(row["display_name"], "Mistral Large 3")
        self.assertEqual(row["model_family"], "Mistral Large")
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["official_source_url"], "https://docs.mistral.ai/inference/pricing")
        self.assertEqual(row["accessed_at"], "2026-09-02T11:29:12Z")
        self.assertEqual(row["last_verified_at"], "2026-09-02T11:29:12Z")
        self.assertNotIn("aliases", row)
        self.assertNotIn("lifecycle", row)

    def test_v2_and_hugging_face_include_all_current_models(self):
        self.assertEqual(set(self.v2), set(EXPECTED))
        self.assertEqual(set(self.hf), set(EXPECTED))
        for model_id, expected in EXPECTED.items():
            with self.subTest(model_id=model_id):
                v2 = self.v2[model_id]
                hf = self.hf[model_id]
                self.assertTrue(v2["defaultSafe"])
                self.assertEqual(v2["verificationStatus"], "verified")
                self.assertEqual(
                    (v2["inputPrice"], v2["cachedInputPrice"], v2["outputPrice"]),
                    expected["prices"][:3],
                )
                self.assertEqual(
                    (v2["batchInputPrice"], v2["batchOutputPrice"]),
                    expected["prices"][3:],
                )
                self.assertEqual(hf["pricing_unit"], "1M tokens")
                self.assertEqual(hf["verification_status"], "verified")
                processing_modes = {
                    component["condition"]["processing_mode"]
                    for component in hf["pricing_components"]
                }
                self.assertEqual(processing_modes, {"standard", "batch"})


if __name__ == "__main__":
    unittest.main()
