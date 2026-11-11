import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from coordinator.results import get_results_root

_DEPTH = {"experiment": 1, "attempt": 2, "sweep": 3, "run": 4}


def _resolve_managed_path(root: Path | str, kind: str, path: Path | str) -> Path:
    """Reject paths outside the results tree or at unexpected depths."""
    if kind not in _DEPTH:
        raise ValueError(f"Unknown result type: {kind}")

    root = Path(root).expanduser().resolve()
    target = Path(path).expanduser()

    if target.is_symlink():
        raise ValueError("Result path must not be a symbolic link.")

    target = target.resolve()

    try:
        parts = target.relative_to(root).parts
    except ValueError as exc:
        raise ValueError("Result path is outside the results directory.") from exc

    if len(parts) != _DEPTH[kind] or not target.is_dir():
        raise ValueError("Result directory no longer exists at the expected location.")

    return target


def _validate_name(name: str, *, allow_empty: bool = False) -> None:
    if not isinstance(name, str) or (not name and not allow_empty):
        raise ValueError("Name must not be empty.")
    if name != name.strip() or name in {".", ".."}:
        raise ValueError("Name must not have surrounding spaces or be '.' or '..'.")
    if any(char in name for char in ("/", "\\", "@", "\x00", "\n", "\r")):
        raise ValueError(
            "Name must not contain a path separator, '@', or a line break."
        )


def _write_metadata(path: Path, content: bytes) -> None:
    """Replace metadata atomically while retaining its existing permissions."""
    descriptor, temporary = tempfile.mkstemp(prefix=".meta-", dir=path.parent)

    try:
        os.fchmod(descriptor, path.stat().st_mode)

        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)

        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def rename_result(root: Path | str, kind: str, path: Path | str, name: str) -> Path:
    """Rename the editable part of a stored result and matching metadata."""
    target = _resolve_managed_path(root, kind, path)
    _validate_name(name, allow_empty=kind != "experiment")

    if kind == "experiment":
        new_dirname = name
    elif kind == "attempt":
        revision = target.name.split("@", 1)[-1]
        new_dirname = f"{name}@{revision}" if name else revision
    else:
        suffix = target.name.rsplit("@", 1)[-1]
        new_dirname = f"{name}@{suffix}" if name else suffix

    destination = target.with_name(new_dirname)

    if destination == target:
        return target
    if destination.exists():
        raise FileExistsError(f"A result named '{new_dirname}' already exists.")

    field = {"experiment": "experiment"}.get(kind)
    changes = []

    if field:
        for meta_path in (
            target.rglob("metadata.json")
            if kind == "experiment"
            else [target / "metadata.json"]
        ):
            if meta_path.is_symlink():
                continue

            original = meta_path.read_bytes()

            try:
                metadata = json.loads(original)
            except (ValueError, UnicodeDecodeError):
                continue

            if not isinstance(metadata, dict):
                continue

            metadata[field] = name
            updated = json.dumps(
                metadata, indent=2, sort_keys=True, default=str
            ).encode()
            changes.append((meta_path.relative_to(target), original, updated))

    target.rename(destination)
    written = []

    try:
        for relative_path, original, updated in changes:
            _write_metadata(destination / relative_path, updated)
            written.append((relative_path, original))
    except OSError:
        for relative_path, original in reversed(written):
            _write_metadata(destination / relative_path, original)

        destination.rename(target)
        raise

    return destination


def delete_result(root: Path | str, kind: str, path: Path | str) -> None:
    target = _resolve_managed_path(root, kind, path)
    shutil.rmtree(target)


@dataclass(frozen=True)
class ResultRun:
    path: Path
    experiment: str
    label: str
    revision: str
    attempt: str
    started: str
    axis: str
    params: dict
    shared: dict
    sweep: str
    metadata: dict
    patch_path: Path | None

    @property
    def identity(self) -> str:
        return str(self.path)


def scan_results(root: Path | str | None = None) -> tuple[list[ResultRun], list[str]]:
    """Read metadata without loading CSV data; report invalid runs."""
    root = Path(root) if root is not None else get_results_root()
    runs = []
    warnings = []

    if not root.is_dir():
        return runs, [f"Results directory does not exist: {root}"]

    for run_dir in sorted(root.glob("*/*/*/*")):
        if not run_dir.is_dir():
            continue

        meta_path = run_dir / "metadata.json"

        if not meta_path.is_file():
            warnings.append(f"Skipped {run_dir}: missing metadata.json")
            continue

        if not (run_dir / "data.csv").is_file():
            warnings.append(f"Skipped {run_dir}: missing data.csv")
            continue

        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))

            if not isinstance(metadata, dict):
                raise ValueError("metadata is not an object")

            axis = metadata["axis"]

            if not isinstance(axis, str) or not axis:
                raise ValueError("axis must be a nonempty string")

            params = metadata.get("run_params", {})
            shared = metadata.get("sweep_params", {})

            if not isinstance(params, dict) or not isinstance(shared, dict):
                raise ValueError("params and shared must be objects")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            warnings.append(f"Skipped {run_dir}: invalid metadata.json ({exc})")
            continue

        revision_dir = run_dir.parent.parent
        parts = revision_dir.name.split("@", 1)
        attempt = parts[0] if len(parts) == 2 else ""
        patch = revision_dir / "source.patch"
        runs.append(
            ResultRun(
                path=run_dir,
                experiment=run_dir.parent.parent.parent.name,
                label=run_dir.name.rsplit("@", 1)[0]
                if "@" in run_dir.name
                else run_dir.name[:8],
                revision=str(metadata.get("revision", parts[-1])),
                attempt=attempt,
                started=str(metadata.get("started", "")),
                axis=axis,
                params=params,
                shared=shared,
                sweep=run_dir.parent.name,
                metadata=metadata,
                patch_path=patch if patch.is_file() else None,
            )
        )

    runs.sort(key=lambda run: (run.started, run.experiment, run.label), reverse=True)
    return runs, warnings


def load_selected(
    runs: list[ResultRun],
) -> tuple[str, list[tuple[ResultRun, pd.DataFrame]], list[str]]:
    """Load selected CSVs and return their shared axis and numeric metrics."""
    if not runs:
        raise ValueError("Select at least one run.")

    axes = {run.axis for run in runs}

    if len(axes) != 1:
        raise ValueError(
            "Selected runs sweep different axes; select runs with the same axis."
        )

    axis = runs[0].axis
    loaded = []
    metrics = None

    for run in runs:
        try:
            frame = pd.read_csv(run.path / "data.csv")
        except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            raise ValueError(f"Cannot read {run.path / 'data.csv'}: {exc}") from exc

        if axis not in frame or not pd.api.types.is_numeric_dtype(frame[axis]):
            raise ValueError(f"{run.path}: axis '{axis}' is missing or nonnumeric.")

        numeric = {
            column
            for column in frame.columns
            if column != axis and pd.api.types.is_numeric_dtype(frame[column])
        }
        metrics = numeric if metrics is None else metrics & numeric
        loaded.append((run, frame))

    return axis, loaded, sorted(metrics or [])


def make_figure(
    axis: str,
    loaded: list[tuple[ResultRun, pd.DataFrame]],
    metric: str,
    error: str | None = None,
    logx: bool = False,
    logy: bool = False,
):
    import plotly.graph_objects as go

    figure = go.Figure()

    for run, frame in loaded:
        if metric not in frame or not pd.api.types.is_numeric_dtype(frame[metric]):
            raise ValueError(f"{run.path}: metric '{metric}' is missing or nonnumeric.")
        if error and (
            error not in frame or not pd.api.types.is_numeric_dtype(frame[error])
        ):
            raise ValueError(
                f"{run.path}: error column '{error}' is missing or nonnumeric."
            )
        if error and (frame[error].dropna() < 0).any():
            raise ValueError(f"{run.path}: error bars must be nonnegative.")
        if logx and (frame[axis].dropna() <= 0).any():
            raise ValueError(f"{run.path}: log x requires positive axis values.")
        if logy and (frame[metric].dropna() <= 0).any():
            raise ValueError(f"{run.path}: log y requires positive metric values.")

        ordered = frame.sort_values(axis)
        figure.add_scatter(
            x=ordered[axis],
            y=ordered[metric],
            mode="lines+markers",
            name=f"{run.experiment} / {run.attempt + '@' if run.attempt else ''}{run.revision} / {run.sweep} / {run.label}",
            error_y={"type": "data", "array": ordered[error], "visible": True}
            if error
            else None,
        )

    figure.update_layout(
        xaxis_title=axis,
        yaxis_title=metric,
        xaxis_type="log" if logx else "linear",
        yaxis_type="log" if logy else "linear",
        autosize=True,
        hovermode="closest",
        template="plotly_white",
        legend_title="Runs",
        legend={
            "orientation": "h",
            "x": 0.5,
            "xanchor": "center",
            "y": -0.2,
            "yanchor": "top",
        },
        margin={"b": 120},
    )

    if logx:
        figure.update_xaxes(
            dtick=1,
            exponentformat="power",
            showexponent="all",
            minor={
                "dtick": "D1",
                "showgrid": True,
                "gridcolor": "rgba(120, 130, 140, 0.25)",
                "griddash": "dot",
                "ticks": "outside",
                "ticklen": 3,
            },
        )

    if logy:
        figure.update_yaxes(
            dtick=1,
            exponentformat="power",
            showexponent="all",
            minor={
                "dtick": "D1",
                "showgrid": True,
                "gridcolor": "rgba(120, 130, 140, 0.25)",
                "griddash": "dot",
                "ticks": "outside",
                "ticklen": 3,
            },
        )

    return figure
