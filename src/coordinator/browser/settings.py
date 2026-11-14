import json
import os
import stat
import tempfile
from pathlib import Path, PurePosixPath

PANEL_DEFAULTS = {
    "experiment": True,
    "attempt": True,
    "sweep": True,
    "patch": True,
    "data": False,
    "metadata": False,
}
PATCH_WIDTH_MIN = 180
PATCH_WIDTH_MAX = 1600


def make_default_settings() -> dict:
    return {
        "version": 1,
        "plot": {"metric": None, "logx": False, "logy": False},
        "selected_runs": [],
        "panels": {kind: {} for kind in PANEL_DEFAULTS},
        "patch_width": None,
    }


def get_default_settings_path(results_root: Path) -> Path:
    """Use the project notebook when present, otherwise the results directory."""
    notebook = results_root.parent / "notebooks" / "results_browser.ipynb"

    if notebook.is_file():
        return notebook.with_name("results_browser.settings.json")

    return results_root / ".results_browser.settings.json"


def _is_valid_relative_path(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False

    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and path.as_posix() == value
        and bool(path.parts)
        and all(part not in {".", ".."} for part in path.parts)
    )


def load_settings(path: Path) -> dict:
    """Read and validate a versioned browser settings file."""
    if not path.exists():
        return make_default_settings()

    data = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Expected a version 1 settings object.")

    plot = data.get("plot")
    selected = data.get("selected_runs")
    panels = data.get("panels")
    patch_width = data.get("patch_width")

    if (
        not isinstance(plot, dict)
        or not isinstance(selected, list)
        or not isinstance(panels, dict)
    ):
        raise ValueError("Settings must contain plot, selected_runs, and panels.")
    if not isinstance(plot.get("logx"), bool) or not isinstance(plot.get("logy"), bool):
        raise ValueError("Plot axis settings must be booleans.")

    metric = plot.get("metric")

    if metric is not None and not isinstance(metric, str):
        raise ValueError("Plot metric must be a string or null.")
    if not all(_is_valid_relative_path(item) for item in selected):
        raise ValueError("Selected runs must have relative paths.")
    if set(panels) - set(PANEL_DEFAULTS):
        raise ValueError("Settings contain an unknown panel type.")
    if patch_width is not None and (
        type(patch_width) is not int
        or not PATCH_WIDTH_MIN <= patch_width <= PATCH_WIDTH_MAX
    ):
        raise ValueError("Invalid source patch width.")

    for kind in PANEL_DEFAULTS:
        items = panels.get(kind, {})

        if not isinstance(items, dict) or any(
            not _is_valid_relative_path(key) or not isinstance(value, bool)
            for key, value in items.items()
        ):
            raise ValueError(f"Invalid {kind} panel settings.")

    return {
        "version": 1,
        "plot": {"metric": metric, "logx": plot["logx"], "logy": plot["logy"]},
        "selected_runs": sorted(set(selected)),
        "panels": {kind: dict(panels.get(kind, {})) for kind in PANEL_DEFAULTS},
        "patch_width": patch_width,
    }


def save_settings(path: Path, settings: dict) -> None:
    """Replace settings atomically after writing valid JSON."""
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".results-browser-", suffix=".json", dir=path.parent
    )

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            if mode is not None:
                os.fchmod(handle.fileno(), mode)

            json.dump(settings, handle, indent=2, sort_keys=True)
            handle.write("\n")

        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def remap_paths(settings: dict, old: str, new: str | None) -> None:
    def remap_path(value):
        if value != old and not value.startswith(f"{old}/"):
            return value

        return None if new is None else new + value[len(old) :]

    settings["selected_runs"] = sorted(
        {
            updated
            for value in settings["selected_runs"]
            if (updated := remap_path(value)) is not None
        }
    )

    for panels in settings["panels"].values():
        updated = {
            mapped: state
            for value, state in panels.items()
            if (mapped := remap_path(value)) is not None
        }
        panels.clear()
        panels.update(updated)
