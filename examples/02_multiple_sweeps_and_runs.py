import numpy as np
from coordinator import Experiment, Run, Sweep, run


def evaluate_arithmetic_mean(params) -> dict:
    errors = []

    for _ in range(10000):
        mean = params["mean"]

        if params["noise"] == "gaussian":
            samples = mean + np.random.normal(scale=params["sigma"], size=100)
        elif params["noise"] == "laplace":
            samples = mean + np.random.laplace(scale=params["sigma"], size=100)
        else:
            raise RuntimeError("Unknown noise type")

        mean_estimate = np.mean(samples)
        errors.append(mean - mean_estimate)

    mean_square_error = np.mean(np.array(errors) ** 2)
    return {"MSE": mean_square_error}


experiment = Experiment(
    "multiple-sweeps-and-runs",
    [
        Sweep(
            params={"mean": 5},
            axis_name="sigma",
            axis_vals=[0.5, 1, 2, 3],
            runs=[
                Run({"noise": "gaussian"}, evaluate_arithmetic_mean),
                Run({"noise": "laplace"}, evaluate_arithmetic_mean),
            ],
        ),
        Sweep(
            params={"sigma": 1},
            axis_name="mean",
            axis_vals=[-2, -1, 1, 2],
            runs=[
                Run({"noise": "gaussian"}, evaluate_arithmetic_mean),
                Run({"noise": "laplace"}, evaluate_arithmetic_mean),
            ],
        ),
    ],
)

run(experiment)
