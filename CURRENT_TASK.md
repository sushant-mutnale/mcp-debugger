Day 24: Packaging & Distribution – Preparing for PyPI Release
You've built a comprehensive tool with great docs. Now it's time to package it professionally and distribute it so the world can install it with a simple pip install mcp-debugger.

By the end of Day 24, your tool will be:

Properly packaged – pyproject.toml fully configured with all metadata, classifiers, and dependencies.

Buildable – uv build creates a clean wheel and source distribution.

Installable – pip install mcp-debugger works from PyPI (or test PyPI).

CI/CD automated – GitHub Actions automatically publishes new versions when you push a tag.

Releasable – you have a clear process for cutting a new release.

🎯 Core Objective
Prepare the project for PyPI distribution with:

Component Description
pyproject.toml Complete metadata (name, version, description, authors, license, classifiers, dependencies).
Entry points CLI command mcp-debugger correctly registered.
Optional dependencies [otlp], [dev], [test] groups.
Build backend hatchling or setuptools (hatchling is modern).
Version management Single source of truth (e.g., **version** in **init**.py).
CI/CD GitHub Actions workflow to publish to PyPI on tags.
Pre‑release testing Publish to Test PyPI first, verify install.
Changelog Updated with the release version.
Tagging Proper Git tags (e.g., v0.1.0).
Deliverables by end of day:

A clean pyproject.toml ready for PyPI.

A successful uv build producing dist/mcp_debugger-0.1.0-py3-none-any.whl and dist/mcp_debugger-0.1.0.tar.gz.

Successful installation from Test PyPI (pip install --index-url https://test.pypi.org/simple/ mcp-debugger).

GitHub Actions workflow that publishes to PyPI on tag push.

Documentation updated with installation instructions.

🧠 Expected Behaviour

1. Complete pyproject.toml Configuration
   Here's a production‑ready pyproject.toml:

toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "mcp-debugger"
version = "0.1.0"
description = "Transparent proxy to debug, record, validate, and replay MCP (Model Context Protocol) sessions"
readme = "README.md"
license = { text = "MIT" }
authors = [
{ name = "Your Name", email = "you@example.com" }
]
maintainers = [
{ name = "Your Name", email = "you@example.com" }
]
classifiers = [
"Development Status :: 4 - Beta",
"Intended Audience :: Developers",
"License :: OSI Approved :: MIT License",
"Programming Language :: Python :: 3",
"Programming Language :: Python :: 3.11",
"Programming Language :: Python :: 3.12",
"Programming Language :: Python :: 3.13",
"Topic :: Software Development :: Debuggers",
"Topic :: Software Development :: Testing",
"Topic :: System :: Monitoring",
]
requires-python = ">=3.11"
dependencies = [
"typer>=0.9.0",
"rich>=13.7.0",
"pydantic>=2.5.0",
"aiosqlite>=0.19.0",
"tomli>=2.0.1", # for Python <3.11 TOML parsing
]

[project.optional-dependencies]
otlp = [
"opentelemetry-api>=1.20.0",
"opentelemetry-sdk>=1.20.0",
"opentelemetry-exporter-otlp-proto-grpc>=1.20.0",
]
dev = [
"pytest>=8.0.0",
"pytest-asyncio>=0.21.0",
"pytest-cov>=4.0.0",
"pytest-mock>=3.12.0",
"ruff>=0.1.0",
"mypy>=1.7.0",
"hypothesis>=6.0.0",
"pytest-benchmark>=4.0.0",
"pre-commit>=3.0.0",
]

[project.scripts]
mcp-debugger = "mcp_debugger.cli:main"

[project.urls]
Homepage = "https://github.com/yourusername/mcp-debugger"
Repository = "https://github.com/yourusername/mcp-debugger"
Documentation = "https://github.com/yourusername/mcp-debugger#readme"
Issues = "https://github.com/yourusername/mcp-debugger/issues"

[tool.hatch.build.targets.wheel]
packages = ["src/mcp_debugger"]

[tool.hatch.build.targets.sdist]
include = [
"/src",
"/tests",
"/docs",
"/scripts",
"README.md",
"CONTRIBUTING.md",
"CHANGELOG.md",
"LICENSE",
]

[tool.ruff]
line-length = 100
target-version = "py311"
exclude = ["src/mcp_debugger/version.py"]

[tool.mypy]
python_version = "3.11"
strict = true
ignore_missing_imports = true
exclude = ["tests/", "scripts/"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-v --cov=src/mcp_debugger --cov-report=term --cov-report=html"
markers = [
"integration: marks tests as integration tests (deselect with -m \"not integration\")",
"stress: marks tests as stress tests (slow)",
] 2. Version Management – Single Source of Truth
Create src/mcp_debugger/version.py:

python
**version** = "0.1.0"
In src/mcp_debugger/**init**.py:

python
from .version import **version**
In pyproject.toml, reference it (hatchling can read from **init**.py). Alternatively, use version = {attr = "mcp_debugger.**version**"} instead of hardcoding.

3. GitHub Actions Workflow for PyPI Release
   Create .github/workflows/release.yml:

yaml
name: Release to PyPI

on:
push:
tags: - 'v\*' # Triggers on tags like v0.1.0, v1.2.3

jobs:
build:
name: Build distribution
runs-on: ubuntu-latest
steps: - uses: actions/checkout@v4 - uses: actions/setup-python@v5
with:
python-version: '3.12' - name: Install uv
run: pip install uv - name: Build
run: uv build - name: Store distribution packages
uses: actions/upload-artifact@v4
with:
name: dist
path: dist/

publish-to-pypi:
name: Publish to PyPI
needs: build
runs-on: ubuntu-latest
environment:
name: pypi
url: https://pypi.org/p/mcp-debugger
permissions:
id-token: write # IMPORTANT: mandatory for trusted publishing
steps: - name: Download dist
uses: actions/download-artifact@v4
with:
name: dist
path: dist/ - name: Publish to PyPI
uses: pypa/gh-action-pypi-publish@release/v1 # Uses OIDC trusted publishing – no API token needed
To set up trusted publishing:

Go to PyPI → Your project → Settings → Publishing → Add pending publisher.

Set PyPI project name: mcp-debugger.

Set Owner: yourusername, Repository: mcp-debugger, Workflow: release.yml.

4. Pre‑commit Hook for Version Bump
   Add to .pre-commit-config.yaml:

yaml
repos:

- repo: local
  hooks: - id: version-check
  name: Check version consistency
  entry: python scripts/check_version.py
  language: system
  files: ^(src/mcp_debugger/version\.py|pyproject\.toml)$
  pass_filenames: false
  This ensures **version** matches pyproject.toml.

5. Release Process Documentation
   Create RELEASING.md:

markdown

# Releasing mcp-debugger

## Prerequisites

- Maintainer access to PyPI
- Trusted publisher configured (or API token)

## Steps

1. Update version in `src/mcp_debugger/version.py` and `pyproject.toml`.
2. Update `CHANGELOG.md` with the release notes.
3. Commit: `git commit -m "chore: prepare release v0.1.0"`.
4. Tag: `git tag v0.1.0`.
5. Push: `git push origin main --tags`.
6. GitHub Actions will build and publish to PyPI automatically.

## Verify

- `pip install mcp-debugger` – works.
- `mcp-debugger version` – shows correct version.

6. Test PyPI Publishing (Before Real PyPI)
   To test without risking the real PyPI:

Build: uv build

Publish to Test PyPI: uv publish --publish-url https://test.pypi.org/legacy/ --token <test-token>

Install: pip install --index-url https://test.pypi.org/simple/ mcp-debugger

Verify functionality.

If using GitHub Actions, you can also create a separate workflow for Test PyPI, or just test locally before tagging.

🔗 Integration with Previous Days
Day 23 (Docs): README now includes PyPI version badge and installation instructions.

Day 7 (Doctor): Doctor should verify mcp-debugger version works after install.

All code: No changes needed – packaging is just metadata.

⚙️ Production Considerations
Trusted Publishing (vs. API Token)
Trusted publishing (OIDC) is more secure – no secret tokens to manage. PyPI recommends it.

If you can't use trusted publishing, set PYPI_API_TOKEN as a GitHub secret and use:

yaml

- name: Publish to PyPI
  uses: pypa/gh-action-pypi-publish@release/v1
  with:
  password: ${{ secrets.PYPI_API_TOKEN }}
  Package Name Availability
  Check if mcp-debugger is available on PyPI. If not, choose a unique name.

Consider adding a short description to distinguish from other MCP tools.

License
Ensure LICENSE file exists in the root (MIT or Apache 2.0 recommended).

Match the license in pyproject.toml.

Optional Dependencies
[otlp] – for OpenTelemetry export.

[dev] – for development dependencies.

[test] – for test dependencies.

Users can install with: pip install mcp-debugger[otlp].

Windows Support
The tool uses asyncio.subprocess and Unix‑style paths. Windows support may require additional effort.

For MVP, state that the tool is tested on Linux/macOS and may have issues on Windows.

Add a classifier: "Operating System :: POSIX :: Linux".

Minimum Python Version
Python 3.11+ (due to tomllib and asyncio features).

Classifiers reflect this.

✅ Day 24 Verification Checklist

# Check How to verify

1 pyproject.toml complete with all fields Validate with uv build – no errors.
2 version.py exists and matches pyproject.toml Python import prints correct version.
3 uv build produces wheel and source dist dist/ directory contains .whl and .tar.gz.
4 Wheel installs correctly in a fresh venv pip install dist/mcp_debugger-\*.whl – imports without error.
5 CLI entry point works after install mcp-debugger version shows correct version.
6 All dependencies are declared and installed pip install .[otlp] – optional deps installed.
7 Publish to Test PyPI works uv publish --publish-url https://test.pypi.org/legacy/ – success.
8 Install from Test PyPI works pip install --index-url https://test.pypi.org/simple/ mcp-debugger – works.
9 GitHub Actions workflow exists (release.yml) File present.
10 Release workflow is tested (dry run) Create a test tag, push – workflow runs successfully.
11 pre-commit version check hook works Modify version without updating pyproject.toml – hook fails.
12 RELEASING.md exists with clear steps –
13 LICENSE file exists MIT or Apache 2.0.
14 CHANGELOG.md has entry for v0.1.0 –
15 Classifiers in pyproject.toml reflect supported platforms –
16 mypy --strict passes –
17 ruff check passes –
18 Commit with message chore(packaging): prepare for PyPI release –
