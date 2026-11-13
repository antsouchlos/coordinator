import json
import re

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
from coordinator.browser.settings import make_default_settings, remap_paths
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


@pytest.mark.parametrize("kind", ["attempt", "sweep", "run"])
def test_ui_result_label_keeps_id_and_settings(tmp_path, kind):
    pytest.importorskip("ipywidgets")
    pytest.importorskip("anywidget")
    from coordinator.browser.ui import launch_results_browser

    run_path = write_run(
        tmp_path, attempt="aaa1111", sweep="bbb2222", name="ccc3333"
    )
    settings_path = tmp_path / "settings.json"
    dashboard = launch_results_browser(tmp_path, settings_path=settings_path)
    overview = dashboard.children[5]
    path = {"attempt": run_path.parent.parent, "sweep": run_path.parent, "run": run_path}[kind]
    identity = path.name

    def get_edit_target():
        match = re.search(
            rf"<span class='coordinator-editable'[^>]*data-result-id='(\d+)' data-kind='{kind}' data-edit-name='([^']*)'>([^<]*)</span>([^<]*)",
            overview.html,
        )
        assert match is not None
        return match

    initial = get_edit_target()
    assert initial.group(2) == ""
    assert initial.group(3) == "Add label"
    assert initial.group(4) == f" · {identity}"
    assert f"aria-label='Edit {kind} label'" in overview.html

    overview.request = {
        "id": 1,
        "action": "select",
        "kind": "run",
        "path": str(run_path),
        "checked": True,
    }
    overview.request = {
        "id": 2,
        "action": "panel",
        "kind": "data",
        "path": run_path.relative_to(tmp_path).as_posix(),
        "open": True,
    }
    overview.request = {
        "id": 3,
        "action": "rename",
        "target": initial.group(1),
        "name": "new",
    }
    assert overview.response["ok"] is True

    renamed_path = path.with_name(f"new@{identity}")
    renamed_run = renamed_path / run_path.relative_to(path) if kind != "run" else renamed_path
    assert renamed_run.is_dir()
    assert not path.exists()
    assert overview.selection["runs"] == [str(renamed_run)]
    settings = json.loads(settings_path.read_text())
    relative_run = renamed_run.relative_to(tmp_path).as_posix()
    assert settings["selected_runs"] == [relative_run]
    assert settings["panels"]["data"] == {relative_run: True}
    metadata = json.loads((renamed_run / "metadata.json").read_text())
    assert metadata["attempt_id"] == "aaa1111"
    assert metadata["sweep_id"] == "bbb2222"
    assert metadata["run_id"] == "ccc3333"

    labeled = get_edit_target()
    assert labeled.group(2) == labeled.group(3) == "new"
    assert labeled.group(4) == f"@{identity}"
    overview.request = {
        "id": 4,
        "action": "rename",
        "target": labeled.group(1),
        "name": "changed",
    }
    assert overview.response["ok"] is True
    changed_path = path.with_name(f"changed@{identity}")
    assert changed_path.is_dir()
    assert get_edit_target().group(2) == "changed"

    overview.request = {
        "id": 5,
        "action": "rename",
        "target": get_edit_target().group(1),
        "name": "",
    }
    assert overview.response["ok"] is True
    assert run_path.is_dir()
    assert overview.selection["runs"] == [str(run_path)]
    assert get_edit_target().group(4) == f" · {identity}"
    settings = json.loads(settings_path.read_text())
    assert settings["selected_runs"] == [run_path.relative_to(tmp_path).as_posix()]
    assert settings["panels"]["data"] == {
        run_path.relative_to(tmp_path).as_posix(): True
    }


def test_ui_labeled_results_show_fixed_ids(tmp_path):
    pytest.importorskip("ipywidgets")
    pytest.importorskip("anywidget")
    from coordinator.browser.ui import launch_results_browser

    write_run(
        tmp_path,
        attempt="try@aaa1111",
        sweep="comparison@bbb2222",
        name="curve@ccc3333",
    )
    overview = launch_results_browser(
        tmp_path, settings_path=tmp_path / "settings.json"
    ).children[5]

    for label, identity in (
        ("try", "aaa1111"),
        ("comparison", "bbb2222"),
        ("curve", "ccc3333"),
    ):
        assert f"data-edit-name='{label}'>{label}</span>@{identity}" in overview.html
