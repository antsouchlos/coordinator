from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass

from coordinator.git import get_revision_and_patch
from coordinator.results import _get_identity_hash, resolve_and_open_run


@dataclass(frozen=True, init=False)
class AttemptId:
    _value: str

    def __init__(self, revision: str) -> None:
        object.__setattr__(self, "_value", revision)

    def value(self) -> str:
        return self._value


@dataclass(frozen=True, init=False)
class SweepId:
    _hash: str

    def __init__(
        self,
        experiment_id: AttemptId,
        axis_name: str,
        axis_values: Sequence,
        params: dict,
    ) -> None:
        identity = {
            "experiment_id": experiment_id.value(),
            "axis_name": axis_name,
            "axis_values": list(axis_values),
            "params": dict(params),
        }
        object.__setattr__(self, "_hash", _get_identity_hash(identity))

    def value(self) -> str:
        return self._hash


@dataclass(frozen=True, init=False)
class RunId:
    _hash: str

    def __init__(self, params: dict, sweep_id: SweepId) -> None:
        identity = {"params": dict(params), "sweep_id": sweep_id.value()}
        object.__setattr__(self, "_hash", _get_identity_hash(identity))

    def value(self) -> str:
        return self._hash


class Run:
    def __init__(self, params: dict, evaluator_func: Callable[[dict], dict]) -> None:
        if not isinstance(params, dict):
            raise TypeError("run params must be a dictionary")
        if not callable(evaluator_func):
            raise TypeError("evaluator_func must be callable")

        self.params = params
        self.evaluate_func = evaluator_func
        self.id: RunId | None = None


class Sweep:
    def __init__(
        self,
        params: dict,
        axis_name: str,
        axis_vals: Sequence,
        runs: Sequence[Run],
    ) -> None:
        if not isinstance(params, dict):
            raise TypeError("sweep params must be a dictionary")
        if not isinstance(axis_name, str) or not axis_name:
            raise ValueError("axis_name must be a nonempty string")
        if isinstance(axis_vals, (str, bytes)):
            raise TypeError("axis_vals must be a sequence of values")
        if axis_name in params:
            raise ValueError("axis name overlaps sweep parameters")

        for run in runs:
            if not isinstance(run, Run):
                raise TypeError("runs must contain Run objects")

            overlapping_names = set(run.params) & (set(params) | {axis_name})

            if overlapping_names:
                raise ValueError(
                    "run parameters overlap sweep parameters or axis: "
                    f"{sorted(overlapping_names)}"
                )

        self.params = params
        self.axis_name = axis_name
        self.axis_vals = axis_vals
        self.runs = deepcopy(runs)
        self.id: SweepId | None = None


class Experiment:
    def __init__(self, name: str, sweeps: Sequence[Sweep]) -> None:
        if (
            not isinstance(name, str)
            or not name
            or name in {".", ".."}
            or any(character in name for character in "/\\\x00")
        ):
            raise ValueError("experiment name must be a valid directory name")

        self.name = name
        self.sweeps = deepcopy(sweeps)
        revision, self.patch = get_revision_and_patch()
        self.id = AttemptId(revision)

        ids = []

        for sweep in self.sweeps:
            if not isinstance(sweep, Sweep):
                raise TypeError("sweeps must contain Sweep objects")

            sweep.id = SweepId(
                self.id,
                sweep.axis_name,
                sweep.axis_vals,
                sweep.params,
            )
            ids.append(sweep.id)

            for run in sweep.runs:
                run.id = RunId(run.params, sweep.id)
                ids.append(run.id)

        if len(ids) != len(set(ids)):
            raise ValueError("duplicate sweep or run ID")


def run(experiment: Experiment) -> None:
    if not isinstance(experiment, Experiment):
        raise TypeError("run expects an Experiment")

    for sweep in experiment.sweeps:
        run_directories = [
            resolve_and_open_run(experiment, sweep, item, experiment.patch)
            for item in sweep.runs
        ]

        for axis_value in sweep.axis_vals:
            for item, run_directory in zip(sweep.runs, run_directories):
                point = {**sweep.params, **item.params, sweep.axis_name: axis_value}

                if run_directory.has_row({sweep.axis_name: axis_value}):
                    continue

                metrics = item.evaluate_func(point)

                if not isinstance(metrics, dict):
                    raise TypeError("evaluator must return a dictionary")
                if set(metrics) & set(point):
                    raise ValueError("evaluator metrics overlap parameter names")

                run_directory.append({**point, **metrics})
