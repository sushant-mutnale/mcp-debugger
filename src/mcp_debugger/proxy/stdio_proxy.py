"""Asynchronous stdio proxy core for intercepting MCP sessions."""

import asyncio
import json
import logging
import shlex
import sys
from typing import Any, List, Optional

from mcp_debugger.protocol.schemas import parse_jsonrpc_message
from mcp_debugger.protocol.error_classifier import ErrorClassifier
from mcp_debugger.storage.database import Database

logger = logging.getLogger("mcp_debugger.proxy")


def split_command(cmd: str) -> List[str]:
    """Parse a server command string into arguments, handling Windows path slashes and quotes."""
    return shlex.split(cmd, posix=True)


class StdioProxy:
    """Stdio proxy engine that runs between an MCP client and server."""

    def __init__(
        self,
        server_command: str,
        database: Database,
        session_id: int,
        verbose: bool = False,
    ) -> None:
        """Initialize standard I/O proxy with database connection and session mappings."""
        self.server_command = server_command
        self.database = database
        self.session_id = session_id
        self.verbose = verbose
        self.process: Optional[asyncio.subprocess.Process] = None
        self.process_exit_code: Optional[int] = None
        self._running_tasks: List[asyncio.Task[Any]] = []

    async def _read_stdin_to_queue(
        self, queue: asyncio.Queue[Optional[str]], loop: asyncio.AbstractEventLoop
    ) -> None:
        """Read lines from sys.stdin in a background thread and push them onto the async queue."""
        import threading

        def blocking_read() -> None:
            while True:
                try:
                    line = sys.stdin.readline()
                    if not line:  # EOF
                        break
                    loop.call_soon_threadsafe(queue.put_nowait, line)
                except Exception as e:
                    logger.warning("Error reading from standard input: %s", e)
                    break
            loop.call_soon_threadsafe(queue.put_nowait, None)

        # Spawn a daemon thread so it does not block interpreter shutdown
        thread = threading.Thread(target=blocking_read, daemon=True)
        thread.start()
        await asyncio.sleep(0)  # Yield control to let the thread spin up

    async def run(self) -> int:
        """Start the subprocess, instantiate the pipeline readers, and run the event piping loop."""
        # Split command arguments
        args = split_command(self.server_command)
        if not args:
            logger.error("No valid server command arguments parsed.")
            return 1

        logger.info("Launching server subprocess: %s", args)
        try:
            self.process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=None,  # inherit stderr so we can see server logging in terminal
            )
        except FileNotFoundError:
            # Fallback to shell invocation on Windows if direct command lookup failed
            logger.info("Direct executable execution failed. Falling back to shell execution...")
            try:
                self.process = await asyncio.create_subprocess_shell(
                    self.server_command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=None,
                )
            except Exception as e:
                logger.error("Failed to spawn server subprocess shell: %s", e)
                return 1
        except Exception as e:
            logger.error("Failed to spawn server subprocess: %s", e)
            return 1

        if self.process and self.process.stdout:
            # Increase StreamReader limit to 10MB to handle large tool outputs and schemas
            setattr(self.process.stdout, "_limit", 10 * 1024 * 1024)

        queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        # Start stdin thread reader
        stdin_task = asyncio.create_task(self._read_stdin_to_queue(queue, loop))

        # Start pipe listener coroutines
        client_task = asyncio.create_task(self._client_to_server_loop(queue))
        server_task = asyncio.create_task(self._server_to_client_loop())
        monitor_task = asyncio.create_task(self._monitor_subprocess())

        self._running_tasks = [client_task, server_task, monitor_task]

        # Enable batch writes – the proxy is the only high-throughput writer
        self.database.start_flush_task()

        try:
            await asyncio.gather(*self._running_tasks, return_exceptions=True)
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("Standard I/O proxy loop interrupted.")
        finally:
            stdin_task.cancel()
            await self._cleanup()

        return self.process_exit_code if self.process_exit_code is not None else 0

    async def _client_to_server_loop(self, queue: asyncio.Queue[Optional[str]]) -> None:
        """Loop reading from client standard input queue and forwarding to server stdin."""
        try:
            while True:
                line = await queue.get()
                if line is None:
                    logger.info("Client standard input EOF reached. Initiating shutdown.")
                    break

                # Process and log message
                await self._handle_message(line, direction="client_to_server")

                # Forward raw bytes to server
                if self.process and self.process.stdin:
                    try:
                        self.process.stdin.write(line.encode("utf-8"))
                        await self.process.stdin.drain()
                    except Exception as e:
                        logger.warning("Failed to forward bytes to server stdin: %s", e)
                        break
        finally:
            if self.process and self.process.stdin:
                try:
                    self.process.stdin.close()
                except Exception:
                    pass

    async def _server_to_client_loop(self) -> None:
        """Loop reading from server standard output pipe and forwarding to client stdout."""
        if not self.process or not self.process.stdout:
            return

        while True:
            try:
                line_bytes = await self.process.stdout.readline()
                if not line_bytes:
                    logger.info("Server standard output EOF reached. Initiating shutdown.")
                    break

                line = line_bytes.decode("utf-8")

                # Check if the line is valid JSON before forwarding.
                # Non-JSON lines (e.g. Node.js debug logs written to stdout) must NOT
                # be forwarded to the client – that would corrupt its JSON-RPC stream.
                stripped = line.strip()
                if stripped:
                    try:
                        json.loads(stripped)
                        is_json = True
                    except json.JSONDecodeError:
                        is_json = False
                else:
                    is_json = True  # blank lines are harmless; forward them

                if is_json:
                    # Process, log, and forward valid JSON-RPC messages
                    await self._handle_message(line, direction="server_to_client")
                    sys.stdout.write(line)
                    sys.stdout.flush()
                else:
                    # Non-JSON: print to stderr so the user can see it, but do NOT
                    # forward to client stdout and do NOT record as a protocol error.
                    print(
                        f"[mcp-debugger] server log: {stripped[:500]}",
                        file=sys.stderr,
                    )
                    await self.database.log_raw_line(
                        session_id=self.session_id,
                        source="server_stdout",
                        raw_text=stripped,
                    )
            except Exception as e:
                logger.warning("Error reading from server standard output: %s", e)
                break

    async def _monitor_subprocess(self) -> None:
        """Monitor server subprocess exit code and shutdown standard I/O pipes on exit."""
        if not self.process:
            return
        code = await self.process.wait()
        self.process_exit_code = code
        logger.info("Server subprocess exited with code %s", code)

        # Cancel active pipe loops on process termination
        for task in self._running_tasks:
            if task != asyncio.current_task() and not task.done():
                task.cancel()

    # ---- Large-message size limit (bytes) ---------------------------
    _WARN_SIZE = 1 * 1024 * 1024  # 1 MB  – warn but still store
    _MAX_SIZE = 10 * 1024 * 1024  # 10 MB – truncate storage

    async def _handle_message(self, line: str, direction: str) -> None:
        """Safely decode, validate, and log JSON-RPC messages to the database."""
        stripped = line.strip()
        if not stripped:
            return

        # Guard against pathologically large messages
        msg_bytes = len(stripped.encode("utf-8"))
        if msg_bytes > self._WARN_SIZE:
            print(
                f"[mcp-debugger warning] Large message from {direction}: {msg_bytes / 1024:.0f} KB",
                file=sys.stderr,
            )
        if msg_bytes > self._MAX_SIZE:
            print(
                "[mcp-debugger warning] Message exceeds 10 MB limit – skipping storage.",
                file=sys.stderr,
            )
            # Still forward to client/server but do not store
            return

        try:
            payload = json.loads(stripped)

            # If server response to tools/list, perform tool logging
            if direction == "server_to_client" and isinstance(payload, dict):
                result = payload.get("result")
                if isinstance(result, dict) and "tools" in result:
                    tools_list = result["tools"]
                    if isinstance(tools_list, list):
                        for t in tools_list:
                            await self.database.log_tool(self.session_id, t)

            message_id: Optional[int] = None
            try:
                # Attempt standard Pydantic schema validation
                msg = parse_jsonrpc_message(payload)
                try:
                    message_id = await self.database.log_message(
                        session_id=self.session_id, direction=direction, message=msg
                    )
                except Exception as db_err:
                    print(
                        f"[mcp-debugger error] Failed to log message to database: {db_err}",
                        file=sys.stderr,
                    )
            except Exception as val_err:
                if self.verbose:
                    logger.debug("Validation failed for message: %s (Error: %s)", stripped, val_err)
                # Log raw payload to SQLite on schema mismatches
                try:
                    message_id = await self.database.log_message(
                        session_id=self.session_id, direction=direction, message=payload
                    )
                except Exception as db_err:
                    print(
                        f"[mcp-debugger error] Failed to log raw message to database: {db_err}",
                        file=sys.stderr,
                    )

            if message_id is not None and message_id > 0:
                classifier = ErrorClassifier()
                classification = classifier.classify(payload)
                if classification is not None:
                    cat, msg_text, sug = classification
                    err_code = None
                    if "error" in payload and isinstance(payload["error"], dict):
                        raw_code = payload["error"].get("code")
                        if raw_code is not None:
                            try:
                                err_code = int(raw_code)
                            except Exception:
                                pass
                    try:
                        await self.database.log_error(
                            session_id=self.session_id,
                            message_id=message_id,
                            error_type=cat,
                            error_message=msg_text,
                            suggestion=sug,
                            error_code=err_code,
                        )
                    except Exception as db_err:
                        print(
                            f"[mcp-debugger error] Failed to log classified error to database: {db_err}",
                            file=sys.stderr,
                        )
        except json.JSONDecodeError as json_err:
            # Print warnings strictly to stderr to prevent interference with stdout stream
            print(
                f"[mcp-debugger warning] Intercepted non-JSON line from {direction}: "
                f"{stripped[:200]}... (Error: {json_err})",
                file=sys.stderr,
            )
            # Log parser failure details in database errors
            try:
                await self.database.log_error(
                    session_id=self.session_id,
                    message_id=None,
                    error_type="protocol",
                    error_message=f"Malformed JSON: {json_err}",
                    suggestion="Ensure messages conform to standard JSON format.",
                    error_code=-32700,
                    stack_trace=stripped,
                )
            except Exception as db_err:
                print(
                    f"[mcp-debugger error] Failed to log error to database: {db_err}",
                    file=sys.stderr,
                )

    async def _cleanup(self) -> None:
        """Perform graceful termination of the server subprocess and finalize the database session."""
        if self.process:
            logger.info("Terminating server subprocess...")
            try:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    logger.warning("Subprocess did not terminate gracefully. Killing it...")
                    self.process.kill()
                    await self.process.wait()
            except ProcessLookupError:
                pass
            except Exception as e:
                logger.warning("Error encountered during subprocess cleanup: %s", e)
            finally:
                self.process = None

        exit_code = self.process_exit_code if self.process_exit_code is not None else 0
        status = "completed" if exit_code == 0 else "error"
        try:
            # Stop the batch flush task and drain all remaining queued writes
            # before we record the final session status. This ensures every
            # message is persisted even if the proxy exits quickly.
            await self.database.stop_flush_task()
            await self.database.close_session(self.session_id, status=status)
            logger.info("Closed session %s with status '%s'", self.session_id, status)
        except Exception as e:
            logger.warning("Failed to close session in database: %s", e)
