# Sharing expensive setup between runs, and storing extra metadata.
#
# sweep loops over axis values on the outside and runs on the inside, so a
# cached setup that depends only on the axis value (and shared parameters) is
# built once per axis value and reused by every run.
#
#   python examples/04_expensive_setup.py

import functools
import random

from coordinator import Run, sweep


@functools.cache
def make_samples(noise, count):
    print(f"generating samples for noise={noise}")
    return [random.gauss(0, noise) for _ in range(count)]


def evaluate(point):
    samples = make_samples(point["noise"], point["count"])
    errors = [abs(sample) ** point["power"] for sample in samples]
    return {"mean_error": sum(errors) / len(errors)}


def main():
    sweep(
        [
            Run("absolute", evaluate, {"power": 1}),
            Run("squared", evaluate, {"power": 2}),
        ],
        axis="noise",
        axis_values=[0.1, 0.2, 0.5, 1.0],
        experiment="expensive-setup",
        shared={"count": 10000},
        meta={"note": "samples shared between runs"},
    )


if __name__ == "__main__":
    main()
