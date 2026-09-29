"""
Layout:

    <git toplevel>/results/<experiment>/[<attempt>@]<commit>[-dirty_<patch_hash>]/
        source.patch      # only when the worktree was dirty
        <label>@<param_hash>/
            data.csv
            meta.json

- Outside a git repository, `./results` is used and the commit is `nogit`.
- The patch hash is calculated from `git diff HEAD` and serves to
  differentiate runs with different uncommitted code versions.
- NEW_ATTEMPT_NAME prefixes newly created revision directories only.
  Existing directories are matched by revision, ignoring the attempt name.
- If matching runs already exist, datapoints are appended instead of
  recomputed.
"""

import csv
import datetime
import functools
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

#
#
# Run identification
#
#


def get_param_hash(params: dict) -> str:
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


@functools.cache
def _get_patch() -> str:
    return _run_git_cmd("diff", "HEAD")


def get_revision() -> str:
    commit = _run_git_cmd("rev-parse", "--short=7", "HEAD") or "nogit"
    patch = _get_patch()
    if not patch:
        return commit

    patch_hash = hashlib.sha256(patch.encode()).hexdigest()[:6]
    return f"{commit}-dirty_{patch_hash}"


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
    revision = get_revision()
    attempt = os.environ.get("NEW_ATTEMPT_NAME", "")
    revision_dir = experiment_dir / (f"{attempt}@{revision}" if attempt else revision)
    for candidate in sorted(experiment_dir.glob("*")):
        if candidate.is_dir() and candidate.name.split("@")[-1] == revision:
            revision_dir = candidate
            break

    run_dir = revision_dir / f"{label}@{get_param_hash(params)}"
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
    patch = _get_patch()
    if patch and not patch_path.exists():
        patch_path.write_text(patch)

    return RunDir(run_dir)


#
#
# Reading
#
#


def load_experiment_runs(experiment: str, latest_only: bool = True) -> pd.DataFrame:
    experiment_dir = get_results_root() / experiment

    curves = {}
    for run_dir in sorted(experiment_dir.glob("*/*@*")):
        if run_dir.is_dir():
            curves.setdefault(run_dir.name, []).append(run_dir)

    frames = []
    for curve, run_dirs in curves.items():
        if latest_only:
            run_dirs = [
                max(
                    run_dirs,
                    key=lambda path: json.loads((path / "meta.json").read_text())[
                        "started"
                    ],
                )
            ]

        for run_dir in run_dirs:
            data_path = run_dir / "data.csv"
            if not data_path.exists():
                continue

            frame = pd.read_csv(data_path)
            frame["curve"] = curve
            frame["label"] = curve.split("@")[0]
            frame["revision"] = run_dir.parent.name.split("@")[-1]
            frame["run"] = run_dir.parent.name
            frames.append(frame)

    if not frames:
        raise FileNotFoundError(f"No runs found under {experiment_dir}")

    return pd.concat(frames, ignore_index=True).sort_values(
        ["curve", "run"], kind="stable"
    )
