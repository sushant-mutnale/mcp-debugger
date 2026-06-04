# Contributing Guidelines

Thank you for your interest in contributing to **MCP Debugger**! This document outlines the development workflow, code style standards, and tooling instructions.

---

## 1. Development Environment Setup

This project uses `uv` for package management and Python 3.11+.

### Step 1: Clone the Repository
```bash
git clone https://github.com/sushant-mutnale/mcp-debugger.git
cd mcp-debugger
```

### Step 2: Set Up Virtual Environment & Dependencies
Initialize and activate your environment, then install in editable mode with development dependencies:
```bash
# Using uv (recommended)
uv venv
source .venv/bin/activate  # Or .venv\Scripts\activate on Windows
uv pip install -e .[dev]
```

### Step 3: Run Verification Commands
Verify that the CLI package is installed correctly and tests run green:
```bash
mcp-debugger version
pytest
```

---

## 2. Code Quality & Standards

We enforce strict linting, formatting, and static analysis checks to maintain code safety:

- **Style & Formatter**: We use `ruff` for code linting and formatting. Run these before pushing changes:
  ```bash
  ruff check src/ tests/
  ruff format src/ tests/
  ```
- **Type Safety**: Code must pass strict `mypy` audits:
  ```bash
  mypy src/ tests/
  ```
- **Logging**:
  - Always log internal debug/info data to `sys.stderr` or file-handlers.
  - Do not use print statements or log to `sys.stdout` in the proxy logic, as this corrupts standard I/O communication between client and server.
- **Error Handling**:
  - Avoid bare `except:` statements.
  - Fail loudly on critical startup bugs (like failing to launch the subprocess) and retry transient errors (like sqlite lock errors).

---

## 3. Git & Pull Request Workflow

1. Create a descriptive feature branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Make your edits and include comprehensive unit/integration tests under `tests/`.
3. Verify that all linting, formatting, type checking, and tests pass successfully:
   ```bash
   ruff check src/ tests/
   ruff format src/ tests/ --check
   mypy src/ tests/
   pytest
   ```
4. Commit your changes with clear, imperative-style commit messages:
   ```bash
   git commit -m "feat: add schema validator for initialize method"
   ```
5. Push to your branch and open a Pull Request.
