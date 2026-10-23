import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.release_worktree import create, directory_links, link_directory, remove


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


class ReleaseWorktreeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.origin = base / "origin"
        self.origin.mkdir()
        git(self.origin, "init", "-q", "-b", "main")
        git(self.origin, "config", "user.name", "t")
        git(self.origin, "config", "user.email", "t@example.com")
        (self.origin / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
        (self.origin / "README.md").write_text("x\n", encoding="utf-8")
        git(self.origin, "add", "-A")
        git(self.origin, "commit", "-q", "-m", "base")
        self.repo = base / "repo"
        git(base, "clone", "-q", str(self.origin), str(self.repo))
        git(self.repo, "config", "user.name", "t")
        git(self.repo, "config", "user.email", "t@example.com")
        self.dependencies = base / "real-node-modules"
        (self.dependencies / "pkg").mkdir(parents=True)
        (self.dependencies / "pkg" / "index.js").write_text("keep\n", encoding="utf-8")
        self.package = base / "real-package"
        self.package.mkdir()
        (self.package / "package.json").write_text("{}\n", encoding="utf-8")
        self.worktree = base / "wt"

    def tearDown(self):
        self.tmp.cleanup()

    def test_remove_unlinks_every_link_and_keeps_the_linked_files(self):
        create(self.repo, self.worktree, "data/x", "origin/main", self.dependencies)
        self.assertEqual((self.worktree / "node_modules/pkg/index.js").read_text(encoding="utf-8"), "keep\n")
        nested = self.worktree / "packages-cache" / "node_modules"
        nested.mkdir(parents=True)
        link_directory(nested / "workspace-package", self.package)
        self.assertEqual(sorted(path.name for path in directory_links(self.worktree)), ["node_modules", "workspace-package"])

        remove(self.repo, self.worktree, force=True, delete_branch=False)

        self.assertFalse(self.worktree.exists())
        self.assertEqual((self.dependencies / "pkg/index.js").read_text(encoding="utf-8"), "keep\n")
        self.assertTrue((self.package / "package.json").is_file())
        self.assertNotIn(str(self.worktree.resolve()).replace("\\", "/").lower(),
                         git(self.repo, "worktree", "list").replace("\\", "/").lower())

    def test_remove_refuses_uncommitted_work(self):
        create(self.repo, self.worktree, "data/y", "origin/main", None)
        (self.worktree / "README.md").write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "uncommitted changes"):
            remove(self.repo, self.worktree, force=False, delete_branch=False)
        self.assertTrue(self.worktree.exists())

    def test_remove_can_delete_a_merged_branch(self):
        create(self.repo, self.worktree, "data/z", "origin/main", None)
        remove(self.repo, self.worktree, force=False, delete_branch=True)
        self.assertEqual(git(self.repo, "branch", "--list", "data/z"), "")

    def test_create_refuses_an_existing_path(self):
        self.worktree.mkdir()
        with self.assertRaisesRegex(SystemExit, "already exists"):
            create(self.repo, self.worktree, "data/w", "origin/main", None)


if __name__ == "__main__":
    unittest.main()
