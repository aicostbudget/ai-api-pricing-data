import tempfile
import unittest
from pathlib import Path

from tests.website_source import resolve_website_source


class WebsiteSourceResolverTests(unittest.TestCase):
    def test_ci_layout_uses_repository_website_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "pricing-repository"
            website_source = root / "website-source"
            website_source.mkdir(parents=True)

            self.assertEqual(
                resolve_website_source(root, environ={}),
                website_source,
            )

    def test_environment_override_takes_precedence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "pricing-repository"
            override = Path(temp_dir) / "explicit-website-source"
            (root / "website-source").mkdir(parents=True)
            override.mkdir()

            self.assertEqual(
                resolve_website_source(
                    root,
                    environ={"WEBSITE_SOURCE_ROOT": str(override)},
                ),
                override,
            )

    def test_missing_source_lists_every_candidate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "pricing-repository"
            override = Path(temp_dir) / "missing-override"

            with self.assertRaisesRegex(FileNotFoundError, "Website source not found") as raised:
                resolve_website_source(
                    root,
                    environ={"WEBSITE_SOURCE_ROOT": str(override)},
                )

            message = str(raised.exception)
            self.assertIn(str(override), message)
            self.assertIn(str(root / "website-source"), message)
            self.assertIn(
                str(root.parent / "ai-cost-control-tool" / "aicostguard-english"),
                message,
            )


if __name__ == "__main__":
    unittest.main()
