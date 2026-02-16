# Nuberu Monorepo

**Nuberu** is a discrete-event simulation framework for modeling serverless cloud infrastructures. It simulates the behavior of VMs, containers, load balancers, and workloads to evaluate costs, performance, and scaling policies.

Built on top of [aSimPy](https://github.com/jldiaz-uniovi/asimpy) and extended via [pluggy](https://pluggy.readthedocs.io/), Nuberu is modular, extensible, and suitable for both academic research and production capacity planning.

## Key Features

- **Plugin-based architecture** — Load balancers, runtime models, cost models, and data providers are all plugins
- **Bidirectional request flow** — Full round-trip simulation with configurable network delays
- **Drain mode** — Graceful container shutdown that completes in-flight requests
- **O(1) monitoring** — Event capture with zero memory overhead during simulation
- **Reproducible** — Seed-based random generation for deterministic results

## Repository Structure

```
nuberu-monorepo/
├── core/               # Nuberu core simulation engine
├── plugins/            # Official extension plugins (13)
│   ├── nuberu-plugin-load-balancer/
│   ├── nuberu-plugin-smoothwrr-load-balancer/
│   ├── nuberu-plugin-runtime-model-simple/
│   ├── nuberu-plugin-poisson-distribution/
│   ├── nuberu-plugin-conlloovia-data-provider/
│   ├── nuberu-plugin-custom-monitor/
│   ├── nuberu-plugin-report-generator/
│   └── ...
├── examples/           # Example configurations and experiments
└── docs/doc/           # Official documentation
```

## Quick Start

### Prerequisites

- Python 3.11 or higher
- [uv](https://docs.astral.sh/uv/) package manager

### Installation

```bash
git clone https://github.com/jldiaz-uniovi/nuberu-monorepo.git
cd nuberu-monorepo
uv sync
```

### Run a Simulation

```bash
uv run python -m nuberu.cli.main run examples/simul2026-examples/configs/example.yaml
```

## Documentation

📖 **[Full Documentation](docs/doc/README.md)** — Getting started, architecture, guides, and reference.

| Section | Description |
|---------|-------------|
| [Getting Started](docs/doc/getting-started.md) | First simulation in under 10 minutes |
| [Architecture Overview](docs/doc/concepts/architecture-overview.md) | Components, events, and plugin system |
| [Configuration Reference](docs/doc/configuration-reference.md) | Complete YAML specification |
| [Writing Plugins](docs/doc/guides/writing-plugins.md) | Create your own extensions |
| [Contributing](docs/doc/contributing.md) | Development setup and conventions |

## License

This project is licensed under the MIT License.
