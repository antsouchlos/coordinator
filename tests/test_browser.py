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


def write_run(root, experiment, revision, label, *, axis="noise", rows=None, patch=None):
    run_dir = root / experiment / revision / f"{label}@abc123"
    run_dir.mkdir(parents=True)
    (run_dir / "meta.json").write_text(json.dumps({
        "experiment": experiment,
        "label": label,
        "revision": revision.split("@")[-1],
        "started": "2026-01-01T00:00:00",
        "axis": axis,
        "params": {"samples": 10},
        "shared": {"bias": 0.1},
        "note": "fixture",
    }))
    pd.DataFrame(rows or {"noise": [1, 2], "score": [3, 4], "err": [0.1, 0.2]}).to_csv(run_dir / "data.csv", index=False)
    if patch is not None:
        (run_dir.parent / "source.patch").write_text(patch)
    return run_dir


def test_scan_indexes_metadata_and_patch_without_reading_csv(tmp_path):
    path = write_run(tmp_path, "exp-a", "first@abcdef0-dirty_123456", "curve", patch="diff --git a/x b/x")
    runs, warnings = scan_results(tmp_path)
    assert not warnings
    assert len(runs) == 1
    run = runs[0]
    assert run.path == path
    assert run.experiment == "exp-a"
    assert run.attempt == "first"
    assert run.axis == "noise"
    assert run.params == {"samples": 10}
    assert run.metadata["note"] == "fixture"
    assert run.patch_path == path.parent / "source.patch"


def test_scan_reports_incomplete_and_invalid_runs(tmp_path):
    good = write_run(tmp_path, "exp", "abcdef0", "good")
    missing_meta = write_run(tmp_path, "exp", "abcdef0", "missing")
    (missing_meta / "meta.json").unlink()
    invalid = write_run(tmp_path, "exp", "abcdef0", "invalid")
    (invalid / "meta.json").write_text("{broken")
    missing_csv = write_run(tmp_path, "exp", "abcdef0", "no-csv")
    (missing_csv / "data.csv").unlink()
    runs, warnings = scan_results(tmp_path)
    assert [run.path for run in runs] == [good]
    assert len(warnings) == 3
    assert any("missing meta.json" in message for message in warnings)
    assert any("invalid meta.json" in message for message in warnings)
    assert any("missing data.csv" in message for message in warnings)


def test_load_and_compare_runs_across_experiments(tmp_path):
    write_run(tmp_path, "exp-a", "aaa1111", "curve")
    write_run(tmp_path, "exp-b", "bbb2222", "curve")
    runs, _ = scan_results(tmp_path)
    axis, loaded, metrics = load_selected(runs)
    assert axis == "noise"
    assert metrics == ["err", "score"]
    figure = make_figure(axis, loaded, "score", "err", logx=True)
    assert len(figure.data) == 2
    assert figure.layout.xaxis.type == "log"
    assert figure.layout.xaxis.dtick == 1
    assert figure.layout.xaxis.exponentformat == "power"
    assert figure.layout.xaxis.showexponent == "all"
    assert figure.layout.xaxis.minor.dtick == "D1"
    assert figure.layout.xaxis.minor.showgrid is True
    assert figure.layout.xaxis.minor.griddash == "dot"
    assert figure.layout.yaxis.exponentformat is None
    assert figure.layout.yaxis.minor.showgrid is None
    assert figure.layout.autosize is True
    assert figure.layout.legend.orientation == "h"
    assert figure.layout.legend.y < 0
    assert all(trace.error_y.visible for trace in figure.data)
    assert figure.data[0].name != figure.data[1].name


def test_incompatible_axes_and_metrics(tmp_path):
    write_run(tmp_path, "exp", "aaa1111", "first")
    write_run(tmp_path, "exp", "bbb2222", "second", axis="time", rows={"time": [1, 2], "other": [2, 3]})
    runs, _ = scan_results(tmp_path)
    with pytest.raises(ValueError, match="different axes"):
        load_selected(runs)
    axis, loaded, metrics = load_selected(runs[:1])
    assert axis == "time"
    assert metrics == ["other"]
    with pytest.raises(ValueError, match="metric"):
        make_figure(axis, loaded, "score")


def test_log_scale_rejects_nonpositive_values(tmp_path):
    write_run(tmp_path, "exp", "aaa1111", "curve", rows={"noise": [0, 1], "score": [2, -1]})
    runs, _ = scan_results(tmp_path)
    axis, loaded, _ = load_selected(runs)
    with pytest.raises(ValueError, match="log x"):
        make_figure(axis, loaded, "score", logx=True)
    with pytest.raises(ValueError, match="log y"):
        make_figure(axis, loaded, "score", logy=True)


def test_nested_overview_search_refresh_and_patch(tmp_path):
    pytest.importorskip("ipywidgets")
    first = write_run(
        tmp_path, "exp", "try-one@aaa1111", "first",
        rows={"noise": [1, 2], "score": [3, 4], "note": ["<cell>", "other"]},
        patch="diff <script>alert(1)</script>",
    )
    meta_path = first / "meta.json"
    metadata = json.loads(meta_path.read_text())
    metadata["params"].update({
        "alpha": 1, "beta": 2, "gamma": 3, "delta": 4,
        "long_parameter_name": "<visible value>",
    })
    meta_path.write_text(json.dumps(metadata))
    write_run(tmp_path, "exp", "try-one@aaa1111", "second")
    write_run(tmp_path, "exp", "bbb2222", "third")
    from coordinator.browser_ui import launch_results_browser
    dashboard = launch_results_browser(tmp_path)
    search, refresh = dashboard.children[2].children
    overview = dashboard.children[5]
    markup = overview.html
    assert "3 runs" in dashboard.children[3].value
    assert "try-one" in markup
    assert markup.count("class='coordinator-run'") == 3
    assert "&lt;cell&gt;" in markup
    assert "<cell>" not in markup
    for key in ("alpha", "long_parameter_name", "samples", "Shared: bias"):
        assert f">{key}</th>" in markup
    assert "&lt;visible value&gt;" in markup
    assert "&lt;script&gt;" in markup
    assert "<script>" not in markup
    assert "No source patch" in markup

    search.value = "second"
    assert overview.html.count("class='coordinator-run'") == 1
    assert "1 matching run" in dashboard.children[3].value
    search.value = ""
    write_run(tmp_path, "exp-two", "ccc3333", "fourth")
    refresh.click()
    assert "4 runs" in dashboard.children[3].value
    assert "exp-two" in overview.html


def test_overview_preserves_valid_runs_when_metadata_is_invalid(tmp_path):
    pytest.importorskip("ipywidgets")
    write_run(tmp_path, "exp", "aaa1111", "good")
    bad = write_run(tmp_path, "exp", "aaa1111", "bad")
    (bad / "meta.json").write_text("{broken")
    from coordinator.browser_ui import launch_results_browser

    dashboard = launch_results_browser(tmp_path)
    assert "1 run" in dashboard.children[3].value
    assert "invalid meta.json" in dashboard.children[4].value
    assert "good" in dashboard.children[5].html


def test_rename_experiment_updates_directory_and_metadata(tmp_path):
    first = write_run(tmp_path, "old", "try@aaa1111-dirty_123456", "curve", patch="diff")
    write_run(tmp_path, "old", "bbb2222", "other")
    destination = rename_result(tmp_path, "experiment", first.parent.parent, "new")
    assert destination == tmp_path / "new"
    assert not (tmp_path / "old").exists()
    assert (destination / "try@aaa1111-dirty_123456" / "source.patch").read_text() == "diff"
    runs, warnings = scan_results(tmp_path)
    assert not warnings
    assert {run.experiment for run in runs} == {"new"}
    assert {run.metadata["experiment"] for run in runs} == {"new"}


def test_rename_attempt_changes_only_prefix(tmp_path):
    run = write_run(tmp_path, "exp", "old@aaa1111-dirty_123456", "curve")
    renamed = rename_result(tmp_path, "attempt", run.parent, "new")
    assert renamed.name == "new@aaa1111-dirty_123456"
    unnamed = rename_result(tmp_path, "attempt", renamed, "")
    assert unnamed.name == "aaa1111-dirty_123456"
    assert (unnamed / run.name / "data.csv").exists()
    assert rename_result(tmp_path, "attempt", unnamed, "named").name == "named@aaa1111-dirty_123456"


def test_rename_run_preserves_parameter_hash_and_updates_label(tmp_path):
    run = write_run(tmp_path, "exp", "aaa1111", "old")
    renamed = rename_result(tmp_path, "run", run, "new")
    assert renamed.name == "new@abc123"
    assert json.loads((renamed / "meta.json").read_text())["label"] == "new"
    assert scan_results(tmp_path)[0][0].label == "new"


def test_rename_rejects_collisions_invalid_names_and_outside_paths(tmp_path):
    first = write_run(tmp_path, "exp", "aaa1111", "first")
    write_run(tmp_path, "exp", "aaa1111", "second")
    with pytest.raises(FileExistsError):
        rename_result(tmp_path, "run", first, "second")
    for name in ("", "../bad", "a@b", " spaced "):
        with pytest.raises(ValueError):
            rename_result(tmp_path, "run", first, name)
    with pytest.raises(ValueError, match="outside"):
        delete_result(tmp_path, "run", tmp_path.parent)
    assert first.exists()


@pytest.mark.parametrize("kind", ["run", "attempt", "experiment"])
def test_delete_removes_selected_subtree(tmp_path, kind):
    first = write_run(tmp_path, "exp", "aaa1111", "first", patch="diff")
    second = write_run(tmp_path, "exp", "aaa1111", "second")
    target = {"run": first, "attempt": first.parent, "experiment": first.parent.parent}[kind]
    delete_result(tmp_path, kind, target)
    assert not target.exists()
    assert second.exists() is (kind == "run")


def test_overview_actions_rescan_and_report_errors(tmp_path):
    pytest.importorskip("ipywidgets")
    write_run(tmp_path, "exp", "aaa1111", "curve")
    write_run(tmp_path, "taken", "bbb2222", "other")
    from coordinator.browser_ui import launch_results_browser

    dashboard = launch_results_browser(tmp_path)
    overview = dashboard.children[5]
    overview.request = {"id": 1, "action": "rename", "target": "0", "name": "taken"}
    assert overview.response["ok"] is False
    assert "already exists" in overview.response["error"]
    overview.request = {"id": 2, "action": "rename", "target": "2", "name": "new-curve"}
    assert overview.response["ok"] is True
    assert "data-edit-name='new-curve'" in overview.html
    overview.request = {"id": 3, "action": "delete", "target": "2"}
    assert overview.response["ok"] is True
    assert not (tmp_path / "exp" / "aaa1111" / "new-curve@abc123").exists()


def test_selection_plots_runs_across_experiments_and_changes_metric(tmp_path):
    pytest.importorskip("ipywidgets")
    first = write_run(tmp_path, "exp-a", "aaa1111", "curve")
    second = write_run(tmp_path, "exp-b", "bbb2222", "curve")
    from coordinator.browser_ui import launch_results_browser

    dashboard = launch_results_browser(tmp_path)
    plot_area, overview = dashboard.children[1], dashboard.children[5]
    overview.plot_width = 1040
    assert plot_area.layout.display == "none"
    assert overview.html.count("data-select-kind='run'") == 2
    for index, run in enumerate((first, second), start=1):
        overview.request = {"id": index, "action": "select", "kind": "run", "path": str(run), "checked": True}
        assert overview.response["ok"] is True
    assert set(overview.selection["runs"]) == {str(first), str(second)}
    controls, figure = plot_area.children
    metric, logx, logy = controls.children
    assert plot_area.layout.display == "flex"
    assert plot_area.layout.width == "100%"
    assert plot_area.layout.margin == "0 0 28px 0"
    assert "coordinator-comparison-figure" in figure._dom_classes
    assert figure.layout.height == 600
    assert figure.layout.width == 1040
    overview.plot_width = 1180
    assert figure.layout.width == 1180
    assert len(figure.data) == 2
    assert figure.data[0].name != figure.data[1].name
    assert set(metric.options) == {"score", "err"}
    metric.value = "score"
    assert dashboard.children[1].children[1].layout.yaxis.title.text == "score"
    assert dashboard.children[1].children[1].layout.width == 1180
    logx.value = True
    assert dashboard.children[1].children[1].layout.xaxis.type == "log"
    assert dashboard.children[1].children[1].layout.xaxis.exponentformat == "power"
    logy.value = True
    assert dashboard.children[1].children[1].layout.yaxis.type == "log"
    assert dashboard.children[1].children[1].layout.yaxis.exponentformat == "power"
    assert dashboard.children[1].children[1].layout.yaxis.minor.dtick == "D1"
    assert dashboard.children[1].children[1].layout.yaxis.minor.showgrid is True
    overview.request = {"id": 3, "action": "select", "kind": "run", "path": str(first), "checked": False}
    overview.request = {"id": 4, "action": "select", "kind": "run", "path": str(second), "checked": False}
    assert plot_area.layout.display == "none"
    assert not plot_area.children


def test_attempt_selection_includes_hidden_runs_and_shows_partial_state(tmp_path):
    pytest.importorskip("ipywidgets")
    first = write_run(tmp_path, "exp", "try@aaa1111", "first")
    second = write_run(tmp_path, "exp", "try@aaa1111", "second")
    from coordinator.browser_ui import launch_results_browser

    dashboard = launch_results_browser(tmp_path)
    search, _ = dashboard.children[2].children
    overview = dashboard.children[5]
    search.value = "first"
    assert overview.html.count("class='coordinator-run'") == 1
    overview.request = {"id": 1, "action": "select", "kind": "attempt", "path": str(first.parent), "checked": True}
    assert set(overview.selection["runs"]) == {str(first), str(second)}
    assert overview.selection["attempts"][str(first.parent)] == "all"
    overview.request = {"id": 2, "action": "select", "kind": "run", "path": str(first), "checked": False}
    assert overview.selection["attempts"][str(first.parent)] == "some"
    search.value = ""
    assert overview.html.count("data-select-kind='run'") == 2
    overview.request = {"id": 3, "action": "select", "kind": "attempt", "path": str(first.parent), "checked": False}
    assert overview.selection["runs"] == []


def test_selection_survives_rename_and_refresh_and_drops_deleted_runs(tmp_path):
    pytest.importorskip("ipywidgets")
    first = write_run(tmp_path, "exp", "try@aaa1111", "first")
    from coordinator.browser_ui import launch_results_browser

    dashboard = launch_results_browser(tmp_path)
    _, refresh = dashboard.children[2].children
    overview = dashboard.children[5]
    overview.request = {"id": 1, "action": "select", "kind": "run", "path": str(first), "checked": True}
    overview.request = {"id": 2, "action": "rename", "target": "0", "name": "new-exp"}
    renamed = tmp_path / "new-exp" / first.parent.name / first.name
    assert overview.selection["runs"] == [str(renamed)]
    refresh.click()
    assert overview.selection["runs"] == [str(renamed)]
    renamed.joinpath("data.csv").unlink()
    refresh.click()
    assert overview.selection["runs"] == []
    assert dashboard.children[1].layout.display == "none"


def test_selection_follows_attempt_and_run_renames_then_delete(tmp_path):
    pytest.importorskip("ipywidgets")
    first = write_run(tmp_path, "exp", "try@aaa1111", "first")
    from coordinator.browser_ui import launch_results_browser

    dashboard = launch_results_browser(tmp_path)
    overview = dashboard.children[5]
    overview.request = {"id": 1, "action": "select", "kind": "run", "path": str(first), "checked": True}
    overview.request = {"id": 2, "action": "rename", "target": "1", "name": "new-try"}
    moved = tmp_path / "exp" / "new-try@aaa1111" / first.name
    assert overview.selection["runs"] == [str(moved)]
    overview.request = {"id": 3, "action": "rename", "target": "2", "name": "new-first"}
    moved = moved.with_name("new-first@abc123")
    assert overview.selection["runs"] == [str(moved)]
    overview.request = {"id": 4, "action": "delete", "target": "2"}
    assert overview.selection["runs"] == []
    assert dashboard.children[1].layout.display == "none"


def test_incompatible_selection_keeps_checkboxes_and_shows_message(tmp_path):
    pytest.importorskip("ipywidgets")
    first = write_run(tmp_path, "exp", "aaa1111", "first")
    second = write_run(tmp_path, "exp", "bbb2222", "second", axis="time", rows={"time": [1, 2], "other": [2, 3]})
    from coordinator.browser_ui import launch_results_browser

    dashboard = launch_results_browser(tmp_path)
    plot_area, overview = dashboard.children[1], dashboard.children[5]
    for index, run in enumerate((first, second), start=1):
        overview.request = {"id": index, "action": "select", "kind": "run", "path": str(run), "checked": True}
    assert len(overview.selection["runs"]) == 2
    assert "different axes" in plot_area.children[1].value


def test_no_shared_metric_keeps_selection_and_shows_message(tmp_path):
    pytest.importorskip("ipywidgets")
    first = write_run(tmp_path, "exp", "aaa1111", "first")
    second = write_run(tmp_path, "exp", "bbb2222", "second", rows={"noise": [1, 2], "other": [2, 3]})
    from coordinator.browser_ui import launch_results_browser

    dashboard = launch_results_browser(tmp_path)
    plot_area, overview = dashboard.children[1], dashboard.children[5]
    for index, run in enumerate((first, second), start=1):
        overview.request = {"id": index, "action": "select", "kind": "run", "path": str(run), "checked": True}
    assert len(overview.selection["runs"]) == 2
    assert "no common numeric metric" in plot_area.children[1].value


def test_browser_settings_save_and_restore_exact_view(tmp_path):
    pytest.importorskip("ipywidgets")
    results = tmp_path / "results"
    run = write_run(results, "exp", "try@aaa1111", "curve")
    notebook = tmp_path / "notebooks" / "results_browser.ipynb"
    notebook.parent.mkdir()
    notebook.write_text("{}")
    from coordinator.browser_ui import launch_results_browser

    dashboard = launch_results_browser(results)
    plot_area, overview = dashboard.children[1], dashboard.children[5]
    relative_run = run.relative_to(results).as_posix()
    relative_attempt = run.parent.relative_to(results).as_posix()
    overview.request = {"id": 1, "action": "select", "kind": "run", "path": str(run), "checked": True}
    metric, logx, logy = plot_area.children[0].children
    metric.value = "score"
    logx.value = True
    logy.value = True
    for index, kind, path, opened in (
        (2, "experiment", "exp", False),
        (3, "attempt", relative_attempt, False),
        (4, "patch", relative_attempt, False),
        (5, "data", relative_run, True),
        (6, "metadata", relative_run, True),
    ):
        overview.request = {"id": index, "action": "panel", "kind": kind, "path": path, "open": opened}
        assert overview.response["ok"] is True
    search, _ = dashboard.children[2].children
    search.value = "missing"
    search.value = ""
    assert "data-panel-kind='data' data-panel-path='exp/try@aaa1111/curve@abc123' data-initial-open='true' open" in overview.html
    search.value = "missing"
    settings_file = notebook.with_name("results_browser.settings.json")
    saved = json.loads(settings_file.read_text())
    assert saved["plot"] == {"metric": "score", "logx": True, "logy": True}
    assert saved["selected_runs"] == [relative_run]
    assert saved["panels"]["experiment"] == {"exp": False}
    assert saved["panels"]["data"] == {relative_run: True}
    assert "search" not in saved

    restored = launch_results_browser(results)
    restored_search, _ = restored.children[2].children
    restored_plot, restored_overview = restored.children[1], restored.children[5]
    assert restored_search.value == ""
    assert restored_overview.selection["runs"] == [str(run)]
    assert restored_plot.children[1].layout.xaxis.type == "log"
    assert restored_plot.children[1].layout.yaxis.type == "log"
    assert restored_plot.children[0].children[0].value == "score"
    for kind, path, opened in (
        ("experiment", "exp", False),
        ("attempt", relative_attempt, False),
        ("patch", relative_attempt, False),
        ("data", relative_run, True),
        ("metadata", relative_run, True),
    ):
        attributes = f"data-panel-kind='{kind}' data-panel-path='{path}' data-initial-open='{str(opened).lower()}'"
        assert attributes in restored_overview.html
        if opened:
            assert f"{attributes} open" in restored_overview.html

    run.joinpath("data.csv").unlink()
    restored.children[2].children[1].click()
    cleaned = json.loads(settings_file.read_text())
    assert cleaned["selected_runs"] == []
    assert cleaned["panels"]["data"] == {}
    assert cleaned["panels"]["metadata"] == {}


def test_settings_paths_follow_rename_and_delete(tmp_path):
    pytest.importorskip("ipywidgets")
    run = write_run(tmp_path, "exp", "try@aaa1111", "curve")
    from coordinator.browser_ui import launch_results_browser

    settings_file = tmp_path / "custom-view.json"
    dashboard = launch_results_browser(tmp_path, settings_path=settings_file)
    overview = dashboard.children[5]
    overview.request = {"id": 1, "action": "select", "kind": "run", "path": str(run), "checked": True}
    overview.request = {"id": 2, "action": "panel", "kind": "data", "path": "exp/try@aaa1111/curve@abc123", "open": True}
    overview.request = {"id": 3, "action": "panel", "kind": "patch", "path": "exp/try@aaa1111", "open": False}
    overview.request = {"id": 4, "action": "rename", "target": "0", "name": "new-exp"}
    saved = json.loads(settings_file.read_text())
    assert saved["selected_runs"] == ["new-exp/try@aaa1111/curve@abc123"]
    assert saved["panels"]["data"] == {"new-exp/try@aaa1111/curve@abc123": True}
    assert saved["panels"]["patch"] == {"new-exp/try@aaa1111": False}
    overview.request = {"id": 5, "action": "delete", "target": "1"}
    saved = json.loads(settings_file.read_text())
    assert saved["selected_runs"] == []
    assert saved["panels"]["data"] == {}
    assert saved["panels"]["patch"] == {}


def test_invalid_settings_warn_without_overwriting_file(tmp_path):
    pytest.importorskip("ipywidgets")
    run = write_run(tmp_path, "exp", "aaa1111", "curve")
    from coordinator.browser_ui import launch_results_browser

    settings_file = tmp_path / "invalid.json"
    settings_file.write_text("{broken")
    dashboard = launch_results_browser(tmp_path, settings_path=settings_file)
    overview = dashboard.children[5]
    assert "Automatic saving is disabled" in dashboard.children[4].value
    overview.request = {"id": 1, "action": "select", "kind": "run", "path": str(run), "checked": True}
    assert len(dashboard.children[1].children[1].data) == 1
    assert settings_file.read_text() == "{broken"


def test_settings_write_failure_warns_and_keeps_browser_usable(tmp_path, monkeypatch):
    pytest.importorskip("ipywidgets")
    run = write_run(tmp_path, "exp", "aaa1111", "curve")
    from coordinator import browser_ui

    def fail_save(_path, _settings):
        raise PermissionError("read only")

    monkeypatch.setattr(browser_ui, "save_settings", fail_save)
    dashboard = browser_ui.launch_results_browser(tmp_path, settings_path=tmp_path / "view.json")
    overview = dashboard.children[5]
    overview.request = {"id": 1, "action": "select", "kind": "run", "path": str(run), "checked": True}
    assert overview.selection["runs"] == [str(run)]
    assert "read only" in dashboard.children[4].value


def test_log_controls_show_error_and_allow_recovery(tmp_path):
    pytest.importorskip("ipywidgets")
    run = write_run(tmp_path, "exp", "aaa1111", "curve", rows={"noise": [0, 1], "score": [2, -1]})
    from coordinator.browser_ui import launch_results_browser

    dashboard = launch_results_browser(tmp_path)
    plot_area, overview = dashboard.children[1], dashboard.children[5]
    overview.request = {"id": 1, "action": "select", "kind": "run", "path": str(run), "checked": True}
    controls, _ = plot_area.children
    metric, logx, logy = controls.children
    metric.value = "score"
    logx.value = True
    assert "log x requires positive" in plot_area.children[1].value
    logx.value = False
    logy.value = True
    assert "log y requires positive" in plot_area.children[1].value
    logy.value = False
    assert len(plot_area.children[1].data) == 1
