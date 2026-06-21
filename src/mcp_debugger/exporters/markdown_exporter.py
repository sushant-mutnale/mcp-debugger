"""Markdown exporter – generates a human-readable session report."""

import json
from datetime import datetime, timezone
from typing import Any, Dict, IO, List, Optional

from mcp_debugger.analytics import SessionStats

# Maximum raw-JSON bytes included inside a <details> block per message.
_RAW_TRUNCATE_BYTES = 4096


def _fmt_duration(seconds: Optional[int]) -> str:
    if seconds is None:
        return "N/A"
    m, s = divmod(seconds, 60)
    return f"{m}m {s}s" if m > 0 else f"{s}s"


def _fmt_latency(ms: Optional[float]) -> str:
    if ms is None:
        return "—"
    return f"{ms:.1f}ms"


def _direction_arrow(direction: str) -> str:
    return "→ server" if direction == "client_to_server" else "← client"


def _decode_json_field(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return raw
    return raw


class MarkdownExporter:
    """Generate a Markdown session report.

    The report contains:

    * **Metadata** – session header table.
    * **Summary** – key totals.
    * **Tool Inventory** – per-tool stats table.
    * **Errors** – classified errors table.
    * **Message Log** – one row per message; with ``include_raw=True`` each
      row is followed by a ``<details>`` block containing the full JSON.
    """

    def __init__(self, include_raw: bool = False, pretty: bool = False) -> None:
        """Initialise the exporter.

        Args:
            include_raw: If ``True``, append a ``<details>`` JSON block for
                each message.
            pretty: If ``True``, pretty-print the JSON inside ``<details>``
                blocks (only relevant when *include_raw* is ``True``).
        """
        self.include_raw = include_raw
        self.pretty = pretty

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export(
        self,
        session: Dict[str, Any],
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        errors: List[Dict[str, Any]],
        stats: SessionStats,
        out: IO[str],
    ) -> None:
        """Write the full Markdown report to *out*."""
        session_id = session.get("id", "?")
        name = session.get("friendly_name") or f"Session #{session_id}"

        out.write(f"# MCP Session Report – {name}\n\n")
        self._write_metadata(session, stats, out)
        self._write_summary(stats, out)
        self._write_tools(stats, out)
        self._write_errors(errors, out)
        self._write_message_log(messages, out)

    # ------------------------------------------------------------------
    # Section writers
    # ------------------------------------------------------------------

    @staticmethod
    def _write_metadata(
        session: Dict[str, Any],
        stats: SessionStats,
        out: IO[str],
    ) -> None:
        out.write("## Metadata\n\n")
        out.write("| Property | Value |\n")
        out.write("| :------- | :---- |\n")
        rows = [
            ("Session ID", str(session.get("id", ""))),
            ("Name", session.get("friendly_name") or "—"),
            ("Server command", f"`{session.get('server_command', '')}`"),
            ("Started", str(session.get("started_at") or "—")),
            ("Ended", str(session.get("ended_at") or "—")),
            ("Duration", _fmt_duration(stats.duration_seconds)),
            ("Status", str(session.get("status") or "—")),
        ]
        for label, value in rows:
            out.write(f"| {label} | {value} |\n")
        out.write("\n")

    @staticmethod
    def _write_summary(stats: SessionStats, out: IO[str]) -> None:
        total_errors = sum(stats.errors_by_category.values())
        total = stats.total_messages
        error_rate_pct = f"{(total_errors / total * 100):.1f}%" if total > 0 else "0%"
        out.write("## Summary\n\n")
        out.write(
            f"- **Total messages:** {total} "
            f"({stats.client_to_server_count} → server, "
            f"{stats.server_to_client_count} ← client)\n"
        )
        out.write(f"- **Errors:** {total_errors} ({error_rate_pct} error rate)\n")
        out.write(f"- **Tools called:** {len(stats.top_tools)}\n")
        if stats.latency_avg is not None:
            out.write(f"- **Avg latency:** {_fmt_latency(stats.latency_avg)}\n")
        out.write("\n")

    @staticmethod
    def _write_tools(stats: SessionStats, out: IO[str]) -> None:
        out.write("## Tool Inventory\n\n")
        if not stats.top_tools:
            out.write("_No tools discovered in this session._\n\n")
            return
        out.write("| Tool | Calls | Avg Latency | Error Rate |\n")
        out.write("| :--- | :---: | :---: | :---: |\n")
        for tool in stats.top_tools:
            avg_lat = _fmt_latency(tool.avg_latency_ms)
            err_pct = f"{tool.error_rate * 100:.0f}%"
            out.write(f"| {tool.name} | {tool.calls} | {avg_lat} | {err_pct} |\n")
        out.write("\n")

    @staticmethod
    def _write_errors(errors: List[Dict[str, Any]], out: IO[str]) -> None:
        out.write("## Errors\n\n")
        if not errors:
            out.write("_No errors recorded._\n\n")
            return
        out.write("| Type | Code | Message | Suggestion |\n")
        out.write("| :--- | :---: | :--- | :--- |\n")
        for err in errors:
            etype = err.get("error_type") or "—"
            code = str(err.get("error_code") or "—")
            msg = (err.get("error_message") or "").replace("|", "\\|")
            sug = (err.get("suggestion") or "—").replace("|", "\\|")
            out.write(f"| {etype} | {code} | {msg} | {sug} |\n")
        out.write("\n")

    def _write_message_log(self, messages: List[Dict[str, Any]], out: IO[str]) -> None:
        out.write("## Message Log\n\n")
        if not messages:
            out.write("_No messages recorded._\n\n")
            return

        out.write("| # | Direction | Method | Timestamp | Latency |\n")
        out.write("| :- | :-------- | :----- | :-------- | :------ |\n")
        for i, msg in enumerate(messages, start=1):
            direction = _direction_arrow(msg.get("direction") or "")
            method = msg.get("method") or "—"
            ts_raw = msg.get("timestamp")
            ts_str: str
            if isinstance(ts_raw, (int, float)):
                ts_str = datetime.fromtimestamp(ts_raw / 1000.0, tz=timezone.utc).strftime(
                    "%H:%M:%S.%f"
                )[:-3]  # trim to milliseconds
            else:
                ts_str = str(ts_raw or "—")
            latency = _fmt_latency(msg.get("latency_ms"))
            out.write(f"| {i} | {direction} | `{method}` | {ts_str} | {latency} |\n")

        if self.include_raw:
            out.write("\n")
            for i, msg in enumerate(messages, start=1):
                direction = msg.get("direction") or ""
                method = msg.get("method") or "message"
                out.write(f"<details>\n<summary>Message #{i}: {method} ({direction})</summary>\n\n")
                # Build a clean dict (decode JSON fields)
                clean: Dict[str, Any] = {
                    k: _decode_json_field(v) for k, v in msg.items() if k not in ("session_id",)
                }
                raw_json = json.dumps(clean, indent=2 if self.pretty else None, default=str)
                if len(raw_json) > _RAW_TRUNCATE_BYTES:
                    raw_json = raw_json[:_RAW_TRUNCATE_BYTES] + "\n... [truncated]"
                out.write(f"```json\n{raw_json}\n```\n\n</details>\n\n")
