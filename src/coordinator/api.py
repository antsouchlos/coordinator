import datetime

from coordinator.results import get_run_file_handler, write_source_patch_if_not_exists
from coordinator.types import Experiment, Run, Sweep  # noqa: F401


def _append_metadata(
    current_metadata: dict,
    start_datetime: datetime.datetime,
    end_datetime: datetime.datetime,
    sweep_params: dict,
    run_params: dict,
    axis_name: str,
) -> dict:
    if "sweep_params" not in current_metadata:
        current_metadata["sweep_params"] = sweep_params

    if "run_params" not in current_metadata:
        current_metadata["run_params"] = run_params

    if "axis_name" not in current_metadata:
        current_metadata["axis_name"] = axis_name

    if "start_datetime" not in current_metadata:
        current_metadata["start_datetime"] = start_datetime.strftime(
            "%Y-%m-%d_%H:%M:%S"
        )

    if "duration_seconds" not in current_metadata:
        current_metadata["duration_seconds"] = 0

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
            current_metadata = run_file_handler.read_metadata()

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

                start_datetime = datetime.datetime.now()
                metrics = item.evaluate_func(sim_params)
                end_datetime = datetime.datetime.now()

                print(f"{sweep.axis_name}={axis_value}: {metrics}")

                if not metrics.keys().isdisjoint(sim_params.keys()):
                    raise ValueError("evaluator metrics overlap parameter names")

                run_file_handler.append_datapoint(
                    {**sim_params, **metrics, sweep.axis_name: axis_value}
                )

                current_metadata = _append_metadata(
                    current_metadata,
                    start_datetime,
                    end_datetime,
                    sweep.params,
                    item.params,
                    sweep.axis_name,
                )

                run_file_handler.write_metadata(current_metadata)
