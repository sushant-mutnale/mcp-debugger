"""Configuration management for mcp-debugger.

Loads and saves a TOML config file at ``~/.mcp-debugger/config.toml``
(or ``%APPDATA%\\mcp-debugger\\config.toml`` on Windows).

Usage::

    from mcp_debugger.config import Config

    cfg = Config()
    cfg.load()                           # idempotent, safe to call repeatedly
    timeout = cfg.get("replay.timeout", 5000)
    cfg.set("replay.timeout", 10000)

Keys use dot-notation: ``"replay.timeout"``, ``"aliases.fs"``, etc.

Precedence (handled by the caller, not this module):
    CLI flag > Config file > Hardcoded default
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("mcp_debugger.config")

# ---------------------------------------------------------------------------
# Default configuration values
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: Dict[str, Any] = {
    "general": {
        "default_output": "rich",
        "color": True,
    },
    "proxy": {
        "timeout": 5000,
        "verbose": False,
        "default_session_name": "mcp-session",
    },
    "replay": {
        "timeout": 5000,
        "default_server": "",
        "auto_save": False,
        "diff_only": False,
        "otlp_endpoint": "http://localhost:4317",
        "otlp_service_name": "mcp-debugger",
        "otlp_export": False,
    },
    "export": {
        "default_format": "json",
        "pretty_json": True,
    },
    "validate": {
        "strict": False,
        "auto_validate": False,
    },
    "doctor": {
        "check_optional": True,
        "node_path": "",
    },
    "aliases": {},
    "profiles": {},
}

# ---------------------------------------------------------------------------
# Config file location
# ---------------------------------------------------------------------------


def _config_dir() -> Path:
    """Return the platform-appropriate config directory."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA") or Path.home()
        return Path(appdata) / "mcp-debugger"
    return Path.home() / ".mcp-debugger"


def default_config_path() -> Path:
    """Return the default path to config.toml."""
    return _config_dir() / "config.toml"


# ---------------------------------------------------------------------------
# TOML helpers
# ---------------------------------------------------------------------------


def _loads_toml(text: str) -> Dict[str, Any]:
    """Parse TOML text using the stdlib tomllib (Python 3.11+)."""
    if sys.version_info >= (3, 11):
        import tomllib  # pragma: no cover

        return tomllib.loads(text)
    else:  # pragma: no cover
        try:
            import tomllib  # type: ignore[no-redef]
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]
        return tomllib.loads(text)  # type: ignore[no-any-return]


def _dumps_toml(data: Dict[str, Any]) -> str:
    """Serialize a two-level dict to TOML text.

    Supports:
    * Flat sections: ``[section]`` with string/int/float/bool scalar values.
    * One nested level for ``[aliases]`` and ``[profiles]``.
    * Profiles have their own sub-table: ``[profiles.name]``.

    This is intentionally minimal – it only handles the structures that appear
    in the default config.
    """
    lines: list[str] = [
        "# mcp-debugger configuration",
        "# Edit this file or use `mcp-debugger config set <key> <value>`",
        "",
    ]

    for section, value in data.items():
        if not isinstance(value, dict):
            continue

        # aliases and profiles get special handling (one extra level)
        if section == "profiles":
            lines.append(f"[{section}]")
            for profile_name, profile_val in value.items():
                if isinstance(profile_val, dict):
                    lines.append(f"[{section}.{profile_name}]")
                    for k, v in profile_val.items():
                        lines.append(f"{k} = {_toml_value(v)}")
                    lines.append("")
            continue

        lines.append(f"[{section}]")
        for k, v in value.items():
            lines.append(f"{k} = {_toml_value(v)}")
        lines.append("")

    return "\n".join(lines)


def _toml_value(v: Any) -> str:
    """Serialize a scalar value to TOML format."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        # Escape backslashes and double-quotes
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return f'"{v}"'


# ---------------------------------------------------------------------------
# Config class
# ---------------------------------------------------------------------------


class Config:
    """Read/write the mcp-debugger configuration file.

    Attributes:
        path: Absolute path to the config file.  Defaults to the
            platform-standard location but can be overridden (e.g. in tests).
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path: Path = path or default_config_path()
        self._data: Dict[str, Any] = {}
        self._loaded: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load (or reload) the config from disk.

        If the file does not exist, uses :data:`DEFAULT_CONFIG`.
        If the file is invalid TOML, logs a warning and uses defaults.
        Idempotent – safe to call multiple times.
        """
        import copy

        self._data = copy.deepcopy(DEFAULT_CONFIG)

        if not self.path.exists():
            self._loaded = True
            return

        try:
            text = self.path.read_text(encoding="utf-8")
            parsed = _loads_toml(text)
            # Deep-merge parsed on top of defaults so missing keys still have values
            _deep_merge(self._data, parsed)
        except Exception as exc:
            logger.warning("Config file %s is invalid (%s). Using defaults.", self.path, exc)

        self._loaded = True

    def save(self) -> None:
        """Write the current in-memory config to disk.

        Creates parent directories if they don't exist.
        Sets file permissions to 0o600.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = _dumps_toml(self._data)
        self.path.write_text(text, encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass  # Windows may not support this

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value using dot-notation.

        Args:
            key: Dot-separated path, e.g. ``"replay.timeout"``.
            default: Value to return if the key is not found.

        Returns:
            The config value or *default*.
        """
        if not self._loaded:
            self.load()
        parts = key.split(".")
        node: Any = self._data
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, key: str, value: Any) -> None:
        """Set a config value using dot-notation and persist to disk.

        Creates intermediate sections as needed.

        Args:
            key: Dot-separated path, e.g. ``"replay.timeout"``.
            value: The value to store.
        """
        if not self._loaded:
            self.load()
        parts = key.split(".")
        node: Dict[str, Any] = self._data
        for part in parts[:-1]:
            if part not in node or not isinstance(node[part], dict):
                node[part] = {}
            node = node[part]
        # Coerce string numbers/booleans to their native types
        node[parts[-1]] = _coerce(value)
        self.save()

    def unset(self, key: str) -> bool:
        """Remove a config key, reverting it to the default.

        Args:
            key: Dot-separated path.

        Returns:
            ``True`` if the key was found and removed, ``False`` otherwise.
        """
        if not self._loaded:
            self.load()
        parts = key.split(".")
        node: Dict[str, Any] = self._data
        for part in parts[:-1]:
            if not isinstance(node, dict) or part not in node:
                return False
            node = node[part]
        if parts[-1] in node:
            del node[parts[-1]]
            self.save()
            return True
        return False

    def all(self) -> Dict[str, Any]:
        """Return a copy of the full in-memory config dict."""
        if not self._loaded:
            self.load()
        import copy

        return copy.deepcopy(self._data)

    def reset(self) -> None:
        """Reset the config to defaults and persist."""
        import copy

        self._data = copy.deepcopy(DEFAULT_CONFIG)
        self._loaded = True
        self.save()

    def resolve_alias(self, alias: str) -> Optional[str]:
        """Look up *alias* in ``[aliases]`` and return the server command.

        Args:
            alias: Short alias name (e.g. ``"fs"``).

        Returns:
            The server command string, or ``None`` if the alias is not found.
        """
        if not self._loaded:
            self.load()
        aliases = self._data.get("aliases", {})
        if not isinstance(aliases, dict):
            return None
        result = aliases.get(alias)
        return str(result) if result is not None else None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> None:
    """Recursively merge *override* into *base* in-place."""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _coerce(value: Any) -> Any:
    """Coerce CLI string inputs to native Python types when possible."""
    if not isinstance(value, str):
        return value
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


# ---------------------------------------------------------------------------
# Module-level singleton (lazy, one per process)
# ---------------------------------------------------------------------------

_GLOBAL_CONFIG: Optional[Config] = None


def get_config(path: Optional[Path] = None) -> Config:
    """Return the process-wide :class:`Config` singleton.

    The first call initialises and loads the config.  Subsequent calls
    return the cached instance (unless *path* is specified, in which case
    a new instance is created).

    Args:
        path: Override config path (mostly useful in tests).
    """
    global _GLOBAL_CONFIG
    if path is not None:
        cfg = Config(path=path)
        cfg.load()
        return cfg
    if _GLOBAL_CONFIG is None:
        _GLOBAL_CONFIG = Config()
        _GLOBAL_CONFIG.load()
    return _GLOBAL_CONFIG
