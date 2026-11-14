import json

import pandas as pd
import pytest

from coordinator import Experiment, Run, Sweep, run
from coordinator.browser import (
    delete_result,
    load_selected,
    make_figure,
    rename_result,
    scan_results,
)
from coordinator.browser.settings import load_settings, make_default_settings, remap_paths
from coordinator.results import get_results_root


def write_run(
    root,
    experiment="exp",
    attempt="try@aaa1111",
    sweep="bbb2222",
    name="ccc3333",
    *,
    axis="noise",
    patch=None,
):
    path = root / experiment / attempt / sweep / name
    path.mkdir(parents=True)
    metadata = {
        "experiment": experiment,
        "attempt_id": attempt.split("@")[-1],
        "sweep_id": sweep.split("@")[-1],
        "run_id": name.split("@")[-1],
        "started": "2026-01-01T00:00:00",
        "axis": axis,
        "axis_vals": [1, 2],
        "sweep_params": {"bias": 0.1},
        "run_params": {"samples": 10},
    }
    (path / "metadata.json").write_text(json.dumps(metadata))
    pd.DataFrame({axis: [1, 2], "score": [3, 4], "err": [0.1, 0.2]}).to_csv(
        path / "data.csv", index=False
    )

    if patch is not None:
        (path.parent.parent / "source.patch").write_text(patch)

    return path


def test_scan_new_depth_and_patch(tmp_path):
    path = write_run(tmp_path, patch="diff")
    runs, warnings = scan_results(tmp_path)
    assert not warnings and len(runs) == 1
    item = runs[0]
    assert item.path == path and item.experiment == "exp"
    assert item.attempt == "try" and item.sweep == "bbb2222"
    assert item.patch_path == path.parent.parent / "source.patch"
    assert item.params == {"samples": 10} and item.shared == {"bias": 0.1}
    assert item.label == "ccc3333"[:8]


def test_scan_and_plot_api_generated_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    get_results_root.cache_clear()

    try:
        experiment = Experiment(
            "exp",
            [
                Sweep(
                    {"bias": 0.1},
                    "noise",
                    [1, 2],
                    [Run({"samples": 10}, lambda params: {"score": params["noise"] * 2})],
                )
            ],
        )
        run(experiment)

        runs, warnings = scan_results(get_results_root())
        assert warnings == []
        assert len(runs) == 1
        assert runs[0].axis == "noise"
        assert runs[0].shared == {"bias": 0.1}
        assert runs[0].params == {"samples": 10}
        assert runs[0].started == runs[0].metadata["start_datetime"]

        axis, loaded, metrics = load_selected(runs)
        assert axis == "noise"
        assert metrics == ["score"]
        assert len(make_figure(axis, loaded, "score").data) == 1
    finally:
        get_results_root.cache_clear()


def test_scan_reports_invalid_runs(tmp_path):
    good = write_run(tmp_path, name="good")
    bad = write_run(tmp_path, name="bad")
    (bad / "metadata.json").write_text("{broken")
    missing = write_run(tmp_path, name="missing")
    (missing / "data.csv").unlink()
    runs, warnings = scan_results(tmp_path)
    assert [item.path for item in runs] == [good]
    assert len(warnings) == 2


def test_plot_new_format(tmp_path):
    write_run(tmp_path, name="first", axis="noise")
    write_run(tmp_path, name="second", axis="noise")
    runs, _ = scan_results(tmp_path)
    axis, loaded, metrics = load_selected(runs)
    assert axis == "noise" and metrics == ["err", "score"]
    figure = make_figure(axis, loaded, "score", "err", logx=True)
    assert len(figure.data) == 2
    assert figure.layout.xaxis.type == "log"
    assert all(trace.error_y.visible for trace in figure.data)
    write_run(tmp_path, sweep="other", name="third", axis="time")

    with pytest.raises(ValueError, match="different axes"):
        load_selected(scan_results(tmp_path)[0])


def test_plot_uses_labels_without_ids(tmp_path):
    write_run(
        tmp_path,
        attempt="try@aaa1111",
        sweep="comparison@bbb2222",
        name="curve@ccc3333",
    )
    write_run(
        tmp_path,
        attempt="ddd4444",
        sweep="eee5555",
        name="fff6666",
    )
    axis, loaded, _metrics = load_selected(scan_results(tmp_path)[0])

    figure = make_figure(axis, loaded, "score")

    assert {trace.name for trace in figure.data} == {
        "exp / try / comparison / curve",
        "exp / ddd4444 / eee5555 / fff6666",
    }


def test_sweep_rename_delete_and_settings_paths(tmp_path):
    run = write_run(tmp_path)
    root = tmp_path
    settings = make_default_settings()
    old = run.parent.relative_to(root).as_posix()
    settings["selected_runs"] = [run.relative_to(root).as_posix()]
    settings["panels"]["sweep"][old] = False
    settings["panels"]["data"][run.relative_to(root).as_posix()] = True
    named = rename_result(root, "sweep", run.parent, "comparison")
    assert named.name == "comparison@bbb2222"
    remap_paths(settings, old, named.relative_to(root).as_posix())
    assert settings["panels"]["sweep"] == {named.relative_to(root).as_posix(): False}
    assert settings["selected_runs"] == [
        (named / run.name).relative_to(root).as_posix()
    ]
    assert scan_results(root)[0][0].path == named / run.name
    renamed = rename_result(root, "run", named / run.name, "curve")
    assert renamed.name == "curve@ccc3333"
    remap_paths(
        settings,
        (named / run.name).relative_to(root).as_posix(),
        renamed.relative_to(root).as_posix(),
    )
    assert settings["selected_runs"] == [renamed.relative_to(root).as_posix()]
    delete_result(root, "sweep", named)
    remap_paths(settings, named.relative_to(root).as_posix(), None)
    assert settings["selected_runs"] == []
    assert settings["panels"]["sweep"] == {}
    assert settings["panels"]["data"] == {}


def test_attempt_rename_keeps_patch_lookup(tmp_path):
    path = write_run(tmp_path, patch="diff")
    renamed = rename_result(tmp_path, "attempt", path.parent.parent, "new")
    assert renamed.name == "new@aaa1111"
    indexed, warnings = scan_results(tmp_path)
    assert not warnings
    assert indexed[0].patch_path == renamed / "source.patch"


def test_react_browser_controller_preserves_settings_and_paths(tmp_path):
    from coordinator.browser.controller import BrowserController

    run_path = write_run(tmp_path, patch="diff")
    settings_path = tmp_path / "settings.json"
    browser = BrowserController(tmp_path, settings_path)
    run = run_path.relative_to(tmp_path).as_posix()
    sweep = run_path.parent.relative_to(tmp_path).as_posix()
    assert browser.snapshot()["index"]["runs"][0]["path"] == run
    assert browser.snapshot()["index"]["runs"][0]["has_patch"] is True

    browser.dispatch("select", {"generation": 0, "kind": "sweep", "path": sweep, "checked": True})
    browser.dispatch("panel", {"generation": 0, "kind": "data", "path": run, "open": True})
    assert browser.settings["selected_runs"] == [run]
    assert browser.settings["panels"]["data"] == {run: True}
    assert browser.plot()["metrics"] == ["err", "score"]
    assert browser.content("patch", run_path.parent.parent.relative_to(tmp_path).as_posix())["text"] == "diff"
    assert browser.content("data", run)["rows"][0] == [1, 3, 0.1]

    result = browser.dispatch("rename", {"generation": 0, "kind": "sweep", "path": sweep, "name": "comparison"})
    new_sweep = run_path.parent.with_name("comparison@bbb2222")
    new_run = (new_sweep / run_path.name).relative_to(tmp_path).as_posix()
    assert result["snapshot"]["settings"]["selected_runs"] == [new_run]
    assert browser.settings["panels"]["data"] == {new_run: True}
    assert json.loads(settings_path.read_text())["selected_runs"] == [new_run]

    cleared = browser.dispatch("clear_selection", {"generation": browser.generation})
    assert cleared["settings"]["selected_runs"] == []
    assert json.loads(settings_path.read_text())["selected_runs"] == []
    assert browser.plot()["figure"] is None

    with pytest.raises(ValueError, match="refreshed"):
        browser.dispatch("select", {"generation": 0, "kind": "run", "path": run, "checked": True})
    browser.dispatch("delete", {"generation": browser.generation, "kind": "sweep", "path": new_sweep.relative_to(tmp_path).as_posix()})
    assert browser.settings["selected_runs"] == []


def test_react_browser_controller_scopes_bulk_panel_toggles(tmp_path):
    from coordinator.browser.controller import BrowserController

    write_run(tmp_path, experiment="first", attempt="a@1", sweep="s@1", name="r@1")
    write_run(tmp_path, experiment="first", attempt="a@1", sweep="v@4", name="r@4")
    write_run(tmp_path, experiment="first", attempt="b@2", sweep="t@2", name="r@2")
    write_run(tmp_path, experiment="second", attempt="c@3", sweep="u@3", name="r@3")
    settings_path = tmp_path / "settings.json"
    browser = BrowserController(tmp_path, settings_path)

    def panel(kind, path, opened):
        return browser.dispatch("panel", {"generation": 0, "kind": kind, "path": path, "open": opened})

    def panel_all(kind, path, opened):
        return browser.dispatch("panel_all", {"generation": 0, "kind": kind, "path": path, "open": opened})

    panel("attempt", "second/c@3", False)
    panel("sweep", "first/b@2/t@2", False)
    panel_all("experiment", "first", False)
    panel_all("attempt", "first/a@1", False)
    panel_all("sweep", "first/a@1/s@1", False)

    assert browser.settings["panels"]["experiment"] == {"first": False, "second": False}
    assert browser.settings["panels"]["attempt"] == {
        "first/a@1": False, "first/b@2": False, "second/c@3": False,
    }
    assert browser.settings["panels"]["sweep"] == {
        "first/a@1/s@1": False, "first/a@1/v@4": False, "first/b@2/t@2": False,
    }

    reloaded = BrowserController(tmp_path, settings_path)
    assert reloaded.settings["panels"] == browser.settings["panels"]
    reloaded.dispatch("panel_all", {"generation": 0, "kind": "experiment", "path": "first", "open": True})
    reloaded.dispatch("panel_all", {"generation": 0, "kind": "attempt", "path": "first/a@1", "open": True})
    reloaded.dispatch("panel_all", {"generation": 0, "kind": "sweep", "path": "first/a@1/s@1", "open": True})
    assert reloaded.settings["panels"]["experiment"] == {}
    assert reloaded.settings["panels"]["attempt"] == {"second/c@3": False}
    assert reloaded.settings["panels"]["sweep"] == {"first/b@2/t@2": False}

    with pytest.raises(ValueError, match="Invalid panel state"):
        reloaded.dispatch("panel_all", {"generation": 0, "kind": "data", "path": "first", "open": False})
    with pytest.raises(ValueError, match="Result is no longer available"):
        reloaded.dispatch("panel_all", {"generation": 0, "kind": "attempt", "path": "missing", "open": False})


def test_source_patch_width_persists_and_legacy_settings_load(tmp_path, monkeypatch):
    from coordinator.browser.controller import BrowserController

    settings_path = tmp_path / "settings.json"
    legacy = make_default_settings()
    del legacy["patch_width"]
    settings_path.write_text(json.dumps(legacy))
    assert load_settings(settings_path)["patch_width"] is None

    browser = BrowserController(tmp_path, settings_path)
    response = browser.dispatch("patch_width", {"generation": 0, "width": 560})
    assert response["settings"]["patch_width"] == 560
    assert json.loads(settings_path.read_text())["patch_width"] == 560
    assert BrowserController(tmp_path, settings_path).snapshot()["settings"]["patch_width"] == 560

    for width in (179, 1601, True, 400.5, None):
        with pytest.raises(ValueError, match="Invalid source patch width"):
            browser.dispatch("patch_width", {"generation": 0, "width": width})
    assert browser.settings["patch_width"] == 560

    def failed_save(*_args):
        raise OSError("disk unavailable")

    monkeypatch.setattr("coordinator.browser.controller.save_settings", failed_save)
    failed = browser.dispatch("patch_width", {"generation": 0, "width": 600})
    assert failed["settings"]["patch_width"] == 560
    assert "disk unavailable" in failed["settings_error"]
    assert json.loads(settings_path.read_text())["patch_width"] == 560


def test_large_index_is_metadata_only(tmp_path, monkeypatch):
    from coordinator.browser.controller import BrowserController

    template = {"axis": "x", "run_params": {"seed": 1}, "sweep_params": {"scale": 2}}
    sweep = tmp_path / "exp" / "attempt" / "sweep"
    for number in range(2000):
        path = sweep / f"run-{number:04d}"
        path.mkdir(parents=True)
        (path / "metadata.json").write_text(json.dumps(template))
        (path / "data.csv").touch()
    monkeypatch.setattr(pd, "read_csv", lambda *_args, **_kwargs: pytest.fail("CSV loaded during browsing"))

    browser = BrowserController(tmp_path, tmp_path / "settings.json")
    response = browser.dispatch("boot", {})
    assert len(response["snapshot"]["index"]["runs"]) == 2000
    assert browser.dispatch("plot", {"generation": 0})["plot"]["figure"] is None
    assert not any("metadata" in item for item in response["snapshot"]["index"]["runs"])
    assert all(not run.metadata for run in browser.index.runs)


def test_browser_widget_message_contract(tmp_path, monkeypatch):
    from coordinator.browser.ui import launch_results_browser

    write_run(tmp_path)
    widget = launch_results_browser(tmp_path, settings_path=tmp_path / "settings.json")
    sent = []
    monkeypatch.setattr(widget, "send", lambda message: sent.append(message))
    widget._handle_message(widget, {"id": 1, "action": "boot", "payload": {}}, [])
    assert sent[-1]["ok"] and sent[-1]["id"] == 1
    assert len(sent[-1]["snapshot"]["index"]["runs"]) == 1
    widget._handle_message(widget, {"id": 2, "action": "select", "payload": {"generation": -1}}, [])
    assert sent[-1]["ok"] is False
