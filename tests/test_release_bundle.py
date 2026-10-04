import hashlib
import json
import re
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import build_release_bundle as release_bundle
from scripts.export_huggingface import preserve_generated_at_for_timestamp_only_change
from scripts.build_release_bundle import (
    ROOT,
    V1_SOURCES,
    asset,
    V2_SOURCES,
    build_contents,
    projection_stats,
    verify_contents,
    write_bundle,
)


class ReleaseBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v1 = {name: (ROOT / path).read_bytes() for name, path in V1_SOURCES.items()}
        cls.v2 = {name: (ROOT / "huggingface" / name.removeprefix("pricing-v2-")).read_bytes() for name in V2_SOURCES}

    def fixture_bundle(self):
        files = {**self.v1, **self.v2}
        manifest = {"status": "candidate", "release_version": None, "release_date": None, "projections": {}}
        for projection, prefix, sources in (
            ("github_pages_v1", "github-pages-v1", V1_SOURCES),
            ("pricing_v2", "pricing-v2", V2_SOURCES),
        ):
            stats = projection_stats(files[f"{prefix}-prices.json"], files[f"{prefix}-prices.csv"], files[f"{prefix}-meta.json"], projection)
            manifest["projections"][projection] = {**stats, "assets": [asset(name, path, files[name]) for name, path in sources.items()]}
        files["release-manifest.json"] = json.dumps(manifest).encode()
        files["SHA256SUMS.txt"] = "".join(f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n" for name in sorted(files)).encode()
        return files

    def pinned_checkout(self):
        website = Path("D:/ai-cost-control-tool/aicostguard-english")
        if not website.is_dir():
            self.skipTest("local Website checkout is unavailable")
        tracked_paths = set(subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", "HEAD", "--", "data/snapshots/"],
            cwd=ROOT,
            text=True,
        ).splitlines())
        snapshot_dates = {
            parts[2]
            for path in tracked_paths
            if len(parts := path.split("/")) == 4
            and parts[:2] == ["data", "snapshots"]
            and parts[3] in {"prices.json", "prices.csv"}
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[2])
        }
        self.assertTrue(snapshot_dates, "HEAD has no tracked dated V1 snapshot")
        snapshot = max(snapshot_dates)
        for suffix in ("json", "csv"):
            self.assertIn(f"data/snapshots/{snapshot}/prices.{suffix}", tracked_paths)
        return website, snapshot

    def build_with_pinned_source_change(self, changed_path, change):
        website, snapshot = self.pinned_checkout()
        original_source = release_bundle.source

        def altered_source(repo, revision, path):
            content = original_source(repo, revision, path)
            if path != changed_path:
                return content
            payload = json.loads(content)
            change(payload)
            return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

        with patch.object(release_bundle, "source", side_effect=altered_source):
            return build_contents("HEAD", website, "HEAD", snapshot)

    def test_valid_v1_and_v2(self):
        for prefix, projection, assets in (
            ("github-pages-v1", "github_pages_v1", self.v1),
            ("pricing-v2", "pricing_v2", self.v2),
        ):
            stats = projection_stats(assets[f"{prefix}-prices.json"], assets[f"{prefix}-prices.csv"], assets[f"{prefix}-meta.json"], projection)
            self.assertGreater(stats["records"], 0)
            self.assertGreater(stats["providers"], 0)

    def test_v1_prices_with_v2_meta_fails(self):
        with self.assertRaises(ValueError):
            projection_stats(self.v1["github-pages-v1-prices.json"], self.v1["github-pages-v1-prices.csv"], self.v2["pricing-v2-meta.json"], "github_pages_v1")

    def test_v2_prices_with_v1_meta_fails(self):
        with self.assertRaises(ValueError):
            projection_stats(self.v2["pricing-v2-prices.json"], self.v2["pricing-v2-prices.csv"], self.v1["github-pages-v1-meta.json"], "pricing_v2")

    def test_record_count_mismatch_fails(self):
        meta = json.loads(self.v1["github-pages-v1-meta.json"])
        meta["model_count"] += 1
        with self.assertRaisesRegex(ValueError, "count mismatch"):
            projection_stats(self.v1["github-pages-v1-prices.json"], self.v1["github-pages-v1-prices.csv"], json.dumps(meta).encode(), "github_pages_v1")

    def test_modified_asset_fails_hash_check(self):
        files = self.fixture_bundle()
        files["github-pages-v1-prices.csv"] += b"\n"
        with self.assertRaises(ValueError):
            verify_contents(files)

    def test_source_path_projection_mismatch_fails(self):
        files = self.fixture_bundle()
        manifest = json.loads(files["release-manifest.json"])
        manifest["projections"]["pricing_v2"]["assets"][0]["source_path"] = "api/v1/prices.json"
        files["release-manifest.json"] = json.dumps(manifest).encode()
        with self.assertRaisesRegex(ValueError, "source_path"):
            verify_contents(files)

    def test_two_builds_are_byte_identical(self):
        first = self.fixture_bundle()
        second = self.fixture_bundle()
        self.assertEqual(first, second)
        verify_contents(first)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "candidate"
            write_bundle(first, output)
            self.assertEqual({path.name: path.read_bytes() for path in output.iterdir()}, first)
            with self.assertRaises(FileExistsError):
                write_bundle(second, output)

    def test_pinned_website_export_build_when_checkout_available(self):
        website, snapshot = self.pinned_checkout()
        files = build_contents("HEAD", website, "HEAD", snapshot)
        manifest = verify_contents(files)
        self.assertEqual(manifest["snapshot_date"], snapshot)
        self.assertEqual(manifest["snapshot_path"], f"data/snapshots/{snapshot}/")
        self.assertEqual(files["pricing-v2-prices.json"], release_bundle.source(ROOT, "HEAD", "huggingface/prices.json"))

    def test_timestamp_only_drift_keeps_pinned_hf_generated_at(self):
        mirror = json.loads(release_bundle.source(ROOT, "HEAD", "huggingface/prices.json"))
        mirror_time = datetime.fromisoformat(mirror["metadata"]["generated_at"].replace("Z", "+00:00"))
        newer_time = (mirror_time + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        self.assertLess(mirror_time + timedelta(seconds=1), datetime.now(timezone.utc))

        def change_generated_at(meta):
            meta["generated_at"] = newer_time

        files = self.build_with_pinned_source_change("api/v1/meta.json", change_generated_at)
        manifest = verify_contents(files)
        self.assertEqual(manifest["projections"]["pricing_v2"]["generated_at"], mirror["metadata"]["generated_at"])
        self.assertEqual(files["pricing-v2-prices.json"], release_bundle.source(ROOT, "HEAD", "huggingface/prices.json"))

    def test_record_drift_still_fails_pinned_hf_parity(self):
        def change_record(mirror):
            mirror["records"][0]["notes"] += " changed"

        with self.assertRaisesRegex(ValueError, "Website export and HF mirror differ: pricing-v2-prices.json"):
            self.build_with_pinned_source_change("huggingface/prices.json", change_record)

    def test_substantive_metadata_drift_still_fails_pinned_hf_parity(self):
        def change_metadata(mirror):
            mirror["metadata"]["last_updated"] = "2030-01-01T00:00:00Z"

        with self.assertRaisesRegex(ValueError, "Website export and HF mirror differ: pricing-v2-prices.json"):
            self.build_with_pinned_source_change("huggingface/prices.json", change_metadata)

    def test_substantive_drift_does_not_preserve_generated_at(self):
        mirror = json.loads(release_bundle.source(ROOT, "HEAD", "huggingface/prices.json"))
        for field in ("records", "metadata"):
            with self.subTest(field=field):
                current = json.loads(json.dumps(mirror))
                candidate = json.loads(json.dumps(mirror))
                candidate["metadata"]["generated_at"] = "2000-01-01T00:00:00Z"
                if field == "records":
                    current["records"][0]["notes"] += " changed"
                else:
                    current["metadata"]["last_updated"] = "2030-01-01T00:00:00Z"
                preserve_generated_at_for_timestamp_only_change(candidate, current)
                self.assertEqual(candidate["metadata"]["generated_at"], "2000-01-01T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
