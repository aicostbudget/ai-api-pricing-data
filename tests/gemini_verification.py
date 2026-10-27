"""Preserve Gemini price facts while allowing sourced verification metadata to advance."""

from datetime import datetime, timezone


def assert_gemini_facts_and_verification(test_case, before, after):
    test_case.assertEqual(
        [(row["provider_id"], row["model_id"]) for row in after],
        [(row["provider_id"], row["model_id"]) for row in before],
    )
    for old, current in zip(before, after):
        for field in ("last_verified_at", "accessed_at"):
            if old[field] != current[field]:
                test_case.assertRegex(current[field], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
                previous = datetime.fromisoformat(old[field].replace("Z", "+00:00"))
                refreshed = datetime.fromisoformat(current[field].replace("Z", "+00:00"))
                test_case.assertGreaterEqual(refreshed, previous)
                test_case.assertLessEqual(refreshed, datetime.now(timezone.utc))
                test_case.assertTrue(current["official_source_url"].startswith("https://"))
        # Gemini 2.5 Pro now has an explicit current pricing contract; retain the V1 facts and identity.
        if current["model_id"] in {"gemini-2.5-pro", "gemini-3.8-flash"}:
            for key in ("provider_id", "model_id", "display_name", "status", "effective_from", "pricing"):
                test_case.assertEqual(current[key], old[key], key)
            test_case.assertEqual(len(current["price_records"]), 8)
            test_case.assertTrue(all(record["verification_status"] == "verified" for record in current["price_records"]))
            test_case.assertTrue(all(set(record["source_refs"]) <= set(current["official_source_urls"]) for record in current["price_records"]))
            continue
        # These models gained record-level verified Standard and Batch records (2026-10-27);
        # every other fact, including the V1 pricing block, must stay unchanged.
        if current["model_id"] in {"gemini-2.5-flash", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite"}:
            ignored = {"price_records", "last_verified_at", "accessed_at", "released_at", "release_evidence",
                       "access_status", "access_evidence", "access_checked_at", "binding_status", "binding_evidence"}
            test_case.assertEqual(
                {key: value for key, value in current.items() if key not in ignored},
                {key: value for key, value in old.items() if key not in ignored},
            )
            records = current["price_records"]
            test_case.assertEqual(sorted(record["processing_mode"] for record in records), ["batch", "standard"])
            test_case.assertTrue(all(record["verification_status"] == "verified" for record in records))
            official = set(current.get("official_source_urls") or [current["official_source_url"]])
            test_case.assertTrue(all(set(record["source_refs"]) <= official for record in records))
            continue
        # Gemini 3.6 Flash moved its two pricing_periods into equivalent current and future
        # Standard/Batch price_records (2026-10-27); only that notes sentence may change.
        if current["model_id"] == "gemini-3.6-flash" and "pricing_periods" not in current:
            ignored = {"price_records", "pricing_periods", "notes", "last_verified_at", "accessed_at", "released_at",
                       "release_evidence", "access_status", "access_evidence", "access_checked_at", "binding_status",
                       "binding_evidence"}
            test_case.assertEqual(
                {key: value for key, value in current.items() if key not in ignored},
                {key: value for key, value in old.items() if key not in ignored},
            )
            test_case.assertEqual(
                current["notes"],
                old["notes"].replace(
                    "Structured pricing_periods preserves the 2027-01-01 Standard and Batch rates.",
                    "Structured price records preserve the 2027-01-01 Standard and Batch rates as future records.",
                ),
            )
            expected = []
            for period in old["pricing_periods"]:
                for mode, prefix in (("standard", ""), ("batch", "batch_")):
                    expected.append((mode, period["pricing_status"], period["effective_from"], period["effective_until"],
                                     tuple(float(period["pricing"][prefix + name]) for name in ("input", "cached_input", "output"))))
            actual = []
            for record in current["price_records"]:
                amounts = {charge["component"]: float(charge["amount"]) for charge in record["charges"]}
                actual.append((record["processing_mode"], record["pricing_status"], record["effective_from"], record["effective_until"],
                               tuple(amounts[name] for name in ("input", "cached_input", "output"))))
            test_case.assertEqual(sorted(actual), sorted(expected))
            test_case.assertTrue(all(record["verification_status"] == "verified" for record in current["price_records"]))
            official = set(current.get("official_source_urls") or [current["official_source_url"]])
            test_case.assertTrue(all(set(record["source_refs"]) <= official for record in current["price_records"]))
            continue
        if current["model_id"] in {"gemini-3.5-flash", "gemini-3.7-flash"}:
            allowed_lifecycle_updates = {
                "last_verified_at", "accessed_at", "status", "notes", "lifecycle",
                "official_source_urls", "released_at", "release_evidence", "access_status",
                "access_evidence", "access_checked_at", "binding_status", "binding_evidence",
            }
            test_case.assertEqual(
                {key: value for key, value in current.items() if key not in allowed_lifecycle_updates},
                {key: value for key, value in old.items() if key not in allowed_lifecycle_updates},
            )
            test_case.assertEqual(current["status"], "deprecated")
            test_case.assertEqual(current["lifecycle"]["deprecation_date"], "2026-10-08")
            test_case.assertNotIn("retirement_date", current["lifecycle"])
            continue
        test_case.assertEqual(
            {key: value for key, value in current.items() if key not in ("last_verified_at", "accessed_at", "released_at", "release_evidence", "access_status", "access_evidence", "access_checked_at", "binding_status", "binding_evidence")},
            {key: value for key, value in old.items() if key not in ("last_verified_at", "accessed_at", "released_at", "release_evidence", "access_status", "access_evidence", "access_checked_at", "binding_status", "binding_evidence")},
        )
