"""Analytics engine for calculating session statistics and comparisons."""

import json
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from mcp_debugger.storage.database import Database

# Unicode block elements for sparkline: 8 levels
BLOCKS = [" ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]


class ToolMetric(BaseModel):
    """Calculated metrics for a single tool."""

    name: str
    calls: int = 0
    avg_latency_ms: Optional[float] = None
    error_rate: float = 0.0
    errors_count: int = 0


class SessionStats(BaseModel):
    """Container for computed session statistics."""

    session_id: int
    friendly_name: Optional[str] = None
    server_command: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    status: str
    duration_seconds: Optional[int] = None
    total_messages: int = 0
    client_to_server_count: int = 0
    server_to_client_count: int = 0
    top_tools: List[ToolMetric] = Field(default_factory=list)
    errors_by_category: Dict[str, int] = Field(default_factory=dict)
    latency_min: Optional[float] = None
    latency_max: Optional[float] = None
    latency_avg: Optional[float] = None
    latency_trend: List[float] = Field(default_factory=list)
    method_distribution: Dict[str, int] = Field(default_factory=dict)
    error_trend: List[int] = Field(default_factory=list)


class ToolChange(BaseModel):
    """Calculated deltas for a specific tool between two sessions."""

    name: str
    calls_a: int = 0
    calls_b: int = 0
    change_pct: Optional[float] = None  # None if division by zero
    change_str: str  # e.g. "+15%", "-75%", "removed", "new"
    avg_latency_a: Optional[float] = None
    avg_latency_b: Optional[float] = None
    avg_latency_change_pct: Optional[float] = None


class ComparisonStats(BaseModel):
    """Container for comparative session statistics."""

    session_id_a: int
    session_id_b: int
    duration_a: Optional[int] = None
    duration_b: Optional[int] = None
    duration_change_pct: Optional[float] = None
    duration_change_str: str = ""
    messages_a: int = 0
    messages_b: int = 0
    messages_change_abs: int = 0
    tool_changes: List[ToolChange] = Field(default_factory=list)
    new_tools: List[str] = Field(default_factory=list)
    removed_tools: List[str] = Field(default_factory=list)
    errors_a: int = 0
    errors_b: int = 0
    error_rate_a: float = 0.0
    error_rate_b: float = 0.0
    error_rate_change_str: str = ""


def generate_sparkline(values: List[float], width: int = 30) -> str:
    """Generate a horizontal Unicode sparkline representing values over time.
    
    If length of values is greater than target width, downsamples by averaging.
    """
    if not values:
        return ""

    # Downsample if needed
    if len(values) > width:
        chunk_size = len(values) / width
        sampled = []
        for i in range(width):
            start = int(i * chunk_size)
            end = int((i + 1) * chunk_size)
            if start == end:
                end = start + 1
            chunk = values[start:end]
            if chunk:
                sampled.append(sum(chunk) / len(chunk))
        values = sampled

    min_v = min(values)
    max_v = max(values)

    if max_v == min_v:
        # If all values are 0 (common for error count), show empty/lowest bar
        if max_v == 0:
            return " " * len(values)
        # Otherwise show middle bar
        return "▄" * len(values)

    sparkline = []
    for val in values:
        # Scale to index 0-7
        idx = int(((val - min_v) / (max_v - min_v)) * 7)
        idx = max(0, min(7, idx))
        sparkline.append(BLOCKS[idx])

    return "".join(sparkline)


def generate_bar_chart(counts: Dict[str, int], max_width: int = 30) -> List[Tuple[str, int, float, str]]:
    """Generate bar chart segments (label, count, percentage, bar_string) sorted by count descending."""
    if not counts:
        return []

    total = sum(counts.values())
    sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)

    results = []
    for label, count in sorted_items:
        pct = count / total if total > 0 else 0.0
        filled = int(pct * max_width)
        empty = max_width - filled
        bar_str = "█" * filled + "░" * empty
        results.append((label, count, pct, bar_str))

    return results


async def aggregate_session_stats(db: Database, session_id: int) -> SessionStats:
    """Query database and calculate aggregates for a single session."""
    session = await db.get_session(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")

    # Fetch messages and errors
    messages = await db.get_messages(session_id)
    errors = await db.get_errors(session_id)

    # Compute client vs server message counts, and method distribution
    c2s_count = 0
    s2c_count = 0
    method_dist: Dict[str, int] = defaultdict(int)

    # We also keep track of error flags chronologically for the error trend sparkline
    chrono_errors: List[int] = []

    for msg in messages:
        direction = msg.get("direction")
        if direction == "client_to_server":
            c2s_count += 1
        elif direction == "server_to_client":
            s2c_count += 1

        method = msg.get("method")
        if method:
            method_dist[method] += 1

        # Check for error status
        is_err = False
        if msg.get("error") is not None:
            is_err = True
        elif msg.get("message_type") == "response" and msg.get("result") is not None:
            try:
                res = json.loads(msg["result"])
                if isinstance(res, dict) and res.get("isError") is True:
                    is_err = True
            except Exception:
                pass
        
        # We only look at response messages (server_to_client) or requests that errored for trend
        # For simplicity, track error flags for all server_to_client responses chronologically
        if direction == "server_to_client":
            chrono_errors.append(1 if is_err else 0)

    # Compute latency list
    latency_list = [
        msg["latency_ms"]
        for msg in messages
        if msg.get("latency_ms") is not None
    ]

    # Compute tool usage metrics
    # Query all request-response pairs for tools/call
    conn = await db._get_conn()
    tool_calls: Dict[str, List[Tuple[Optional[float], bool]]] = defaultdict(list)
    try:
        async with conn.execute(
            """
            SELECT 
                req.params as req_params,
                resp.latency_ms as latency_ms,
                resp.result as resp_result,
                resp.error as resp_error
            FROM messages req
            LEFT JOIN messages resp ON req.session_id = resp.session_id 
                                    AND req.message_id = resp.message_id 
                                    AND resp.message_type = 'response'
            WHERE req.session_id = ? 
              AND req.method = 'tools/call' 
              AND req.message_type = 'request'
            """,
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                req_params_str = row[0]
                latency_ms = row[1]
                resp_result_str = row[2]
                resp_error_str = row[3]

                tool_name = "unknown"
                if req_params_str:
                    try:
                        params = json.loads(req_params_str)
                        if isinstance(params, dict) and "name" in params:
                            tool_name = params["name"]
                    except Exception:
                        pass

                is_error = False
                if resp_error_str:
                    is_error = True
                elif resp_result_str:
                    try:
                        res = json.loads(resp_result_str)
                        if isinstance(res, dict) and res.get("isError") is True:
                            is_error = True
                    except Exception:
                        pass

                tool_calls[tool_name].append((latency_ms, is_error))
    except Exception:
        # Fallback or log warning
        pass

    top_tools: List[ToolMetric] = []
    for tname, calls in tool_calls.items():
        total_calls = len(calls)
        errors_count = sum(1 for c in calls if c[1])
        error_rate = (errors_count / total_calls) if total_calls > 0 else 0.0

        latencies = [c[0] for c in calls if c[0] is not None]
        avg_lat = (sum(latencies) / len(latencies)) if latencies else None

        top_tools.append(
            ToolMetric(
                name=tname,
                calls=total_calls,
                avg_latency_ms=avg_lat,
                error_rate=error_rate,
                errors_count=errors_count,
            )
        )
    # Sort tools by call count descending
    top_tools.sort(key=lambda x: x.calls, reverse=True)

    # Compute errors by category
    errors_by_cat: Dict[str, int] = defaultdict(int)
    for err in errors:
        cat = err.get("error_type") or "unknown"
        errors_by_cat[cat] += 1

    # Latency aggregates
    lat_min = min(latency_list) if latency_list else None
    lat_max = max(latency_list) if latency_list else None
    lat_avg = (sum(latency_list) / len(latency_list)) if latency_list else None

    # Parse timestamps for duration if needed
    duration_sec = session.get("duration_seconds")
    if duration_sec is None and session.get("started_at"):
        try:
            started = datetime.strptime(session["started_at"], "%Y-%m-%d %H:%M:%S")
            ended = datetime.strptime(session["ended_at"], "%Y-%m-%d %H:%M:%S") if session.get("ended_at") else datetime.now()
            duration_sec = int((ended - started).total_seconds())
        except Exception:
            pass

    return SessionStats(
        session_id=session_id,
        friendly_name=session.get("friendly_name"),
        server_command=session.get("server_command") or "",
        started_at=session.get("started_at"),
        ended_at=session.get("ended_at"),
        status=session.get("status") or "unknown",
        duration_seconds=duration_sec,
        total_messages=len(messages),
        client_to_server_count=c2s_count,
        server_to_client_count=s2c_count,
        top_tools=top_tools,
        errors_by_category=dict(errors_by_cat),
        latency_min=lat_min,
        latency_max=lat_max,
        latency_avg=lat_avg,
        latency_trend=latency_list,
        method_distribution=dict(method_dist),
        error_trend=chrono_errors,
    )


def compare_sessions_stats(stats_a: SessionStats, stats_b: SessionStats) -> ComparisonStats:
    """Compare two SessionStats aggregates and calculate deltas."""
    dur_a = stats_a.duration_seconds
    dur_b = stats_b.duration_seconds
    dur_pct = None
    dur_change_str = "—"
    if dur_a is not None and dur_b is not None:
        if dur_a > 0:
            dur_pct = ((dur_b - dur_a) / dur_a) * 100
            if dur_b < dur_a:
                dur_change_str = f"↓ {abs(dur_pct):.0f}% faster"
            elif dur_b > dur_a:
                dur_change_str = f"↑ {abs(dur_pct):.0f}% slower"
            else:
                dur_change_str = "no change"
        else:
            dur_change_str = "—"

    msg_a = stats_a.total_messages
    msg_b = stats_b.total_messages
    msg_diff = msg_b - msg_a

    # Maps tool names to stats
    tools_a_map = {t.name: t for t in stats_a.top_tools}
    tools_b_map = {t.name: t for t in stats_b.top_tools}

    all_tool_names = set(tools_a_map.keys()) | set(tools_b_map.keys())
    tool_changes: List[ToolChange] = []
    new_tools: List[str] = []
    removed_tools: List[str] = []

    for name in all_tool_names:
        ta = tools_a_map.get(name)
        tb = tools_b_map.get(name)

        if ta and not tb:
            removed_tools.append(name)
            tool_changes.append(
                ToolChange(
                    name=name,
                    calls_a=ta.calls,
                    calls_b=0,
                    change_pct=None,
                    change_str="✗ removed",
                    avg_latency_a=ta.avg_latency_ms,
                    avg_latency_b=None,
                    avg_latency_change_pct=None,
                )
            )
        elif tb and not ta:
            new_tools.append(name)
            tool_changes.append(
                ToolChange(
                    name=name,
                    calls_a=0,
                    calls_b=tb.calls,
                    change_pct=None,
                    change_str="★ new",
                    avg_latency_a=None,
                    avg_latency_b=tb.avg_latency_ms,
                    avg_latency_change_pct=None,
                )
            )
        elif ta and tb:
            diff = tb.calls - ta.calls
            pct = ((tb.calls - ta.calls) / ta.calls) * 100 if ta.calls > 0 else 0.0
            if diff > 0:
                change_str = f"↑ +{pct:.0f}%"
            elif diff < 0:
                change_str = f"↓ {pct:.0f}%"
            else:
                change_str = "no change"

            lat_change_pct = None
            if ta.avg_latency_ms is not None and tb.avg_latency_ms is not None and ta.avg_latency_ms > 0:
                lat_change_pct = ((tb.avg_latency_ms - ta.avg_latency_ms) / ta.avg_latency_ms) * 100

            tool_changes.append(
                ToolChange(
                    name=name,
                    calls_a=ta.calls,
                    calls_b=tb.calls,
                    change_pct=pct,
                    change_str=change_str,
                    avg_latency_a=ta.avg_latency_ms,
                    avg_latency_b=tb.avg_latency_ms,
                    avg_latency_change_pct=lat_change_pct,
                )
            )

    # Errors calculation
    err_a = sum(stats_a.errors_by_category.values())
    err_b = sum(stats_b.errors_by_category.values())

    err_rate_a = (err_a / msg_a) * 100 if msg_a > 0 else 0.0
    err_rate_b = (err_b / msg_b) * 100 if msg_b > 0 else 0.0

    if err_rate_b < err_rate_a:
        err_rate_change_str = "↓ improvement"
    elif err_rate_b > err_rate_a:
        err_rate_change_str = "↑ regression"
    else:
        err_rate_change_str = "no change"

    return ComparisonStats(
        session_id_a=stats_a.session_id,
        session_id_b=stats_b.session_id,
        duration_a=dur_a,
        duration_b=dur_b,
        duration_change_pct=dur_pct,
        duration_change_str=dur_change_str,
        messages_a=msg_a,
        messages_b=msg_b,
        messages_change_abs=msg_diff,
        tool_changes=tool_changes,
        new_tools=new_tools,
        removed_tools=removed_tools,
        errors_a=err_a,
        errors_b=err_b,
        error_rate_a=err_rate_a,
        error_rate_b=err_rate_b,
        error_rate_change_str=err_rate_change_str,
    )
