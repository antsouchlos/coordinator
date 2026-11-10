# Returning an error estimate alongside the metric.
#
#   python examples/03_error_bars.py

import math
import random
import statistics

from coordinator import Run, sweep


def evaluate(point):
    errors = [abs(random.gauss(0, point["noise"])) for _ in range(100)]
    return {
        "mean_error": statistics.mean(errors),
        "mean_error_err": statistics.stdev(errors) / math.sqrt(len(errors)),
    }


def main():
    sweep(
        [Run("gaussian", evaluate)],
        axis="noise",
        axis_values=[10**exponent for exponent in range(-3, 1)],
        experiment="error-bars",
    )


if __name__ == "__main__":
    main()
