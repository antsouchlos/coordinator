# coordinator

Generic simulation and plotting utilities.

- Results are stored as CSV files with their respective parameters
- Points that have already been computed are skipped
- Results are organized by commit and when generated from a dirty git commit,
  patches are stored alongside them

Results directory structure:
```
results/<experiment>/[<attempt>@]<commit>[-dirty_<patch_hash>]/
    source.patch           # only when the worktree was dirty
    <label>@<identity_hash>/
        data.csv
        meta.json
```

`attempt` is taken from the `NEW_ATTEMPT_NAME` environment variable, if set.
It is only used when a new revision directory is created. If a directory
for the current revision already exists, results are added to it regardless of
the environment variable value.

```bash
NEW_ATTEMPT_NAME=first-try python simulate.py
```

The commit in the directory name is always the current Git `HEAD`. To limit
which uncommitted changes add a `-dirty_<hash>` suffix and appear in
`source.patch`, create `.coordinatorinclude` at the repository root. Changes
to `.coordinatorinclude` itself always count as dirty changes.

```gitignore
src/simulation/**
configs/**
!configs/generated/**
```

## Installation

```sh
git clone <repository-url>
pip install .
```

## Usage

More extensive examples can be found in the `examples/` directory.

```python
import random
from coordinator import Run, sweep

def evaluate(point):
    errors = [abs(random.gauss(0, point["noise"])) for _ in range(1000)]
    return {"mean_error": sum(errors) / len(errors)}

sweep(
    [Run("gaussian", evaluate)],
    axis="noise",
    axis_values=[0.1, 0.2, 0.5, 1.0],
    experiment="error-over-noise",
)
```

## Browse results in JupyterLab

Copy `notebooks/results_browser.ipynb` into your project and run it to inspect and plot runs.
