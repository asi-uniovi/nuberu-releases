"""
nuberu_plugin_runtime_model_simple
===================================

A simple runtime model plugin for the Nuberu cloud simulation framework.

This plugin provides a basic runtime model that handles request processing,
queueing, and service time computation for containers in the simulation.
"""

from .plugin import RuntimeModelSimple, RuntimeModelPlugin

__all__ = ["RuntimeModelSimple", "RuntimeModelPlugin"]
__version__ = "0.1.0"
