import csv
import hashlib
import json
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.export_huggingface import (
    CSV_HEADERS,
    FORBIDDEN_UTM,
    HF_DIR,
    META_PATH,
    PROJECTION_PATH,
    REQUIRED_UTM,
    VIEWER_CSV_HEADERS,
    VIEWER_OMITTED_FIELDS,
    artifact_contents,
    date_only,
    expected_public_keys,
    parse_date,
    public_pricing_components,
    preserve_existing_generated_at_for_timestamp_only_change,
    validate_huggingface_artifacts,
)


class HuggingFaceExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads((HF_DIR / "prices.json").read_text(encoding="utf-8"))
        cls.metadata = cls.payload["metadata"]
        cls.records = cls.payload["records"]
        cls.projection = json.loads(PROJECTION_PATH.read_text(encoding="utf-8"))
        with (HF_DIR / "prices.csv").open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            cls.prices_csv_headers = tuple(reader.fieldnames or ())
            cls.prices_csv_rows = list(reader)
        with (HF_DIR / "train.csv").open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            cls.train_csv_headers = tuple(reader.fieldnames or ())
            cls.train_csv_rows = list(reader)

    def test_export_artifacts_are_internally_consistent(self):
        validate_huggingface_artifacts()
        self.assertEqual(self.metadata["schema_version"], "1.5.0")
        self.assertEqual(self.metadata["last_verified_at"], self.metadata["last_updated"])

    def test_viewer_projection_preserves_rows_identities_providers_and_values(self):
        json_keys = {(row["provider_id"], row["model_id"]) for row in self.records}
        prices_by_key = {
            (row["provider_id"], row["model_id"]): row
            for row in self.prices_csv_rows
        }
        train_by_key = {
            (row["provider_id"], row["model_id"]): row
            for row in self.train_csv_rows
        }

        self.assertEqual(len(self.train_csv_rows), len(self.prices_csv_rows))
        self.assertEqual(len(self.train_csv_rows), len(self.records))
        self.assertEqual(set(train_by_key), set(prices_by_key))
        self.assertEqual(set(train_by_key), json_keys)
        self.assertEqual(
            {row["provider_id"] for row in self.train_csv_rows},
            {row["provider_id"] for row in self.prices_csv_rows},
        )
        self.assertEqual(len({row["provider_id"] for row in self.train_csv_rows}), 7)
        self.assertIn("xai", {row["provider_id"] for row in self.train_csv_rows})
        for key, train_row in train_by_key.items():
            self.assertEqual(
                train_row,
                {field: prices_by_key[key][field] for field in VIEWER_CSV_HEADERS},
                key,
            )

    def test_viewer_projection_omits_only_heavy_serialized_fields(self):
        self.assertEqual(self.prices_csv_headers, CSV_HEADERS)
        self.assertEqual(self.train_csv_headers, VIEWER_CSV_HEADERS)
        self.assertEqual(set(CSV_HEADERS) - set(VIEWER_CSV_HEADERS), VIEWER_OMITTED_FIELDS)
        self.assertTrue(VIEWER_OMITTED_FIELDS.isdisjoint(self.train_csv_headers))
        self.assertTrue(VIEWER_OMITTED_FIELDS.issubset(self.prices_csv_headers))
        self.assertIn("pricing_tier_count", self.train_csv_headers)
        self.assertIn("official_source_url", self.train_csv_headers)

    def test_viewer_projection_is_deterministic_and_covers_all_xai_models(self):
        first = artifact_contents(self.payload)["train.csv"]
        second = artifact_contents(self.payload)["train.csv"]
        self.assertEqual(first, second)
        prices_xai = {
            row["model_id"] for row in self.prices_csv_rows if row["provider_id"] == "xai"
        }
        train_xai = {
            row["model_id"] for row in self.train_csv_rows if row["provider_id"] == "xai"
        }
        json_xai = {
            row["model_id"] for row in self.records if row["provider_id"] == "xai"
        }
        self.assertEqual(train_xai, prices_xai)
        self.assertEqual(train_xai, json_xai)
        self.assertEqual(len(train_xai), 5)

    def test_export_matches_full_public_website_key_set(self):
        actual = {(row["provider_id"], row["model_id"]) for row in self.records}
        self.assertEqual(actual, expected_public_keys(self.projection))
        self.assertEqual(len(actual), len(self.records))
        self.assertEqual(len(self.records), 47, "audited public Website distribution must include Claude Fable 5.1, Claude Mythos 5.1, Grok 4.6, and Cohere Parse v5")
        self.assertEqual(self.metadata["record_count"], len(self.records))
        self.assertEqual(self.metadata["provider_count"], 7)

    def test_projection_prices_match_and_fallbacks_are_explicit(self):
        projection_by_key = {(row["provider"], row["id"]): row for row in self.projection["models"]}
        fallback_count = 0
        for record in self.records:
            key = (record["provider_id"], record["model_id"])
            projected = projection_by_key[key]
            if projected["inputPrice"] is not None and projected["outputPrice"] is not None:
                self.assertEqual(record["input_price_per_1m_tokens"], projected["inputPrice"], key)
                self.assertEqual(record["cached_input_price_per_1m_tokens"], projected["cachedInputPrice"], key)
                self.assertEqual(record["output_price_per_1m_tokens"], projected["outputPrice"], key)
            elif record["billing_unit"] is not None:
                self.assertIsNone(record["input_price_per_1m_tokens"], key)
                self.assertIsNone(record["cached_input_price_per_1m_tokens"], key)
                self.assertIsNone(record["output_price_per_1m_tokens"], key)
                self.assertIsNone(record["pricing_unit"], key)
                self.assertEqual(record["unit_price"], 1.5, key)
            else:
                fallback_count += 1
                self.assertIn("legacy fallback", record["notes"], key)
                self.assertNotIn("excluded_default_candidate", projected["blockedFromDefaultReasons"], key)
        self.assertEqual(fallback_count, 4)

    def test_all_record_provenance_matches_projection_semantics(self):
        projection_by_key = {
            (row["provider"], row["id"]): row
            for row in self.projection["models"]
        }
        non_verified = []
        for record in self.records:
            key = (record["provider_id"], record["model_id"])
            projected = projection_by_key[key]
            self.assertEqual(record["official_source_url"], projected["officialSourceUrl"], key)
            self.assertEqual(record["verification_status"], projected["verificationStatus"], key)
            self.assertEqual(record["last_verified_at"], date_only(projected.get("verifiedAt")), key)
            self.assertEqual(record["checked_at"], date_only(projected.get("checkedAt")), key)
            if projected.get("verifiedAt") is None:
                non_verified.append(record)
                self.assertIsNone(record["last_verified_at"], key)
                self.assertIsNotNone(record["checked_at"], key)
        self.assertEqual(len(non_verified), 4)
        self.assertEqual(
            {record["verification_status"] for record in non_verified},
            {"review_required", "partially_verified"},
        )

    def test_grok_4_3_tiers_match_public_website_projection(self):
        projected = next(row for row in self.projection["models"] if row["id"] == "grok-4.3")
        record = next(row for row in self.records if row["model_id"] == "grok-4.3")
        self.assertEqual(record["pricing_tier_count"], len(projected["pricingTiers"]))
        self.assertEqual(
            {tier["pricing_id"] for tier in record["pricing_tiers"]},
            {tier["pricingId"] for tier in projected["pricingTiers"]},
        )
        with (HF_DIR / "prices.csv").open(encoding="utf-8", newline="") as handle:
            csv_record = next(row for row in csv.DictReader(handle) if row["model_id"] == "grok-4.3")
        self.assertEqual(int(csv_record["pricing_tier_count"]), record["pricing_tier_count"])
        self.assertEqual(csv_record["verification_status"], record["verification_status"])
        self.assertEqual(csv_record["checked_at"], record["checked_at"])
        self.assertEqual(json.loads(csv_record["pricing_tiers_json"]), record["pricing_tiers"])

    def test_all_components_match_projection_and_csv_contract(self):
        projection_by_key = {(row["provider"], row["id"]): row for row in self.projection["models"]}
        component_count = 0
        cache_write_count = 0
        with (HF_DIR / "prices.csv").open(encoding="utf-8", newline="") as handle:
            csv_rows = {(row["provider_id"], row["model_id"]): row for row in csv.DictReader(handle)}
            headers = list(next(iter(csv_rows.values())).keys())
        legacy_headers = [
            "provider_id", "provider", "model_id", "model", "input_price_per_1m_tokens",
            "cached_input_price_per_1m_tokens", "output_price_per_1m_tokens", "currency",
            "pricing_unit", "status", "availability", "official_source_url", "verification_status",
            "last_verified_at", "checked_at", "effective_from", "effective_until", "notes",
            "pricing_tier_count", "pricing_tiers_json",
        ]
        self.assertEqual(headers[:-6], legacy_headers)
        self.assertEqual(
            headers[-6:],
            ["time_pricing_json", "pricing_components_json", "unit_price", "billing_unit", "billing_quantity", "pricing_dimension"],
        )
        for record in self.records:
            key = (record["provider_id"], record["model_id"])
            expected = public_pricing_components(projection_by_key[key])
            self.assertEqual(record["pricing_components"], expected, key)
            self.assertEqual(json.loads(csv_rows[key]["pricing_components_json"]), expected, key)
            component_count += len(expected)
            cache_write_count += sum(item["component"].startswith("cache_write") for item in expected)
            for component in expected:
                self.assertIsInstance(component["amount"], str, key)
                self.assertEqual(len(component["source_refs"]), len(component["source_urls"]), key)
                self.assertTrue(all(url.startswith("https://") for url in component["source_urls"]), key)
        self.assertEqual(component_count, 302)
        self.assertEqual(cache_write_count, 37)
        self.assertTrue(any(not record["pricing_components"] for record in self.records))

    def test_eleven_cache_pricing_targets_have_component_contract(self):
        target_ids = {
            "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "claude-fable-5", "claude-fable-5-1", "claude-mythos-5-1",
            "claude-haiku-4.5", "claude-opus-4.8", "claude-opus-5",
            "claude-sonnet-4.6", "claude-sonnet-5",
        }
        by_id = {record["model_id"]: record for record in self.records}
        self.assertEqual(target_ids - set(by_id), set())
        for model_id in target_ids:
            self.assertTrue(any(item["component"].startswith("cache_write") for item in by_id[model_id]["pricing_components"]), model_id)

    def test_parse_v5_uses_page_billing_without_token_prices(self):
        record = next(
            row
            for row in self.records
            if row["provider_id"] == "cohere" and row["model_id"] == "parse-v5.0"
        )
        self.assertIsNone(record["input_price_per_1m_tokens"])
        self.assertIsNone(record["cached_input_price_per_1m_tokens"])
        self.assertIsNone(record["output_price_per_1m_tokens"])
        self.assertIsNone(record["pricing_unit"])
        self.assertEqual(record["unit_price"], 1.5)
        self.assertEqual(record["billing_unit"], "per_1000_pages")
        self.assertEqual(record["billing_quantity"], 1000)
        self.assertEqual(record["pricing_dimension"], "document_page")
        self.assertEqual(len(record["pricing_components"]), 1)
        component = record["pricing_components"][0]
        self.assertEqual(component["component"], "document_page")
        self.assertEqual(component["unit"], "per_1000_pages")
        self.assertEqual(component["amount"], "1.5")

    def test_removing_additive_component_fields_reproduces_p0_1_records(self):
        baseline_records = []
        for record in self.records:
            if (record.get("provider_id"), record.get("model_id")) in {
                ("cohere", "parse-v5.0"),
                ("xai", "grok-4.6"),
                ("xai", "grok-build-0.1"),
            }:
                continue
            baseline = dict(record)
            for field in (
                "pricing_components",
                "unit_price",
                "billing_unit",
                "billing_quantity",
                "pricing_dimension",
            ):
                baseline.pop(field, None)
            baseline_records.append(baseline)
        digest = hashlib.sha256(
            json.dumps(baseline_records, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        self.assertEqual(digest, "9788e2f64195dd2fbe963bd916862bdeeb9cb4fb2dff4a0f1d9b00f1b88c975e")

    def test_timestamps_preserve_verification_semantics(self):
        pricing_meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        self.assertLessEqual(parse_date(self.metadata["generated_at"]), parse_date(pricing_meta["generated_at"]))
        self.assertEqual(self.metadata["last_updated"], pricing_meta["last_verified_at"])
        generated_at = datetime.fromisoformat(self.metadata["generated_at"].replace("Z", "+00:00"))
        verified = [
            parse_date(row["last_verified_at"])
            for row in self.records
            if row["last_verified_at"]
        ]
        self.assertGreaterEqual(generated_at, max(verified))
        self.assertLessEqual(generated_at, datetime.now(timezone.utc))
        self.assertTrue(all(value <= datetime.now(timezone.utc) for value in verified))
        checked = [parse_date(row["checked_at"]) for row in self.records if row["checked_at"]]
        self.assertGreaterEqual(generated_at, max(checked))

    def test_timestamp_only_regeneration_preserves_existing_generated_at(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            current = json.loads(json.dumps(self.payload))
            (output_dir / "prices.json").write_text(json.dumps(current), encoding="utf-8")
            candidate = json.loads(json.dumps(current))
            candidate["metadata"]["generated_at"] = "2026-08-11T00:00:00Z"
            preserve_existing_generated_at_for_timestamp_only_change(candidate, output_dir)
            self.assertEqual(candidate["metadata"]["generated_at"], current["metadata"]["generated_at"])

            candidate["records"][0]["notes"] += " changed"
            candidate["metadata"]["generated_at"] = "2026-08-11T00:00:00Z"
            preserve_existing_generated_at_for_timestamp_only_change(candidate, output_dir)
            self.assertEqual(candidate["metadata"]["generated_at"], "2026-08-11T00:00:00Z")

    def test_prices_are_finite_non_negative_or_null(self):
        for row in self.records:
            for field in (
                "input_price_per_1m_tokens",
                "cached_input_price_per_1m_tokens",
                "output_price_per_1m_tokens",
            ):
                value = row[field]
                if value is not None:
                    self.assertIsInstance(value, (int, float), (row["provider_id"], row["model_id"], field))
                    self.assertGreaterEqual(value, 0, (row["provider_id"], row["model_id"], field))

    def test_dataset_card_uses_utm_only_for_html_acquisition_links(self):
        card = (HF_DIR / "README.md").read_text(encoding="utf-8")
        urls = set(re.findall(r"https://aicostbudget\.com/[^\s)]+", card))
        clean_api_urls = {
            "https://aicostbudget.com/api/datasets/ai-api-pricing.json",
            "https://aicostbudget.com/api/datasets/ai-api-pricing.csv",
        }
        acquisition_urls = {
            "https://aicostbudget.com/en/datasets/ai-api-pricing?utm_source=huggingface&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=dataset_card_dataset",
            "https://aicostbudget.com/en/ai-api-cost-calculator?utm_source=huggingface&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=dataset_card_calculator",
            "https://aicostbudget.com/en/model-pricing-comparison?utm_source=huggingface&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=dataset_card_comparison",
            "https://aicostbudget.com/en/model-price-monitor?utm_source=huggingface&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=dataset_card_price_monitor",
        }
        self.assertEqual(urls, clean_api_urls | acquisition_urls)
        for url in acquisition_urls:
            for marker in REQUIRED_UTM:
                self.assertIn(marker, url)
        for marker in FORBIDDEN_UTM:
            self.assertNotIn(marker, card)
        for url in clean_api_urls:
            self.assertNotRegex(url, r"[?&]utm_")
        self.assertIn("not a separately curated subset", card)


if __name__ == "__main__":
    unittest.main()
