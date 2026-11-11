"""Git revision and selected worktree patch used as attempt provenance.

The patch includes files matched by .coordinatorinclude and excludes ignored files.
Without include rules, all nonignored changed files are selected.
"""

import hashlib
import os
import subprocess
from pathlib import Path

import pathspec


def _run_git_command(*args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args], capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return ""
    return completed.stdout.strip()


def _read_git_bytes(*args: str, input_data: bytes | None = None) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *args], input=input_data, capture_output=True, check=False
        )
    except FileNotFoundError:
        return b""
    return completed.stdout


def _decode_nul_paths(data: bytes) -> list[str]:
    return [os.fsdecode(path) for path in data.split(b"\0") if path]


def get_repository_root() -> Path | None:
    root = _run_git_command("rev-parse", "--show-toplevel")
    return Path(root) if root else None


def _get_patch() -> bytes:
    root = get_repository_root()
    if root is None:
        return b""

    include_path = root / ".coordinatorinclude"
    rules = include_path.read_text().splitlines() if include_path.exists() else []
    has_rules = any(line.strip() and not line.startswith("#") for line in rules)
    spec = pathspec.GitIgnoreSpec.from_lines(rules) if has_rules else None

    tracked_changes = _decode_nul_paths(
        _read_git_bytes("-C", root, "diff", "--name-only", "-z", "HEAD")
    )
    untracked = _decode_nul_paths(
        _read_git_bytes("-C", root, "ls-files", "--others", "--exclude-standard", "-z")
    )
    config_name = ".coordinatorinclude"
    if (
        include_path.exists()
        and config_name not in tracked_changes
        and config_name not in untracked
    ):
        if not _read_git_bytes("-C", root, "ls-files", "--error-unmatch", "--", config_name):
            untracked.append(config_name)

    candidates = sorted(set(tracked_changes + untracked) - {config_name})
    ignored = set()
    if candidates:
        ignored = set(
            _decode_nul_paths(
                _read_git_bytes(
                    "-C",
                    root,
                    "check-ignore",
                    "--no-index",
                    "-z",
                    "--stdin",
                    input_data=b"\0".join(os.fsencode(path) for path in candidates)
                    + b"\0",
                )
            )
        )

    selected = {
        path
        for path in candidates
        if path not in ignored and (spec is None or spec.match_file(path))
    }
    if config_name in tracked_changes or config_name in untracked:
        selected.add(config_name)

    tracked_selected = sorted(selected.intersection(tracked_changes))
    untracked_selected = sorted(selected.intersection(untracked))
    patch = b""
    if tracked_selected:
        patch = _read_git_bytes(
            "-C",
            root,
            "diff",
            "--no-ext-diff",
            "--binary",
            "HEAD",
            "--",
            *(f":(literal){path}" for path in tracked_selected),
        )
    for path in untracked_selected:
        patch += _read_git_bytes(
            "-C", root, "diff", "--no-index", "--binary", "--", "/dev/null", path
        )
    return patch


def get_revision_and_patch() -> tuple[str, bytes]:
    commit = _run_git_command("rev-parse", "--short=7", "HEAD") or "nogit"
    patch = _get_patch()
    if not patch:
        return commit, patch

    patch_hash = hashlib.sha256(patch).hexdigest()[:6]
    return f"{commit}-dirty_{patch_hash}", patch

