from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples" / "llm_cost_diagnostics.py"
SAMPLE = ROOT / "examples" / "sample_llm_attempts.json"
CATALOG = ROOT / "data" / "pricing-v2-preview" / "generated" / "model-pricing.v2.json"
SPEC = importlib.util.spec_from_file_location("llm_cost_diagnostics", SCRIPT)
assert SPEC and SPEC.loader
diagnostics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostics)


def fixture_catalog() -> dict:
    pricing_id = "price:fixture/model-a:standard:short:current"
    condition = {
        "processingMode": "standard",
        "contextClass": "short",
        "regionPolicy": "global",
        "promptTokenThreshold": None,
        "tierSelection": None,
        "effectiveUntil": None,
    }
    components = []
    for component, amount in (("input", "2"), ("cached_input", "0.5"), ("output", "8")):
        components.append(
            {
                "pricingId": pricing_id,
                "component": component,
                "amount": amount,
                "currency": "USD",
                "modality": "text",
                "unit": "per_1m_tokens",
                "calculationDefault": True,
                "verificationStatus": "verified",
                "condition": condition,
            }
        )
    return {
        "models": [
            {
                "provider": "fixture",
                "id": "model-a",
                "defaultSafe": True,
                "verificationStatus": "verified",
                "billingModelInternalId": None,
                "selectedPriceRecordId": pricing_id,
                "selectedBillingPriceRecordId": pricing_id,
                "priceRecords": [
                    {
                        "pricingId": pricing_id,
                        "processingMode": "standard",
                        "contextClass": "short",
                        "pricingStatus": "current",
                        "effectiveUntil": None,
                        "calculationDefault": True,
                        "verificationStatus": "verified",
                    }
                ],
                "pricingComponents": components,
            }
        ]
    }


def attempt_document(*attempts: dict) -> dict:
    return {"input_provenance": "unit_test_fixture", "attempts": list(attempts)}


def attempt(
    attempt_id: str,
    *,
    task_id: str = "anonymous-task",
    attempt_type: str = "first_attempt",
    success: bool = False,
    billing_status: str = "billed",
    usage: dict | None = None,
) -> dict:
    return {
        "task_id": task_id,
        "attempt_id": attempt_id,
        "attempt_type": attempt_type,
        "provider_id": "fixture",
        "model_id": "model-a",
        "success": success,
        "billing_status": billing_status,
        "usage": usage if usage is not None else {"input": 1000, "output": 100},
    }


class LlmCostDiagnosticsTests(unittest.TestCase):
    def test_checked_in_synthetic_sample_summary(self) -> None:
        summary = diagnostics.summarize(diagnostics.load_json(SAMPLE), diagnostics.load_json(CATALOG))

        self.assertEqual(summary["task_count"], 3)
        self.assertEqual(summary["successful_task_count"], 2)
        self.assertEqual(summary["category_counts"], {"first_attempt": 3, "retry": 1, "fallback": 1})
        self.assertEqual(summary["category_costs"]["first_attempt"], Decimal("0.2875"))
        self.assertEqual(summary["category_costs"]["retry"], Decimal("0.15"))
        self.assertEqual(summary["category_costs"]["fallback"], Decimal("0.3"))
        self.assertEqual(summary["total_cost"], Decimal("0.7375"))
        self.assertEqual(summary["cost_per_successful_task"], Decimal("0.36875"))

    def test_explicit_not_billed_attempt_is_zero(self) -> None:
        record = attempt("a", success=True, billing_status="not_billed")
        summary = diagnostics.summarize(attempt_document(record), fixture_catalog())

        self.assertEqual(summary["total_cost"], Decimal("0"))
        self.assertEqual(summary["not_billed_attempt_count"], 1)

    def test_not_billed_attempt_still_requires_model_identity(self) -> None:
        record = attempt("a", billing_status="not_billed")
        record["provider_id"] = ""
        with self.assertRaisesRegex(diagnostics.DiagnosticError, "provider_id must be a non-empty string"):
            diagnostics.summarize(attempt_document(record), fixture_catalog())

    def test_unknown_billing_status_fails_instead_of_zero(self) -> None:
        record = attempt("a", billing_status="unknown")
        with self.assertRaisesRegex(diagnostics.UnsupportedBillingError, "unknown billing status"):
            diagnostics.summarize(attempt_document(record), fixture_catalog())

    def test_missing_component_rate_fails(self) -> None:
        catalog = fixture_catalog()
        catalog["models"][0]["pricingComponents"] = [
            component
            for component in catalog["models"][0]["pricingComponents"]
            if component["component"] != "cached_input"
        ]
        record = attempt("a", usage={"cached_input": 1000})
        with self.assertRaisesRegex(diagnostics.UnsupportedBillingError, "no supported cached_input rate"):
            diagnostics.summarize(attempt_document(record), catalog)

    def test_unsupported_usage_component_fails(self) -> None:
        record = attempt("a", usage={"request": 1})
        with self.assertRaisesRegex(diagnostics.UnsupportedBillingError, "unsupported usage components: request"):
            diagnostics.summarize(attempt_document(record), fixture_catalog())

    def test_conditional_rate_fails(self) -> None:
        catalog = fixture_catalog()
        catalog["models"][0]["pricingComponents"][0]["condition"]["promptTokenThreshold"] = 200000
        record = attempt("a", usage={"input": 1000})
        with self.assertRaisesRegex(diagnostics.UnsupportedBillingError, "unsupported billing conditions"):
            diagnostics.summarize(attempt_document(record), catalog)

    def test_unknown_condition_field_fails(self) -> None:
        catalog = fixture_catalog()
        catalog["models"][0]["pricingComponents"][0]["condition"]["futureCondition"] = "unknown"
        record = attempt("a", usage={"input": 1000})
        with self.assertRaisesRegex(diagnostics.UnsupportedBillingError, "unsupported billing conditions"):
            diagnostics.summarize(attempt_document(record), catalog)

    def test_retry_cannot_change_model(self) -> None:
        first = attempt("a")
        retry = attempt("b", attempt_type="retry", success=True)
        retry["model_id"] = "model-b"
        with self.assertRaisesRegex(diagnostics.DiagnosticError, "changes model"):
            diagnostics.summarize(attempt_document(first, retry), fixture_catalog())

    def test_fallback_must_change_model(self) -> None:
        first = attempt("a")
        fallback = attempt("b", attempt_type="fallback", success=True)
        with self.assertRaisesRegex(diagnostics.DiagnosticError, "keeps the same model"):
            diagnostics.summarize(attempt_document(first, fallback), fixture_catalog())

    def test_no_success_reports_no_cost_per_success(self) -> None:
        summary = diagnostics.summarize(attempt_document(attempt("a")), fixture_catalog())
        self.assertIsNone(summary["cost_per_successful_task"])
        rendered = diagnostics.format_summary(summary, CATALOG)
        self.assertIn("Cost per successful task (USD): N/A (no successful tasks)", rendered)

    def test_cli_output_matches_readme_example(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), str(SAMPLE)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Successful tasks: 2", completed.stdout)
        self.assertIn("Total estimated cost (USD): 0.737500", completed.stdout)
        self.assertIn("Cost per successful task (USD): 0.368750", completed.stdout)

    def test_cli_returns_nonzero_for_unknown_billing(self) -> None:
        document = attempt_document(attempt("a", billing_status="unknown"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempts.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), str(path), "--pricing-catalog", str(CATALOG)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("unknown billing status", completed.stderr)

    def test_missing_model_fails(self) -> None:
        record = attempt("a")
        record["model_id"] = "missing"
        with self.assertRaisesRegex(diagnostics.UnsupportedBillingError, "missing from Pricing V2"):
            diagnostics.summarize(attempt_document(record), fixture_catalog())

    def test_non_default_safe_model_fails(self) -> None:
        catalog = deepcopy(fixture_catalog())
        catalog["models"][0]["defaultSafe"] = False
        with self.assertRaisesRegex(diagnostics.UnsupportedBillingError, "not default-safe"):
            diagnostics.summarize(attempt_document(attempt("a")), catalog)


if __name__ == "__main__":
    unittest.main()
