# One run swept over one axis.
#
#   python examples/01_basic.py
#
# Set NEW_ATTEMPT_NAME to prefix a new results directory, e.g.
#   NEW_ATTEMPT_NAME=first python examples/01_basic.py

import random

from coordinator import Run, sweep


def evaluate(point):
    errors = [abs(random.gauss(0, point["noise"])) for _ in range(1000)]
    return {"mean_error": sum(errors) / len(errors)}


def main():
    sweep(
        [Run("gaussian", evaluate)],
        axis="noise",
        axis_values=[0.1, 0.2, 0.5, 1.0],
        experiment="basic",
    )


if __name__ == "__main__":
    main()
