import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.update_release_approvals import (
    PROJECTION_PATH,
    SCOPE_PATH,
    WEBSITE_FIXTURE_PATH,
    digest,
    update_approvals,
    website_fixture_row,
)
from tests.test_official_pricing_closure import digest as closure_digest


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def write(repo, path, value):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def model(model_id, price=None, status="active"):
    return {"provider_id": "mistral-ai", "model_id": model_id, "status": status,
            "official_source_url": f"https://docs.example/{model_id}",
            "pricing": {"input": price, "output": price, "cached_input": None}}


class UpdateReleaseApprovalsTests(unittest.TestCase):
    def test_digest_matches_the_closure_test(self):
        row = {"b": [1, {"z": "é"}], "a": None}
        self.assertEqual(digest(row), closure_digest(row))

    def test_website_row_comes_from_the_canonical_record(self):
        self.assertEqual(website_fixture_row(model("tts", status="preview")), {
            "id": "tts", "status": "preview", "inputPrice": None, "cachedInputPrice": None,
            "outputPrice": None, "officialPriceUrl": "https://docs.example/tts",
        })

    def test_prepared_release_gets_digests_and_website_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, "init", "-q", "-b", "main")
            git(repo, "config", "user.name", "t")
            git(repo, "config", "user.email", "t@example.com")
            write(repo, "data/canonical/models.json", [model("old", 1)])
            write(repo, SCOPE_PATH, {"canonical": {}, "projection": {}})
            write(repo, WEBSITE_FIXTURE_PATH, [{"id": "old", "inputPrice": 1}])
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "base")
            write(repo, "data/canonical/models.json", [model("old", 2), model("new", status="preview")])
            git(repo, "commit", "-q", "-am", "source")
            projection = {"models": [{"canonicalInternalId": "mistral-ai/old", "id": "old", "inputPrice": 2},
                                     {"canonicalInternalId": "mistral-ai/new", "id": "new", "inputPrice": None}]}
            write(repo, PROJECTION_PATH, projection)
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "artifacts")

            result = update_approvals(repo)

            scope = json.loads((repo / SCOPE_PATH).read_text(encoding="utf-8"))
            self.assertEqual(scope["canonical"], {"mistral-ai/old": digest(model("old", 2)), "mistral-ai/new": digest(model("new", status="preview"))})
            self.assertEqual(scope["projection"]["mistral-ai/new"], digest(projection["models"][1]))
            website = json.loads((repo / WEBSITE_FIXTURE_PATH).read_text(encoding="utf-8"))
            self.assertEqual([row["id"] for row in website], ["old", "new"], "only added models get a Website row")
            self.assertEqual(result["website_fixture_added"], ["new"])
            self.assertTrue(any("price change" in item and "mistral-ai/old" in item for item in result["manual"]))


if __name__ == "__main__":
    unittest.main()
