"""Create and remove release worktrees without the Windows traps.

create: fetch origin, add a worktree on a new branch from origin/main, and optionally link a
        node_modules directory from another checkout instead of reinstalling it.
remove: refuse a worktree with uncommitted work, unlink every directory link inside it without
        following it (Python 3.11 rmtree and os.walk descend into Windows junctions and would
        delete the linked dependencies), then remove the worktree, falling back to a long-path
        delete when git cannot.

  python scripts/release_worktree.py create D:/ai-api-pricing-data-x --branch data/x
  python scripts/release_worktree.py create D:/site-x --repo D:/site --branch fix/x --link-node-modules D:/site/node_modules
  python scripts/release_worktree.py remove D:/ai-api-pricing-data-x [--delete-branch]
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT: junctions and symlinks on Windows


def git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=repo, text=True, encoding="utf-8", capture_output=True)
    if check and result.returncode:
        raise SystemExit(f"git {' '.join(args)} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def is_link(entry: os.DirEntry) -> bool:
    if entry.is_symlink():
        return True
    attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    return bool(attributes & REPARSE_POINT)


def directory_links(root: Path) -> list[Path]:
    """Every symlink or junction under root, without descending into any of them."""
    links: list[Path] = []
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            entries = list(os.scandir(current))
        except FileNotFoundError:
            continue
        for entry in entries:
            if is_link(entry):
                links.append(Path(entry.path))
            elif entry.is_dir(follow_symlinks=False):
                pending.append(Path(entry.path))
    return links


def unlink(link: Path) -> None:
    # A directory junction or directory symlink is removed with rmdir, which removes only the link.
    try:
        os.rmdir(link)
    except NotADirectoryError:
        os.unlink(link)
    except OSError:
        os.unlink(link)


def link_directory(link: Path, target: Path) -> None:
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    else:
        link.symlink_to(target, target_is_directory=True)


def long_path(path: Path) -> str:
    text = str(path.resolve())
    return "\\\\?\\" + text if os.name == "nt" and not text.startswith("\\\\?\\") else text


def _make_writable_and_retry(function, path, _exc_info):
    os.chmod(path, stat.S_IWRITE)
    function(path)


def create(repo: Path, path: Path, branch: str, base: str, node_modules: Path | None) -> None:
    if path.exists():
        raise SystemExit(f"{path} already exists")
    git(repo, "fetch", "--quiet", "origin")
    git(repo, "worktree", "add", "-b", branch, str(path), base)
    if node_modules:
        if not (node_modules / ".package-lock.json").exists() and not any(node_modules.iterdir()):
            raise SystemExit(f"{node_modules} does not look like an installed node_modules")
        link_directory(path / "node_modules", node_modules)
    print(f"created {path} on {branch} from {git(repo, 'rev-parse', '--short', base)}")


def remove(repo: Path, path: Path, force: bool, delete_branch: bool) -> None:
    path = path.resolve()
    if not path.exists():
        git(repo, "worktree", "prune")
        raise SystemExit(f"{path} does not exist (pruned stale worktree records)")
    branch = git(path, "branch", "--show-current", check=False)
    dirty = git(path, "status", "--porcelain", "--untracked-files=all", check=False)
    if dirty and not force:
        raise SystemExit(f"{path} has uncommitted changes; commit them or pass --force:\n{dirty}")
    links = directory_links(path)
    for link in links:
        unlink(link)
    removed = subprocess.run(["git", "worktree", "remove", "--force", str(path)], cwd=repo, capture_output=True, text=True)
    if removed.returncode and path.exists():
        shutil.rmtree(long_path(path), onerror=_make_writable_and_retry)
    git(repo, "worktree", "prune")
    print(f"removed {path} (unlinked {len(links)} directory link{'s' if len(links) != 1 else ''})")
    if delete_branch and branch:
        git(repo, "branch", "-d", branch)
        print(f"deleted merged branch {branch}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    add = sub.add_parser("create")
    add.add_argument("path", type=Path)
    add.add_argument("--branch", required=True)
    add.add_argument("--base", default="origin/main")
    add.add_argument("--repo", type=Path, default=ROOT)
    add.add_argument("--link-node-modules", type=Path)
    rm = sub.add_parser("remove")
    rm.add_argument("path", type=Path)
    rm.add_argument("--repo", type=Path, default=ROOT)
    rm.add_argument("--force", action="store_true", help="discard uncommitted changes in the worktree")
    rm.add_argument("--delete-branch", action="store_true", help="also delete its branch if fully merged")
    args = parser.parse_args()
    if args.action == "create":
        create(args.repo.resolve(), args.path, args.branch, args.base, args.link_node_modules)
    else:
        remove(args.repo.resolve(), args.path, args.force, args.delete_branch)


if __name__ == "__main__":
    sys.exit(main())
