"""
Layout:

    <git toplevel>/results/<experiment>/[<label>@]<attempt-id>/
        source.patch      # only when the worktree was dirty
        [<label>@]<sweep-id>/<run-id>/
            data.csv
            metadata.json

- Outside a git repository, `./results` is used.
- NEW_ATTEMPT_NAME prefixes newly created revision directories only.
  Existing directories are matched by revision, ignoring the attempt name.
- If matching runs already exist, datapoints are appended instead of
  recomputed.
- Sweep and run IDs are full SHA-256 hashes; labels are cosmetic.
"""

import csv
import datetime
import functools
import hashlib
import json
import math
import os
from pathlib import Path

import pandas as pd

from coordinator.git import get_repository_root


def _validate_identity_value(value, location: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{location} must be a finite JSON value")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_identity_value(item, f"{location}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{location} keys must be strings")
            _validate_identity_value(item, f"{location}.{key}")
        return
    raise TypeError(f"{location} must contain only JSON-compatible values")


def _serialize_identity(identity: dict) -> str:
    _validate_identity_value(identity, "run identity")
    return json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _get_identity_hash(identity: dict) -> str:
    return hashlib.sha256(_serialize_identity(identity).encode()).hexdigest()


@functools.cache
def get_results_root() -> Path:
    return (get_repository_root() or Path.cwd()) / "results"


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
            if value is None:
                matches &= column.isna()
            elif (
                pd.api.types.is_float_dtype(column)
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            ):
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


def _find_id_directory(parent: Path, identity: str) -> Path | None:
    matches = (
        sorted(
            candidate
            for candidate in parent.glob("*")
            if candidate.is_dir() and candidate.name.rsplit("@", 1)[-1] == identity
        )
        if parent.exists()
        else []
    )
    if len(matches) > 1:
        raise ValueError(f"Multiple directories match identity {identity}")
    return matches[0] if matches else None


def resolve_and_open_run(experiment, sweep, run, patch: bytes) -> RunDir:
    attempt_id = experiment._id.value()
    sweep_id = sweep._id.value()
    run_id = run._id.value()
    experiment_dir = get_results_root() / experiment._name
    attempt_name = os.environ.get("NEW_ATTEMPT_NAME", "")
    if attempt_name and (
        attempt_name in {".", ".."}
        or any(character in attempt_name for character in "/\\@\x00")
    ):
        raise ValueError("NEW_ATTEMPT_NAME must be a valid label")
    attempt_dir = _find_id_directory(experiment_dir, attempt_id)
    if attempt_dir is None:
        directory_name = f"{attempt_name}@{attempt_id}" if attempt_name else attempt_id
        attempt_dir = experiment_dir / directory_name
    sweep_dir = _find_id_directory(attempt_dir, sweep_id) or attempt_dir / sweep_id
    run_dir = _find_id_directory(sweep_dir, run_id) or sweep_dir / run_id
    expected = {
        "attempt_id": attempt_id,
        "sweep_id": sweep_id,
        "run_id": run_id,
        "axis": sweep._axis_name,
        "axis_vals": list(sweep._axis_vals),
        "sweep_params": sweep._params,
        "run_params": run._params,
    }
    metadata_path = run_dir / "metadata.json"
    if run_dir.exists():
        try:
            stored = json.loads(metadata_path.read_text())
            if any(stored.get(key) != value for key, value in expected.items()):
                raise ValueError("stored identity differs")
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError(f"Cannot reuse {run_dir}: invalid run identity") from exc
        return RunDir(run_dir)

    run_dir.mkdir(parents=True)
    metadata = {
        **expected,
        "experiment": experiment._name,
        "revision": attempt_id,
        "started": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True))
    patch_path = attempt_dir / "source.patch"
    if patch and not patch_path.exists():
        patch_path.write_bytes(patch)
    return RunDir(run_dir)
