import functools
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from coordinator.git import get_repository_root
from coordinator.types import Experiment, Run, Sweep


@functools.cache
def get_results_root() -> Path:
    return (get_repository_root() or Path.cwd()) / "results"


class RunFileHandler:
    def __init__(self, path: Path):
        self.path = path
        self.data_path = path / "data.csv"
        self.metadata_path = path / "metadata.json"

    def has_datapoint(self, axis_name: str, axis_value: float):
        if not self.data_path.exists():
            return False

        df = pd.read_csv(self.data_path)
        return np.any(np.isclose(np.array(df[axis_name])), axis_value)  # type: ignore[]

    def append_datapoint(self, point: dict):
        df = pd.DataFrame([point])
        df.to_csv(
            self.data_path, mode="a", header=not self.data_path.exists(), index=False
        )

    def read_metadata(self):
        if not self.metadata_path.exists():
            return {}

        with open(self.metadata_path) as fp:
            return json.load(fp)

    def write_metadata(self, metadata: dict):
        with open(self.metadata_path, "w") as fp:
            json.dump(metadata, fp)


def _dir_matches_id(dir_name: str, id: str):
    if "@" in dir_name:
        dir_id = dir_name.split("@")[1]
    else:
        dir_id = dir_name

    return dir_id == id


def _find_subdir_path_by_id(parent_path: Path, id: str) -> Path:
    dir_list = os.listdir(parent_path)

    dir_name = next(
        filter(
            lambda dir_name: _dir_matches_id(dir_name, id),
            dir_list,
        ),
        id,
    )

    return parent_path / dir_name


def write_source_patch_if_not_exists(experiment: Experiment):
    results_path = get_results_root()
    experiment_path = results_path / experiment.name
    experiment_path.mkdir(parents=True, exist_ok=True)

    attempt_path = _find_subdir_path_by_id(
        experiment_path, experiment.attempt_id.value()
    )
    experiment_path.mkdir(parents=True, exist_ok=True)

    patch_path = attempt_path / "source.patch"
    if experiment.patch and not patch_path.exists():
        Path(attempt_path).mkdir(parents=True)
        patch_path.write_bytes(experiment.patch)


def get_run_file_handler(
    experiment: Experiment, sweep: Sweep, run: Run
) -> RunFileHandler:
    results_path = get_results_root()
    experiment_path = results_path / experiment.name
    experiment_path.mkdir(parents=True, exist_ok=True)

    attempt_path = _find_subdir_path_by_id(
        experiment_path, experiment.attempt_id.value()
    )
    attempt_path.mkdir(parents=True, exist_ok=True)

    sweep_path = _find_subdir_path_by_id(
        attempt_path,
        sweep.id.value(),  # type: ignore[id is never None]
    )
    sweep_path.mkdir(parents=True, exist_ok=True)

    run_path = _find_subdir_path_by_id(
        sweep_path,
        run.id.value(),  # type: ignore[id is never None]
    )
    run_path.mkdir(parents=True, exist_ok=True)

    return RunFileHandler(run_path)
