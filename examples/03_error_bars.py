import math
import random
import statistics

from coordinator import Experiment, Run, Sweep, run


def evaluate(point):
    errors = [abs(random.gauss(0, point["noise"])) for _ in range(100)]
    return {
        "mean_error": statistics.mean(errors),
        "mean_error_err": statistics.stdev(errors) / math.sqrt(len(errors)),
    }


def run_example():
    run(Experiment("error-bars", [Sweep(
        params={}, axis_name="noise", axis_vals=[10**exponent for exponent in range(-3, 1)],
        runs=[Run(params={}, evaluator_func=evaluate)],
    )]))

if __name__ == "__main__":
    run_example()
