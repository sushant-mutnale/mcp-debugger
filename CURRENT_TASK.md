Day 20: Configuration Management – Making the Tool Your Own
You have a feature‑rich tool now: recording, inspection, validation, error classification, statistics, export, replay with diff, and OTLP export. But users are typing long commands with many flags every time. They want defaults: “I always use --timeout 10000”, “I want OTLP export enabled by default”, “I have a preferred server command I use for replay”.

Day 20 adds a central configuration system – a user‑editable config.toml file that stores defaults for all commands, server aliases, and user preferences. This makes mcp-debugger feel polished and professional.

By the end of Day 20, users can:

bash
mcp-debugger config init                  # create default config
mcp-debugger config set replay.timeout 10000
mcp-debugger config set replay.default_server "npx -y @modelcontextprotocol/server-filesystem /tmp"
mcp-debugger config set alias.fs "npx -y @modelcontextprotocol/server-filesystem /tmp"
mcp-debugger config set alias.gh "npx -y @modelcontextprotocol/server-github"

mcp-debugger replay 42 --alias fs         # uses the alias
mcp-debugger replay 42                    # uses replay.default_server if set
🎯 Core Objective
Build a configuration management system with:

Component	Description
Config file	~/.mcp-debugger/config.toml – TOML format, human‑editable.
Config commands	mcp-debugger config init, config get, config set, config list, config reset.
Default values	Sensible defaults for all flags (timeout, OTLP endpoint, etc.).
Aliases	Short names for server commands (e.g., fs → npx -y .../server-filesystem /tmp).
Integration	All CLI commands read config values as fallbacks if flags are not provided.
Precedence	CLI flags > Config file > Hardcoded defaults.
Doctor integration	mcp-debugger doctor now checks config file validity.
Deliverables by end of day:

src/mcp_debugger/config.py – Config class with load/save/get/set.

CLI commands: config init, config get, config set, config list, config reset.

Update all existing commands to read from config.

Unit tests for config module.

Documentation.

🧠 Expected Behaviour
1. Config File Structure (~/.mcp-debugger/config.toml)
toml
# mcp-debugger configuration
# Generated with `mcp-debugger config init`

[general]
# Default output format for commands that support it
# Values: "rich", "json"
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
# Default export format (json, markdown, otlp)
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
# Short names for server commands
# Usage: mcp-debugger replay 42 --alias fs
fs = "npx -y @modelcontextprotocol/server-filesystem /tmp"
gh = "npx -y @modelcontextprotocol/server-github"
pg = "npx -y @modelcontextprotocol/server-postgres postgresql://localhost/mcp"
fetch = "npx -y @modelcontextprotocol/server-fetch"

[profiles]
# Replay profiles (also accessible via `replay profile` commands)
# Replay profiles are stored here for consistency
[profiles.prod]
server = "npx -y @modelcontextprotocol/server-filesystem /prod/data"
timeout = 10000
2. Config Commands
Command	Behaviour
mcp-debugger config init	Create default config file in ~/.mcp-debugger/config.toml (if missing). If file exists, prompt before overwriting (or use --force).
mcp-debugger config get <key>	Show the value of a specific config key (e.g., config get replay.timeout). If key is nested, use dot notation.
mcp-debugger config set <key> <value>	Set a config value. Creates the key if it doesn't exist.
mcp-debugger config list	Show all config values in a formatted table.
mcp-debugger config reset	Reset config to defaults (prompt before overwriting).
mcp-debugger config unset <key>	Remove a config key (revert to default).
Examples:

bash
mcp-debugger config set replay.timeout 10000
mcp-debugger config set aliases.fs "npx -y @modelcontextprotocol/server-filesystem /tmp"
mcp-debugger config get replay.default_server
mcp-debugger config list
3. Integration with CLI Commands
Every CLI command will now:

Load config at startup (cached to avoid repeated file reads).

For each flag, check if the flag was provided by the user. If not, check the config for a matching key. If still not found, use the hardcoded default.

Precedence: CLI flag > Config file > Code default.

Example for replay command:

python
# In replay command
timeout = ctx.obj["timeout"] or config.get("replay.timeout", 5000)
server = server or config.get("replay.default_server")
4. Config Validation
On load, validate that the config file is valid TOML.

If invalid, print a warning and use defaults.

The doctor command should check config validity and report any issues.

5. Alias Resolution
When a command receives --alias <name>:

Look up <name> in config.aliases.

If found, use the alias value as the server command.

If --server is also provided, --server takes precedence (or vice versa – decide: alias is a shorthand, so --server overrides).

6. Profiles (Optional)
Replay profiles (Day 18) are now stored in the same config file under [profiles]. The replay profile commands read/write from the config. This consolidates storage.

🔗 Integration with Previous Days
All days: Every command that accepts flags now reads from config.

Day 10 (Validate): validate.strict and validate.auto_validate config keys.

Day 17/18 (Replay): replay.* config keys.

Day 13 (Export): export.* config keys.

Day 7 (Doctor): Now checks config validity and reports issues.

⚙️ Production Considerations
Config File Location
Linux/macOS: ~/.mcp-debugger/config.toml

Windows: %APPDATA%\mcp-debugger\config.toml (use appdirs library to handle cross‑platform). For MVP, assume Linux/macOS; mention Windows support later.

File Permissions
Config file may contain sensitive data (e.g., PostgreSQL connection strings). Set permissions to 0o600 (owner read/write only) on creation.

Performance
Load config once at CLI startup and cache it.

On config set, write to file immediately (but keep cache in sync).

Error Handling
If config file is missing, treat as empty (all defaults).

If config file is corrupt, print a warning and use defaults.

If config set fails (e.g., permission denied), print error and exit.

Forward Compatibility
If a new config key is added in a future version, old config files should still work (ignore unknown keys). Use tomllib with parse_float or custom handling.

✅ Day 20 Verification Checklist
#	Check	How to verify
1	mcp-debugger config init creates ~/.mcp-debugger/config.toml	File exists, contains all sections.
2	mcp-debugger config list shows all config values in a table	Output includes general, proxy, replay, aliases, etc.
3	mcp-debugger config get replay.timeout returns the value	Correct value printed.
4	mcp-debugger config set replay.timeout 10000 updates the file	get now returns 10000.
5	CLI commands respect config values	Run mcp-debugger replay 42 (without flags) – uses replay.default_server if set.
6	CLI flags override config values	mcp-debugger replay 42 --timeout 2000 uses 2000, not config.
7	Aliases work: mcp-debugger replay 42 --alias fs	Resolves to server command from aliases.fs.
8	--alias with --server – --server wins	Confirm precedence.
9	config unset replay.timeout removes the key	get now returns default (5000).
10	config reset restores defaults	All keys revert to original defaults.
11	doctor reports config file status	Shows ✓ Config file valid or ✗ Config file invalid.
12	Config file permissions are 600	ls -l ~/.mcp-debugger/config.toml → -rw-------.
13	Corrupt config file is handled gracefully	Edit file to invalid TOML, run mcp-debugger replay – warning printed, defaults used.
14	Unit tests for config module (load, save, get, set)	pytest tests/test_config.py passes.
15	mypy --strict passes	–
16	ruff check passes	–
17	Documentation updated (docs/config.md with all keys and examples)	–
18	Commit with message feat(config): add configuration management	–