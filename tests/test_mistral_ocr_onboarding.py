from __future__ import annotations

import json
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
OCR_IDS = {"mistral-ocr-4-0", "mistral-ocr-4-1"}


def read_json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


class MistralOCROnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.providers = read_json("data/canonical/providers.json")
        cls.canonical = {
            (row["provider_id"], row["model_id"]): row
            for row in read_json("data/canonical/models.json")
        }
        cls.v2 = {
            (row["provider"], row["id"]): row
            for row in read_json("data/pricing-v2-preview/generated/model-pricing.v2.json")["models"]
        }
        cls.hf = {
            (row["provider_id"], row["model_id"]): row
            for row in read_json("huggingface/prices.json")["records"]
        }

    def test_provider_count_and_exact_ocr_identities(self):
        self.assertEqual(len(self.providers), 8)
        actual = {
            model_id
            for provider_id, model_id in self.canonical
            if provider_id == "mistral-ai" and model_id.startswith("mistral-ocr-")
        }
        self.assertEqual(actual, OCR_IDS)
        self.assertEqual(
            self.canonical[("mistral-ai", "mistral-ocr-4-1")]["aliases"],
            ["mistral-ocr-latest", "mistral-ocr-4"],
        )
        self.assertNotIn("aliases", self.canonical[("mistral-ai", "mistral-ocr-4-0")])

    def test_canonical_uses_verified_generic_page_contract(self):
        for model_id in OCR_IDS:
            with self.subTest(model_id=model_id):
                row = self.canonical[("mistral-ai", model_id)]
                self.assertEqual(row["status"], "active")
                self.assertEqual(row["release_stage"], "stable")
                self.assertEqual(row["model_category"], "document_parsing")
                self.assertTrue(all(row["pricing"].get(field) is None for field in (
                    "unit", "input", "output", "cached_input", "batch_input", "batch_output"
                )))
                self.assertEqual(len(row["pricing_components"]), 1)
                component = row["pricing_components"][0]
                self.assertEqual(
                    (component["component"], component["modality"], component["unit"], component["amount"]),
                    ("document_page", "document", "per_1000_pages", 4.0),
                )
                self.assertFalse(component["calculation_default"])
                self.assertEqual(component["processing_mode"], "standard")
                self.assertNotIn("configuration", component)
                urls = row["official_source_urls"]
                self.assertIn(row["official_source_url"], urls)
                self.assertTrue(all(urlparse(url).hostname in {"docs.mistral.ai", "mistral.ai"} for url in urls))

    def test_api_v2_and_hf_publish_non_token_prices_without_token_projection(self):
        for model_id in OCR_IDS:
            with self.subTest(model_id=model_id):
                api = read_json(f"api/v1/models/mistral-ai/{model_id}.json")
                self.assertEqual(api, self.canonical[("mistral-ai", model_id)])

                v2 = self.v2[("mistral-ai", model_id)]
                self.assertEqual(v2["verificationStatus"], "verified")
                self.assertFalse(v2["defaultSafe"])
                self.assertIsNone(v2["inputPrice"])
                self.assertIsNone(v2["cachedInputPrice"])
                self.assertIsNone(v2["outputPrice"])
                self.assertEqual(len(v2["pricingComponents"]), 1)
                self.assertEqual(v2["pricingComponents"][0]["unit"], "per_1000_pages")
                self.assertEqual(v2["pricingComponents"][0]["amount"], "4")
                self.assertFalse(v2["pricingComponents"][0]["calculationDefault"])

                hf = self.hf[("mistral-ai", model_id)]
                self.assertIsNone(hf["pricing_unit"])
                self.assertIsNone(hf["input_price_per_1m_tokens"])
                self.assertIsNone(hf["output_price_per_1m_tokens"])
                self.assertEqual((hf["unit_price"], hf["billing_unit"], hf["billing_quantity"]), (4.0, "per_1000_pages", 1000))
                self.assertEqual(hf["pricing_dimension"], "document_page")
                self.assertEqual(hf["verification_status"], "verified")

    def test_cohere_parse_page_contract_is_unchanged(self):
        parse = self.canonical[("cohere", "parse-v5.0")]
        component = parse["pricing_components"][0]
        self.assertEqual(
            (component["id"], component["component"], component["modality"], component["unit"], component["amount"]),
            ("document_parsing_pages", "document_page", "document", "per_1000_pages", 1.5),
        )
        self.assertFalse(component["calculation_default"])
        hf = self.hf[("cohere", "parse-v5.0")]
        self.assertEqual((hf["unit_price"], hf["billing_unit"], hf["billing_quantity"]), (1.5, "per_1000_pages", 1000))

    def test_no_out_of_scope_mistral_mixed_billing_was_added(self):
        model_ids = {
            model_id for provider_id, model_id in self.canonical if provider_id == "mistral-ai"
        }
        self.assertFalse(any("voxtral" in model_id for model_id in model_ids))
        self.assertNotIn("mistral-moderation-2603", model_ids)


if __name__ == "__main__":
    unittest.main()
