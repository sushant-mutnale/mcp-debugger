# Configuration Reference

`mcp-debugger` reads a TOML configuration file so you don't have to retype the same flags every time.

## File Location

| Platform | Default path |
|----------|-------------|
| Linux / macOS | `~/.mcp-debugger/config.toml` |
| Windows | `%APPDATA%\mcp-debugger\config.toml` |

The file is created with **permissions `0o600`** (owner read/write only) to protect any sensitive values such as database connection strings in server commands.

If the file is missing, all defaults are used. If the file is corrupt (invalid TOML), a warning is printed and defaults are used — no command will crash.

---

## Quick Start

```bash
# Create the default config file
mcp-debugger config init

# See all current values
mcp-debugger config list

# Change a value
mcp-debugger config set replay.timeout 10000

# Add an alias for a server command
mcp-debugger config set aliases.fs "npx -y @modelcontextprotocol/server-filesystem /tmp"

# Use the alias when replaying
mcp-debugger replay 42 --alias fs

# Remove a key (reverts to hardcoded default)
mcp-debugger config unset replay.timeout

# Reset everything to defaults
mcp-debugger config reset
```

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `config init [--force]` | Create the default config file. Prompts before overwriting unless `--force` is given. |
| `config get <key>` | Print the value of a single config key (dot-notation). |
| `config set <key> <value>` | Set a config key and save. Values are auto-coerced to int/bool/float where possible. |
| `config unset <key>` | Delete a key from the file (reverts to hardcoded default on next read). |
| `config list` | Display all config values in a formatted table. |
| `config reset [--force]` | Overwrite the config file with factory defaults. |

---

## Precedence

```
CLI flag  >  Config file  >  Hardcoded default
```

If you supply `--timeout 2000` on the command line, that value wins regardless of what is in the config file.

---

## Full Config Schema

```toml
# mcp-debugger configuration
# Generated with `mcp-debugger config init`

[general]
# Default output format for commands that support it: "rich" | "json"
default_output = "rich"

# Whether to enable colours (auto-detected if not set)
color = true

[proxy]
# Default timeout for proxy operations (milliseconds)
timeout = 5000

# Whether to show verbose output during proxy run
verbose = false

# Default name for sessions (if not provided via --name)
default_session_name = "mcp-session"

[replay]
# Default timeout per request-response (milliseconds)
timeout = 5000

# Default server command for replay (can be overridden by --server or --alias)
default_server = ""

# Whether to auto-save replay results
auto_save = false

# Whether to show diff-only output by default
diff_only = false

# Default OTLP endpoint
otlp_endpoint = "http://localhost:4317"

# Default OTLP service name
otlp_service_name = "mcp-debugger"

# Whether to enable OTLP export by default
otlp_export = false

[export]
# Default export format: "json" | "markdown" | "otlp"
default_format = "json"

# Whether to pretty-print JSON by default
pretty_json = true

[validate]
# Whether to use strict mode (fail on warnings) or permissive mode (warnings only)
strict = false

# Whether to run validation on recorded sessions by default
auto_validate = false

[doctor]
# Whether to check for optional dependencies (npx, node, etc.)
check_optional = true

# Path to Node.js executable (auto-detected if empty)
node_path = ""

[aliases]
# Short names for server commands.
# Usage: mcp-debugger replay 42 --alias <name>
#
# Example entries (uncomment to enable):
# fs = "npx -y @modelcontextprotocol/server-filesystem /tmp"
# gh = "npx -y @modelcontextprotocol/server-github"
# pg = "npx -y @modelcontextprotocol/server-postgres postgresql://localhost/mcp"

[profiles]
# Replay profiles stored here for consistency.
# Example:
# [profiles.prod]
# server = "npx -y @modelcontextprotocol/server-filesystem /prod/data"
# timeout = 10000
```

---

## Key Reference

### `[replay]` section

These keys are used by `mcp-debugger replay` when the corresponding CLI flag is not provided.

| Key | Default | Corresponding flag |
|-----|---------|-------------------|
| `replay.timeout` | `5000` | `--timeout` |
| `replay.default_server` | `""` | `--server` (fallback) |
| `replay.auto_save` | `false` | `--save` |
| `replay.diff_only` | `false` | `--no-diff` |
| `replay.otlp_export` | `false` | `--otlp-export` |
| `replay.otlp_endpoint` | `"http://localhost:4317"` | `--otlp-endpoint` |
| `replay.otlp_service_name` | `"mcp-debugger"` | `--otlp-service-name` |

### `[export]` section

| Key | Default | Corresponding flag |
|-----|---------|-------------------|
| `export.default_format` | `"json"` | `--format` |
| `export.pretty_json` | `true` | `--pretty` |

### `[aliases]` section

Define short names for server commands. Alias values are full shell commands passed to the server launcher.

```bash
mcp-debugger config set aliases.dev "python -m my_mcp_server --debug"
mcp-debugger replay 5 --alias dev
```

Precedence when both are given: `--server` overrides `--alias`.

---

## Examples

### Set a default server for all replays

```bash
mcp-debugger config set replay.default_server "npx -y @modelcontextprotocol/server-filesystem /tmp"
mcp-debugger replay 42   # no --server needed
```

### Enable OTLP export by default

```bash
mcp-debugger config set replay.otlp_export true
mcp-debugger config set replay.otlp_endpoint "http://jaeger:4317"
```

### Configure multiple server aliases

```bash
mcp-debugger config set aliases.local "python -m myserver --port 8080"
mcp-debugger config set aliases.staging "ssh staging npx -y @mcp/server-fs /data"

mcp-debugger replay 10 --alias local
mcp-debugger replay 10 --alias staging
```

### Use markdown export by default

```bash
mcp-debugger config set export.default_format markdown
mcp-debugger export 42         # now exports as Markdown automatically
mcp-debugger export 42 --format json  # explicit flag overrides config
```
