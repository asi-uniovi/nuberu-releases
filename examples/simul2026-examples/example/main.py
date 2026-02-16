"""
nuberu/cli.py
-------------  Small but production-ready command-line interface
Usage
-----
$ nuberu-run --help
$ nuberu-run config.yml           # run and drain
$ nuberu-run config.yml -H        # hard-stop at stop_time
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pydantic import ValidationError

from nuberu import Simulation, SimulationBuilder

_LOGGER = logging.getLogger("nuberu.cli")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="nuberu-run",
        description="Run a Nuberu simulation from a YAML config file",
    )
    parser.add_argument(
        "config",
        type=Path,
        help="Path to a simulation YAML file",
    )
    parser.add_argument(
        "-S",
        "--seed",
        type=int,
        default=None,
        help="Override the seed declared in the YAML",
    )
    parser.add_argument(
        "-H",
        "--hard-stop",
        action="store_true",
        help="Stop immediately at stop_time (skip draining)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:  # pragma: no cover
    """CLI entry-point called by ``python -m nuberu.cli`` or console-script."""
    args = _parse_args(argv or sys.argv[1:])
    try:
        builder = SimulationBuilder(args.config)
    except (FileNotFoundError, ValidationError) as exc:
        _LOGGER.error("Invalid configuration: %s", exc)
        sys.exit(1)

    # Optional seed override
    if args.seed is not None:
        builder.cfg.simulation.seed = args.seed

    # Hard stop must disable draining; otherwise we keep waiting for slow requests
    if args.hard_stop:
        builder.set_drain_mode(False)

    sim: Simulation = builder.build()

    sim.run()


if __name__ == "__main__":  # pragma: no cover
    main()
