import json
import math
import subprocess

import pytest

from coordinator import Run, results, sweep
from coordinator.browser import rename_result
from coordinator.results import _get_revision, get_results_root, resolve_and_open_run


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.com")
    (tmp_path / ".gitignore").write_text("ignored.txt\nresults/\n")
    (tmp_path / "keep.txt").write_text("original\n")
    (tmp_path / "skip.txt").write_text("original\n")
    git(tmp_path, "add", ".gitignore", "keep.txt", "skip.txt")
    git(tmp_path, "commit", "-qm", "Initial")
    monkeypatch.chdir(tmp_path)
    get_results_root.cache_clear()
    yield tmp_path
    get_results_root.cache_clear()


def test_include_rules_scope_dirty_hash_and_patch(repo):
    (repo / ".coordinatorinclude").write_text("*.txt\n!skip.txt\n")
    git(repo, "add", ".coordinatorinclude")
    git(repo, "commit", "-qm", "Add include rules")
    commit = git(repo, "rev-parse", "--short=7", "HEAD")

    (repo / "skip.txt").write_text("changed\n")
    (repo / "ignored.txt").write_text("ignored\n")
    assert _get_revision() == commit

    (repo / "keep.txt").write_text("changed\n")
    revision = _get_revision()
    assert revision.startswith(f"{commit}-dirty_")
    run = resolve_and_open_run("experiment", "curve", {}, "size")
    patch = (run.path.parent / "source.patch").read_text()
    assert "keep.txt" in patch
    assert "skip.txt" not in patch
    assert "ignored.txt" not in patch

    (repo / "keep.txt").write_text("changed again\n")
    assert _get_revision() != revision


def test_untracked_files_and_include_rules_change_revision(repo):
    (repo / ".coordinatorinclude").write_text("src/**\n!src/generated/**\n")
    git(repo, "add", ".coordinatorinclude")
    git(repo, "commit", "-qm", "Add include rules")
    commit = git(repo, "rev-parse", "--short=7", "HEAD")
    (repo / "src" / "generated").mkdir(parents=True)
    (repo / "src" / "generated" / "skip.py").write_text("skip = True\n")
    assert _get_revision() == commit

    (repo / "src" / "model.py").write_text("model = True\n")
    revision = _get_revision()
    assert revision.startswith(f"{commit}-dirty_")
    patch_path = (
        resolve_and_open_run("experiment", "curve", {}, "size").path.parent
        / "source.patch"
    )
    patch = patch_path.read_text()
    assert "src/model.py" in patch
    assert "src/generated/skip.py" not in patch

    (repo / "src" / "model.py").unlink()
    git(repo, "apply", "--check", str(patch_path))
    assert _get_revision() == commit
    (repo / ".coordinatorinclude").write_text("src/**\n!src/generated/**\n# revised\n")
    assert _get_revision().startswith(f"{commit}-dirty_")
    assert (
        ".coordinatorinclude"
        in (
            resolve_and_open_run("other", "curve", {}, "size").path.parent
            / "source.patch"
        ).read_text()
    )


def test_git_ignored_tracked_file_is_excluded_and_nested_cwd_uses_root(
    repo, monkeypatch
):
    (repo / ".coordinatorinclude").write_text("src/**\n")
    (repo / "src").mkdir()
    (repo / "src" / ".gitignore").write_text("ignored.py\n")
    (repo / "src" / "ignored.py").write_text("original\n")
    (repo / "src" / "kept.py").write_text("original\n")
    git(repo, "add", ".coordinatorinclude", "src/.gitignore", "src/kept.py")
    git(repo, "add", "-f", "src/ignored.py")
    git(repo, "commit", "-qm", "Add source files")
    commit = git(repo, "rev-parse", "--short=7", "HEAD")
    monkeypatch.chdir(repo / "src")
    (repo / "src" / "ignored.py").write_text("changed\n")
    assert _get_revision() == commit
    (repo / "src" / "kept.py").write_text("changed\n")
    assert _get_revision().startswith(f"{commit}-dirty_")


@pytest.mark.parametrize("include_file", [False, True])
def test_missing_or_empty_include_file_tracks_all_nonignored_files(repo, include_file):
    if include_file:
        (repo / ".coordinatorinclude").write_text("")
        git(repo, "add", ".coordinatorinclude")
        git(repo, "commit", "-qm", "Add empty include file")
    commit = git(repo, "rev-parse", "--short=7", "HEAD")
    (repo / "ignored.txt").write_text("ignored\n")
    assert _get_revision() == commit
    (repo / "new.txt").write_text("new\n")
    assert _get_revision().startswith(f"{commit}-dirty_")


def test_new_commit_creates_revision_and_existing_run_resumes(repo, monkeypatch):
    (repo / ".coordinatorinclude").write_text("keep.txt\n")
    git(repo, "add", ".coordinatorinclude")
    git(repo, "commit", "-qm", "Add include rules")
    monkeypatch.setenv("NEW_ATTEMPT_NAME", "first")
    evaluations = []

    def evaluate(point):
        evaluations.append(point["size"])
        return {"score": point["size"]}

    first = sweep([Run("curve", evaluate)], "size", [1], "experiment")[0]
    assert first.parent.name.startswith("first@")
    assert json.loads((first / "meta.json").read_text())["revision"] == _get_revision()
    monkeypatch.setenv("NEW_ATTEMPT_NAME", "second")
    resumed = sweep([Run("curve", evaluate)], "size", [1, 2], "experiment")[0]
    assert resumed == first
    assert evaluations == [1, 2]

    (repo / "skip.txt").write_text("unrelated committed change\n")
    git(repo, "add", "skip.txt")
    git(repo, "commit", "-qm", "Change excluded file")
    second = sweep([Run("curve", evaluate)], "size", [1], "experiment")[0]
    assert second.parent.name.startswith("second@")
    assert second.parent != first.parent
    assert evaluations == [1, 2, 1]


def test_identity_includes_axis_and_effective_fixed_params(repo):
    def evaluate(point):
        return {"score": point.get("size", point.get("width"))}

    first = sweep(
        [Run("curve", evaluate, {"power": 2})],
        "size",
        [1],
        "experiment",
        shared={"bias": 1, "power": 0, "size": 99},
    )[0]
    same = sweep(
        [Run("renamed", evaluate, {"power": 2})],
        "size",
        [1, 2],
        "experiment",
        shared={"bias": 1, "power": 9, "size": 88},
    )[0]
    changed_shared = sweep(
        [Run("curve", evaluate, {"power": 2})],
        "size",
        [1],
        "experiment",
        shared={"bias": 2},
    )[0]
    changed_axis = sweep(
        [Run("curve", evaluate, {"power": 2})],
        "width",
        [1],
        "experiment",
        shared={"bias": 1},
    )[0]

    assert same == first
    assert changed_shared != first
    assert changed_axis != first
    assert len(first.name.rsplit("@", 1)[-1]) == 16
    assert len((first / "data.csv").read_text().splitlines()) == 3
    metadata = json.loads((first / "meta.json").read_text())
    assert metadata["label"] == "curve"
    assert metadata["identity"] == {"axis": "size", "params": {"bias": 1, "power": 2}}


def test_duplicate_labels_have_distinct_paths_and_same_identity_runs_once(repo):
    calls = []

    def evaluate(point):
        calls.append(point["power"])
        return {"score": point["power"]}

    paths = sweep(
        [
            Run("curve", evaluate, {"power": 1}),
            Run("curve", evaluate, {"power": 2}),
            Run("alias", evaluate, {"power": 1}),
        ],
        "size",
        [1, 2],
        "experiment",
    )

    assert len(paths) == 3
    assert paths[0] != paths[1]
    assert paths[0] == paths[2]
    assert calls == [1, 2, 1, 2]


def test_renamed_run_is_reused_by_identity(repo):
    calls = []

    def evaluate(point):
        calls.append(point["size"])
        return {"score": point["size"]}

    original = sweep([Run("old", evaluate)], "size", [1], "experiment")[0]
    renamed = rename_result(get_results_root(), "run", original, "new")
    reused = sweep([Run("another", evaluate)], "size", [1, 2], "experiment")[0]

    assert reused == renamed
    assert calls == [1, 2]
    assert json.loads((renamed / "meta.json").read_text())["label"] == "new"


@pytest.mark.parametrize("value", [math.nan, math.inf, object(), {1: "bad"}, (1, 2)])
def test_non_json_identity_values_are_rejected(repo, value):
    with pytest.raises((TypeError, ValueError)):
        sweep(
            [Run("curve", lambda point: {}, {"bad": value})], "size", [1], "experiment"
        )
    assert not get_results_root().exists()


def test_meta_cannot_override_identity(repo):
    with pytest.raises(ValueError, match="reserved fields: axis"):
        sweep(
            [Run("curve", lambda point: {})],
            "size",
            [1],
            "experiment",
            meta={"axis": "other"},
        )
    assert not get_results_root().exists()


def test_existing_run_identity_is_verified_before_reuse(repo, monkeypatch):
    monkeypatch.setattr(results, "_get_identity_hash", lambda identity: "a" * 16)
    first = resolve_and_open_run("experiment", "curve", {"power": 1}, "size")

    with pytest.raises(ValueError, match="invalid run identity"):
        resolve_and_open_run("experiment", "curve", {"power": 2}, "size")

    assert len(list(first.path.parent.iterdir())) == 1
