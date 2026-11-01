from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts import validate

ROOT = Path(__file__).resolve().parents[1]
PROJECTION = ROOT / "data" / "pricing-v2-preview" / "generated" / "model-pricing.v2.json"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class HostedModelListingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.canonical = read_json(ROOT / "data" / "canonical" / "models.json")
        cls.keys = {(row["provider_id"], row["model_id"]) for row in cls.canonical}
        cls.listings = [row for row in cls.canonical if row.get("hosted_model")]

    def test_listings_point_at_direct_models_on_their_platform(self):
        self.assertTrue(self.listings, "Claude on Bedrock/Vertex listings are tracked")
        for row in self.listings:
            hosted = row["hosted_model"]
            self.assertIn((hosted["provider_id"], hosted["model_id"]), self.keys)
            self.assertEqual(validate.HOSTED_PLATFORM_PROVIDERS[hosted["platform"]], row["provider_id"])

    def test_validator_rejects_broken_listings(self):
        listing = {"provider_id": "aws", "model_id": "bedrock-x", "hosted_model": {"provider_id": "anthropic", "model_id": "missing", "platform": "amazon-bedrock"}}
        with self.assertRaises(SystemExit):
            validate.validate_hosted_model(listing, ("aws", "bedrock-x"), {("anthropic", "claude")})
        listing["hosted_model"] = {"provider_id": "anthropic", "model_id": "claude", "platform": "google-vertex-ai"}
        with self.assertRaises(SystemExit):
            validate.validate_hosted_model(listing, ("aws", "bedrock-x"), {("anthropic", "claude")})
        listing["hosted_model"]["platform"] = "amazon-bedrock"
        validate.validate_hosted_model(listing, ("aws", "bedrock-x"), {("anthropic", "claude")})

    def test_listings_are_deferred_from_the_public_dataset(self):
        projection = {f"{row['provider']}/{row['id']}": row for row in read_json(PROJECTION)["models"]}
        listed = {f"{row['provider_id']}/{row['model_id']}" for row in self.listings}
        deferred = {
            key for key, row in projection.items()
            if row["governanceReason"] == "cloud_platform_listing_deferred_from_public_dataset"
        }
        self.assertEqual(deferred, listed)
        for key in listed:
            self.assertEqual(projection[key]["publicExposure"], "excluded", key)
            self.assertFalse(projection[key]["defaultSafe"], key)
            self.assertIn("cloud_platform_listing", projection[key]["blockedFromDefaultReasons"], key)
            self.assertEqual(projection[key]["verificationStatus"], "verified", key)
            self.assertTrue(projection[key].get("priceRecords"), key)


if __name__ == "__main__":
    unittest.main()
