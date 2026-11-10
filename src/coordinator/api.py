from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from coordinator.results import resolve_and_open_run


@dataclass
class Run:
    label: str
    evaluate: Callable[[dict], dict]
    params: dict = field(default_factory=dict)


def sweep(
    runs: list[Run],
    axis: str,
    axis_values,
    experiment: str,
    shared: dict | None = None,
    meta: dict | None = None,
) -> list[Path]:
    """
    Evaluate every (run, axis value) point not yet stored in its run directory.

    Each run's `evaluate` receives `{**shared, **run.params, axis: value}` and
    returns the metrics stored alongside it. Axis values form the outer loop
    and runs the inner one, so an evaluator may cache setup that depends only
    on `shared` and the axis value. Return result paths in input-run order.
    Runs with the same axis and effective fixed parameters share one result;
    the first matching run evaluates missing points.
    """

    shared = shared if shared is not None else {}
    run_dirs = [
        resolve_and_open_run(
            experiment,
            run.label,
            run.params,
            axis,
            shared,
            meta,
        )
        for run in runs
    ]

    for value in axis_values:
        processed = set()
        for run, run_dir in zip(runs, run_dirs):
            if run_dir.path in processed:
                continue
            processed.add(run_dir.path)
            point = {**shared, **run.params, axis: value}
            if run_dir.has_row(point):
                print(f"{run.label}, {axis}: {value}, already done")
                continue

            metrics = run.evaluate(point)
            run_dir.append({**point, **metrics})

            formatted = ", ".join(f"{key}: {metric}" for key, metric in metrics.items())
            print(f"{run.label}, {axis}: {value}, {formatted}")

    return [run_dir.path for run_dir in run_dirs]
