from collections.abc import Callable
from dataclasses import dataclass, field

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
) -> dict:
    """
    Evaluate every (run, axis value) point not yet stored in its run directory.

    Each run's `evaluate` receives `{**shared, **run.params, axis: value}` and
    returns the metrics stored alongside it. Axis values form the outer loop
    and runs the inner one, so an evaluator may cache setup that depends only
    on `shared` and the axis value.
    """

    shared = shared or {}
    run_dirs = {
        run.label: resolve_and_open_run(
            experiment,
            run.label,
            {key: value for key, value in run.params.items() if key != axis},
            {"axis": axis, "shared": shared, **(meta or {})},
        )
        for run in runs
    }

    for value in axis_values:
        for run in runs:
            point = {**shared, **run.params, axis: value}
            run_dir = run_dirs[run.label]
            if run_dir.has_row(point):
                print(f"{run.label}, {axis}: {value}, already done")
                continue

            metrics = run.evaluate(point)
            run_dir.append({**point, **metrics})

            formatted = ", ".join(f"{key}: {metric}" for key, metric in metrics.items())
            print(f"{run.label}, {axis}: {value}, {formatted}")

    return {label: run_dir.path for label, run_dir in run_dirs.items()}
