import json

import pandas as pd
import pytest

from coordinator.browser import (
    delete_result,
    load_selected,
    make_figure,
    rename_result,
    scan_results,
)
from coordinator.browser.settings import make_default_settings, remap_paths


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


def test_ui_sweep_group_and_selection(tmp_path):
    pytest.importorskip("ipywidgets")
    pytest.importorskip("anywidget")
    run = write_run(tmp_path)
    from coordinator.browser.ui import launch_results_browser

    dashboard = launch_results_browser(
        tmp_path, settings_path=tmp_path / "settings.json"
    )
    overview = dashboard.children[5]
    assert "coordinator-sweep" in overview.html
    overview.request = {
        "id": 1,
        "action": "select",
        "kind": "sweep",
        "path": str(run.parent),
        "checked": True,
    }
    assert overview.selection["runs"] == [str(run)]
    overview.request = {
        "id": 2,
        "action": "panel",
        "kind": "sweep",
        "path": run.parent.relative_to(tmp_path).as_posix(),
        "open": False,
    }
    assert overview.response["ok"] is True
    assert json.loads((tmp_path / "settings.json").read_text())["panels"]["sweep"] == {
        run.parent.relative_to(tmp_path).as_posix(): False
    }
