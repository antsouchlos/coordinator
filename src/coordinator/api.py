import datetime
import hashlib
import json
import math
from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass

from coordinator.git import get_revision_and_patch
from coordinator.results import get_run_file_handler, write_source_patch_if_not_exists


def _validate_identity_value(value, location: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{location} must be a finite JSON value")

        return

    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_identity_value(item, f"{location}[{index}]")

        return

    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{location} keys must be strings")

            _validate_identity_value(item, f"{location}.{key}")

        return

    raise TypeError(f"{location} must contain only JSON-compatible values")


def _serialize_identity(identity: dict) -> str:
    _validate_identity_value(identity, "run identity")
    return json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _get_identity_hash(identity: dict) -> str:
    return hashlib.sha256(_serialize_identity(identity).encode()).hexdigest()


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
        self.attempt_id = AttemptId(revision)

        ids = []

        for sweep in self.sweeps:
            if not isinstance(sweep, Sweep):
                raise TypeError("sweeps must contain Sweep objects")

            sweep.id = SweepId(
                self.attempt_id,
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


def _append_metadata(
    current_metadata: dict,
    start_datetime: datetime.datetime,
    end_datetime: datetime.datetime,
    sweep_params: dict,
    axis_name: str,
) -> dict:
    if "sweep_params" not in current_metadata:
        current_metadata["sweep_params"] = sweep_params

    if "axis_name" not in current_metadata:
        current_metadata["axis_name"] = sweep_params

    if "start_datetime" not in current_metadata:
        current_metadata["start_datetime"] = start_datetime

    if "duration" not in current_metadata:
        current_metadata["duration"] = 0

    current_metadata["duration_seconds"] += (
        end_datetime - start_datetime
    ).total_seconds()

    return current_metadata


def run(experiment: Experiment) -> None:
    write_source_patch_if_not_exists(experiment)

    for sweep in experiment.sweeps:
        run_file_handlers = [
            get_run_file_handler(experiment, sweep, item) for item in sweep.runs
        ]

        for item, run_file_handler in zip(sweep.runs, run_file_handlers):
            start_datetime = datetime.datetime.now()

            for axis_value in sweep.axis_vals:
                if run_file_handler.has_datapoint(sweep.axis_name, axis_value):
                    print(
                        f"Datapoint for {sweep.axis_name}={axis_value} exists. Skipping simulation."
                    )
                    continue

                sim_params = {
                    **sweep.params,
                    **item.params,
                    sweep.axis_name: axis_value,
                }

                metrics = item.evaluate_func(sim_params)
                print(f"{sweep.axis_name}={axis_value}: {metrics}")

                if not metrics.keys().isdisjoint(sim_params.keys()):
                    raise ValueError("evaluator metrics overlap parameter names")

                run_file_handler.append_datapoint(
                    {**sim_params, **metrics, sweep.axis_name: axis_value}
                )

            end_datetime = datetime.datetime.now()

            current_metadata = run_file_handler.read_metadata()
            run_file_handler.write_metadata(
                _append_metadata(
                    current_metadata,
                    start_datetime,
                    end_datetime,
                    sweep.params,
                    sweep.axis_name,
                )
            )
