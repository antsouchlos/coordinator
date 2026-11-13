import hashlib
import json
import math
import subprocess

import pytest
from coordinator.git import get_repository_root, get_revision_and_patch
from coordinator.results import get_results_root
from coordinator.types import AttemptId, Experiment, Run, RunId, Sweep, SweepId


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
    assert base.attempt_id.value() == run_git(repo, "rev-parse", "--short=7", "HEAD")
    assert other_values.sweeps[0].id.value() != base.sweeps[0].id.value()
    assert (
        other_values.sweeps[0].runs[0].id.value() != base.sweeps[0].runs[0].id.value()
    )
    assert other_sweep.sweeps[0].id.value() != base.sweeps[0].id.value()
    assert other_run.sweeps[0].id.value() == base.sweeps[0].id.value()
    assert other_run.sweeps[0].runs[0].id.value() != base.sweeps[0].runs[0].id.value()

    sweep = base.sweeps[0]
    sweep_payload = {
        "experiment_id": base.attempt_id.value(),
        "axis_name": "size",
        "axis_values": [1, 2],
        "params": {"bias": 1},
    }
    expected_sweep_id = hashlib.sha256(
        json.dumps(sweep_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:7]
    run_payload = {"params": {"power": 2}, "sweep_id": expected_sweep_id}
    expected_run_id = hashlib.sha256(
        json.dumps(run_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:7]
    assert isinstance(base.attempt_id, AttemptId)
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
    assert experiment.attempt_id.value() == run_git(
        repo, "rev-parse", "--short=7", "HEAD"
    )


def test_revision_changes_with_selected_patch_and_commit(repo):
    first_revision, first_patch = get_revision_and_patch()
    assert first_patch == b""

    (repo / "skip.txt").write_text("excluded change\n")
    assert get_revision_and_patch() == (first_revision, first_patch)

    (repo / "keep.txt").write_text("selected change\n")
    dirty_revision, patch = get_revision_and_patch()
    assert dirty_revision.startswith(f"{first_revision}-dirty_")
    assert b"keep.txt" in patch
    assert b"skip.txt" not in patch

    run_git(repo, "add", "keep.txt")
    run_git(repo, "commit", "-qm", "New code")
    committed_revision, committed_patch = get_revision_and_patch()
    assert committed_revision not in {first_revision, dirty_revision}
    assert committed_patch == b""


def test_git_fallback_outside_repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    get_results_root.cache_clear()

    try:
        assert get_repository_root() is None
        assert get_revision_and_patch() == ("nogit", b"")
        assert get_results_root() == tmp_path / "results"
    finally:
        get_results_root.cache_clear()
