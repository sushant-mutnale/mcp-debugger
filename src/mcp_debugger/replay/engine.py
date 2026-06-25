"""Core Replay Engine for replaying recorded MCP sessions."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set
from pydantic import BaseModel

from mcp_debugger.storage.database import Database
from mcp_debugger.replay.diff import DiffNode, compare_json, render_diff

logger = logging.getLogger("mcp_debugger.replay")


class ReplayedMessage(BaseModel):
    """Result of replaying a single message."""

    original_message_id: int
    method: str
    request_sent: Dict[str, Any]
    original_response: Optional[Dict[str, Any]] = None
    replayed_response: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    latency_ms: float
    matches: bool
    diff: Optional[List[DiffNode]] = None
    diff_text: Optional[str] = None


class ReplayResult(BaseModel):
    """Overall summary of a replay session."""

    replay_id: Optional[int] = None
    session_id: int
    target_server_command: str
    started_at: datetime
    ended_at: datetime
    total_messages_replayed: int
    successful_responses: int
    failed_responses: int
    mismatched_responses: int
    timed_out: int
    messages: List[ReplayedMessage]


def deep_compare(val1: Any, val2: Any, ignore_keys: Optional[Set[str]] = None) -> bool:
    """Recursively compare two JSON-compatible values, ignoring specific keys."""
    if ignore_keys is None:
        ignore_keys = {"timestamp", "latency_ms"}

    if isinstance(val1, dict) and isinstance(val2, dict):
        k1 = set(val1.keys()) - ignore_keys
        k2 = set(val2.keys()) - ignore_keys
        if k1 != k2:
            return False
        for k in k1:
            if not deep_compare(val1[k], val2[k], ignore_keys):
                return False
        return True
    elif isinstance(val1, list) and isinstance(val2, list):
        if len(val1) != len(val2):
            return False
        for i1, i2 in zip(val1, val2):
            if not deep_compare(i1, i2, ignore_keys):
                return False
        return True
    else:
        return bool(val1 == val2)


class ReplayEngine:
    """Loads recorded messages from a session and replays them to a target server."""

    def __init__(self, db: Database) -> None:
        """Initialize the ReplayEngine with a Database instance."""
        self.db = db

    async def _reader_loop(
        self,
        reader: asyncio.StreamReader,
        pending_requests: Dict[str, asyncio.Future[Dict[str, Any]]],
    ) -> None:
        """Continuously read lines from the server stdout and resolve pending requests."""
        while True:
            try:
                line_bytes = await reader.readline()
                if not line_bytes:
                    break

                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    # Non-JSON line: ignore and write to stderr
                    logger.debug("Server log: %s", line)
                    continue

                if isinstance(msg, dict) and "id" in msg:
                    msg_id = str(msg["id"])
                    if msg_id in pending_requests:
                        fut = pending_requests.pop(msg_id)
                        if not fut.done():
                            fut.set_result(msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in replay reader loop: %s", e)
                break

    async def _stderr_loop(self, reader: asyncio.StreamReader) -> None:
        """Continuously read lines from the server stderr and write them to sys.stderr."""
        while True:
            try:
                line_bytes = await reader.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace")
                sys.stderr.write(f"[server-stderr] {line}")
                sys.stderr.flush()
            except asyncio.CancelledError:
                break
            except Exception:
                break

    async def replay(
        self,
        session_id: int,
        target_server_command: str,
        timeout_ms: int = 5000,
        replay_mode: str = "exact",
        message_filter: Optional[List[str]] = None,
        persist: bool = True,
        max_messages: Optional[int] = None,
        on_message_replayed: Optional[Callable[[int, int], None]] = None,
    ) -> ReplayResult:
        """Replay client messages from session_id to a new server.

        Args:
            session_id: Source session to replay.
            target_server_command: Command to launch the server for replay.
            timeout_ms: Max wait per request-response pair.
            replay_mode: "exact" (all messages) or "selective" (filtered).
            message_filter: List of method names to replay (if selective).
            persist: Whether to save the replay result in the database.
            max_messages: Maximum number of messages to replay.
            on_message_replayed: Optional callback when a message is replayed, called with (current, total).

        Returns:
            ReplayResult containing original vs replayed responses, diff status.
        """
        started_at = datetime.now(timezone.utc)
        original_msgs = await self.db.get_replay_messages(session_id)

        # Apply selective filtering
        if replay_mode == "selective" and message_filter is not None:
            original_msgs = [m for m in original_msgs if m.get("method") in message_filter]

        # Apply max messages limit
        if max_messages is not None and max_messages > 0:
            original_msgs = original_msgs[:max_messages]

        if not original_msgs:
            # Return empty result if no messages found
            return ReplayResult(
                session_id=session_id,
                target_server_command=target_server_command,
                started_at=started_at,
                ended_at=datetime.now(timezone.utc),
                total_messages_replayed=0,
                successful_responses=0,
                failed_responses=0,
                mismatched_responses=0,
                timed_out=0,
                messages=[],
            )

        process: Optional[asyncio.subprocess.Process] = None
        # Launch target server
        try:
            process = await asyncio.create_subprocess_shell(
                target_server_command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            # Failed to spawn server command
            ended_at = datetime.now(timezone.utc)
            failed_msgs = []
            for msg in original_msgs:
                failed_msgs.append(
                    ReplayedMessage(
                        original_message_id=msg["original_message_id"],
                        method=msg["method"] or "",
                        request_sent={
                            "method": msg["method"],
                            "params": msg["params"],
                            "id": msg["message_id"],
                        },
                        original_response=msg["original_response"],
                        replayed_response=None,
                        error=f"Failed to start server: {e}",
                        latency_ms=0.0,
                        matches=False,
                    )
                )

            replay_id = None
            if persist:
                replay_id = await self.db.save_replay(
                    source_session_id=session_id,
                    target_server_command=target_server_command,
                    status="failed",
                    total_messages=len(failed_msgs),
                    mismatches=len(failed_msgs),
                    messages=[m.model_dump() for m in failed_msgs],
                    started_at=started_at.isoformat(),
                    ended_at=ended_at.isoformat(),
                )

            result = ReplayResult(
                replay_id=replay_id,
                session_id=session_id,
                target_server_command=target_server_command,
                started_at=started_at,
                ended_at=ended_at,
                total_messages_replayed=len(failed_msgs),
                successful_responses=0,
                failed_responses=len(failed_msgs),
                mismatched_responses=0,
                timed_out=0,
                messages=failed_msgs,
            )
            return result

        assert process.stdin and process.stdout
        # Increase StreamReader limit to 10MB to handle large tool outputs and schemas
        setattr(process.stdout, "_limit", 10 * 1024 * 1024)

        pending_requests: Dict[str, asyncio.Future[Dict[str, Any]]] = {}
        reader_task = asyncio.create_task(self._reader_loop(process.stdout, pending_requests))
        stderr_task = None
        if process.stderr:
            stderr_task = asyncio.create_task(self._stderr_loop(process.stderr))

        replayed_messages: List[ReplayedMessage] = []
        server_terminated = False

        try:
            for idx, msg in enumerate(original_msgs):
                method = msg["method"]

                # Apply selective filtering if requested (already done pre-loop, but kept for compatibility)
                if replay_mode == "selective" and message_filter is not None:
                    if method not in message_filter:
                        continue

                msg_id = msg["message_id"]
                params = msg["params"]
                is_notification = msg["message_type"] == "notification" or msg_id is None

                # Reconstruct payload
                payload: Dict[str, Any] = {"jsonrpc": "2.0"}
                if msg_id is not None:
                    try:
                        payload["id"] = int(msg_id)
                    except ValueError:
                        payload["id"] = msg_id
                if method is not None:
                    payload["method"] = method
                if params is not None:
                    payload["params"] = params

                payload_str = json.dumps(payload) + "\n"
                start_time = time.monotonic()
                replayed_resp = None
                error = None
                latency = 0.0
                matches = False

                if server_terminated:
                    error = "Server process terminated"
                else:
                    # Send payload
                    try:
                        process.stdin.write(payload_str.encode("utf-8"))
                        await process.stdin.drain()
                    except Exception as e:
                        error = f"Write error: {e}"
                        server_terminated = True

                    if not error:
                        if is_notification:
                            # Notifications do not have responses
                            latency = (time.monotonic() - start_time) * 1000.0
                            replayed_resp = None
                            matches = msg["original_response"] is None
                            error = None
                        else:
                            # Request: wait for response matching ID
                            fut = asyncio.get_running_loop().create_future()
                            pending_requests[str(msg_id)] = fut

                            try:
                                replayed_resp = await asyncio.wait_for(
                                    fut, timeout=timeout_ms / 1000.0
                                )
                                latency = (time.monotonic() - start_time) * 1000.0
                                matches = deep_compare(replayed_resp, msg["original_response"])
                            except asyncio.TimeoutError:
                                # Clean up pending future
                                if str(msg_id) in pending_requests:
                                    pending_requests.pop(str(msg_id))
                                latency = (time.monotonic() - start_time) * 1000.0
                                matches = False
                                error = "Timeout waiting for response"
                                # Abort remaining messages on first timeout
                                server_terminated = True
                            except Exception as e:
                                latency = (time.monotonic() - start_time) * 1000.0
                                matches = False
                                error = str(e)

                msg_diff = None
                msg_diff_text = None
                if not matches:
                    diff_node = compare_json(msg["original_response"], replayed_resp)
                    if diff_node is not None:
                        msg_diff = [diff_node]
                        msg_diff_text = render_diff(diff_node)

                replayed_messages.append(
                    ReplayedMessage(
                        original_message_id=msg["original_message_id"],
                        method=method or "",
                        request_sent=payload,
                        original_response=msg["original_response"],
                        replayed_response=replayed_resp,
                        error=error,
                        latency_ms=latency,
                        matches=matches,
                        diff=msg_diff,
                        diff_text=msg_diff_text,
                    )
                )
                if on_message_replayed:
                    on_message_replayed(idx + 1, len(original_msgs))

        finally:
            reader_task.cancel()
            if stderr_task:
                stderr_task.cancel()
            if process is not None:
                if process.stdin:
                    try:
                        process.stdin.close()
                        if hasattr(process.stdin, "wait_closed"):
                            await process.stdin.wait_closed()
                    except Exception:
                        pass
                try:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except Exception:
                    try:
                        process.kill()
                        await process.wait()
                    except Exception:
                        pass
                if hasattr(process, "_transport") and process._transport:
                    try:
                        process._transport.close()
                    except Exception:
                        pass
            try:
                await reader_task
            except asyncio.CancelledError:
                pass
            if stderr_task:
                try:
                    await stderr_task
                except asyncio.CancelledError:
                    pass
            process = None
            import gc

            gc.collect()

        ended_at = datetime.now(timezone.utc)

        # Calculate stats
        successful_responses = sum(
            1 for m in replayed_messages if m.replayed_response is not None and not m.error
        )
        failed_responses = sum(
            1 for m in replayed_messages if m.error is not None and "Timeout" not in m.error
        )
        timed_out = sum(
            1 for m in replayed_messages if m.error is not None and "Timeout" in m.error
        )
        mismatched_responses = sum(
            1 for m in replayed_messages if not m.matches and m.replayed_response is not None
        )

        status = "completed"
        if timed_out > 0:
            status = "timeout"
        elif failed_responses > 0:
            status = "failed"

        replay_id = None
        if persist:
            replay_id = await self.db.save_replay(
                source_session_id=session_id,
                target_server_command=target_server_command,
                status=status,
                total_messages=len(replayed_messages),
                mismatches=mismatched_responses + timed_out + failed_responses,
                messages=[m.model_dump() for m in replayed_messages],
                started_at=started_at.isoformat(),
                ended_at=ended_at.isoformat(),
            )

        result = ReplayResult(
            replay_id=replay_id,
            session_id=session_id,
            target_server_command=target_server_command,
            started_at=started_at,
            ended_at=ended_at,
            total_messages_replayed=len(replayed_messages),
            successful_responses=successful_responses,
            failed_responses=failed_responses,
            mismatched_responses=mismatched_responses,
            timed_out=timed_out,
            messages=replayed_messages,
        )

        return result
