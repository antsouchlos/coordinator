import argparse

import numpy as np
from coordinator import Experiment, Run, Sweep, run


def evaluate(params):
    errors = np.random.normal(scale=params["sigma"], size=params["num_samples"])
    return {"MSE": np.mean(errors**2)}


def main():
    # Parse command line arguments

    parser = argparse.ArgumentParser()
    parser.add_argument("--num-samples", type=int, required=True)
    parser.add_argument(
        "--sigmas",
        type=float,
        nargs=3,
        metavar=("START", "STOP", "STEP"),
        required=True,
    )
    args = parser.parse_args()

    sigma_start, sigma_stop, sigma_step = args.sigmas
    sigmas = np.arange(sigma_start, sigma_stop, sigma_step)

    # Run experiment

    experiment = Experiment(
        "command-line-parameters",
        [
            Sweep(
                params={"num_samples": args.num_samples},
                axis_name="sigma",
                axis_vals=sigmas,
                runs=[Run(params={}, evaluator_func=evaluate)],
            )
        ],
    )
    run(experiment)


if __name__ == "__main__":
    main()
