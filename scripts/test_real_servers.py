"""
Real MCP server compatibility test script.

Usage:
    python scripts/test_real_servers.py --server "npx -y @modelcontextprotocol/server-filesystem /tmp"
    python scripts/test_real_servers.py --all
    python scripts/test_real_servers.py --server-name filesystem

Exit codes:
    0 - all tested servers PASS
    1 - one or more servers FAIL
    2 - usage error
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Force UTF-8 output on Windows to avoid charmap encoding errors
if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Make sure the src package is importable when run from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ---------------------------------------------------------------------------
# Server catalogue
# ---------------------------------------------------------------------------

SERVERS: Dict[str, Dict[str, Any]] = {
    "filesystem": {
        "command": "npx -y @modelcontextprotocol/server-filesystem {tmpdir}",
        "env_required": [],
        "tool_args": {
            "read_file": {"path": "{tmpfile}"},
            "list_directory": {"path": "{tmpdir}"},
            "get_file_info": {"path": "{tmpfile}"},
        },
        "startup_wait": 10.0,
        "step_timeout": 15.0,
    },
    "fetch": {
        "command": "uvx mcp-server-fetch",
        "env_required": [],
        "tool_args": {
            "fetch": {"url": "https://example.com"},
        },
        "startup_wait": 15.0,
        "step_timeout": 30.0,
    },
    "github": {
        "command": "npx -y @modelcontextprotocol/server-github",
        "env_required": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
        "tool_args": {
            "search_repositories": {"query": "mcp-debugger"},
            "list_commits": {"owner": "modelcontextprotocol", "repo": "servers", "sha": "main"},
        },
        "startup_wait": 15.0,
        "step_timeout": 30.0,
    },
    "memory": {
        "command": "npx -y @modelcontextprotocol/server-memory",
        "env_required": [],
        "tool_args": {
            "create_entities": {
                "entities": [{"name": "test", "entityType": "test", "observations": ["hello"]}]
            },
        },
        "startup_wait": 10.0,
        "step_timeout": 15.0,
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(method: str, params: Any, req_id: int) -> bytes:
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
    return (json.dumps(msg) + "\n").encode()


def _make_notification(method: str, params: Any) -> bytes:
    msg = {"jsonrpc": "2.0", "method": method, "params": params}
    return (json.dumps(msg) + "\n").encode()


async def _read_response(
    stdout: asyncio.StreamReader,
    expected_id: int,
    timeout: float = 15.0,
) -> Optional[Dict[str, Any]]:
    """Read lines from stdout until we find the response matching expected_id."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        try:
            line_bytes = await asyncio.wait_for(stdout.readline(), timeout=min(remaining, 5.0))
        except asyncio.TimeoutError:
            continue
        if not line_bytes:
            return None
        line = line_bytes.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            # Non-JSON server log line – ignore and keep reading
            print(f"  [server log] {line[:200]}", file=sys.stderr)
            continue
        if isinstance(msg, dict) and msg.get("id") == expected_id:
            return msg
    return None  # timeout


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------


class ServerTestResult:
    def __init__(self, name: str) -> None:
        self.name = name
        self.status = "SKIP"  # PASS | FAIL | SKIP
        self.reason = ""
        self.tools_found: List[str] = []
        self.tool_calls: Dict[str, str] = {}  # tool_name -> PASS|FAIL
        self.issues: List[str] = []

    def __str__(self) -> str:
        lines = [f"\n{'=' * 60}", f"  Server : {self.name}", f"  Status : {self.status}"]
        if self.reason:
            lines.append(f"  Reason : {self.reason}")
        if self.tools_found:
            lines.append(f"  Tools  : {', '.join(self.tools_found[:10])}")
        for tool, status in self.tool_calls.items():
            lines.append(f"    {tool}: {status}")
        for issue in self.issues:
            lines.append(f"  ⚠ {issue}")
        lines.append("=" * 60)
        return "\n".join(lines)


async def run_server_test(
    name: str,
    config: Dict[str, Any],
    tmpdir: str,
    tmpfile: str,
) -> ServerTestResult:
    result = ServerTestResult(name)

    # --- Check required env vars ---
    for var in config.get("env_required", []):
        if not os.environ.get(var):
            result.status = "SKIP"
            result.reason = f"Missing required env var: {var}"
            return result

    # --- Expand command placeholders ---
    command = config["command"].format(tmpdir=tmpdir, tmpfile=tmpfile)
    startup_wait: float = config.get("startup_wait", 10.0)
    step_timeout: float = config.get("step_timeout", 15.0)
    tool_args_map: Dict[str, Any] = {
        k: json.loads(
            json.dumps(v)
            .replace("{tmpdir}", tmpdir.replace("\\", "/"))
            .replace("{tmpfile}", tmpfile.replace("\\", "/"))
        )
        for k, v in config.get("tool_args", {}).items()
    }

    print(f"\n[{name}] Starting: {command}")

    # --- Launch server ---
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ},
        )
    except Exception as e:
        result.status = "FAIL"
        result.reason = f"Failed to start server: {e}"
        return result

    assert process.stdin and process.stdout

    # Increase StreamReader limit to 10MB to handle large tool outputs and schemas
    setattr(process.stdout, "_limit", 10 * 1024 * 1024)

    req_id = 1

    async def send(data: bytes) -> None:
        process.stdin.write(data)  # type: ignore[union-attr]
        await process.stdin.drain()  # type: ignore[union-attr]

    try:
        # Give the server time to start
        await asyncio.sleep(startup_wait)

        # ---- Step 1: initialize ----
        print(f"[{name}] -> initialize")
        await send(
            _make_request(
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "mcp-debugger-compat-test", "version": "1.0"},
                },
                req_id,
            )
        )
        init_resp = await _read_response(process.stdout, req_id, timeout=step_timeout)
        req_id += 1

        if init_resp is None:
            result.status = "FAIL"
            result.reason = "No response to 'initialize' (timeout)"
            return result
        if "error" in init_resp:
            result.status = "FAIL"
            result.reason = f"initialize error: {init_resp['error']}"
            return result

        print(f"[{name}] <- initialize OK")
        proto_version = (init_resp.get("result") or {}).get("protocolVersion", "?")
        print(f"[{name}]   protocolVersion: {proto_version}")

        # ---- Step 2: notifications/initialized ----
        await send(_make_notification("notifications/initialized", {}))
        await asyncio.sleep(0.5)

        # ---- Step 3: tools/list ----
        print(f"[{name}] -> tools/list")
        await send(_make_request("tools/list", {}, req_id))
        tools_resp = await _read_response(process.stdout, req_id, timeout=step_timeout)
        req_id += 1

        if tools_resp is None:
            result.issues.append("No response to tools/list (timeout) - possible server quirk")
        elif "error" in tools_resp:
            result.issues.append(f"tools/list error: {tools_resp['error']}")
        else:
            tools_list = (tools_resp.get("result") or {}).get("tools", [])
            result.tools_found = [t.get("name", "?") for t in tools_list if isinstance(t, dict)]
            print(f"[{name}] <- tools/list: {len(result.tools_found)} tools")

        # ---- Step 4: Call up to 3 tools ----
        tools_to_call = [t for t in result.tools_found if t in tool_args_map][:3]

        # If no known tools, try the first tool from the list with an empty call
        if not tools_to_call and result.tools_found:
            tools_to_call = result.tools_found[:1]
            tool_args_map[tools_to_call[0]] = {}

        for tool_name in tools_to_call:
            args = tool_args_map.get(tool_name, {})
            print(f"[{name}] -> tools/call {tool_name}")
            await send(
                _make_request(
                    "tools/call",
                    {"name": tool_name, "arguments": args},
                    req_id,
                )
            )
            call_resp = await _read_response(process.stdout, req_id, timeout=step_timeout)
            req_id += 1

            if call_resp is None:
                result.tool_calls[tool_name] = "FAIL (timeout)"
            elif "error" in call_resp:
                result.tool_calls[tool_name] = f"FAIL ({call_resp['error'].get('message', '?')})"
                result.issues.append(f"Tool {tool_name} returned error: {call_resp['error']}")
            else:
                tool_result = call_resp.get("result", {})
                is_err = isinstance(tool_result, dict) and tool_result.get("isError", False)
                if is_err:
                    err_content = tool_result.get("content", [])
                    result.tool_calls[tool_name] = "FAIL (isError=true)"
                    result.issues.append(
                        f"Tool {tool_name} returned isError=true. Content: {err_content}"
                    )
                else:
                    result.tool_calls[tool_name] = "PASS"

        # ---- All steps passed ----
        result.status = (
            "PASS" if not any("FAIL" in v for v in result.tool_calls.values()) else "PARTIAL"
        )
        if result.status == "PASS" and result.issues:
            result.status = "PARTIAL"

    except Exception as e:
        result.status = "FAIL"
        result.reason = f"Unexpected error during test: {e}"

    finally:
        try:
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    return result


async def main(args: argparse.Namespace) -> int:
    with tempfile.TemporaryDirectory() as _raw_tmpdir:
        # Resolve to canonical long path (important on Windows where tempfile
        # may return a short path like SUSHAN~1 that the filesystem server rejects)
        tmpdir = str(Path(_raw_tmpdir).resolve())
        # Create a test file inside the temp dir
        tmpfile = os.path.join(tmpdir, "test.txt")
        with open(tmpfile, "w") as f:
            f.write("Hello from mcp-debugger compatibility test\n")

        if args.server:
            # Custom command
            cfg: Dict[str, Any] = {
                "command": args.server,
                "env_required": [],
                "tool_args": {},
                "startup_wait": args.startup_wait,
                "step_timeout": args.step_timeout,
            }
            results = [await run_server_test("custom", cfg, tmpdir, tmpfile)]
        else:
            # Named servers
            names = list(SERVERS.keys()) if args.all else [args.server_name]
            results = []
            for name in names:
                if name not in SERVERS:
                    print(f"Unknown server name: {name}. Choose from: {list(SERVERS.keys())}")
                    return 2
                results.append(await run_server_test(name, SERVERS[name], tmpdir, tmpfile))

    # --- Print summary ---
    print("\n" + "=" * 60)
    print("COMPATIBILITY TEST SUMMARY")
    print("=" * 60)
    pass_count = 0
    fail_count = 0
    skip_count = 0
    for r in results:
        print(r)
        if r.status == "PASS":
            pass_count += 1
        elif r.status == "SKIP":
            skip_count += 1
        else:
            fail_count += 1

    print(f"\nResult: {pass_count} PASS | {fail_count} FAIL | {skip_count} SKIP")

    if args.output:
        _write_markdown_report(results, args.output)
        print(f"Report written to {args.output}")

    return 0 if fail_count == 0 else 1


def _write_markdown_report(results: List[ServerTestResult], path: str) -> None:
    lines = ["# MCP Server Compatibility Report\n"]
    lines.append("| Server | Status | Tools Found | Issues |")
    lines.append("| :----- | :----: | :---------- | :----- |")
    for r in results:
        tools = ", ".join(r.tools_found[:5]) or "—"
        if len(r.tools_found) > 5:
            tools += f" (+{len(r.tools_found) - 5} more)"
        issues = "; ".join(r.issues[:3]) or "None"
        status_icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️", "PARTIAL": "⚠️"}.get(
            r.status, r.status
        )
        lines.append(f"| {r.name} | {status_icon} {r.status} | {tools} | {issues} |")
    lines.append("")
    for r in results:
        lines.append(f"\n## {r.name}\n")
        lines.append(f"**Status:** {r.status}  ")
        if r.reason:
            lines.append(f"**Reason:** {r.reason}  ")
        if r.tools_found:
            lines.append(f"**Tools discovered:** {', '.join(r.tools_found)}")
        for tool, status in r.tool_calls.items():
            lines.append(f"- `{tool}`: {status}")
        if r.issues:
            lines.append("\n**Issues:**")
            for issue in r.issues:
                lines.append(f"- {issue}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Test real MCP servers for compatibility with mcp-debugger"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--server", help="Custom server command to test")
    group.add_argument(
        "--server-name", choices=list(SERVERS.keys()), help="Named server from catalogue"
    )
    group.add_argument("--all", action="store_true", help="Test all servers in catalogue")
    parser.add_argument("--output", help="Write Markdown compatibility report to this file")
    parser.add_argument(
        "--startup-wait", type=float, default=10.0, help="Seconds to wait for server startup"
    )
    parser.add_argument(
        "--step-timeout", type=float, default=15.0, help="Seconds to wait for each step response"
    )

    parsed = parser.parse_args()
    sys.exit(asyncio.run(main(parsed)))
