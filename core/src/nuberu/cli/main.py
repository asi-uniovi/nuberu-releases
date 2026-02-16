import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List

import click
import pydantic
import yaml
from click_aliases import ClickAliasedGroup

from nuberu.core.simulation_builder import SimulationBuilder
from nuberu.core.simulation_config import SimulationConfig
from nuberu.plugins.plugin_manager import PluginManager

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _collect_required_plugins(cfg: SimulationConfig) -> Dict[str, List[str]]:
    """Return the *include* map expected by PluginManager.load_plugins()."""

    def _maybe_plugin(config_obj) -> List[str]:
        """Extract plugin_name if mode is 'plugin' and plugin_name exists"""
        if hasattr(config_obj, "mode") and config_obj.mode == "plugin":
            return (
                [config_obj.plugin_name]
                if hasattr(config_obj, "plugin_name") and config_obj.plugin_name
                else []
            )
        return []

    include: Dict[str, List[str]] = {
        "infrastructure": _maybe_plugin(cfg.infrastructure),
        "performance": _maybe_plugin(cfg.performance_data),
        "allocation": _maybe_plugin(cfg.allocation),
        "load_balancer": _maybe_plugin(cfg.load_balancer),
        "distribution": [
            wl.distribution.plugin_name
            for wl in cfg.workloads
            if hasattr(wl.distribution, "plugin_name") and wl.distribution.plugin_name
        ],
        "cost_model": [cm.plugin_name for cm in cfg.cost_models],
        "runtime_model": (
            ([cfg.runtime_model.plugin_name] if cfg.runtime_model is not None else [])
            + [rm.plugin_name for rm in cfg.runtime_models.values()]
        ),
        "workload": [
            wl.distribution.workloads_plugin_name
            for wl in cfg.workloads
            if getattr(wl.distribution, "workloads_plugin_name", None)
        ],
    }
    # Remove empty lists to keep PluginManager happy
    return {t: names for t, names in include.items() if names}


def _validate_plugins(cfg_path: Path, extra_dirs: List[Path]) -> None:
    """Check that every plugin referenced in *cfg_path* is importable."""

    raw_cfg: Dict[str, Any] = yaml.safe_load(cfg_path.read_text())
    cfg = SimulationConfig.model_validate(
        raw_cfg, context={"base_dir": cfg_path.parent}
    )

    include = _collect_required_plugins(cfg)

    pm = PluginManager()
    for d in extra_dirs:
        pm.add_search_path(d)
    pm.load_plugins(include=include)

    missing: List[str] = []
    registered = pm.list_registered_plugins()
    for comp_type, names in include.items():
        for name in names:
            if name not in registered.get(comp_type, []):
                missing.append(f"{comp_type}:{name}")

    if missing:
        plural = "s" if len(missing) > 1 else ""
        raise click.ClickException(
            f"Missing plugin{plural}: "
            + f"{', '.join(sorted(missing))}"
            + "\n-> Install the corresponding package(s) or use --plugin-dir."
        )


# ---------------------------------------------------------------------------
# Root CLI group
# ---------------------------------------------------------------------------


@click.group(cls=ClickAliasedGroup)
@click.option(
    "--plugin-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    multiple=True,
    help="Additional directory to search for local plugins (can be repeated).",
)
@click.pass_context
def cli(ctx: click.Context, plugin_dir: tuple[Path, ...]) -> None:
    """Nuberu command-line interface."""

    ctx.ensure_object(dict)
    ctx.obj["plugin_dirs"] = list(plugin_dir)


# ---------------------------------------------------------------------------
#  nuberu-cli run <config.yaml>
# ---------------------------------------------------------------------------


@cli.command(
    "run",
    aliases=["r"],
    short_help="Run a simulation from a configuration file",
)
@click.argument("config", type=click.Path(exists=True, path_type=Path))
@click.option("--seed", type=int, help="Override simulation random seed.")
@click.option(
    "-v", "--verbose", count=True, help="Increase verbosity (-v=lenient, -vv=debug)."
)
@click.option(
    "--log-level",
    type=click.Choice(
        ["none", "debug", "info", "warning", "error", "critical", "full"],
        case_sensitive=False,
    ),
    help="Logging level: none (disable all), full/debug (verbose), info (default), warning, error, critical.",
)
@click.option(
    "--no-console-log",
    is_flag=True,
    help="Disable console logging (file only).",
)
@click.option(
    "--no-file-log",
    is_flag=True,
    help="Disable file logging (console only).",
)
@click.option(
    "--hard-stop/--drain",
    default=False,
    help="Stop immediately at stop_time instead of draining pending requests.",
)
@click.pass_context
def run_cmd(
    ctx: click.Context,
    config: Path,
    seed: int | None,
    verbose: int,
    log_level: str | None,
    hard_stop: bool,
    no_console_log: bool,
    no_file_log: bool,
) -> None:
    """Build and run a simulation from YAML *CONFIG*."""

    try:
        # 1 - Early plugin validation (avoids RuntimeWarning later)
        _validate_plugins(config, ctx.obj["plugin_dirs"])

        # 2 - Load raw YAML config and apply CLI overrides BEFORE creating builder
        # This is critical because SimulationBuilder.__init__() calls _setup_logging()
        # which would otherwise use the original config values, ignoring CLI flags.
        raw_cfg = yaml.safe_load(config.read_text())

        # Apply CLI overrides to raw config (priority: CLI > YAML > defaults)
        if "logging" not in raw_cfg:
            raw_cfg["logging"] = {}

        # Priority: log_level > verbose
        if log_level:
            raw_cfg["logging"]["level"] = log_level.lower()
        elif verbose:
            raw_cfg["logging"]["level"] = "info" if verbose == 1 else "debug"

        # Apply console/file logging flags
        if no_console_log:
            raw_cfg["logging"]["log_to_console"] = False

        if no_file_log:
            raw_cfg["logging"]["log_to_file"] = False

        # Apply seed override
        if seed is not None:
            if "simulation" not in raw_cfg:
                raw_cfg["simulation"] = {}
            raw_cfg["simulation"]["seed"] = seed

        # 3 - Build the Simulation with merged config
        # Pass config.parent as base_dir so relative paths resolve from YAML location
        builder = SimulationBuilder(raw_cfg, base_dir=config.parent)

        # Propagate stop policy to the simulation config before building (CLI wins)
        builder.set_drain_mode(not hard_stop)

        mode = "hard-stop" if hard_stop else "drain"
        click.secho(f"Simulation mode: {mode}", fg="cyan")

        sim = builder.build()
        sim.run()
        click.secho("Simulation completed", fg="green")

    except click.ClickException:
        # Let Click-specific errors propagate unchanged
        raise
    except Exception as exc:
        # Secondary safety-net: silence *unawaited coroutine* warning when aborting
        warnings.filterwarnings(
            "ignore", category=RuntimeWarning, message="coroutine .* was never awaited"
        )
        raise click.ClickException(str(exc))


# ---------------------------------------------------------------------------
#  nuberu-cli validate <config.yml>
# ---------------------------------------------------------------------------


@cli.command(
    "validate",
    aliases=["val", "check"],
    short_help="Validate a simulation configuration file",
)
@click.argument("config", type=click.Path(exists=True, path_type=Path))
@click.pass_context
def validate_cmd(ctx: click.Context, config: Path) -> None:
    """
    Validate the YAML file in two steps:

    1.  Make sure the file is syntactically correct and complies with
        the SimulationConfig schema.
    2.  Check that every plugin referenced in the configuration is import-able.

    The command exits with status 0 on success, otherwise prints the
    reason and returns exit 1.
    """
    errors: list[str] = []
    # ------------------------------------------------------------------
    # 1 - YAML + schema validation
    # ------------------------------------------------------------------
    try:
        raw_cfg: dict[str, Any] = yaml.safe_load(config.read_text())
        # Use the parent directory as *base_dir* so relative paths are resolved
        SimulationConfig.model_validate(raw_cfg, context={"base_dir": config.parent})
        click.secho("Configuration valid", fg="green")
    except pydantic.ValidationError as exc:
        # If the YAML is invalid or does not match the schema, raise a Click exception
        errors.append(f"YAML/schema error: {exc}")

    # ------------------------------------------------------------------
    # 2 - Plugin validation
    # ------------------------------------------------------------------
    try:
        _validate_plugins(config, ctx.obj["plugin_dirs"])
        click.secho("All required plugins are available", fg="green")
    except click.ClickException as exc:
        # Re-raise plugin-related Click errors unchanged so Click handles them
        errors.append(str(exc))

    except Exception as exc:
        # Any other exception means the configuration is invalid
        errors.append(f"Plugin validation error: {exc}")

    if errors:
        click.secho("\nFound problem(s):", fg="red")
        for msg in errors:
            click.echo(f" - {msg}")
        sys.exit(1)


@cli.command(
    "progress",
    aliases=["p"],
    short_help="Monitor a log file and display a progress bar",
)
@click.argument("logfile", type=click.Path(exists=False, path_type=Path))
@click.argument("total", type=int)
def progress_cmd(logfile: Path, total: int) -> None:
    """
    Monitor a log file and display a progress bar.

    Args:
        logfile: Path to the log file to monitor.
        total: Final expected value of the number inside square brackets.
    """
    import re
    import time

    from rich.progress import (
        BarColumn,
        Progress,
        TimeElapsedColumn,
        TimeRemainingColumn,
    )

    pat = re.compile(r"\[(\d+(?:\.\d+)?)\]")  # Accepts int or float

    with Progress(
        "[progress.description]{task.description}",
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        refresh_per_second=5,
    ) as bar:
        t = bar.add_task("Processing", total=total)
        while not logfile.exists():
            time.sleep(0.2)  # Wait for the file to exist
        with open(logfile, "r", encoding="utf-8") as f:
            while not bar.finished:
                line = f.readline()
                if not line:  # No new line yet
                    time.sleep(0.5)
                    continue
                m = pat.match(line)
                if m:
                    bar.update(t, completed=min(float(m.group(1)), total))


@cli.command(
    name="version",
    aliases=["v"],
    short_help="Show nuberu versions",
)
def version_cmd() -> None:
    """Show Nuberu-CLI, framework, Python and platform versions."""
    import importlib.metadata as im
    import platform

    def dist_version(dist_name: str) -> str:
        """Return the installed version of *dist_name* or '(unknown)'."""
        try:
            return im.version(dist_name)
        except im.PackageNotFoundError:
            return "(unknown)"

    cli_version = dist_version("nuberu-cli")
    fw_version = dist_version("nuberu")

    click.echo(f"Nuberu-CLI version: {cli_version}")
    click.echo(f"Framework version : {fw_version}")
    click.echo(f"Python            : {platform.python_version()}")
    click.echo(f"Platform          : {platform.platform()}")


if __name__ == "__main__":  # pragma: no cover
    cli()
