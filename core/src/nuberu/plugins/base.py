"""Base class for Nuberu plugins providing automatic hierarchical logger setup."""

import logging
from typing import ClassVar


class PluginBase:
    """
    Base class for all Nuberu plugins.

    Provides automatic hierarchical logger setup based on the plugin_name
    class attribute. Plugins should inherit from this class and define their
    plugin_name (without the "plugins." prefix).

    Example:
        >>> class MyPlugin(PluginBase):
        ...     plugin_name = "conlloovia"  # Just the plugin name, no prefix
        ...
        ...     def some_method(self):
        ...         self.logger.debug("Debug message")
        ...         self.logger.info("Info message")

    The logger will be created with the full namespace "nuberu.plugins.{plugin_name}",
    allowing fine-grained control via configuration:

        logging:
          component_levels:
            plugins.conlloovia: debug
    """

    # Subclasses MUST override this with their plugin name (without "plugins." prefix)
    # Example: "conlloovia" for the conlloovia data provider plugin
    plugin_name: ClassVar[str] = ""

    def __init__(self):
        """Initialize the plugin with a hierarchical logger."""
        if not self.plugin_name:
            # Fallback: derive from class name if plugin_name not set
            class_name = self.__class__.__name__.lower().replace("plugin", "")
            logging.getLogger("nuberu.plugins").warning(
                f"Plugin {self.__class__.__name__} does not define plugin_name. "
                f"Using fallback: {class_name}. Please set plugin_name class attribute."
            )
            plugin_name = class_name
        else:
            plugin_name = self.plugin_name

        # Create hierarchical logger: nuberu.plugins.{plugin_name}
        # The "nuberu.plugins." prefix is automatically added here
        self._logger = logging.getLogger(f"nuberu.plugins.{plugin_name}")

    @property
    def logger(self) -> logging.Logger:
        """Get the plugin's hierarchical logger."""
        return self._logger
