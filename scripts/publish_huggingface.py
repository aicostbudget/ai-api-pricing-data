from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Mapping, TextIO
from urllib.parse import quote

try:
    from export_huggingface import (
        HF_DIR,
        PROJECTION_PATH,
        artifact_contents,
        read_json,
        validate_payload,
    )
except ModuleNotFoundError:
    from scripts.export_huggingface import (
        HF_DIR,
        PROJECTION_PATH,
        artifact_contents,
        read_json,
        validate_payload,
    )


ALLOWED_ARTIFACTS = ("prices.json", "prices.csv", "train.csv", "meta.json")
DEFAULT_HF_REPO_ID = "aicostbudget-ai/ai-api-pricing"
DEFAULT_HF_BRANCH = "main"
BOT_NAME = "AICostBudget Dataset Bot"
BOT_EMAIL = "aicostbudget-dataset-bot@users.noreply.github.com"
COMMIT_PREFIX = "data: publish pricing artifacts from GitHub"


class PublishError(Exception):
    classification = "PUBLISH_FAILURE"


class AuthFailure(PublishError):
    classification = "AUTH_FAILURE"


class NetworkFailure(PublishError):
    classification = "NETWORK_FAILURE"


class RemoteChanged(PublishError):
    classification = "REMOTE_CHANGED"


class ValidationFailure(PublishError):
    classification = "VALIDATION_FAILURE"


class UnexpectedHFChange(PublishError):
    classification = "UNEXPECTED_HF_CHANGE"


class PushFailure(PublishError):
    classification = "PUSH_FAILURE"


class RawGitError(Exception):
    def __init__(self, args: list[str], returncode: int, stdout: str, stderr: str):
        super().__init__(stderr or stdout or f"git exited with {returncode}")
        self.args_list = args
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@dataclass(frozen=True)
class PublishResult:
    status: str
    changed_files: tuple[str, ...]
    hf_head_before: str
    published_commit: str | None = None


GitRunner = Callable[..., subprocess.CompletedProcess[str]]
RemoteHeadReader = Callable[[str, str, Mapping[str, str], str], str]


def sanitize_error(value: object, secrets: tuple[str, ...] = ()) -> str:
    text = str(value)
    for secret in secrets:
        if not secret:
            continue
        for form in {secret, quote(secret, safe=""), quote(secret, safe="-_.")}:
            if form:
                text = text.replace(form, "***")
    text = re.sub(
        r"https://[^/@\s]+@huggingface\.co",
        "https://***@huggingface.co",
        text,
        flags=re.IGNORECASE,
    )
    return text


def require_token(environ: Mapping[str, str]) -> str:
    token = environ.get("HF_TOKEN", "").strip()
    if not token:
        raise AuthFailure("HF_TOKEN is not configured")
    return token


def run_git(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    secrets: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=dict(env) if env is not None else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode:
        raise RawGitError(
            args,
            completed.returncode,
            sanitize_error(completed.stdout, secrets),
            sanitize_error(completed.stderr, secrets),
        )
    return completed


@contextmanager
def git_auth_environment(token: str, temp_root: Path) -> Iterator[dict[str, str]]:
    askpass = temp_root / "hf-askpass.sh"
    askpass.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  *Username*) printf '%s\\n' oauth2 ;;\n"
        "  *Password*) printf '%s\\n' \"$HF_TOKEN\" ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
        newline="\n",
    )
    askpass.chmod(0o700)
    env = os.environ.copy()
    env.update(
        {
            "HF_TOKEN": token,
            "GIT_ASKPASS": str(askpass),
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_TRACE": "0",
            "GIT_TRACE_PACKET": "0",
            "GIT_CURL_VERBOSE": "0",
        }
    )
    try:
        yield env
    finally:
        askpass.unlink(missing_ok=True)


def classify_git_error(error: RawGitError, token: str, *, operation: str) -> PublishError:
    detail = sanitize_error(error.stderr or error.stdout or error, (token,))
    lowered = detail.lower()
    auth_markers = (
        "authentication failed",
        "invalid username or password",
        "could not read username",
        "access denied",
        "permission denied",
        "repository not found",
        "http 401",
        "http 403",
        "returned error: 401",
        "returned error: 403",
    )
    network_markers = (
        "could not resolve host",
        "failed to connect",
        "connection timed out",
        "operation timed out",
        "connection reset",
        "network is unreachable",
        "remote end hung up",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
        "returned error: 5",
    )
    if any(marker in lowered for marker in auth_markers):
        return AuthFailure(detail)
    if operation == "push":
        if "non-fast-forward" in lowered or "fetch first" in lowered or "[rejected]" in lowered:
            return PushFailure(f"NON_FAST_FORWARD: {detail}")
        if any(marker in lowered for marker in network_markers):
            return NetworkFailure(detail)
        return PushFailure(detail)
    if any(marker in lowered for marker in network_markers):
        return NetworkFailure(detail)
    return NetworkFailure(detail)


def validate_source_artifacts(source_dir: Path = HF_DIR) -> None:
    missing = [name for name in ALLOWED_ARTIFACTS if not (source_dir / name).is_file()]
    if missing:
        raise ValidationFailure(f"source artifact missing: {', '.join(missing)}")
    try:
        projection = read_json(PROJECTION_PATH)
        payload = read_json(source_dir / "prices.json")
        validate_payload(payload, projection)
        expected = artifact_contents(payload)
        stale = [
            name
            for name in ALLOWED_ARTIFACTS
            if (source_dir / name).read_text(encoding="utf-8") != expected[name]
        ]
    except Exception as error:
        raise ValidationFailure(sanitize_error(error)) from error
    if stale:
        raise ValidationFailure(
            f"source artifacts are internally inconsistent: {', '.join(stale)}"
        )


def hf_repo_url(repo_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo_id):
        raise ValidationFailure("HF_REPO_ID must use owner/dataset format")
    return f"https://huggingface.co/datasets/{repo_id}"


def read_remote_head(
    repo_url: str,
    branch: str,
    env: Mapping[str, str],
    token: str,
) -> str:
    try:
        completed = run_git(
            ["ls-remote", "--exit-code", repo_url, f"refs/heads/{branch}"],
            env=env,
            secrets=(token,),
        )
    except RawGitError as error:
        raise classify_git_error(error, token, operation="read_remote") from error
    fields = completed.stdout.strip().split()
    if not fields or not re.fullmatch(r"[0-9a-fA-F]{40,64}", fields[0]):
        raise NetworkFailure("Hugging Face remote main HEAD response was invalid")
    return fields[0].lower()


def clone_latest(
    repo_url: str,
    branch: str,
    destination: Path,
    env: Mapping[str, str],
    token: str,
    expected_head: str,
) -> None:
    try:
        run_git(
            ["-c", "core.autocrlf=false", "clone", "--branch", branch, "--single-branch", "--no-tags", repo_url, str(destination)],
            env=env,
            secrets=(token,),
        )
        cloned_head = run_git(["rev-parse", "HEAD"], cwd=destination).stdout.strip().lower()
    except RawGitError as error:
        raise classify_git_error(error, token, operation="clone") from error
    if cloned_head != expected_head:
        raise RemoteChanged(
            f"clone HEAD {cloned_head} differs from HF_HEAD_BEFORE {expected_head}"
        )


def status_paths(repo_dir: Path) -> tuple[str, ...]:
    try:
        raw = run_git(
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd=repo_dir
        ).stdout
    except RawGitError as error:
        raise UnexpectedHFChange(sanitize_error(error)) from error
    entries = raw.split("\0")
    paths: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4:
            paths.append(entry)
            continue
        status = entry[:2]
        paths.append(entry[3:])
        if "R" in status or "C" in status:
            if index < len(entries) and entries[index]:
                paths.append(entries[index])
                index += 1
    return tuple(sorted(set(paths)))


def audit_changed_files(repo_dir: Path) -> tuple[str, ...]:
    changed = status_paths(repo_dir)
    unexpected = [path for path in changed if path not in ALLOWED_ARTIFACTS]
    if unexpected:
        files = "\n".join(f"file: {path}" for path in unexpected)
        raise UnexpectedHFChange(files)
    return changed


def copy_allowlisted_artifacts(source_dir: Path, hf_repo_dir: Path) -> tuple[str, ...]:
    for name in ALLOWED_ARTIFACTS:
        source = source_dir / name
        if not source.is_file():
            raise ValidationFailure(f"source artifact missing: {name}")
        shutil.copyfile(source, hf_repo_dir / name)
    return audit_changed_files(hf_repo_dir)


def source_sha_label(source_sha: str | None) -> str:
    value = (source_sha or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{7,64}", value):
        return value[:7].lower()
    return "local"


def commit_artifacts(repo_dir: Path, source_sha: str | None) -> str:
    try:
        run_git(["config", "user.name", BOT_NAME], cwd=repo_dir)
        run_git(["config", "user.email", BOT_EMAIL], cwd=repo_dir)
        run_git(["add", "--", *ALLOWED_ARTIFACTS], cwd=repo_dir)
        staged = tuple(
            sorted(
                filter(
                    None,
                    run_git(["diff", "--cached", "--name-only", "-z"], cwd=repo_dir).stdout.split("\0"),
                )
            )
        )
        unexpected = [path for path in staged if path not in ALLOWED_ARTIFACTS]
        if unexpected:
            raise UnexpectedHFChange(
                "\n".join(f"file: {path}" for path in unexpected)
            )
        run_git(["diff", "--cached", "--check"], cwd=repo_dir)
        message = f"{COMMIT_PREFIX} {source_sha_label(source_sha)}"
        run_git(["commit", "-m", message], cwd=repo_dir)
        return run_git(["rev-parse", "HEAD"], cwd=repo_dir).stdout.strip().lower()
    except UnexpectedHFChange:
        raise
    except RawGitError as error:
        raise ValidationFailure(sanitize_error(error)) from error


def verify_remote_unchanged(head_before: str, head_pre_push: str) -> None:
    if head_pre_push != head_before:
        raise RemoteChanged(
            f"HF_HEAD_PRE_PUSH {head_pre_push} differs from HF_HEAD_BEFORE {head_before}"
        )


def push_fast_forward(
    repo_dir: Path,
    branch: str,
    env: Mapping[str, str],
    token: str,
) -> None:
    try:
        run_git(
            ["push", "origin", f"HEAD:{branch}"],
            cwd=repo_dir,
            env=env,
            secrets=(token,),
        )
    except RawGitError as error:
        raise classify_git_error(error, token, operation="push") from error


def publish_huggingface(
    *,
    source_dir: Path = HF_DIR,
    repo_url: str,
    branch: str = DEFAULT_HF_BRANCH,
    token: str,
    source_sha: str | None,
    dry_run: bool = False,
    output: TextIO,
    validate_source: Callable[[Path], None] = validate_source_artifacts,
    remote_head_reader: RemoteHeadReader = read_remote_head,
) -> PublishResult:
    if not token.strip():
        raise AuthFailure("HF_TOKEN is not configured")
    if branch != DEFAULT_HF_BRANCH:
        raise ValidationFailure("HF_BRANCH must be main")
    validate_source(source_dir)

    with tempfile.TemporaryDirectory(prefix="aicostbudget-hf-publish-") as temp_dir:
        temp_root = Path(temp_dir)
        clone_dir = temp_root / "hf-repo"
        with git_auth_environment(token, temp_root) as auth_env:
            head_before = remote_head_reader(repo_url, branch, auth_env, token)
            clone_latest(repo_url, branch, clone_dir, auth_env, token, head_before)
            initial_changes = status_paths(clone_dir)
            if initial_changes:
                raise UnexpectedHFChange(
                    "fresh Hugging Face clone was not clean:\n"
                    + "\n".join(f"file: {path}" for path in initial_changes)
                )
            changed = copy_allowlisted_artifacts(source_dir, clone_dir)
            if not changed:
                print("HF_ALREADY_IN_SYNC", file=output)
                return PublishResult("HF_ALREADY_IN_SYNC", (), head_before)

            print("allowed artifact changes:", file=output)
            for path in changed:
                print(f"file: {path}", file=output)
            if dry_run:
                print("DRY_RUN_OK", file=output)
                return PublishResult("DRY_RUN_OK", changed, head_before)

            published_commit = commit_artifacts(clone_dir, source_sha)
            head_pre_push = remote_head_reader(repo_url, branch, auth_env, token)
            verify_remote_unchanged(head_before, head_pre_push)
            push_fast_forward(clone_dir, branch, auth_env, token)
            print(f"HF_PUSHED: {published_commit}", file=output)
            return PublishResult("HF_PUSHED", changed, head_before, published_commit)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Safely publish four approved pricing artifacts into the independent Hugging Face history."
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    token_value = os.environ.get("HF_TOKEN", "")
    try:
        token = require_token(os.environ)
        repo_id = os.environ.get("HF_REPO_ID", DEFAULT_HF_REPO_ID)
        branch = os.environ.get("HF_BRANCH", DEFAULT_HF_BRANCH)
        publish_huggingface(
            repo_url=hf_repo_url(repo_id),
            branch=branch,
            token=token,
            source_sha=os.environ.get("GITHUB_SOURCE_SHA") or os.environ.get("GITHUB_SHA"),
            dry_run=args.dry_run,
            output=os.sys.stdout,
        )
    except PublishError as error:
        message = sanitize_error(error, (token_value,))
        print(f"{error.classification}: {message}", file=os.sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
