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
    search, refresh = dashboard.children[1].children
    overview = dashboard.children[4]
    markup = overview.html
    assert "3 runs" in dashboard.children[2].value
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
    assert "1 matching run" in dashboard.children[2].value
    search.value = ""
    write_run(tmp_path, "exp-two", "ccc3333", "fourth")
    refresh.click()
    assert "4 runs" in dashboard.children[2].value
    assert "exp-two" in overview.html


def test_overview_preserves_valid_runs_when_metadata_is_invalid(tmp_path):
    pytest.importorskip("ipywidgets")
    write_run(tmp_path, "exp", "aaa1111", "good")
    bad = write_run(tmp_path, "exp", "aaa1111", "bad")
    (bad / "meta.json").write_text("{broken")
    from coordinator.browser_ui import launch_results_browser

    dashboard = launch_results_browser(tmp_path)
    assert "1 run" in dashboard.children[2].value
    assert "invalid meta.json" in dashboard.children[3].value
    assert "good" in dashboard.children[4].html


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
    overview = dashboard.children[4]
    overview.request = {"id": 1, "action": "rename", "target": "0", "name": "taken"}
    assert overview.response["ok"] is False
    assert "already exists" in overview.response["error"]
    overview.request = {"id": 2, "action": "rename", "target": "2", "name": "new-curve"}
    assert overview.response["ok"] is True
    assert "data-edit-name='new-curve'" in overview.html
    overview.request = {"id": 3, "action": "delete", "target": "2"}
    assert overview.response["ok"] is True
    assert not (tmp_path / "exp" / "aaa1111" / "new-curve@abc123").exists()
