"""
Layout:

    <git toplevel>/results/<experiment>/[<attempt>@]<commit>[-dirty_<patch_hash>]/
        source.patch      # only when the worktree was dirty
        <label>@<param_hash>/
            data.csv
            meta.json

- Outside a git repository, `./results` is used and the commit is `nogit`.
- The patch hash covers uncommitted changes to files selected by
  `.coordinatorinclude`, including untracked files. Git ignored files are
  excluded. Without include rules, all nonignored files are selected.
- NEW_ATTEMPT_NAME prefixes newly created revision directories only.
  Existing directories are matched by revision, ignoring the attempt name.
- If matching runs already exist, datapoints are appended instead of
  recomputed.
"""

import csv
from dataclasses import dataclass
import datetime
import functools
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pathspec

#
#
# Run identification
#
#


def _get_param_hash(params: dict) -> str:
    blob = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:6]


def _run_git_cmd(*args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args], capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return ""
    return completed.stdout.strip()


def _git_bytes(*args: str, input_data: bytes | None = None) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *args], input=input_data, capture_output=True, check=False
        )
    except FileNotFoundError:
        return b""
    return completed.stdout


def _nul_paths(data: bytes) -> list[str]:
    return [os.fsdecode(path) for path in data.split(b"\0") if path]


def _get_patch() -> bytes:
    root = _run_git_cmd("rev-parse", "--show-toplevel")
    if not root:
        return b""

    include_path = Path(root) / ".coordinatorinclude"
    rules = include_path.read_text().splitlines() if include_path.exists() else []
    has_rules = any(line.strip() and not line.startswith("#") for line in rules)
    spec = pathspec.GitIgnoreSpec.from_lines(rules) if has_rules else None

    tracked_changes = _nul_paths(
        _git_bytes("-C", root, "diff", "--name-only", "-z", "HEAD")
    )
    untracked = _nul_paths(
        _git_bytes("-C", root, "ls-files", "--others", "--exclude-standard", "-z")
    )
    config_name = ".coordinatorinclude"
    if (
        include_path.exists()
        and config_name not in tracked_changes
        and config_name not in untracked
    ):
        if not _git_bytes("-C", root, "ls-files", "--error-unmatch", "--", config_name):
            untracked.append(config_name)

    candidates = sorted(set(tracked_changes + untracked) - {config_name})
    ignored = set()
    if candidates:
        ignored = set(
            _nul_paths(
                _git_bytes(
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
        patch = _git_bytes(
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
        patch += _git_bytes(
            "-C", root, "diff", "--no-index", "--binary", "--", "/dev/null", path
        )
    return patch


def _revision_and_patch() -> tuple[str, bytes]:
    commit = _run_git_cmd("rev-parse", "--short=7", "HEAD") or "nogit"
    patch = _get_patch()
    if not patch:
        return commit, patch

    patch_hash = hashlib.sha256(patch).hexdigest()[:6]
    return f"{commit}-dirty_{patch_hash}", patch


def _get_revision() -> str:
    return _revision_and_patch()[0]


@functools.cache
def get_results_root() -> Path:
    toplevel = _run_git_cmd("rev-parse", "--show-toplevel")
    return (Path(toplevel) if toplevel else Path.cwd()) / "results"


#
#
# Writing
#
#


class RunDir:
    def __init__(self, path: Path):
        self.path = path
        self.data_path = path / "data.csv"

    def has_row(self, params: dict) -> bool:
        if not self.data_path.exists():
            return False

        rows = pd.read_csv(self.data_path)
        if not set(params) <= set(rows.columns):
            return False

        matches = pd.Series(True, index=rows.index)
        for key, value in params.items():
            column = rows[key]
            if pd.api.types.is_float_dtype(column):
                matches &= (column - float(value)).abs() < 1e-12
            else:
                matches &= column.astype(str) == str(value)

        return bool(matches.any())

    def append(self, row: dict) -> None:
        if self.data_path.exists():
            with open(self.data_path, newline="") as handle:
                fieldnames = next(csv.reader(handle))
        else:
            fieldnames = list(row)

        is_new = not self.data_path.exists()
        with open(self.data_path, "a", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            if is_new:
                writer.writeheader()
            writer.writerow(row)


def resolve_and_open_run(
    experiment: str, label: str, params: dict, meta=None
) -> RunDir:
    experiment_dir = get_results_root() / experiment
    revision, patch = _revision_and_patch()
    attempt = os.environ.get("NEW_ATTEMPT_NAME", "")
    revision_dir = experiment_dir / (f"{attempt}@{revision}" if attempt else revision)
    for candidate in sorted(experiment_dir.glob("*")):
        if candidate.is_dir() and candidate.name.split("@")[-1] == revision:
            revision_dir = candidate
            break

    run_dir = revision_dir / f"{label}@{_get_param_hash(params)}"
    if run_dir.exists():
        return RunDir(run_dir)

    run_dir.mkdir(parents=True)

    full_meta = {
        "experiment": experiment,
        "label": label,
        "params": params,
        "revision": revision,
        "started": datetime.datetime.now().isoformat(timespec="seconds"),
        "argv": sys.argv,
        **(meta or {}),
    }
    with open(run_dir / "meta.json", "w") as handle:
        json.dump(full_meta, handle, indent=2, sort_keys=True, default=str)

    patch_path = revision_dir / "source.patch"
    if patch and not patch_path.exists():
        patch_path.write_bytes(patch)

    return RunDir(run_dir)


@dataclass
class RunIdentifier:
    run_params: dict
    ...


@dataclass
class SweepIdentifier:
    sweep_params: dict
    sweep_axis: str
    ...
