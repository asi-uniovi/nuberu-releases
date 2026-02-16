import pytest
from itertools import product
import pandas as pd

distributions = ["poisson", "trace"]
terminations = ["drain", "hard"]
load_balancers = ["smoothWRR", "simple"]
queue_sizes = [0, 1000]
latencies = [0, 20]

old_combinations = list(
    product(distributions, terminations, load_balancers, queue_sizes)
)
new_combinations = list(
    product(distributions, terminations, load_balancers, queue_sizes, latencies)
)


@pytest.mark.parametrize(
    "exp_name", [f"{d}_{t}_{lb}_q{q}" for d, t, lb, q in old_combinations]
)
def test_against_old_experiment_results(read_parquet_files_old, exp_name):
    """This test was ran as an intermediate step to validate the new implementation.

    It compared the results of the old implementation (results/old-30s.parquet) against
    the new one (results/current-30s.parquet)

    Those didn't match because the old implementation had some bugs that produced
    wrong costs, labelled incorrectly "drained" requests as "completed", gave some
    response_time to lost requests (should be NaN) and missed some requests during
    the draining phase.

    This test "cleans" the old results to fix the bugs, but still the results
    are not identical row-by-row because of some outliers, so this implementation
    only tests the main metrics (mean, median, max, min, std) and the status counts
    instead of each particular request
    """
    original_df, current_df = read_parquet_files_old

    exp_name_orig = exp_name
    exp_name_new = exp_name + "_l0"  # New implementation uses latency suffix
    # we compare only against the no-latency version

    # Check if the experiment exists in both DataFrames
    assert exp_name_orig in original_df["experiment"].values, (
        f"Experiment {exp_name_orig} not found in original results"
    )
    assert exp_name_new in current_df["experiment"].values, (
        f"Experiment {exp_name_new} not found in current results"
    )

    # Get the results for the specific experiment
    original_exp, current_exp = get_dataframes(original_df, current_df, exp_name)

    # Ensure ordering for fair comparison of results
    original_exp = original_exp.sort_values(
        by=["injected", "app", "container"]
    ).reset_index(drop=True)
    current_exp = current_exp.sort_values(
        by=["injected", "app", "container"]
    ).reset_index(drop=True)

    # Basic sanity check
    assert list(original_exp.columns) == list(current_exp.columns), (
        "DataFrames have different columns"
    )
    # assert original_exp.shape == current_exp.shape, (
    #    f"DataFrames have different shapes ({original_exp.shape} vs {current_exp.shape})"
    # )

    for app in original_exp.app.unique():
        original_app = original_exp[original_exp.app == app]
        current_app = current_exp[current_exp.app == app]
        assert all(
            original_app.status.value_counts() == current_app.status.value_counts()
        ), f"Status counts for {app} are different"
        assert original_app.response_time.mean() == pytest.approx(
            current_app.response_time.mean(), rel=0.01
        ), f"Mean response time for {app} is different"
        assert original_app.response_time.median() == pytest.approx(
            current_app.response_time.median(), rel=0.01
        ), f"Median response time for {app} is different"
        assert original_app.response_time.max() == pytest.approx(
            current_app.response_time.max(), rel=0.01
        ), f"Max response time for {app} is different"
        assert original_app.response_time.min() == pytest.approx(
            current_app.response_time.min(), rel=0.01
        ), f"Min response time for {app} is different"
        assert original_app.response_time.std() == pytest.approx(
            current_app.response_time.std(), rel=0.05
        ), (
            f"Std response time for {app} is different ({original_app.response_time.std()} vs {current_app.response_time.std()})"
        )

    # Deep comparison of the whole dataframes (skipped due to outliers)
    # pd.testing.assert_frame_equal(
    #     original_exp, current_exp, check_dtype=True, check_like=True
    # )


def get_dataframes(original_df, current_df, experiment_name):
    # Golden data contained meaningless values for rejected requests
    # If the requests has status rejected, end column and response_time column should be nan
    # Also it labelled drained requests as completed
    original_exp = (
        original_df[original_df["experiment"] == experiment_name]
        .copy()
        .reset_index(drop=True)
        .drop(columns=["cost", "experiment"])
    )
    current_exp = (
        current_df[current_df["experiment"] == experiment_name + "_l0"]
        .copy()
        .reset_index(drop=True)
        .drop(columns=["cost", "latency", "e2e_time", "experiment"])
    )
    original_exp.loc[original_exp.status == "rejected", "end"] = float("nan")
    original_exp.loc[original_exp.status == "rejected", "response_time"] = float("nan")
    original_exp.loc[original_exp.status == "drained", "status"] = "completed"

    # In some experiments golden data missed the penultimate requerest, so
    # we need to remove it from the current data
    if len(current_exp) > len(original_exp):
        current_exp = current_exp.drop(current_exp.index[-2])

    return original_exp, current_exp


@pytest.mark.parametrize(
    "exp_name", [f"{d}_{t}_{lb}_q{q}_l{lat}" for d, t, lb, q, lat in new_combinations]
)
def test_against_simul2026_results(read_parquet_files, exp_name):
    """This test compares the new golden data (original-30s.parquet) against
    the new data (current-30s.parquet)
    """
    original_df, current_df = read_parquet_files

    # Check if the experiment exists in both DataFrames
    assert exp_name in original_df["experiment"].values, (
        f"Experiment {exp_name} not found in original results"
    )
    assert exp_name in current_df["experiment"].values, (
        f"Experiment {exp_name} not found in current results"
    )

    # Get the results for the specific experiment
    original_exp = (
        original_df[original_df["experiment"] == exp_name].copy().reset_index(drop=True)
    )
    current_exp = (
        current_df[current_df["experiment"] == exp_name].copy().reset_index(drop=True)
    )

    # Ensure ordering for fair comparison of results
    original_exp = original_exp.sort_values(
        by=["injected", "app", "container"]
    ).reset_index(drop=True)
    current_exp = current_exp.sort_values(
        by=["injected", "app", "container"]
    ).reset_index(drop=True)

    # Basic sanity check
    assert list(original_exp.columns) == list(current_exp.columns), (
        "DataFrames have different columns"
    )

    # Deep comparison of the whole dataframes (skipped due to outliers)
    pd.testing.assert_frame_equal(
        original_exp, current_exp, check_dtype=True, check_like=True
    )
