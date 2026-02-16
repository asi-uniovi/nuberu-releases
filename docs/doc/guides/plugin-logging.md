# Plugin Logging Guide

> How to implement hierarchical logging in your Nuberu plugin.

## Quick Start

### 1. Inherit from `PluginBase`

```python
from nuberu.plugins import PluginBase

class MyPlugin(PluginBase):
    plugin_name = "my_plugin"  # Logger: nuberu.plugins.my_plugin
    
    def __init__(self):
        super().__init__()  # Required — sets up self.logger
    
    def some_method(self):
        self.logger.debug("Detailed trace information")
        self.logger.info("Notable event occurred")
        self.logger.warning("Something unexpected")
        self.logger.error("An error occurred")
```

### 2. Set `plugin_name` Correctly

The `plugin_name` attribute should be just your plugin's name — the `"nuberu.plugins."` prefix is added automatically:

- Correct: `plugin_name = "my_plugin"`
- Wrong: `plugin_name = "plugins.my_plugin"`

### 3. Always Use `self.logger`

```python
# DON'T DO THIS
logger = logging.getLogger("MyPlugin")

class MyPlugin:
    def method(self):
        logger.info("message")  # Uses module-level logger

# DO THIS
from nuberu.plugins import PluginBase

class MyPlugin(PluginBase):
    plugin_name = "my_plugin"
    
    def __init__(self):
        super().__init__()
    
    def method(self):
        self.logger.info("message")  # Uses instance logger
```

---

## User Configuration

Users can control plugin logging granularity via their simulation YAML:

```yaml
logging:
  level: error  # Global level
  component_levels:
    # Control all plugins at once
    plugins: warning
    
    # Control a specific plugin
    plugins.my_plugin: debug  # Note: "plugins." prefix IS used in config YAML
```

---

## Complete Example

```python
# nuberu_plugin_example/plugin.py
import pluggy
from nuberu.plugins import PluginBase

hookimpl = pluggy.HookimplMarker("nuberu")


class ExamplePlugin(PluginBase):
    """Example plugin demonstrating proper logging."""
    
    plugin_name = "example"  # Creates logger: nuberu.plugins.example
    
    def __init__(self):
        super().__init__()
        self.logger.info("ExamplePlugin initialized")
    
    @hookimpl
    def get_factory(self, config):
        self.logger.debug(f"Creating factory with config: {config}")
        
        def factory(env, event_bus):
            self.logger.info("Factory called, creating implementation")
            return ExampleImplementation(env, event_bus, self.logger)
        
        return factory
```

---

## Troubleshooting

### "Plugin does not define plugin_name" warning

Add the `plugin_name` class attribute:

```python
class MyPlugin(PluginBase):
    plugin_name = "my_plugin"  # Add this!
```

### Logging not working

Make sure you're calling `super().__init__()`:

```python
def __init__(self):
    super().__init__()  # Required!
```

---

## Further Reading

- [Writing Plugins](./writing-plugins.md) — Full plugin development guide
- [Configuration Reference](../configuration-reference.md) — Logging configuration options
