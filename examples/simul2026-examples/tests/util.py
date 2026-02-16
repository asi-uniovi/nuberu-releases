import subprocess
from pathlib import Path


def regenerate_parquet():
    repo_root = Path(__file__).resolve().parent.parent
    scripts_dir = repo_root / "scripts"
    configs_dir = repo_root / "configs"
    tests_dir = repo_root / "tests"
    # logs_dir = repo_root / "logs"  # unused
    metrics_dir = repo_root / "metrics"
    metrics_dir.mkdir(exist_ok=True)

    # 1. Regenerate YAMLs
    result = subprocess.run(
        ["uv", "run", "scripts/gen_yamls_jinja.py", "30"],
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "gen_yamls_exps_nuberu.py failed with exit code {}".format(
                result.returncode
            )
        )

    # 2. Move yamls to the place where the run_experiments.py script expects them
    for yaml in scripts_dir.glob("config*yaml"):
        yaml.rename(configs_dir / yaml.name)

    # 3. Run experiments
    result = subprocess.run(
        ["uv", "run", "scripts/run_experiments.py"],
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "run_experiments.py failed with exit code {}".format(result.returncode)
        )

    # 4. Generate parquet file
    result = subprocess.run(
        ["uv", "run", "scripts/gen_parquet_from_monitor_dump.py", "metrics"],
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "gen_parquet.py failed with exit code {}".format(result.returncode)
        )

    # 5. Move yamls and parquet to the tests directory
    # Move the original results
    parquet = metrics_dir / "combined_results.parquet"
    parquet.rename(tests_dir / "results" / "current-30s.parquet")
    for yaml in configs_dir.glob("config*yaml"):
        yaml.rename(tests_dir / "configs" / "current-30s" / yaml.name)


if __name__ == "__main__":
    regenerate_parquet()
    print("Parquet files and configs regenerated successfully.")
