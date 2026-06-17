"""Unit tests for mcp_debugger.config module."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mcp_debugger.config import (
    Config,
    DEFAULT_CONFIG,
    _coerce,
    _deep_merge,
    _dumps_toml,
    _toml_value,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_config(tmp_path: Path) -> Config:
    """Return a Config wired to a temp file (does not exist yet)."""
    return Config(path=tmp_path / "config.toml")


# ---------------------------------------------------------------------------
# _coerce
# ---------------------------------------------------------------------------


class TestCoerce:
    def test_bool_true(self) -> None:
        assert _coerce("true") is True
        assert _coerce("True") is True

    def test_bool_false(self) -> None:
        assert _coerce("false") is False
        assert _coerce("False") is False

    def test_int(self) -> None:
        assert _coerce("42") == 42
        assert isinstance(_coerce("42"), int)

    def test_float(self) -> None:
        assert _coerce("3.14") == pytest.approx(3.14)

    def test_string_passthrough(self) -> None:
        assert _coerce("hello world") == "hello world"

    def test_non_string_passthrough(self) -> None:
        assert _coerce(99) == 99
        assert _coerce(True) is True


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    def test_shallow_override(self) -> None:
        base = {"a": 1, "b": 2}
        _deep_merge(base, {"b": 99, "c": 3})
        assert base == {"a": 1, "b": 99, "c": 3}

    def test_nested_merge(self) -> None:
        base = {"replay": {"timeout": 5000, "default_server": ""}}
        _deep_merge(base, {"replay": {"timeout": 10000}})
        assert base["replay"]["timeout"] == 10000
        assert base["replay"]["default_server"] == ""

    def test_nested_add_key(self) -> None:
        base: dict = {"replay": {}}
        _deep_merge(base, {"replay": {"new_key": "hello"}})
        assert base["replay"]["new_key"] == "hello"


# ---------------------------------------------------------------------------
# _dumps_toml
# ---------------------------------------------------------------------------


class TestDumpsToml:
    def test_roundtrip_simple(self, tmp_path: Path) -> None:
        """Write via _dumps_toml and read back via tomllib."""
        data = {
            "general": {"default_output": "rich", "color": True},
            "proxy": {"timeout": 5000},
        }
        text = _dumps_toml(data)
        assert "[general]" in text
        assert "default_output = \"rich\"" in text
        assert "color = true" in text
        assert "timeout = 5000" in text

    def test_aliases_section(self) -> None:
        data = {"aliases": {"fs": "npx -y server /tmp", "gh": "npx -y github"}}
        text = _dumps_toml(data)
        assert "[aliases]" in text
        assert 'fs = "npx -y server /tmp"' in text

    def test_profiles_section(self) -> None:
        data = {"profiles": {"prod": {"server": "cmd", "timeout": 10000}}}
        text = _dumps_toml(data)
        assert "[profiles.prod]" in text
        assert 'server = "cmd"' in text

    def test_toml_value_string_escaping(self) -> None:
        result = _toml_value('say "hello"')
        assert result == '"say \\"hello\\""'

    def test_toml_value_backslash(self) -> None:
        result = _toml_value("C:\\Users\\foo")
        assert result == '"C:\\\\Users\\\\foo"'


# ---------------------------------------------------------------------------
# Config.load – missing file uses defaults
# ---------------------------------------------------------------------------


class TestConfigLoad:
    def test_missing_file_uses_defaults(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        cfg.load()
        assert cfg.get("replay.timeout") == DEFAULT_CONFIG["replay"]["timeout"]
        assert cfg.get("general.default_output") == "rich"

    def test_idempotent(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        cfg.load()
        cfg.load()  # second load should not raise
        assert cfg.get("proxy.timeout") == 5000

    def test_corrupt_file_uses_defaults(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "config.toml"
        bad_file.write_text("this is not valid TOML {{{", encoding="utf-8")
        cfg = Config(path=bad_file)
        cfg.load()  # must not raise
        assert cfg.get("replay.timeout") == 5000

    def test_valid_file_overrides_defaults(self, tmp_path: Path) -> None:
        toml = '[replay]\ntimeout = 9999\n'
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text(toml, encoding="utf-8")
        cfg = Config(path=cfg_file)
        cfg.load()
        assert cfg.get("replay.timeout") == 9999
        # Keys not in file should still have defaults
        assert cfg.get("proxy.timeout") == 5000


# ---------------------------------------------------------------------------
# Config.get
# ---------------------------------------------------------------------------


class TestConfigGet:
    def test_get_existing_key(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        assert cfg.get("replay.timeout") == 5000

    def test_get_missing_key_returns_default(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        assert cfg.get("replay.nonexistent", "fallback") == "fallback"

    def test_get_missing_key_returns_none(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        assert cfg.get("replay.nonexistent") is None

    def test_get_missing_section(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        assert cfg.get("no_section.key", 42) == 42

    def test_get_nested_aliases(self, tmp_path: Path) -> None:
        toml = '[aliases]\nfs = "npx server"\n'
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text(toml, encoding="utf-8")
        cfg = Config(path=cfg_file)
        assert cfg.get("aliases.fs") == "npx server"


# ---------------------------------------------------------------------------
# Config.set
# ---------------------------------------------------------------------------


class TestConfigSet:
    def test_set_creates_file(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        cfg.set("replay.timeout", 9999)
        assert cfg.path.exists()

    def test_set_updates_in_memory(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        cfg.set("replay.timeout", 9999)
        assert cfg.get("replay.timeout") == 9999

    def test_set_persisted_after_reload(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        cfg.set("replay.timeout", 9999)

        cfg2 = Config(path=cfg.path)
        assert cfg2.get("replay.timeout") == 9999

    def test_set_new_section(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        cfg.set("custom.key", "value")
        assert cfg.get("custom.key") == "value"

    def test_set_coerces_string_int(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        cfg.set("replay.timeout", "3000")
        assert cfg.get("replay.timeout") == 3000
        assert isinstance(cfg.get("replay.timeout"), int)

    def test_set_coerces_string_bool(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        cfg.set("replay.otlp_export", "true")
        assert cfg.get("replay.otlp_export") is True

    def test_set_alias(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        cfg.set("aliases.myserver", "npx -y server /path")
        assert cfg.get("aliases.myserver") == "npx -y server /path"


# ---------------------------------------------------------------------------
# Config.unset
# ---------------------------------------------------------------------------


class TestConfigUnset:
    def test_unset_existing_key(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        cfg.set("replay.timeout", 9999)
        removed = cfg.unset("replay.timeout")
        assert removed is True
        # After unset the key disappears (not reverted to default automatically)
        assert cfg.get("replay.timeout") is None

    def test_unset_missing_key_returns_false(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        removed = cfg.unset("replay.nonexistent")
        assert removed is False

    def test_unset_missing_section_returns_false(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        removed = cfg.unset("no_section.key")
        assert removed is False


# ---------------------------------------------------------------------------
# Config.reset
# ---------------------------------------------------------------------------


class TestConfigReset:
    def test_reset_restores_defaults(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        cfg.set("replay.timeout", 9999)
        cfg.reset()
        assert cfg.get("replay.timeout") == DEFAULT_CONFIG["replay"]["timeout"]

    def test_reset_creates_file(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        cfg.reset()
        assert cfg.path.exists()

    def test_reset_idempotent(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        cfg.reset()
        cfg.reset()
        assert cfg.get("general.default_output") == "rich"


# ---------------------------------------------------------------------------
# Config.resolve_alias
# ---------------------------------------------------------------------------


class TestConfigResolveAlias:
    def test_resolve_existing_alias(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        cfg.set("aliases.fs", "npx -y server /tmp")
        result = cfg.resolve_alias("fs")
        assert result == "npx -y server /tmp"

    def test_resolve_missing_alias_returns_none(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        result = cfg.resolve_alias("does_not_exist")
        assert result is None


# ---------------------------------------------------------------------------
# Config.all
# ---------------------------------------------------------------------------


class TestConfigAll:
    def test_all_returns_copy(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        data = cfg.all()
        assert isinstance(data, dict)
        # Mutating the returned dict does not affect the internal state
        data["replay"]["timeout"] = 999
        assert cfg.get("replay.timeout") == 5000

    def test_all_has_expected_sections(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        data = cfg.all()
        for section in ("general", "proxy", "replay", "export", "validate", "doctor", "aliases"):
            assert section in data


# ---------------------------------------------------------------------------
# File permissions (Unix only)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="chmod not supported on Windows")
class TestConfigFilePermissions:
    def test_permissions_are_600(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        cfg.reset()
        mode = os.stat(cfg.path).st_mode & 0o777
        assert mode == 0o600
