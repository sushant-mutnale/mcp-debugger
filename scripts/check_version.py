#!/usr/bin/env python3
"""Check version consistency across version.py, pyproject.toml, and CHANGELOG.md."""

import re
import sys
import tomllib
from pathlib import Path

def main() -> None:
    # 1. Read version from version.py
    version_py_path = Path("src/mcp_debugger/version.py")
    if not version_py_path.exists():
        print(f"ERROR: {version_py_path} not found")
        sys.exit(1)
    
    version_py_content = version_py_path.read_text(encoding="utf-8")
    version_py_match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', version_py_content)
    if not version_py_match:
        print(f"ERROR: Could not parse __version__ from {version_py_path}")
        sys.exit(1)
    version_py = version_py_match.group(1)

    # 2. Read version from pyproject.toml
    pyproject_path = Path("pyproject.toml")
    if not pyproject_path.exists():
        print("ERROR: pyproject.toml not found")
        sys.exit(1)
    
    try:
        pyproject_data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        version_toml = pyproject_data.get("project", {}).get("version")
        if not version_toml:
            print("ERROR: Could not parse project.version from pyproject.toml")
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: Failed to parse pyproject.toml: {e}")
        sys.exit(1)

    # 3. Read version from CHANGELOG.md
    changelog_path = Path("CHANGELOG.md")
    if not changelog_path.exists():
        print("ERROR: CHANGELOG.md not found")
        sys.exit(1)
    
    changelog_content = changelog_path.read_text(encoding="utf-8")
    # Find first heading like "## vX.Y.Z" or "## [X.Y.Z]"
    changelog_match = re.search(r'^##\s*v?\[?([0-9]+\.[0-9]+\.[0-9]+)\]?', changelog_content, re.MULTILINE)
    if not changelog_match:
        print("ERROR: Could not find latest release version in CHANGELOG.md heading (e.g. ## v0.1.0)")
        sys.exit(1)
    version_changelog = changelog_match.group(1)

    # 4. Compare versions
    if version_py == version_toml and version_py == version_changelog:
        print(f"SUCCESS: All versions match: {version_py}")
        sys.exit(0)
    else:
        print("ERROR: Version mismatch:")
        print(f"   version.py:     {version_py}")
        print(f"   pyproject.toml: {version_toml}")
        print(f"   CHANGELOG.md:   {version_changelog}")
        sys.exit(1)

if __name__ == "__main__":
    main()
