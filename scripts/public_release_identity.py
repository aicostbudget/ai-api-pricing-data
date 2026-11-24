"""Which source commit does the public API describe, and does a rebuild reproduce it?

A file cannot contain the hash of the commit that holds it, so a release is two commits:
the source commit (canonical data plus its snapshot) and the artifact commit that holds the
generated files. `api/v1/meta.json` is written at the source commit, so its `source_commit_sha`
always names the source commit and its `generated_at` is that commit's time.

The Pages workflow used to rebuild with the pushed commit (the artifact commit) and the current
time. The public file then named a different commit and time than the committed copy. This module
reads the identity from the committed `meta.json` instead, and `check-rebuild` fails when a rebuild
from that identity does not reproduce the committed `api/` and `data/` files byte for byte.

    python scripts/public_release_identity.py resolve         # prints release_sha= and generated_at=
    python scripts/public_release_identity.py check-rebuild   # run after scripts/build.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]

SOURCE_PATH = "data/canonical/models.json"
META_PATH = "api/v1/meta.json"
REBUILT_PATHS = ("api", "data")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MAX_LISTED_DIFFERENCES = 20


class IdentityError(ValueError):
    pass


def resolve_public_identity(
    release_revision: str,
    read_blob: Callable[[str, str], bytes],
    is_ancestor: Callable[[str, str], bool],
) -> dict[str, str]:
    """Return {"release_sha", "generated_at"} from the committed meta.json at release_revision."""
    try:
        meta = json.loads(read_blob(release_revision, META_PATH))
    except (subprocess.CalledProcessError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IdentityError(f"{META_PATH} at {release_revision} cannot be read as JSON") from error
    if not isinstance(meta, dict):
        raise IdentityError(f"{META_PATH} must be a JSON object")
    source = meta.get("source_commit_sha")
    if not isinstance(source, str) or not FULL_SHA.fullmatch(source):
        raise IdentityError(f"{META_PATH} source_commit_sha must be a 40-character lowercase git SHA")
    generated_at = meta.get("generated_at")
    if not isinstance(generated_at, str) or not UTC_TIMESTAMP.fullmatch(generated_at):
        raise IdentityError(f"{META_PATH} generated_at must be a UTC timestamp such as 2026-01-01T00:00:00Z")
    try:
        ancestor = is_ancestor(source, release_revision)
    except subprocess.CalledProcessError as error:
        raise IdentityError(f"source commit {source} is not in this checkout (shallow clone?)") from error
    if not ancestor:
        raise IdentityError(f"source commit {source} is not an ancestor of {release_revision}")
    try:
        if read_blob(source, SOURCE_PATH) != read_blob(release_revision, SOURCE_PATH):
            raise IdentityError(f"{SOURCE_PATH} differs between the source commit and {release_revision}: the artifact commit altered authoritative source facts")
    except subprocess.CalledProcessError as error:
        raise IdentityError(f"{SOURCE_PATH} cannot be read at the source commit {source}") from error
    return {"release_sha": source, "generated_at": generated_at}


def assert_rebuild_matches_committed(status_lines: list[str]) -> None:
    """status_lines come from `git status --porcelain` over api/ and data/ after a rebuild."""
    lines = [line for line in status_lines if line.strip()]
    if not lines:
        return
    shown = "\n".join("  " + line for line in lines[:MAX_LISTED_DIFFERENCES])
    more = f"\n  ... and {len(lines) - MAX_LISTED_DIFFERENCES} more" if len(lines) > MAX_LISTED_DIFFERENCES else ""
    raise IdentityError(
        "Rebuilding with the committed source SHA and generated_at does not reproduce the committed "
        f"public files ({len(lines)} differ). Regenerate and commit them with the release tooling:\n{shown}{more}"
    )


def _git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True).stdout


def _read_blob(revision: str, path: str) -> bytes:
    return _git("show", f"{revision}:{path}")


def _is_ancestor(before: str, after: str) -> bool:
    result = subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", before, after], capture_output=True)
    if result.returncode not in (0, 1):
        raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)
    return result.returncode == 0


def _emit(values: dict[str, str]) -> None:
    for key, value in values.items():
        print(f"{key}={value}")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8", newline="\n") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    resolve = commands.add_parser("resolve", help="read the source SHA and generated_at from the committed meta.json")
    resolve.add_argument("--revision", default="HEAD", help="release revision whose committed meta.json is read (default HEAD)")
    commands.add_parser("check-rebuild", help="fail when api/ or data/ differ from the committed files")
    args = parser.parse_args(argv)
    try:
        if args.command == "resolve":
            revision = _git("rev-parse", "--verify", f"{args.revision}^{{commit}}").decode().strip()
            _emit(resolve_public_identity(revision, _read_blob, _is_ancestor))
        else:
            status = _git("status", "--porcelain=v1", "--untracked-files=all", "--", *REBUILT_PATHS).decode("utf-8")
            assert_rebuild_matches_committed(status.splitlines())
            print("Rebuilt public files equal the committed files.")
    except (IdentityError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
