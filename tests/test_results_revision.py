import hashlib
import json
import math
import subprocess

import pandas as pd
import pytest

from coordinator import Experiment, Run, Sweep, run
from coordinator.api import AttemptId, RunId, SweepId
from coordinator.browser import rename_result, scan_results
from coordinator.git import get_repository_root, get_revision_and_patch
from coordinator.results import get_results_root


def run_git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture(name="repo")
def create_repo(tmp_path, monkeypatch):
    run_git(tmp_path, "init", "-q")
    run_git(tmp_path, "config", "user.name", "Test")
    run_git(tmp_path, "config", "user.email", "test@example.com")
    (tmp_path / ".gitignore").write_text("results/\n")
    (tmp_path / "keep.txt").write_text("original\n")
    (tmp_path / "skip.txt").write_text("original\n")
    (tmp_path / ".coordinatorinclude").write_text("keep.txt\n")
    run_git(tmp_path, "add", ".")
    run_git(tmp_path, "commit", "-qm", "Initial")
    monkeypatch.chdir(tmp_path)
    get_results_root.cache_clear()
    yield tmp_path
    get_results_root.cache_clear()


def make_experiment(axis_vals=(1, 2), sweep_params=None, run_params=None, calls=None):
    calls = calls if calls is not None else []

    def evaluate(point):
        calls.append(dict(point))
        return {"score": point["size"] * 2}

    return Experiment(
        "example",
        [
            Sweep(
                sweep_params or {"bias": 1},
                "size",
                axis_vals,
                [Run(run_params or {"power": 2}, evaluate)],
            )
        ],
    )


def test_ids_depend_on_full_axis_list_and_parameters(repo):
    base = make_experiment()
    other_values = make_experiment(axis_vals=(1, 2, 3))
    other_sweep = make_experiment(sweep_params={"bias": 2})
    other_run = make_experiment(run_params={"power": 3})
    assert base.id.value() == run_git(repo, "rev-parse", "--short=7", "HEAD")
    assert (
        len(base.sweeps[0].id.value())
        == len(base.sweeps[0].runs[0].id.value())
        == 64
    )
    assert other_values.sweeps[0].id.value() != base.sweeps[0].id.value()
    assert (
        other_values.sweeps[0].runs[0].id.value()
        != base.sweeps[0].runs[0].id.value()
    )
    assert other_sweep.sweeps[0].id.value() != base.sweeps[0].id.value()
    assert other_run.sweeps[0].id.value() == base.sweeps[0].id.value()
    assert (
        other_run.sweeps[0].runs[0].id.value()
        != base.sweeps[0].runs[0].id.value()
    )

    sweep = base.sweeps[0]
    sweep_payload = {
        "experiment_id": base.id.value(),
        "axis_name": "size",
        "axis_values": [1, 2],
        "params": {"bias": 1},
    }
    expected_sweep_id = hashlib.sha256(
        json.dumps(sweep_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    run_payload = {"params": {"power": 2}, "sweep_id": expected_sweep_id}
    expected_run_id = hashlib.sha256(
        json.dumps(run_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert isinstance(base.id, AttemptId)
    assert isinstance(sweep.id, SweepId)
    assert isinstance(sweep.runs[0].id, RunId)
    assert sweep.id.value() == expected_sweep_id
    assert sweep.runs[0].id.value() == expected_run_id


def test_duplicate_ids_and_parameter_overlap_rejected(repo):
    evaluator = lambda _: {"score": 1}

    with pytest.raises(ValueError, match="duplicate sweep or run ID"):
        Experiment(
            "x",
            [
                Sweep({}, "size", [1], [Run({}, evaluator)]),
                Sweep({}, "size", [1], [Run({}, evaluator)]),
            ],
        )

    with pytest.raises(ValueError, match="duplicate sweep or run ID"):
        Experiment(
            "x", [Sweep({}, "size", [1], [Run({}, evaluator), Run({}, evaluator)])]
        )

    for sweep_params, run_params in [
        ({"size": 1}, {}),
        ({}, {"size": 1}),
        ({"bias": 1}, {"bias": 2}),
    ]:
        with pytest.raises(ValueError, match="overlap"):
            Sweep(sweep_params, "size", [1], [Run(run_params, evaluator)])

    for value in [math.nan, math.inf, object(), {1: "bad"}, (1, 2)]:
        with pytest.raises((TypeError, ValueError)):
            Experiment("x", [Sweep({}, "size", [1], [Run({"bad": value}, evaluator)])])


def test_constructors_retain_inputs_and_copy_runs(repo):
    run_params = {"power": 2}
    sweep_params = {"bias": 1}
    axis_vals = [1, 2]
    original_run = Run(run_params, lambda point: {"score": point["size"]})
    sweep = Sweep(sweep_params, "size", axis_vals, [original_run])
    experiment = Experiment("example", [sweep])

    assert original_run.params is run_params
    assert sweep.params is sweep_params
    assert sweep.axis_vals is axis_vals
    assert sweep.runs[0] is not original_run
    assert sweep.runs[0].params is not run_params
    assert original_run.id is None
    assert experiment.sweeps[0] is not sweep
    assert experiment.id.value() == run_git(repo, "rev-parse", "--short=7", "HEAD")


def test_layout_execution_order_resume_and_cosmetic_rename(repo, monkeypatch):
    monkeypatch.setenv("NEW_ATTEMPT_NAME", "first")
    calls = []

    def evaluate(point):
        calls.append((point["size"], point["power"], point["bias"]))
        return {"score": point["size"] + point["power"]}

    sweep = Sweep(
        {"bias": 1},
        "size",
        [1, 2],
        [Run({"power": 2}, evaluate), Run({"power": 3}, evaluate)],
    )
    experiment = Experiment("example", [sweep])
    assert run(experiment) is None
    assert calls == [(1, 2, 1), (1, 3, 1), (2, 2, 1), (2, 3, 1)]
    attempt = get_results_root() / "example" / f"first@{experiment.id.value()}"
    owned_sweep = experiment.sweeps[0]
    sweep_path = attempt / owned_sweep.id.value()
    first = sweep_path / owned_sweep.runs[0].id.value()
    assert first.is_dir()
    assert list(pd.read_csv(first / "data.csv")["size"]) == [1, 2]
    metadata = json.loads((first / "metadata.json").read_text())
    assert metadata["axis_vals"] == [1, 2]
    assert metadata["sweep_params"] == {"bias": 1}
    assert metadata["run_params"] == {"power": 2}
    renamed_sweep = rename_result(get_results_root(), "sweep", sweep_path, "named")
    renamed_run = rename_result(
        get_results_root(), "run", renamed_sweep / first.name, "curve"
    )
    monkeypatch.setenv("NEW_ATTEMPT_NAME", "second")
    run(experiment)
    assert len(calls) == 4
    assert renamed_run.exists()
    assert len(list((get_results_root() / "example").iterdir())) == 1
    indexed, warnings = scan_results(get_results_root())
    assert len(indexed) == 2 and not warnings
    assert indexed[0].patch_path is None


def test_attempt_changes_with_git_commit_and_selected_patch(repo):
    first = make_experiment()
    run(first)
    first_attempt = first.id.value()
    (repo / "skip.txt").write_text("excluded change\n")
    assert make_experiment().id.value() == first_attempt
    (repo / "keep.txt").write_text("selected change\n")
    run(first)
    assert first.id.value() == first_attempt
    assert [path.name for path in (get_results_root() / "example").iterdir()] == [
        first_attempt
    ]
    second = make_experiment()
    run(second)
    assert second.id.value() != first_attempt and "-dirty_" in second.id.value()
    patch = get_results_root() / "example" / second.id.value() / "source.patch"
    assert "keep.txt" in patch.read_text()
    assert "skip.txt" not in patch.read_text()
    run_git(repo, "add", "keep.txt")
    run_git(repo, "commit", "-qm", "New code")
    third = make_experiment()
    run(third)
    assert third.id.value() not in {first_attempt, second.id.value()}


def test_axis_list_change_creates_new_run(repo):
    first = make_experiment((1, 2))
    run(first)
    second = make_experiment((1, 2, 3))
    run(second)
    assert (
        first.sweeps[0].runs[0].id.value() != second.sweeps[0].runs[0].id.value()
    )
    assert (
        len(list((get_results_root() / "example" / first.id.value()).iterdir())) == 2
    )


def test_multiple_sweeps_run_in_input_order(repo):
    calls = []

    def evaluate(point):
        calls.append((point["bias"], point["size"], point["power"]))
        return {"score": len(calls)}

    experiment = Experiment(
        "ordered",
        [
            Sweep(
                {"bias": 1},
                "size",
                [1, 2],
                [Run({"power": 1}, evaluate), Run({"power": 2}, evaluate)],
            ),
            Sweep({"bias": 2}, "size", [3], [Run({"power": 1}, evaluate)]),
        ],
    )
    run(experiment)
    assert calls == [(1, 1, 1), (1, 1, 2), (1, 2, 1), (1, 2, 2), (2, 3, 1)]
    assert len(scan_results(get_results_root())[0]) == 3


def test_git_fallback_outside_repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    get_results_root.cache_clear()

    try:
        assert get_repository_root() is None
        assert get_revision_and_patch() == ("nogit", b"")
        assert get_results_root() == tmp_path / "results"
    finally:
        get_results_root.cache_clear()
