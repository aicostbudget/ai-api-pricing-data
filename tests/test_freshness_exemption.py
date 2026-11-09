import unittest

from scripts.validate import freshness_exemption

REDIRECT = {
    "kind": "retirement_redirect", "effective_from": "2026-12-01", "source_slug_remains_resolvable": True,
    "redirect_target_model_id": "gemini-3.6-flash", "target_configuration": {"model": "gemini-3.6-flash"},
    "billing_source": "redirect_target", "billing_model_id": "gemini-3.6-flash",
    "billing_configuration": {"model": "gemini-3.6-flash"},
}


class FreshnessExemptionTests(unittest.TestCase):
    def test_retired_is_skipped(self):
        self.assertEqual(freshness_exemption({"status": "retired"}, "2026-11-09"), "retired")

    def test_redirect_skipped_only_once_in_effect(self):
        model = {"status": "deprecated", "lifecycle": {"deprecation_date": "2026-09-01", "scheduled_transition": REDIRECT}}
        self.assertIsNone(freshness_exemption(model, "2026-11-30"))
        self.assertEqual(freshness_exemption(model, "2026-12-01"),
                         "requests redirect to gemini-3.6-flash since 2026-12-01")

    def test_deprecated_and_active_still_need_verification(self):
        # Deprecated models are still billed at their own published rates until they retire.
        self.assertIsNone(freshness_exemption({"status": "deprecated", "lifecycle": {"deprecation_date": "2026-10-14"}}, "2026-11-09"))
        self.assertIsNone(freshness_exemption({"status": "active"}, "2026-11-09"))
        self.assertIsNone(freshness_exemption({"status": "preview"}, "2026-11-09"))


if __name__ == "__main__":
    unittest.main()
