# Coordinator

A simulation managemenet framework.
`coordinator` structures simulations based on `experiments`, `attempts`,
`sweeps` and `runs`. For example:

```text
Experiment: Estimation of the expected value
├── Attempt 1: arithmetic mean
│   ├── Sweep 1: sigma = 0.5, 1, 2, 3; outliers = 5%
│   │   ├── Run A: Gaussian ordinary noise
│   │   └── Run B: Laplace ordinary noise
│   └── Sweep 2: outliers = 0%, 5%, 10%, 20%; sigma = 1
│       ├── Run A: Gaussian ordinary noise
│       └── Run B: Laplace ordinary noise
└── Attempt 2: median
    ├── Sweep 1: sigma = 0.5, 1, 2, 3; outliers = 5%
    │   ├── Run A: Gaussian ordinary noise
    │   └── Run B: Laplace ordinary noise
    └── Sweep 2: outliers = 0%, 5%, 10%, 20%; sigma = 1
        ├── Run A: Gaussian ordinary noise
        └── Run B: Laplace ordinary noise
```

- A `run` contains the datapoints corresponding to one curve plotted over
  the sweeped variable.
- A `sweep` is a collection of runs sweeped over the same variable, with
  different parameters each time.
- An `attempt` is one instance of trying out some modification of the
  algorithm being simulated. An attempt may include multiple sweeps.
- An `experiment` groups several attempts.

New datapoints are appended to existing results and the resimulation of points
that already exist is skipped.
IDs are assigned when an `Experiment` is constructed. Construct a new
`Experiment` after changing its parameters, axis values, or Git revision.

## Usage

```py
from coordinator import Run, Sweep, Experiment, run


def evaluator_func(params):
    pass


experiment = Experiment(
    "some_experiment",
    [
        Sweep(
            params={"b": 3},
            axis_name="c",
            axis_vals=[1, 2, 3],
            runs=[
                Run(params={"a": 1}, evaluator_func=evaluator_func),
                Run(params={"a": 2}, evaluator_func=evaluator_func),
                Run(params={"a": 3}, evaluator_func=evaluator_func),
            ],
        )
    ],
)

run(experiment)
```

More extensive examples can be found in the `examples/` directory.

## Browse results in JupyterLab

Copy `notebooks/results_browser.ipynb` into your project and run it to inspect and plot runs.

## Storing Simulation Results

Results are identified by IDs that depend on several inputs such as
simulation parameters, git commit hashes, etc., as visualized in the block
diagram below.
If any of the inputs to one of the blocks change, this and all subsequent
blocks' IDs also change, ensuring all relevant datapoints are resimulated
under the new parameters.

```text
                          +-----------------+
git HEAD commit hash ---> |                 |
git source patch -------> |   Attempt ID    |
   (files tracked by      |                 |
   coordinator only)      +--------+--------+
                                   |
                                   v
                          +-----------------+
Axis name --------------> |                 |
Axis values ------------> |    Sweep ID     |
Sweep params -----------> |                 |
                          +--------+--------+
                                   |
                                   v
                          +-----------------+
                          |                 |
Run params -------------> |     Run ID      |
                          |                 |
                          +-----------------+
```

The results are stored according to the scheme below.
Attempts can be labeled with `NEW_ATTEMPT_NAME`; sweep and run labels can be
changed in the results browser. Labels use a `<label>@` directory prefix.
Note, however, that the labels are purely cosmetic and don't influence the ID
or resimulation behavior.

```text
results/
└── <experiment_name>/
     └── [<label>@]<attempt_id>/
           ├── source.patch  # Only when the worktree is dirty
           └── [<label>@]<sweep_id>/
                  └── [<label>@]<run_id>/
                        ├── data.csv
                        └── metadata.json
```
