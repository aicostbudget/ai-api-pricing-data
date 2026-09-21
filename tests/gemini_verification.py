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
        if current["model_id"] == "gemini-2.5-pro":
            for key in ("provider_id", "model_id", "display_name", "status", "effective_from", "pricing"):
                test_case.assertEqual(current[key], old[key], key)
            test_case.assertEqual(len(current["price_records"]), 8)
            test_case.assertTrue(all(record["verification_status"] == "verified" for record in current["price_records"]))
            test_case.assertTrue(all(set(record["source_refs"]) <= set(current["official_source_urls"]) for record in current["price_records"]))
            continue
        test_case.assertEqual(
            {key: value for key, value in current.items() if key not in ("last_verified_at", "accessed_at")},
            {key: value for key, value in old.items() if key not in ("last_verified_at", "accessed_at")},
        )
