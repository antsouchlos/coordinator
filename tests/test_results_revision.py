import json
import subprocess

import pytest

from coordinator import Run, sweep
from coordinator.results import get_results_root, _get_revision, resolve_and_open_run


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
    run = resolve_and_open_run("experiment", "curve", {})
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
    patch_path = resolve_and_open_run("experiment", "curve", {}).path.parent / "source.patch"
    patch = patch_path.read_text()
    assert "src/model.py" in patch
    assert "src/generated/skip.py" not in patch

    (repo / "src" / "model.py").unlink()
    git(repo, "apply", "--check", str(patch_path))
    assert _get_revision() == commit
    (repo / ".coordinatorinclude").write_text("src/**\n!src/generated/**\n# revised\n")
    assert _get_revision().startswith(f"{commit}-dirty_")
    assert ".coordinatorinclude" in (resolve_and_open_run("other", "curve", {}).path.parent / "source.patch").read_text()


def test_git_ignored_tracked_file_is_excluded_and_nested_cwd_uses_root(repo, monkeypatch):
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

    first = sweep([Run("curve", evaluate)], "size", [1], "experiment")["curve"]
    assert first.parent.name.startswith("first@")
    assert json.loads((first / "meta.json").read_text())["revision"] == _get_revision()
    monkeypatch.setenv("NEW_ATTEMPT_NAME", "second")
    resumed = sweep([Run("curve", evaluate)], "size", [1, 2], "experiment")["curve"]
    assert resumed == first
    assert evaluations == [1, 2]

    (repo / "skip.txt").write_text("unrelated committed change\n")
    git(repo, "add", "skip.txt")
    git(repo, "commit", "-qm", "Change excluded file")
    second = sweep([Run("curve", evaluate)], "size", [1], "experiment")["curve"]
    assert second.parent.name.startswith("second@")
    assert second.parent != first.parent
    assert evaluations == [1, 2, 1]
