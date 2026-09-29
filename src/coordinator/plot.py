"""
Plot a metric over the swept axis for one or more run directories.

    coordinator-plot results/<experiment>/*/* --y LER --yerr LER_3sigma --logy

Paths without a `data.csv` (e.g. `source.patch`, unfinished runs) are skipped.
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def build_labels(run_dirs: list[Path]) -> list[str]:
    labels = [run_dir.name.split("@")[0] for run_dir in run_dirs]
    if len(set(labels)) == len(labels):
        return labels

    return [f"{run_dir.parent.name}/{run_dir.name}" for run_dir in run_dirs]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--y", required=True, help="column to plot")
    parser.add_argument("--yerr", help="column holding the error bar half-widths")
    parser.add_argument("--logx", action="store_true")
    parser.add_argument("--logy", action="store_true")
    args = parser.parse_args()

    run_dirs = [path for path in args.paths if (path / "data.csv").exists()]
    for path in sorted(set(args.paths) - set(run_dirs)):
        print(f"skipping {path}: no data.csv", file=sys.stderr)
    if not run_dirs:
        sys.exit("no run directories with data.csv given")

    plt.figure()
    axis = None

    for run_dir, label in zip(run_dirs, build_labels(run_dirs)):
        data = pd.read_csv(run_dir / "data.csv")
        with open(run_dir / "meta.json") as handle:
            run_axis = json.load(handle)["axis"]

        if axis is not None and run_axis != axis:
            raise ValueError(f"runs sweep different axes: {axis} and {run_axis}")
        axis = run_axis

        data = data.sort_values(axis)
        plt.errorbar(
            data[axis],
            data[args.y],
            yerr=data[args.yerr] if args.yerr else None,
            marker="o",
            capsize=4,
            label=label,
        )

    plt.xlabel(axis)
    plt.ylabel(args.y)
    if args.logx:
        plt.xscale("log")
    if args.logy:
        plt.yscale("log")
    plt.grid(True, which="both", alpha=0.3)
    plt.legend()
    plt.show()


if __name__ == "__main__":
    main()
