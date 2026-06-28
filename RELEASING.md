# Releasing mcp-debugger

This guide documents the process of preparing, verifying, and publishing a new release of `mcp-debugger`.

---

## 1. Versioning Scheme

`mcp-debugger` uses a single source of truth for its version number:
- **Source of Truth**: `src/mcp_debugger/version.py` (`__version__ = "X.Y.Z"`)

Consistency is enforced before commits by a local pre-commit hook which checks that the version string matches exactly between:
- `src/mcp_debugger/version.py`
- `pyproject.toml` (`[project] version = "X.Y.Z"`)
- `CHANGELOG.md` (the top entry heading: `## vX.Y.Z` or `## [X.Y.Z]`)

---

## 2. Release Steps

### Step A. Prepare the Release Branch
1. Create a release branch (e.g., `release/vX.Y.Z`):
   ```bash
   git checkout -b release/vX.Y.Z
   ```
2. Update the version in `src/mcp_debugger/version.py`.
3. Update the version in `pyproject.toml`.
4. Add a new entry to `CHANGELOG.md` detailing the changes under the heading `## vX.Y.Z (YYYY-MM-DD)`.

### Step B. Verify Version Consistency & Tests
1. Run pre-commit to check version consistency and basic code quality:
   ```bash
   pre-commit run --all-files
   ```
   Or run the script manually:
   ```bash
   python scripts/check_version.py
   ```
2. Run the complete test suite:
   ```bash
   pytest
   ```
3. Run static type checking and linting:
   ```bash
   mypy --strict src/
   ruff check src/
   ```

### Step C. Verification via Test PyPI
Before publishing to the real PyPI, publish to Test PyPI to ensure the package builds and installs cleanly without issues.

1. Build the distribution files:
   ```bash
   uv build
   ```
2. Publish to Test PyPI (you will need a Test PyPI account and API token):
   ```bash
   uv publish --publish-url https://test.pypi.org/legacy/
   ```
3. In a separate, clean directory, create a test virtual environment and install the package:
   ```bash
   uv venv test_env
   # On Windows:
   test_env\Scripts\pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple mcp-debugger
   # On Linux/macOS:
   source test_env/bin/activate
   pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple mcp-debugger
   ```
   *(Note: `--extra-index-url https://pypi.org/simple` is required so that pip can resolve third-party dependencies like `typer` or `rich` from the main PyPI registry).*
4. Run a quick smoke check:
   ```bash
   mcp-debugger --help
   ```

### Step D. Official Release
Once local verification is complete:

1. Commit all release changes:
   ```bash
   git add .
   git commit -m "chore(release): prepare for release vX.Y.Z"
   ```
2. Create an annotated git tag:
   ```bash
   git tag -a vX.Y.Z -m "Release vX.Y.Z"
   ```
3. Push the tag to GitHub:
   ```bash
   git push origin vX.Y.Z
   ```
4. Push your branch and merge it into `main`.

---

## 3. Automated Publishing Setup

The project uses GitHub Actions to automate publishing to PyPI when a version tag (`v*`) is pushed. This is done via **OIDC Trusted Publishing**, meaning no PyPI password or token needs to be stored in GitHub Secrets.

### How to configure Trusted Publishing on PyPI:
1. Log in to your PyPI account.
2. Go to **Publishing** in your account settings.
3. Click **Add Publisher** -> Select **GitHub**.
4. Configure the following values:
   - **GitHub Owner**: `sushant-mutnale`
   - **Repository Name**: `mcp-debugger`
   - **Workflow Name**: `release.yml`
   - **Environment**: (leave blank, or enter `release` if restricted to environment rules)
5. Save the publisher. Once configured, the GitHub Action running on tag pushes will authenticate automatically and publish the package safely to PyPI.
