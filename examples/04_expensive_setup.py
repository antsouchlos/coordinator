"""Reuse cached samples across runs at each axis value."""

import functools
import random

from coordinator import Experiment, Run, Sweep, run


@functools.cache
def make_samples(noise, count):
    print(f"generating samples for noise={noise}")
    return [random.gauss(0, noise) for _ in range(count)]


def evaluate(point):
    samples = make_samples(point["noise"], point["count"])
    errors = [abs(sample) ** point["power"] for sample in samples]
    return {"mean_error": sum(errors) / len(errors)}


def run_example():
    run(
        Experiment(
            "expensive-setup",
            [
                Sweep(
                    params={"count": 10000},
                    axis_name="noise",
                    axis_vals=[0.1, 0.2, 0.5, 1.0],
                    runs=[
                        Run(params={"power": 1}, evaluator_func=evaluate),
                        Run(params={"power": 2}, evaluator_func=evaluate),
                    ],
                )
            ],
        )
    )


if __name__ == "__main__":
    run_example()
