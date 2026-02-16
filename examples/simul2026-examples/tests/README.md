
## Description

The folder tests contains:

- `configs/ `
    - `originals-30s/`

        This folder contains all yaml used for the tests in the paper, but 
        limiting the simulation to 30s to get shorter logs and faster 
        comparisons of results

   - `current-30s/`

        This folder contains all yaml for the same experiments, but using
        the new config syntax, which can be used with the current nuberu
        implementation

- `results/`

   This folder contains two .parquet files, containing the results of
   all the simulations. These files can be loaded in pandas to generate plots,
   tables, and statistics about each experiment result

   There is one parquet file for the old experiments in the 2025 paper, 
   another one for the new experiments in the 2026 paper, and the one for
   the current experiments ran by the tests

`test_compare_results.py` is a set of parametrized tests that compare the
dataframes of each experiment.

## Workflow

Use `uv run pytest` to run the tests, without regenerating the data files.
This only compares the results in the parquet files.

To force running the set of 16 experiments and regenerate the parquet files,
use:

```bash
uv run pytest --regenerate
```

This will overwrite the files in `configs/current-30s/` with the new yaml used,
and the file `results/current-30s.parquet` with the new results. After this,
it will run the tests that compare the results.

