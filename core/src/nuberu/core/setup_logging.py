import logging
import os
import sys
from datetime import datetime
from typing import Callable

from colorama import Back, Fore, Style
from colorama import init as colorama_init

colorama_init(autoreset=True)

# ==============================================================================
# CONSTANTS
# ==============================================================================

LOG_COLORS = {
    "DEBUG": Fore.MAGENTA,
    "INFO": Fore.CYAN,
    "WARNING": Fore.YELLOW + Style.BRIGHT,
    "ERROR": Fore.RED + Style.BRIGHT,
    "CRITICAL": Fore.RED + Back.WHITE + Style.BRIGHT,
}

# Map user-friendly level names
LEVEL_MAP = {
    "debug": "DEBUG",
    "info": "INFO",
    "warning": "WARNING",
    "error": "ERROR",
    "critical": "CRITICAL",
    "full": "DEBUG",  # Alias for debug
}

# ==============================================================================
# SIMULATION TIME MANAGEMENT
# ==============================================================================


# Tiempo simulado (env.now) -> se inyecta externamente
def _sim_time_getter() -> float:
    return -1


def set_sim_time_getter(getter: Callable[[], int | float]) -> None:
    """Set the function that provides simulation time for log prefixes."""
    global _sim_time_getter
    _sim_time_getter = getter


class SimTimeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        sim_time = _sim_time_getter()
        sim_prefix = f"[{sim_time}]".ljust(5)
        base_msg = super().format(record)
        return f"{sim_prefix} {base_msg}"


class ColorSimFormatter(SimTimeFormatter):
    """Formatter that adds colors to log messages based on level."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        color = LOG_COLORS.get(record.levelname, "")
        return f"{color}{base}{Style.RESET_ALL}" if sys.stdout.isatty() else base


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================


def _disable_all_logging() -> None:
    """Completely disable all logging output."""
    root_logger = logging.getLogger()
    logging.disable(logging.CRITICAL)
    root_logger.setLevel(logging.CRITICAL + 1)

    # Disable all existing loggers
    for name in list(logging.Logger.manager.loggerDict.keys()):
        logger_obj = logging.getLogger(name)
        logger_obj.disabled = True
        logger_obj.setLevel(logging.CRITICAL + 1)

    # Add NullHandler to prevent Python's lastResort handler from writing to stderr
    root_logger.handlers.clear()
    root_logger.addHandler(logging.NullHandler())

    # Patch getLogger to disable future loggers created by plugins
    original_getLogger = logging.getLogger

    def patched_getLogger(name=None):
        logger = original_getLogger(name)
        logger.disabled = True
        logger.setLevel(logging.CRITICAL + 1)
        return logger

    logging.getLogger = patched_getLogger  # type: ignore


def _create_console_handler(format_string: str) -> logging.Handler:
    """Create and configure a console (stdout) handler with colored output."""
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ColorSimFormatter(format_string))
    return console_handler


def _create_file_handler(
    output_path: str, log_file_name: str, format_string: str
) -> logging.Handler:
    """Create and configure a file handler with log header."""
    os.makedirs(output_path, exist_ok=True)
    log_path = os.path.join(output_path, log_file_name)

    # Get version for log headers
    try:
        from .. import __version__
    except ImportError:
        __version__ = "unknown"

    # Write professional header first
    separator = "=" * 80
    header = (
        f"{separator}\n"
        f"Nuberu Simulation Framework v{__version__}\n"
        f"Log started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{separator}\n\n"
    )

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(header)

    # Now open in append mode for logging
    file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    file_handler.setFormatter(SimTimeFormatter(format_string))
    return file_handler


# ==============================================================================
# PUBLIC API
# ==============================================================================


def setup_logging(
    level: str = "DEBUG",
    log_to_file: bool = True,
    output_dir: str = "./logs/",
    log_file_name: str = "nuberu.log",
    force_reconfigure: bool = False,
    console_enabled: bool = True,
    component_levels: dict[str, str] | None = None,
) -> None:
    """Configure logging for the simulation framework.

    Args:
        level: Logging level ('none', 'debug', 'info', 'warning', 'error', 'critical', 'full')
        log_to_file: Whether to log to a file
        output_dir: Directory for log files
        log_file_name: Name of the log file
        force_reconfigure: If True, reconfigures even if handlers already exist
        console_enabled: If True, enable console logging
        component_levels: Optional dict mapping component names to their specific log levels.
                         Example: {"workload": "debug", "allocation": "info", "cost_model": "warning"}
                         This allows fine-grained control over component-specific logging.
    """
    # Special case: disable all logging completely
    level_lower = level.lower()
    if level_lower == "none":
        _disable_all_logging()
        return

    # Normalize the level name
    level_normalized = LEVEL_MAP.get(level_lower, level.upper())

    # Get root logger
    root_logger = logging.getLogger()

    # Check if logging handlers are already configured (unless force_reconfigure is True)
    if not force_reconfigure and root_logger.hasHandlers():
        return

    # Clear existing handlers if reconfiguring
    if force_reconfigure:
        root_logger.handlers.clear()

    # Set logging level
    level_value = getattr(logging, level_normalized, logging.INFO)
    root_logger.setLevel(level_value)

    # Define format string
    format_string = "%(levelname)-8s %(name)-12s %(message)s"

    # Track if we added any handler
    has_handlers = False

    # Add console handler if enabled
    if console_enabled:
        root_logger.addHandler(_create_console_handler(format_string))
        has_handlers = True

    # Add file handler if enabled
    if log_to_file:
        root_logger.addHandler(
            _create_file_handler(output_dir, log_file_name, format_string)
        )
        has_handlers = True

    # If no handlers were added, add NullHandler to prevent default stderr output
    if not has_handlers:
        root_logger.addHandler(logging.NullHandler())

    # Configure component-specific log levels if provided
    if component_levels:
        for component, comp_level in component_levels.items():
            comp_level_normalized = LEVEL_MAP.get(
                comp_level.lower(), comp_level.upper()
            )
            comp_level_value = getattr(logging, comp_level_normalized, logging.DEBUG)

            # This works if components use loggers like 'nuberu.component_name'
            component_logger = logging.getLogger(f"nuberu.{component}")
            component_logger.setLevel(comp_level_value)


def setup_logging_from_config(config: dict | None = None) -> None:
    """Configure logging from a configuration dictionary.

    Args:
        config: Configuration dictionary with keys: level, log_to_file, log_to_console,
                output_path, log_file_name, component_levels. If None, uses default values.

                Example config:
                {
                    "level": "critical",
                    "log_to_file": True,
                    "log_to_console": True,
                    "output_path": "./logs/",
                    "log_file_name": "nuberu.log",
                    "component_levels": {
                        "workload": "debug",
                        "allocation": "info"
                    }
                }
    """
    cfg = config or {}
    setup_logging(
        level=cfg.get("level", "full"),
        log_to_file=cfg.get("log_to_file", False),
        console_enabled=cfg.get("log_to_console", True),
        output_dir=cfg.get("output_path", "./logs/"),
        log_file_name=cfg.get("log_file_name", "nuberu.log"),
        component_levels=cfg.get("component_levels"),
    )
