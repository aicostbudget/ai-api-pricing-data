from __future__ import annotations

import json
import unittest
from decimal import Decimal
from pathlib import Path

from scripts.pricing_contract import (
    normalize_canonical_price_records,
    project_v1_compatibility,
    select_price_record,
    validate_model_price_records,
)


ROOT = Path(__file__).resolve().parents[1]
THRESHOLD = 272_000
COMPONENTS = ("input", "cached_input", "cache_write", "cache_write_12h", "output")
# Official pricing-page values per 1M tokens (short context), captured 2026-11-18 in reports/price-evidence:
# input, cached input, 30-minute cache write, 12-hour cache write, output.
OFFICIAL_SHORT = {
    "gpt-6.2-astra": {
        "standard": ("8", "0.4", "10", "20", "40"),
        "batch": ("4", "0.2", "5", "10", "20"),
        "fast": ("16", "0.8", "20", "40", "80"),
        "ultrafast_launch": ("24", "1.2", "30", "60", "120"),
        "ultrafast_list": ("48", "2.4", "60", "120", "240"),
    },
    "gpt-6.2-sol": {
        "standard": ("2", "0.1", "2.5", "5", "10"),
        "batch": ("1", "0.05", "1.25", "2.5", "5"),
        "fast": ("4", "0.2", "5", "10", "20"),
        "ultrafast_launch": ("6", "0.3", "7.5", "15", "30"),
        "ultrafast_list": ("12", "0.6", "15", "30", "60"),
    },
}
# The pricing page also lists long-context rows for Ultrafast (input, cached input, 30-minute cache write, output).
OFFICIAL_ULTRAFAST_LONG = {
    "gpt-6.2-astra": {"launch": ("48", "2.4", "60", "180"), "list": ("96", "4.8", "120", "360")},
    "gpt-6.2-sol": {"launch": ("12", "0.6", "15", "45"), "list": ("24", "1.2", "30", "90")},
}
DISPLAY = {"gpt-6.2-astra": "GPT-6.2 Astra", "gpt-6.2-sol": "GPT-6.2 Sol"}
UNCHANGED_PREDECESSORS = {
    "gpt-6-astra": ("10", "1", "50"),
    "gpt-6.1-sol": ("2", "0.1", "10"),
}


def read_json(relative_path: str):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def amounts(record) -> dict[str, Decimal]:
    return {charge["component"]: Decimal(str(charge["amount"])) for charge in record["charges"]}


def as_tuple(record, components=COMPONENTS) -> tuple[str, ...]:
    values = amounts(record)
    return tuple(format(values[name].normalize(), "f") for name in components)


class Gpt62OnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.canonical = {
            (row["provider_id"], row["model_id"]): row for row in read_json("data/canonical/models.json")
        }
        cls.models = {model_id: cls.canonical[("openai", model_id)] for model_id in OFFICIAL_SHORT}
        cls.normalized = {}
        for model_id, model in cls.models.items():
            validate_model_price_records(model)
            cls.normalized[model_id] = normalize_canonical_price_records(
                f"openai/{model_id}", model["price_records"], lambda url: url
            )

    def indexed(self, model_id: str) -> dict[tuple[str, str, str], dict]:
        return {
            (row["processing_mode"], row["context_class"], row["pricing_status"]): row
            for row in self.models[model_id]["price_records"]
        }

    def test_identity_release_evidence_and_v1_projection(self) -> None:
        for model_id, model in self.models.items():
            with self.subTest(model=model_id):
                self.assertEqual(model["display_name"], DISPLAY[model_id])
                self.assertEqual(model["model_family"], "GPT-6")
                self.assertEqual(model["status"], "active")
                self.assertEqual(model["context_window_tokens"], 1_050_000)
                self.assertEqual(model["released_at"], "2026-11-17")
                self.assertEqual(model["effective_from"], "2026-11-17")
                self.assertEqual(model["release_evidence"]["source_type"], "official_changelog")
                self.assertEqual(
                    model["official_source_url"], f"https://developers.openai.com/api/docs/models/{model_id}"
                )
                for guide in ("pricing", "changelog", "guides/ultrafast-mode", "guides/data-residency"):
                    self.assertIn(f"https://developers.openai.com/api/docs/{guide}", model["official_source_urls"])
                self.assertEqual(model["access_status"], "public")
                self.assertEqual(model["binding_status"], "approved")
                self.assertIn("tool calling requires the Responses API", model["notes"])
                projected = project_v1_compatibility(model["price_records"])
                projected.pop("batch_cached_input")
                expected = dict(model["pricing"])
                expected.pop("batch_cached_input")
                self.assertEqual(projected, expected)

    def test_exact_matrix_and_official_short_context_prices(self) -> None:
        for model_id, official in OFFICIAL_SHORT.items():
            with self.subTest(model=model_id):
                records = self.indexed(model_id)
                self.assertEqual(
                    set(records),
                    {
                        ("standard", "short", "current"), ("standard", "long", "current"),
                        ("batch", "short", "current"), ("batch", "long", "current"),
                        ("fast", "short", "current"), ("fast", "long", "current"),
                        ("ultrafast", "short", "current"), ("ultrafast", "long", "current"),
                        ("ultrafast", "short", "future"), ("ultrafast", "long", "future"),
                    },
                )
                self.assertEqual(len(self.models[model_id]["price_records"]), 10)
                self.assertEqual(sum(row["calculation_default"] for row in records.values()), 1)
                self.assertTrue(records[("standard", "short", "current")]["calculation_default"])
                charge_ids = [c["id"] for row in records.values() for c in row["charges"]]
                self.assertEqual(len(charge_ids), 50)
                self.assertEqual(len(charge_ids), len(set(charge_ids)))
                self.assertEqual(as_tuple(records[("standard", "short", "current")]), official["standard"])
                self.assertEqual(as_tuple(records[("batch", "short", "current")]), official["batch"])
                self.assertEqual(as_tuple(records[("fast", "short", "current")]), official["fast"])
                self.assertEqual(as_tuple(records[("ultrafast", "short", "current")]), official["ultrafast_launch"])
                self.assertEqual(as_tuple(records[("ultrafast", "short", "future")]), official["ultrafast_list"])
                # Flex is not listed for GPT-6.2 on the official pricing page: no record may be invented.
                self.assertFalse(any(row["processing_mode"] == "flex" for row in records.values()))

    def test_explicit_official_ultrafast_long_context_rows(self) -> None:
        columns = ("input", "cached_input", "cache_write", "output")
        for model_id, rows in OFFICIAL_ULTRAFAST_LONG.items():
            with self.subTest(model=model_id):
                records = self.indexed(model_id)
                self.assertEqual(as_tuple(records[("ultrafast", "long", "current")], columns), rows["launch"])
                self.assertEqual(as_tuple(records[("ultrafast", "long", "future")], columns), rows["list"])

    def test_long_context_and_mode_multipliers_follow_the_official_rules(self) -> None:
        for model_id in OFFICIAL_SHORT:
            with self.subTest(model=model_id):
                records = self.indexed(model_id)
                standard = {ctx: amounts(records[("standard", ctx, "current")]) for ctx in ("short", "long")}
                for component in ("input", "cached_input", "cache_write", "cache_write_12h"):
                    self.assertEqual(standard["long"][component], standard["short"][component] * 2)
                self.assertEqual(standard["long"]["output"], standard["short"]["output"] * Decimal("1.5"))
                for context in ("short", "long"):
                    base = standard[context]
                    for mode, status, factor in (
                        ("batch", "current", "0.5"), ("fast", "current", "2"),
                        ("ultrafast", "current", "3"), ("ultrafast", "future", "6"),
                    ):
                        self.assertEqual(
                            amounts(records[(mode, context, status)]),
                            {key: value * Decimal(factor) for key, value in base.items()},
                            (mode, context, status),
                        )
                    # 12-hour cache write is exactly double the 30-minute write everywhere.
                    for mode, status in (("standard", "current"), ("batch", "current"), ("fast", "current"),
                                         ("ultrafast", "current"), ("ultrafast", "future")):
                        row = amounts(records[(mode, context, status)])
                        self.assertEqual(row["cache_write_12h"], row["cache_write"] * 2)

    def test_threshold_contract(self) -> None:
        for model_id in OFFICIAL_SHORT:
            for row in self.models[model_id]["price_records"]:
                self.assertEqual(row["prompt_token_threshold"], THRESHOLD)
                expected = "less_than_or_equal" if row["context_class"] == "short" else "greater_than"
                self.assertEqual(row["tier_selection"]["comparison"], expected)
                self.assertTrue(row["tier_selection"]["cached_prompt_tokens_included"])
                self.assertTrue(row["tier_selection"]["whole_request_pricing"])
            for mode in ("standard", "batch", "fast", "ultrafast"):
                for tokens, context in ((THRESHOLD, "short"), (THRESHOLD + 1, "long")):
                    selected = select_price_record(
                        self.normalized[model_id], processing_mode=mode, prompt_tokens=tokens, at="2026-12-01"
                    )
                    self.assertEqual(selected["selectionStatus"], "available", (model_id, mode, tokens))
                    self.assertEqual(selected["contextClass"], context)

    def test_ultrafast_price_steps_up_on_march_first(self) -> None:
        for model_id, official in OFFICIAL_SHORT.items():
            with self.subTest(model=model_id):
                launch = [Decimal(value) for value in official["ultrafast_launch"]]
                listed = [Decimal(value) for value in official["ultrafast_list"]]
                for day, expected in (("2026-11-17", launch), ("2027-02-28", launch), ("2027-03-01", listed)):
                    selected = select_price_record(
                        self.normalized[model_id], processing_mode="ultrafast", prompt_tokens=1_000, at=day
                    )
                    self.assertEqual(selected["selectionStatus"], "available", (model_id, day))
                    charged = {c["component"]: Decimal(str(c["amount"])) for c in selected["charges"]}
                    self.assertEqual(charged["input"], expected[0], (model_id, day))
                    self.assertEqual(charged["output"], expected[4], (model_id, day))
                    self.assertEqual(
                        selected["pricingStatus"], "future" if day == "2027-03-01" else "current", (model_id, day)
                    )
                before = select_price_record(
                    self.normalized[model_id], processing_mode="ultrafast", prompt_tokens=1_000, at="2026-11-16"
                )
                self.assertEqual(before["selectionStatus"], "unavailable")
                for row in self.models[model_id]["price_records"]:
                    if row["processing_mode"] != "ultrafast":
                        continue
                    self.assertFalse(row["calculation_default"])
                    self.assertIn('service_tier="ultrafast"', row["billing_note"])
                    if row["pricing_status"] == "current":
                        self.assertEqual((row["effective_from"], row["effective_until"]), ("2026-11-17", "2027-02-28"))
                    else:
                        self.assertEqual((row["effective_from"], row["effective_until"]), ("2027-03-01", None))

    def test_regional_uplift_and_data_residency(self) -> None:
        for model_id in OFFICIAL_SHORT:
            with self.subTest(model=model_id):
                for row in self.models[model_id]["price_records"]:
                    adjustments = row["region_policy"]["price_adjustments"]
                    self.assertEqual([item["factor"] for item in adjustments], ["1.10"])
                    expected = ["global", "us"] if row["processing_mode"] == "ultrafast" else ["global", "us", "eu"]
                    self.assertEqual(row["region_policy"]["data_residencies"], expected)
                for mode in ("standard", "batch", "fast"):
                    selected = select_price_record(
                        self.normalized[model_id], processing_mode=mode, prompt_tokens=THRESHOLD,
                        endpoint_geography="regional", data_residency="eu", at="2026-12-01",
                    )
                    self.assertEqual(selected["selectionStatus"], "available", mode)
                eu = select_price_record(
                    self.normalized[model_id], processing_mode="ultrafast", prompt_tokens=THRESHOLD,
                    endpoint_geography="regional", data_residency="eu", at="2026-12-01",
                )
                self.assertEqual(eu["selectionStatus"], "unavailable")
                for residency in ("us", "global"):
                    selected = select_price_record(
                        self.normalized[model_id], processing_mode="ultrafast", prompt_tokens=THRESHOLD,
                        endpoint_geography="regional" if residency == "us" else "global",
                        data_residency=residency, at="2026-12-01",
                    )
                    self.assertEqual(selected["selectionStatus"], "available", residency)

    def test_flex_is_unavailable_and_background_windows_are_not_modeled(self) -> None:
        for model_id in OFFICIAL_SHORT:
            flex = select_price_record(
                self.normalized[model_id], processing_mode="flex", prompt_tokens=1_000, at="2026-12-01"
            )
            self.assertEqual(flex["selectionStatus"], "unavailable", model_id)
            notes = self.models[model_id]["notes"]
            self.assertIn("Flex processing is not listed", notes)
            self.assertIn("not modeled as a processing mode", notes)
            modes = {row["processing_mode"] for row in self.models[model_id]["price_records"]}
            self.assertEqual(modes, {"standard", "batch", "fast", "ultrafast"})

    def test_predecessor_prices_are_untouched(self) -> None:
        for model_id, (input_price, cached, output) in UNCHANGED_PREDECESSORS.items():
            standard = next(
                row for row in self.canonical[("openai", model_id)]["price_records"]
                if row["processing_mode"] == "standard" and row["context_class"] == "short"
            )
            values = amounts(standard)
            self.assertEqual(
                (str(values["input"]), str(values["cached_input"]), str(values["output"])),
                (input_price, cached, output),
            )
        # GPT-6.2 Astra is 20% cheaper on input and output and 60% cheaper on cached input than GPT-6 Astra.
        astra = amounts(self.indexed("gpt-6.2-astra")[("standard", "short", "current")])
        self.assertEqual(astra["input"], Decimal("10") * Decimal("0.8"))
        self.assertEqual(astra["output"], Decimal("50") * Decimal("0.8"))
        self.assertEqual(astra["cached_input"], Decimal("1") * Decimal("0.4"))

    def test_generated_artifacts_and_model_added_events(self) -> None:
        projection = {row["canonicalInternalId"]: row for row in read_json(
            "data/pricing-v2-preview/generated/model-pricing.v2.json")["models"]}
        v2_prices = read_json("data/pricing-v2-preview/prices.json")
        hf = {(row["provider_id"], row["model_id"]): row for row in read_json("huggingface/prices.json")["records"]}
        events = [
            json.loads(line)
            for line in (ROOT / "data/price-change-events/events.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        for model_id, official in OFFICIAL_SHORT.items():
            with self.subTest(model=model_id):
                internal_id = f"openai/{model_id}"
                rows = [row for row in v2_prices if row["modelInternalId"] == internal_id]
                self.assertEqual(len(rows), 10)
                self.assertEqual(sum(len(row["charges"]) for row in rows), 50)
                website = projection[internal_id]
                self.assertTrue(website["defaultSafe"])
                standard = [Decimal(value) for value in official["standard"]]
                self.assertEqual(Decimal(str(website["inputPrice"])), standard[0])
                self.assertEqual(Decimal(str(website["cachedInputPrice"])), standard[1])
                self.assertEqual(Decimal(str(website["outputPrice"])), standard[4])
                self.assertEqual(len(website["pricingComponents"]), 50)
                modes = {component["condition"]["processingMode"] for component in website["pricingComponents"]}
                self.assertEqual(modes, {"standard", "batch", "fast", "ultrafast"})
                record = hf[("openai", model_id)]
                self.assertEqual(Decimal(str(record["input_price_per_1m_tokens"])), standard[0])
                self.assertEqual(len(record["pricing_components"]), 50)
                for path in ("data/prices.json", "api/v1/prices.json"):
                    self.assertEqual(
                        sum(1 for row in read_json(path)["models"]
                            if row["provider_id"] == "openai" and row["model_id"] == model_id), 1, path)
                self.assertEqual(read_json(f"api/v1/models/openai/{model_id}.json"), self.models[model_id])
                added = [e for e in events if e["model_id"] == model_id and e["change_type"] == "model_added"]
                self.assertEqual(len(added), 1)
                self.assertEqual(added[0]["effective_from"], "2026-11-17")
                # No successor_transition is invented: GPT-6 Astra and GPT-6.1 Sol stay available.
                self.assertFalse(any(e["model_id"] == model_id and e["change_type"] == "successor_transition" for e in events))
        for old_id in UNCHANGED_PREDECESSORS:
            self.assertFalse(any(
                e["model_id"] == old_id and e["effective_from"] == "2026-11-17" for e in events
            ), old_id)


if __name__ == "__main__":
    unittest.main()
