import hashlib
import json
import tempfile
import unittest
from pathlib import Path

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
        website = Path("D:/ai-cost-control-tool/aicostguard-english")
        if not website.is_dir():
            self.skipTest("local Website checkout is unavailable")
        files = build_contents("HEAD", website, "HEAD", "2026-09-30")
        verify_contents(files)


if __name__ == "__main__":
    unittest.main()
