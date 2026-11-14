"""State and request handling for the React results browser."""

import json
from collections import OrderedDict
from pathlib import Path

import pandas as pd
from plotly.utils import PlotlyJSONEncoder

from coordinator.browser import delete_result, make_figure, rename_result
from coordinator.browser.index import ResultIndex
from coordinator.browser.settings import (
    PANEL_DEFAULTS,
    PATCH_WIDTH_MAX,
    PATCH_WIDTH_MIN,
    get_default_settings_path,
    load_settings,
    make_default_settings,
    remap_paths,
    save_settings,
)


class BrowserController:
    def __init__(self, root: Path, settings_path: Path | None = None):
        self.root = root.expanduser().resolve()
        self.settings_path = settings_path or get_default_settings_path(self.root)
        self.settings_error = ""
        self.settings_writable = True
        try:
            self.settings = load_settings(self.settings_path)
        except (OSError, ValueError, TypeError) as exc:
            self.settings = make_default_settings()
            self.settings_error = f"Could not load browser settings from {self.settings_path}: {exc}. Automatic saving is disabled."
            self.settings_writable = False
        self.index = ResultIndex.scan(self.root)
        self.generation = 0
        self._frames: OrderedDict[str, tuple[tuple[int, int], pd.DataFrame]] = OrderedDict()
        self._content: OrderedDict[str, tuple[tuple[int, int], object]] = OrderedDict()
        self._reconcile()

    def _save(self) -> bool:
        if not self.settings_writable:
            return False
        try:
            save_settings(self.settings_path, self.settings)
            self.settings_error = ""
            return True
        except OSError as exc:
            self.settings_error = f"Could not save browser settings to {self.settings_path}: {exc}"
            return False

    def _reconcile(self) -> None:
        if not self.root.is_dir():
            return
        changed = False
        valid_runs = self.index.paths("run")
        selected = sorted(set(self.settings["selected_runs"]) & valid_runs)
        if selected != self.settings["selected_runs"]:
            self.settings["selected_runs"] = selected
            changed = True
        for kind in PANEL_DEFAULTS:
            valid = self.index.paths(kind)
            panels = self.settings["panels"][kind]
            for path in list(panels):
                if path not in valid:
                    del panels[path]
                    changed = True
        if changed:
            self._save()

    def snapshot(self) -> dict:
        return {
            "generation": self.generation,
            "index": self.index.manifest(),
            "settings": self.settings,
            "settings_error": self.settings_error,
        }

    def refresh(self) -> dict:
        self.index = ResultIndex.scan(self.root)
        self.generation += 1
        self._frames.clear()
        self._content.clear()
        self._reconcile()
        return self.snapshot()

    def _path(self, kind: str, relative: str) -> Path:
        if relative not in self.index.paths(kind):
            raise ValueError("Result is no longer available. Refresh the browser.")
        path = self.root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError("Result path is outside the results directory.")
        return path

    def _file(self, path: Path) -> Path:
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError("Result file is outside the results directory.")
        return path

    @staticmethod
    def _stamp(path: Path) -> tuple[int, int]:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size

    @staticmethod
    def _cached(cache: OrderedDict, key: str, stamp: tuple[int, int], read):
        if key in cache and cache[key][0] == stamp:
            cache.move_to_end(key)
            return cache[key][1]
        value = read()
        cache[key] = (stamp, value)
        cache.move_to_end(key)
        while len(cache) > 32:
            cache.popitem(last=False)
        return value

    def _frame(self, run) -> pd.DataFrame:
        path = self._file(run.path / "data.csv")
        try:
            return self._cached(self._frames, str(path), self._stamp(path), lambda: pd.read_csv(path))
        except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            raise ValueError(f"Cannot read {path}: {exc}") from exc

    def content(self, kind: str, relative: str, page: int = 0) -> dict:
        if kind == "patch":
            path = self._file(self._path("attempt", relative) / "source.patch")
            if not path.is_file():
                return {"text": "No source patch for this revision."}
            try:
                text = self._cached(self._content, str(path), self._stamp(path),
                                    lambda: path.read_text(encoding="utf-8"))
            except OSError as exc:
                raise ValueError(f"Could not read source patch: {exc}") from exc
            return {"text": text}
        if kind == "metadata":
            path = self._file(self._path("run", relative) / "metadata.json")
            try:
                text = self._cached(self._content, str(path), self._stamp(path),
                                    lambda: json.dumps(json.loads(path.read_text(encoding="utf-8")), indent=2, sort_keys=True))
            except (OSError, ValueError) as exc:
                raise ValueError(f"Could not read metadata: {exc}") from exc
            return {"text": text, "path": str(path.parent)}
        if kind == "data":
            if not isinstance(page, int) or page < 0:
                raise ValueError("Invalid data page.")
            run = self.index.members("run", relative)[0]
            frame = self._frame(run)
            size = 100
            start = page * size
            rows = frame.iloc[start:start + size].astype(object)
            rows = rows.where(pd.notna(rows), None)
            return {"columns": list(frame.columns), "rows": rows.values.tolist(),
                    "page": page, "pages": max(1, (len(frame) + size - 1) // size)}
        raise ValueError("Unknown content type.")

    def plot(self) -> dict:
        chosen = [run for run in self.index.runs if self.index.relative(run.path) in self.settings["selected_runs"]]
        if not chosen:
            return {"metrics": [], "figure": None, "error": None}
        axes = {run.axis for run in chosen}
        if len(axes) != 1:
            return {"metrics": [], "figure": None, "error": "Selected runs sweep different axes; select runs with the same axis."}
        axis = chosen[0].axis
        try:
            loaded = [(run, self._frame(run)) for run in chosen]
            metrics = None
            for run, frame in loaded:
                if axis not in frame or not pd.api.types.is_numeric_dtype(frame[axis]):
                    raise ValueError(f"{run.path}: axis '{axis}' is missing or nonnumeric.")
                numeric = {col for col in frame if col not in {axis, *run.params, *run.shared}
                           and pd.api.types.is_numeric_dtype(frame[col])}
                metrics = numeric if metrics is None else metrics & numeric
            metrics = sorted(metrics or [])
            if not metrics:
                raise ValueError("Selected runs have no common numeric metric.")
            metric = self.settings["plot"]["metric"]
            if metric not in metrics:
                metric = metrics[0]
                self.settings["plot"]["metric"] = metric
                self._save()
            figure = make_figure(axis, loaded, metric, logx=self.settings["plot"]["logx"],
                                 logy=self.settings["plot"]["logy"])
            figure_data = json.loads(json.dumps(figure.to_plotly_json(), cls=PlotlyJSONEncoder))
            return {"metrics": metrics, "metric": metric, "figure": figure_data, "error": None}
        except ValueError as exc:
            return {"metrics": [], "figure": None, "error": str(exc)}

    def dispatch(self, action: str, payload: dict) -> dict:
        if action == "boot":
            return {"snapshot": self.snapshot()}
        if action == "refresh":
            return {"snapshot": self.refresh()}
        if payload.get("generation") != self.generation:
            raise ValueError("Browser has refreshed; retry this action.")
        if action == "content":
            return {"content": self.content(payload.get("kind"), payload.get("path"), payload.get("page", 0))}
        if action == "plot":
            return {"plot": self.plot()}
        if action == "clear_selection":
            self.settings["selected_runs"] = []
            self._save()
            return {"settings": self.settings, "settings_error": self.settings_error}
        if action == "panel":
            kind, path, opened = payload.get("kind"), payload.get("path"), payload.get("open")
            if kind not in PANEL_DEFAULTS or not isinstance(opened, bool):
                raise ValueError("Invalid panel state.")
            self._path(kind, path)
            panels = self.settings["panels"][kind]
            previous = panels.copy()
            if opened == PANEL_DEFAULTS[kind]:
                panels.pop(path, None)
            else:
                panels[path] = opened
            if not self._save():
                panels.clear()
                panels.update(previous)
            return {"settings": self.settings, "settings_error": self.settings_error}
        if action == "panel_all":
            kind, path, opened = payload.get("kind"), payload.get("path"), payload.get("open")
            if kind not in {"experiment", "attempt", "sweep"} or not isinstance(opened, bool):
                raise ValueError("Invalid panel state.")
            self._path(kind, path)
            paths = self.index.paths(kind)
            if kind != "experiment":
                parent = path.rsplit("/", 1)[0]
                paths = {item for item in paths if item.rsplit("/", 1)[0] == parent}
            panels = self.settings["panels"][kind]
            previous = panels.copy()
            for item in paths:
                if opened == PANEL_DEFAULTS[kind]:
                    panels.pop(item, None)
                else:
                    panels[item] = opened
            if not self._save():
                panels.clear()
                panels.update(previous)
            return {"settings": self.settings, "settings_error": self.settings_error}
        if action == "select":
            kind, path, checked = payload.get("kind"), payload.get("path"), payload.get("checked")
            if not isinstance(checked, bool):
                raise ValueError("Invalid selection state.")
            members = self.index.members(kind, path)
            selected = set(self.settings["selected_runs"])
            paths = {self.index.relative(run.path) for run in members}
            selected.update(paths) if checked else selected.difference_update(paths)
            self.settings["selected_runs"] = sorted(selected)
            self._save()
            return {"settings": self.settings, "settings_error": self.settings_error}
        if action == "plot_options":
            metric = payload.get("metric")
            logx, logy = payload.get("logx"), payload.get("logy")
            if (metric is not None and not isinstance(metric, str)) or not isinstance(logx, bool) or not isinstance(logy, bool):
                raise ValueError("Invalid plot settings.")
            self.settings["plot"] = {"metric": metric, "logx": logx, "logy": logy}
            self._save()
            return {"settings": self.settings, "settings_error": self.settings_error}
        if action == "patch_width":
            width = payload.get("width")
            if type(width) is not int or not PATCH_WIDTH_MIN <= width <= PATCH_WIDTH_MAX:
                raise ValueError("Invalid source patch width.")
            previous = self.settings["patch_width"]
            self.settings["patch_width"] = width
            if not self._save():
                self.settings["patch_width"] = previous
            return {"settings": self.settings, "settings_error": self.settings_error}
        if action in {"rename", "delete"}:
            kind, path = payload.get("kind"), payload.get("path")
            if kind not in {"experiment", "attempt", "sweep", "run"}:
                raise ValueError("Unknown result type.")
            target = self._path(kind, path)
            if action == "rename":
                destination = rename_result(self.root, kind, target, payload.get("name"))
                remap_paths(self.settings, path, self.index.relative(destination))
            else:
                delete_result(self.root, kind, target)
                remap_paths(self.settings, path, None)
            self._save()
            return {"snapshot": self.refresh()}
        raise ValueError("Unknown browser action.")
