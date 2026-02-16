# SIMUL2026 examples

This folder contains the code required to replicate the experiments in the 2026 paper, and some integration tests to ensure that the results are consistent with pre-stored ones.

## Instructions

### Setup

Use `uv` to manage dependencies, and to run the examples and tests:

```
uv venv
uv install
```

To run one example:

```
uv run python example/main.py configs/example.yaml
```

### Running all paper examples

To run all paper examples:

1. Ensure that all required .yaml are in the `configs/` folder, or re-create them by running the following command (3600 is the duration of each simulation in seconds):

    ```
    uv run python scripts/gen_yamls_jinja.py 3600
    ```

    This script uses jinja2 to fill in the template `base_template.yaml.j2` with the required parameters for each experiment. This template is currently using the syntax for the 2.1 version of the configuration files.

2. From the `examples/simul2026-examples/` folder, run:

    ```
    uv run python scripts/run_experiments.py
    ```

    This will launch as many experiments in parallel as there are CPU cores, each corresponding to one of the paper's experiments, and leave the logs of each simulation in folder `logs/`.

3. Collect all logs into a single parquet file, amenable for later analysis:

    ```
    uv run python scripts/gen_parquet_from_monitor_dump.py metrics/
    ```

    This will create a file `combined_results.parquet` in the specified metrics folder.

### Running integration tests

To run the integration tests, from the `examples/simul2026-examples/` folder, run:

```
uv run pytest --regenerate
```

This will create a set of .yaml files with the experiments in the paper, except that simulation is restricted to 30s. It will create a parquet file with the results which is later compared to a pre-stored one to ensure consistency.

To run the tests without regenerating the reference results, run:

```
uv run pytest
```

