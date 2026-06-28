# Production Standards

This document establishes the code quality, testing guidelines, error handling policies, and CI/CD/pre-commit standards for the **MCP Debugger** repository.

---

## 1. Logging Guidelines

To maintain transparency and ensure pipes are not polluted, the codebase adheres to strict logging standards:

- **Logger Instantiation**: Instantiated at module level using:
  ```python
  import logging
  logger = logging.getLogger(__name__)
  ```
- **Stream Isolation**:
  - **Stdout Is Reserved**: Because standard input and output are the communication channels for the stdio proxy, no modules may log to `sys.stdout`.
  - **Stderr Targets**: All system logging must write to `sys.stderr` or private log files.
- **Log Levels**:
  - `INFO`: General system messages, session starts, and connection states.
  - `DEBUG`: Full JSON-RPC payload content and validation logs.
  - `WARNING` / `ERROR`: Intercepted proxy anomalies, connection drops, and validation failures.

---

## 2. Error Handling Policies

Uncaught exceptions or silent failures break proxy streams and corrupt session recordings.

- **No Silent Exception Eating**:
  - **Incorrect**:
    ```python
    try:
        do_something()
    except Exception:
        pass
    ```
  - **Correct**:
    ```python
    try:
        do_something()
    except Exception as e:
        logger.error("Failed to execute something: %s", e, exc_info=True)
        # Handle or reraise...
    ```
- **Recoverable Errors & Retries**:
  - If out-of-band actions fail (such as logging messages into SQLite due to disk locks), write attempts must retry up to 3 times with exponential backoff before fallback logging to `stderr`.
- **Fatal Failures**:
  - When errors are unrecoverable (such as failure to spin up the target server subprocess during proxy start), the tool must log details, write clean shutdown signals to the active interfaces, and exit using a non-zero code (e.g. `sys.exit(1)`).

---

## 3. Testing Requirements

- **Unit Testing**:
  - Mock third-party boundaries, subprocess environments, and sqlite db engines using `pytest` fixtures.
- **Integration Testing**:
  - Run real-world scenarios inside tests, executing locally available public MCP servers (like the filesystem or fetch servers) and verifying end-to-end data pipeline operations.
- **Property-based Testing**:
  - Leverage `hypothesis` to check that arbitrary dictionaries conforming to MCP JSON-RPC structures consistently round-trip serialize/deserialize without data loss or exceptions.
- **Async Safety**:
  - Use `pytest-asyncio` for asynchronous execution coverage.

---

## 4. CI/CD Pipeline (GitHub Actions)

Automation pipelines run under `.github/workflows/` on each push or pull request to the `main` branch.

- **Check Workflow**:
  - Validates formatting with `ruff format --check`.
  - Audits code styles with `ruff check`.
  - Verifies static type checking with `mypy --strict`.
  - Runs the full test suite with `pytest` across Python version matrices `3.11` and `3.12`.
- **Release Workflow**:
  - Triggered on tag publications (e.g., `v*`).
  - Automatically compiles wheels using `uv build` and publishes distribution packages to PyPI.

---

## 5. Pre-Commit Hooks

Developers are encouraged to run local checks before committing changes. The pre-commit checks should run:

1. **Lint Checks**:
   ```bash
   ruff check --fix
   ```
2. **Formatter**:
   ```bash
   ruff format
   ```
3. **Type Check**:
   ```bash
   mypy src/
   ```
4. **Fast Unit Tests**:
   ```bash
   pytest -m "not integration"
   ```
