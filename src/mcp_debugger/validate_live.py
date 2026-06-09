"""Runner for live MCP server protocol validation."""

import asyncio
import json
import logging
import os
import tempfile
from typing import List, Tuple

from mcp_debugger.protocol.validator import ProtocolValidator, ValidationResult
from mcp_debugger.proxy.stdio_proxy import split_command
from mcp_debugger.storage.database import Database

logger = logging.getLogger("mcp_debugger.validate_live")


async def run_live_validation(server_command: str) -> Tuple[int, List[ValidationResult]]:
    """Starts the server, executes a predefined test sequence, captures all messages,

    and returns (session_id, validation_results).
    """
    # Create a unique temporary database file
    fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    db = Database(db_path=temp_path)
    await db.connect()

    session_id = await db.create_session(
        server_command=server_command, friendly_name="temp-validate"
    )
    if session_id == -1:
        await db.close()
        try:
            os.remove(temp_path)
        except Exception:
            pass
        return -1, [
            ValidationResult(
                rule_name="database_init",
                passed=False,
                severity="critical",
                message="Failed to initialize temporary validation database.",
            )
        ]

    results: List[ValidationResult] = []
    process = None

    args = split_command(server_command)
    if not args:
        await db.close()
        try:
            os.remove(temp_path)
        except Exception:
            pass
        return session_id, [
            ValidationResult(
                rule_name="server_startup",
                passed=False,
                severity="critical",
                message=f"No valid server command arguments parsed from '{server_command}'.",
            )
        ]

    async def _execute_handshake_sequence() -> None:
        nonlocal process
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            try:
                process = await asyncio.create_subprocess_shell(
                    server_command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except Exception as e:
                raise RuntimeError(f"Failed to spawn server subprocess shell: {e}")
        except Exception as e:
            raise RuntimeError(f"Failed to spawn server subprocess: {e}")

        # Send initialize request
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "mcp-debugger-validator", "version": "0.1.0"},
            },
        }
        await db.log_message(session_id, "client_to_server", init_req)
        if process.stdin:
            process.stdin.write((json.dumps(init_req) + "\n").encode("utf-8"))
            await process.stdin.drain()

        # Wait for initialize response
        init_response_found = False
        if process.stdout:
            for _ in range(20):
                line_bytes = await process.stdout.readline()
                if not line_bytes:
                    raise EOFError("Server stdout closed while waiting for initialize response")
                line = line_bytes.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    await db.log_message(session_id, "server_to_client", {"raw": line})
                    continue

                await db.log_message(session_id, "server_to_client", payload)
                if isinstance(payload, dict) and payload.get("id") == 1:
                    init_response_found = True
                    break

        if not init_response_found:
            raise RuntimeError("Initialize response not received or ID mismatch")

        # Send notifications/initialized
        initialized_notif = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        await db.log_message(session_id, "client_to_server", initialized_notif)
        if process.stdin:
            process.stdin.write((json.dumps(initialized_notif) + "\n").encode("utf-8"))
            await process.stdin.drain()

        # Send tools/list request
        tools_req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
        }
        await db.log_message(session_id, "client_to_server", tools_req)
        if process.stdin:
            process.stdin.write((json.dumps(tools_req) + "\n").encode("utf-8"))
            await process.stdin.drain()

        # Wait for tools/list response
        tools_response_found = False
        if process.stdout:
            for _ in range(20):
                line_bytes = await process.stdout.readline()
                if not line_bytes:
                    raise EOFError("Server stdout closed while waiting for tools/list response")
                line = line_bytes.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    await db.log_message(session_id, "server_to_client", {"raw": line})
                    continue

                await db.log_message(session_id, "server_to_client", payload)
                if isinstance(payload, dict) and payload.get("id") == 2:
                    tools_response_found = True
                    # Extract and log tools to DB
                    result = payload.get("result")
                    if isinstance(result, dict) and "tools" in result:
                        tools_list = result["tools"]
                        if isinstance(tools_list, list):
                            for t in tools_list:
                                await db.log_tool(session_id, t)
                    break

        if not tools_response_found:
            raise RuntimeError("tools/list response not received or ID mismatch")

    try:
        # Wrap everything in a 10s timeout
        await asyncio.wait_for(_execute_handshake_sequence(), timeout=10.0)
    except asyncio.TimeoutError:
        results.append(
            ValidationResult(
                rule_name="handshake_timeout",
                passed=False,
                severity="critical",
                message="Server failed to complete handshake within 10 seconds timeout.",
            )
        )
    except EOFError as e:
        results.append(
            ValidationResult(
                rule_name="server_connection",
                passed=False,
                severity="critical",
                message=f"Connection lost: {e}",
            )
        )
    except Exception as e:
        results.append(
            ValidationResult(
                rule_name="server_startup",
                passed=False,
                severity="critical",
                message=str(e),
            )
        )
    finally:
        if process:
            try:
                process.terminate()
                await process.wait()
            except Exception:
                pass

    # Run session validator on the logged messages
    try:
        validator = ProtocolValidator()
        session_results = await validator.validate_session(session_id, db)
        results.extend(session_results)
    except Exception as e:
        results.append(
            ValidationResult(
                rule_name="validation_engine",
                passed=False,
                severity="critical",
                message=f"Validation engine encountered an error: {e}",
            )
        )

    await db.close()
    try:
        os.remove(temp_path)
    except Exception:
        pass

    return session_id, results
