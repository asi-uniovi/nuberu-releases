import sys
from pathlib import Path
import pandas as pd
import pytest

# Get the path of the results, relative to the script directory
script_dir = Path(__file__).resolve().parent
results_path = script_dir / "results"

original_results = "originals-30s.parquet"
current_results = "current-30s.parquet"
old_results = "old-30s.parquet"


# Create a fixture to read two parquet files as pandas DataFrames
@pytest.fixture(scope="module")
def read_parquet_files():
    # Define the paths to the parquet files
    original_path = results_path / original_results
    current_path = results_path / current_results

    # Read the parquet files into pandas DataFrames
    original_df = pd.read_parquet(original_path)
    current_df = pd.read_parquet(current_path)

    return original_df, current_df


@pytest.fixture(scope="module")
def read_parquet_files_old():
    # Define the paths to the parquet files
    original_path = results_path / old_results
    current_path = results_path / current_results

    # Read the parquet files into pandas DataFrames
    original_df = pd.read_parquet(original_path)
    current_df = pd.read_parquet(current_path)

    return original_df, current_df


# Add option to regenerate parquet files and scenarios
def pytest_addoption(parser):
    parser.addoption(
        "--regenerate",
        action="store_true",
        default=False,
        help="Regenerate scenarios and parquet files from the simulator",
    )


@pytest.fixture(scope="session", autouse=True)
def maybe_regenerate_data(request):
    current_dir = Path(__file__).parent
    if str(current_dir) not in sys.path:
        sys.path.append(str(current_dir))

    from util import regenerate_parquet

    if request.config.getoption("--regenerate"):
        print("Regenerating data from the simulator...")
        regenerate_parquet()
    else:
        print("Using already generated data.")
