import csv
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (("cohere", "command-a-plus"), ("anthropic", "claude-mythos-5-1"))


def read_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


class FreshnessFactualCorrectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = {
            (row["provider_id"], row["model_id"]): row
            for row in read_json("data/canonical/models.json")
        }

    def test_command_a_plus_vault_rates_are_instance_prices(self):
        row = self.models[TARGETS[0]]
        self.assertIn("USD $17.50 per L instance-hour", row["notes"])
        self.assertIn("USD $32.50 per XL instance-hour", row["notes"])
        self.assertIn("Standard Model Vault is a separate managed deployment option", row["notes"])
        self.assertNotIn("$57.50", row["notes"])
        self.assertIn("null is not zero", row["notes"])
        self.assertIn("https://docs.cohere.com/docs/model-vault/standard/pricing", row["official_source_urls"])

    def test_command_a_plus_token_prices_and_identity_are_preserved(self):
        row = self.models[TARGETS[0]]
        self.assertEqual(row["display_name"], "Command A+")
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["pricing"], {
            "currency": "USD", "unit": "1M tokens",
            "input": None, "output": None, "cached_input": None,
            "cache_write": None, "cache_write_1h": None,
            "batch_input": None, "batch_output": None,
        })
        projection = read_json("data/pricing-v2-preview/generated/model-pricing.v2.json")
        projected = next(x for x in projection["models"] if x["canonicalInternalId"] == "cohere/command-a-plus")
        self.assertEqual(projected["publicExposure"], "excluded")

    def test_mythos_verification_required_keeps_restricted_access_and_prices(self):
        row = self.models[TARGETS[1]]
        self.assertIn("Active (verification required)", row["notes"])
        self.assertIn("access restricted to organizations verified through Anthropic verification programs", row["notes"])
        self.assertNotIn("invite only", row["notes"])
        self.assertNotIn("Project Glasswing", row["notes"])
        self.assertEqual(row["display_name"], "Claude Mythos 5.1")
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["access_status"], "restricted")
        self.assertEqual(row["binding_status"], "approved")
        self.assertEqual(row["pricing"], {
            "currency": "USD", "unit": "1M tokens", "input": 10.0,
            "output": 50.0, "cached_input": 0.25, "cache_write": 12.5,
            "cache_write_1h": 20.0, "batch_input": 5.0, "batch_output": 25.0,
        })
        self.assertTrue(all(x["official_model_id"] == "claude-mythos-5-1" for x in row["access_evidence"]))
        self.assertIn("https://platform.claude.com/docs/en/models/mythos-5-1/overview", row["official_source_urls"])

    def test_current_v1_json_and_csv_publish_the_corrected_notes(self):
        for base in ("data", "api/v1"):
            aggregate = {(x["provider_id"], x["model_id"]): x for x in read_json(f"{base}/prices.json")["models"]}
            with (ROOT / base / "prices.csv").open(encoding="utf-8", newline="") as stream:
                csv_rows = {(x["provider_id"], x["model_id"]): x for x in csv.DictReader(stream)}
            for provider, model in TARGETS:
                expected = self.models[(provider, model)]
                with self.subTest(base=base, model=model):
                    self.assertEqual(aggregate[(provider, model)], expected)
                    self.assertEqual(read_json(f"{base}/models/{provider}/{model}.json"), expected)
                    provider_row = next(x for x in read_json(f"{base}/providers/{provider}.json")["models"] if x["model_id"] == model)
                    self.assertEqual(provider_row, expected)
                    self.assertEqual(csv_rows[(provider, model)]["notes"], expected["notes"])

    def test_v2_billing_notes_and_sql_seed_follow_canonical(self):
        prices = read_json("data/pricing-v2-preview/prices.json")
        seed = (ROOT / "data/pricing-v2-preview/generated/seed-pricing.preview.sql").read_text(encoding="utf-8")
        for provider, model in TARGETS:
            price_id = f"price:{provider}/{model}:standard:short:current"
            row = next(x for x in prices if x["pricingId"] == price_id)
            notes = self.models[(provider, model)]["notes"]
            self.assertEqual(row["billingNote"], notes)
            # SQL string literals escape apostrophes by doubling them.
            self.assertIn(notes.replace("'", "''"), seed)


if __name__ == "__main__":
    unittest.main()
