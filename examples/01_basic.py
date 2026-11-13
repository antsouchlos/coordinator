import numpy as np
from coordinator import Experiment, Run, Sweep, run


def evaluate(params):
    errors = np.random.normal(scale=params["sigma"], size=10000)
    return {"MSE": np.mean(errors**2)}


def main():
    experiment = Experiment(
        "basic",
        [
            Sweep(
                params={},
                axis_name="sigma",
                axis_vals=[0.1, 0.2, 0.5, 1.0],
                runs=[Run(params={}, evaluator_func=evaluate)],
            )
        ],
    )
    run(experiment)


if __name__ == "__main__":
    main()
