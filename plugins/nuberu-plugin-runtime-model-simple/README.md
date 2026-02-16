# nuberu-plugin-runtime-model-simple

A simple runtime model plugin for the Nuberu cloud simulation framework.

## Overview

This plugin provides a basic runtime model implementation that manages:
- Request enqueueing with configurable queue size limits
- Service time computation based on performance data
- Request processing simulation
- Metrics tracking and event publishing

## Installation

This plugin is automatically discovered when installed in the same environment as Nuberu through the entry-points mechanism.

## Configuration

### Global Default Runtime Model

Define a default runtime model for all applications:

```yaml
runtime_model:
  plugin_name: simple
  plugin_config:
    queue_size: 0  # 0 = unlimited queue, >0 = limited queue size
```

### Per-Application Runtime Models

You can specify different runtime models for each application using the `runtime_models` section. Applications not listed will use the default `runtime_model`:

```yaml
# Default for all apps
runtime_model:
  plugin_name: simple
  plugin_config:
    queue_size: 0

# Overrides for specific apps
runtime_models:
  app_0:
    plugin_name: simple
    plugin_config:
      queue_size: 1080  # Custom queue for app_0
  app_1:
    plugin_name: simple
    plugin_config:
      queue_size: 500   # Different queue for app_1
  # Other apps will use the default runtime_model
```

## Features

- **Queue Management**: Configurable queue size (0 for unlimited)
- **Performance-based Service Time**: Computes service time from RPS data
- **Event Publishing**: Publishes processing events to the event bus
- **Metrics**: Provides queue metrics for monitoring

## Factory Pattern

This plugin uses the factory pattern architecture:
- The hook receives `config` with `queue_size`
- Returns a factory function that captures the config
- Factory receives runtime dependencies (`env`, `container`, `performance_data`, `event_bus`)
- Creates and returns a `RuntimeModelSimple` instance

## Example Usage

### Simple Configuration

The plugin is automatically loaded and used by Nuberu when configured in the YAML file:

```yaml
runtime_model:
  plugin_name: simple
  plugin_config:
    queue_size: 1000  # Maximum 1000 requests in queue
```

### Per-Application Configuration

Define different runtime models for each application:

```yaml
runtime_model:
  plugin_name: simple
  plugin_config:
    queue_size: 0  # Default: unlimited queue

runtime_models:
  high_priority_app:
    plugin_name: simple
    plugin_config:
      queue_size: 2000  # Larger queue for high priority
  batch_processing_app:
    plugin_name: simple
    plugin_config:
      queue_size: 100   # Smaller queue for batch processing
```

## Dependencies

- nuberu
- pluggy
- asimpy (via nuberu)
