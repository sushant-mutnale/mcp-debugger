# Contributing to mcp-debugger

## Setup

```bash
git clone https://github.com/your-org/mcp-debugger.git
cd mcp-debugger
python -m venv .venv
.venv\Scripts\activate        # Windows
# or: source .venv/bin/activate  # Linux/macOS
pip install -e ".[dev]"
```

## Running Tests

### All tests
```bash
pytest
```

### With coverage report
```bash
pytest --cov=mcp_debugger --cov-report=term-missing
```

### HTML coverage report (opens in browser)
```bash
pytest --cov=mcp_debugger --cov-report=html
start htmlcov/index.html    # Windows
# or: open htmlcov/index.html   # macOS
```

### A specific test file
```bash
pytest tests/test_cli/test_inspect.py -v
```

### A specific test by name
```bash
pytest -k "test_stats_command" -v
```

## Test Structure

```
tests/
├── conftest.py                   # Shared fixtures (DB, temp dirs)
├── test_cli/                     # CLI command tests
│   ├── test_cli_config.py        # Config subcommands
│   ├── test_cli_edge_cases.py    # Error paths, KeyboardInterrupt, etc.
│   ├── test_export.py
│   ├── test_inspect.py
│   ├── test_list.py
│   ├── test_proxy.py
│   ├── test_replay.py
│   ├── test_stats.py
│   └── test_validate.py
├── test_config/                  # Config loading/saving
├── test_exporters/               # JSON, Markdown, OTLP exporters
├── test_integration/             # End-to-end pipeline tests
├── test_property.py              # Hypothesis property-based tests
├── test_protocol/                # JSON-RPC schema, validator, classifier
├── test_proxy/                   # stdio proxy lifecycle
├── test_replay/                  # Replay engine and diff logic
├── test_storage/                 # Database CRUD
└── test_stress.py                # Performance and load tests
```

## Static Analysis

```bash
# Linting (must pass with zero errors)
ruff check src/ tests/

# Auto-fix safe issues
ruff check src/ tests/ --fix

# Type checking (must pass with zero errors)
mypy src/mcp_debugger --ignore-missing-imports
```

## Coverage Targets

| Module | Target |
|--------|--------|
| `protocol/` | 100% |
| `config.py` | 95% |
| `storage/database.py` | 90% |
| `proxy/stdio_proxy.py` | 85% |
| `replay/engine.py` | 90% |
| `cli.py` | 90%+ |
| **Overall** | **>90%** |

## Adding New Tests

1. Mirror the `src/` directory structure under `tests/`.
2. Use `AsyncMock` for async database/network calls.
3. Use `typer.testing.CliRunner` for CLI command tests.
4. Use `tmp_path` fixture for any file I/O.
5. Use `patch.dict("sys.modules", {...})` to simulate missing optional dependencies.
6. Do **not** use `patch("builtins.__import__")` — it breaks the test runner.

## CI

GitHub Actions runs on every push and pull request:
- Python 3.11 and 3.12
- All tests must pass
- Coverage must stay above 90%
- `ruff` and `mypy` must report zero errors

See `.github/workflows/ci.yml`.
