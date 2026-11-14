"""Filesystem index for the notebook results browser."""

import json
from dataclasses import dataclass
from pathlib import Path

from coordinator.browser import ResultRun


@dataclass
class ResultIndex:
    root: Path
    runs: list[ResultRun]
    warnings: list[str]

    @classmethod
    def scan(cls, root: Path) -> "ResultIndex":
        runs = []
        warnings = []
        if not root.is_dir():
            return cls(root, runs, [f"Results directory does not exist: {root}"])
        for path in sorted(root.glob("*/*/*/*")):
            if not path.is_dir() or path.is_symlink() or not path.resolve().is_relative_to(root):
                continue
            metadata_path = path / "metadata.json"
            data_path = path / "data.csv"
            if not metadata_path.is_file() or metadata_path.is_symlink():
                warnings.append(f"Skipped {path}: missing metadata.json")
                continue
            if not data_path.is_file() or data_path.is_symlink():
                warnings.append(f"Skipped {path}: missing data.csv")
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if not isinstance(metadata, dict):
                    raise ValueError("metadata is not an object")
                axis = metadata.get("axis_name", metadata.get("axis"))
                params = metadata.get("run_params", {})
                shared = metadata.get("sweep_params", {})
                if not isinstance(axis, str) or not axis:
                    raise ValueError("axis must be a nonempty string")
                if not isinstance(params, dict) or not isinstance(shared, dict):
                    raise ValueError("params and shared must be objects")
            except (OSError, ValueError, TypeError) as exc:
                warnings.append(f"Skipped {path}: invalid metadata.json ({exc})")
                continue
            attempt = path.parent.parent
            attempt_name = attempt.name.split("@", 1)
            patch = attempt / "source.patch"
            runs.append(ResultRun(
                path=path,
                experiment=path.parent.parent.parent.name,
                label=path.name.rsplit("@", 1)[0] if "@" in path.name else path.name[:8],
                revision=str(metadata.get("revision", attempt_name[-1])),
                attempt=attempt_name[0] if len(attempt_name) == 2 else "",
                started=str(metadata.get("start_datetime", metadata.get("started", ""))),
                axis=axis,
                params=params,
                shared=shared,
                sweep=path.parent.name,
                metadata={},
                patch_path=patch if patch.is_file() and not patch.is_symlink() else None,
            ))
        runs.sort(key=lambda run: (run.started, run.experiment, run.label), reverse=True)
        return cls(root, runs, warnings)

    def paths(self, kind: str) -> set[str]:
        levels = {"experiment": 2, "attempt": 1, "sweep": 0, "run": None,
                  "patch": 1, "data": None, "metadata": None}
        if kind not in levels:
            raise ValueError("Unknown result type.")
        level = levels[kind]
        return {self.relative(run.path.parents[level]) if level is not None else self.relative(run.path)
                for run in self.runs}

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def members(self, kind: str, path: str) -> list[ResultRun]:
        if kind not in {"run", "sweep", "attempt"} or path not in self.paths(kind):
            raise ValueError("Result is no longer available. Refresh the browser.")
        target = self.root / path
        return [run for run in self.runs if run.path == target or
                (kind != "run" and target in run.path.parents)]

    def manifest(self) -> dict:
        """Send only display/search fields; full metadata and CSVs stay on disk."""
        items = []
        for run in self.runs:
            rel = self.relative(run.path)
            items.append({
                "path": rel,
                "experiment": run.experiment,
                "attempt": run.path.parent.parent.name,
                "sweep": run.path.parent.name,
                "run": run.path.name,
                "started": run.started,
                "axis": run.axis,
                "params": run.params,
                "shared": run.shared,
                "has_patch": run.patch_path is not None,
            })
        return {"runs": items, "warnings": self.warnings}
