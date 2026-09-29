# Loading results into a DataFrame for a custom plot.
# Run examples/02_compare_runs.py first.
#
#   python examples/05_load_results.py

import matplotlib.pyplot as plt

from coordinator import load_experiment_runs


def main():
    data = load_experiment_runs("compare-runs")

    for label, run in data.groupby("label"):
        run = run.sort_values("noise")
        plt.plot(run["noise"], run["mean_error"], marker="o", label=label)

    plt.xlabel("noise")
    plt.ylabel("mean_error")
    plt.legend()
    plt.show()


if __name__ == "__main__":
    main()
