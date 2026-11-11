import random

from coordinator import Experiment, Run, Sweep, run


def evaluate(point):
    errors = [abs(random.gauss(0, point["noise"])) for _ in range(1000)]
    return {"mean_error": sum(errors) / len(errors)}


def run_example():
    experiment = Experiment(
        "basic",
        [Sweep(params={}, axis_name="noise", axis_vals=[0.1, 0.2, 0.5, 1.0], runs=[Run(params={}, evaluator_func=evaluate)])],
    )
    run(experiment)


if __name__ == "__main__":
    run_example()
