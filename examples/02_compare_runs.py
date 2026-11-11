import random

from coordinator import Experiment, Run, Sweep, run


def evaluate(point):
    errors = [
        abs(random.gauss(point["bias"], point["noise"]))
        for _ in range(point["samples"])
    ]
    return {"mean_error": sum(errors) / len(errors)}


def run_example():
    run(Experiment("compare-runs", [Sweep(
        params={"bias": 0.1}, axis_name="noise", axis_vals=[0.1, 0.2, 0.5, 1.0],
        runs=[Run(params={"samples": 10}, evaluator_func=evaluate),
              Run(params={"samples": 1000}, evaluator_func=evaluate)],
    )]))

if __name__ == "__main__":
    run_example()
