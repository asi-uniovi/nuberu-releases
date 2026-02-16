# Contributing to Nuberu

> How to set up your development environment, contribute code, and follow project conventions.

## Development Environment

### Prerequisites

- Python 3.11 or higher
- [uv](https://docs.astral.sh/uv/) package manager
- Git

### Setup

We use **uv workspaces** to manage the monorepo. A single sync command installs the core and all plugins in editable mode:

```bash
git clone https://github.com/jldiaz-uniovi/nuberu-monorepo.git
cd nuberu-monorepo
uv sync --all-extras
```

This creates a single virtual environment (`.venv`) at the root containing:
- The `nuberu` core (editable mode)
- All plugins from `plugins/` (editable mode)
- All development dependencies (pytest, linters, etc.)

### IDE Configuration (VS Code)

1. Open the command palette (`Ctrl+Shift+P`)
2. Select **"Python: Select Interpreter"**
3. Choose the interpreter at `./.venv/bin/python` (Linux/macOS) or `.\.venv\Scripts\python.exe` (Windows)

---

## Branching Strategy

- **`main`**: Active development branch. All new features and PRs target this branch.
- **`legacy-v0.2.0`**: Frozen snapshot for reproducibility of published paper results. Read-only.

---

## Testing

### Quick Regression Tests (Root Workspace)

Run all tests across the monorepo:

```bash
uv run pytest
```

> **Limitation**: Custom CLI flags defined in subdirectory `conftest.py` files won't work from the root.

### Component-Level Tests (Isolated)

For working on a specific component:

```bash
cd examples/simul2026-examples
uv venv && uv sync
uv run pytest
```

### Writing Good Tests

1. **Never rely on `os.getcwd()`** or relative paths like `open("./data.json")`
2. **Always anchor paths** to the test file location:

   ```python
   from pathlib import Path
   TEST_DATA_PATH = Path(__file__).parent / "data.json"
   ```

---

## Code Conventions

- **Protocols over inheritance**: Contracts are defined using `typing.Protocol`
- **Pydantic for config validation**: All configuration uses Pydantic models
- **Plugin-first**: Extensible functionality is implemented as plugins, not in the core
- **Logging**: Use `PluginBase` for proper hierarchical logging (see [Plugin Logging](./guides/plugin-logging.md))

---

## Documentation Structure

| Directory | Content |
|-----------|---------|
| `docs/doc/` | Official user documentation (this guide lives here) |
| `docs/dev/` | Internal developer guides and technical notes |
| `docs/adr/` | Architecture Decision Records — immutable logs of decisions |
| `docs/rfc/` | Requests for Comments — proposals for discussion |

### Writing Standards

- Write documentation in **English**
- Use **standard Markdown links** (no WikiLinks): `[text](./path.md)`
- Use **relative paths** so links work in VS Code, GitHub, and other renderers

---

## Pull Request Workflow

1. Create a feature branch (e.g., `feat/my-feature` or `docs/my-doc`)
2. Make your changes and ensure tests pass: `uv run pytest`
3. Open a Pull Request against `main`
4. Address review feedback
5. Merge once approved

---

## Creating a New Plugin

See the [Writing Plugins](./guides/writing-plugins.md) guide for a complete walkthrough.

Quick checklist:
1. Create package structure under `plugins/`
2. Implement the appropriate Specs interface
3. Register entry points in `pyproject.toml`
4. Install with `uv pip install -e ./plugins/your-plugin`
5. Add to a simulation YAML config and test

---

## Further Reading

- [Architecture Overview](./concepts/architecture-overview.md) — Understand the system before contributing
- [Writing Plugins](./guides/writing-plugins.md) — Create your own extensions
- [Configuration Reference](./configuration-reference.md) — Full YAML specification
