import csv
import io
import json
import unittest

from scripts.export_huggingface_history import (
    CHANGE_HEADERS,
    EVENTS_PATH,
    HISTORY_HF_DIR,
    SNAPSHOT_HEADERS,
    SNAPSHOTS_DIR,
    artifact_contents,
    latest_snapshot_per_day,
    read_events,
)
from scripts.lib import parse_snapshot_id


def rows(text):
    return list(csv.DictReader(io.StringIO(text)))


class HuggingFaceHistoryExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contents = artifact_contents()
        cls.snapshots = rows(cls.contents["price_snapshots.csv"])
        cls.changes = rows(cls.contents["price_changes.csv"])
        cls.events = read_events()

    def test_committed_artifacts_are_current(self):
        for name, content in self.contents.items():
            self.assertEqual((HISTORY_HF_DIR / name).read_text(encoding="utf-8"), content, name)

    def test_headers(self):
        self.assertEqual(tuple(self.contents["price_snapshots.csv"].splitlines()[0].split(",")), SNAPSHOT_HEADERS)
        self.assertEqual(tuple(self.contents["price_changes.csv"].splitlines()[0].split(",")), CHANGE_HEADERS)

    def test_one_snapshot_per_day_using_the_last_release(self):
        ids = latest_snapshot_per_day()
        days = [parse_snapshot_id(snapshot_id)[0] for snapshot_id in ids]
        self.assertEqual(len(days), len(set(days)))
        # Derived from the committed snapshots so a later same-day release does not break the pin.
        last_per_day = {}
        for path in SNAPSHOTS_DIR.iterdir():
            if (path / "prices.json").is_file():
                day, sequence = parse_snapshot_id(path.name)
                if sequence > last_per_day.get(day, ("", 0))[1]:
                    last_per_day[day] = (path.name, sequence)
        self.assertEqual(sorted(ids), sorted(name for name, _ in last_per_day.values()))
        self.assertNotIn("2026-10-29", ids)
        expected_rows = sum(
            len(json.loads((SNAPSHOTS_DIR / snapshot_id / "prices.json").read_text(encoding="utf-8"))["models"])
            for snapshot_id in ids
        )
        self.assertEqual(len(self.snapshots), expected_rows)
        self.assertEqual({row["snapshot_id"] for row in self.snapshots}, set(ids))

    def test_change_labels_separate_provider_changes_from_dataset_revisions(self):
        labels = {row["change_vs_previous_snapshot"] for row in self.snapshots}
        self.assertLessEqual(labels, {"first_seen", "unchanged", "price_change", "dataset_revision"})
        first_day = min(row["snapshot_date"] for row in self.snapshots)
        self.assertTrue(all(
            row["change_vs_previous_snapshot"] == "first_seen"
            for row in self.snapshots
            if row["snapshot_date"] == first_day
        ))
        event_ids = {event["event_id"] for event in self.events}
        for row in self.snapshots:
            if row["change_vs_previous_snapshot"] == "price_change":
                self.assertIn(row["price_change_event_id"], event_ids, row)
            else:
                self.assertEqual(row["price_change_event_id"], "", row)
        gemini = [
            row for row in self.snapshots
            if row["model_id"] == "gemini-3.6-flash" and row["change_vs_previous_snapshot"] == "price_change"
        ]
        self.assertEqual([(row["snapshot_date"], row["input_price"]) for row in gemini], [("2026-08-29", "0.75")])

    def test_each_model_is_first_seen_once(self):
        first_seen = [
            (row["provider_id"], row["model_id"])
            for row in self.snapshots
            if row["change_vs_previous_snapshot"] == "first_seen"
        ]
        self.assertEqual(len(first_seen), len(set(first_seen)))

    def test_changes_mirror_every_event(self):
        self.assertEqual([row["event_id"] for row in self.changes], [event["event_id"] for event in self.events])
        self.assertEqual(len(self.changes), len(EVENTS_PATH.read_text(encoding="utf-8").splitlines()))
        price_update = next(row for row in self.changes if row["event_id"].startswith("google-gemini:gemini-3.6-flash:price_update"))
        self.assertEqual(
            (price_update["old_input_price"], price_update["new_input_price"], price_update["old_output_price"], price_update["new_output_price"]),
            ("1.5", "0.75", "7.5", "3.75"),
        )

    def test_unknown_prices_stay_empty(self):
        self.assertFalse(any(
            row[column] in {"None", "null"}
            for row in self.snapshots
            for column in ("input_price", "cached_input_price", "output_price")
        ))

    def test_card_declares_both_configs(self):
        card = (HISTORY_HF_DIR / "README.md").read_text(encoding="utf-8")
        self.assertIn("path: price_snapshots.csv", card)
        self.assertIn("path: price_changes.csv", card)
        self.assertIn("dataset_revision", card)
        self.assertIn("not a provider price change", card)


if __name__ == "__main__":
    unittest.main()
