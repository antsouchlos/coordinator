# Several runs with different parameters simulated over the same axis.
#
#   python examples/02_compare_runs.py

import random

from coordinator import Run, sweep


def evaluate(point):
    errors = [
        abs(random.gauss(point["bias"], point["noise"]))
        for _ in range(point["samples"])
    ]
    return {"mean_error": sum(errors) / len(errors)}


def main():
    sweep(
        [
            Run("10 samples", evaluate, {"samples": 10}),
            Run("1000 samples", evaluate, {"samples": 1000}),
        ],
        axis="noise",
        axis_values=[0.1, 0.2, 0.5, 1.0],
        experiment="compare-runs",
        shared={"bias": 0.1},
    )


if __name__ == "__main__":
    main()
