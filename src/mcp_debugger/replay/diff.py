"""JSON diffing and rendering module for MCP Replay Engine."""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, List, Optional
from pydantic import BaseModel


class DiffType(str, Enum):
    UNCHANGED = "unchanged"
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


class DiffNode(BaseModel):
    path: str
    type: DiffType
    old_value: Any = None
    new_value: Any = None
    children: List[DiffNode] = []


def compare_json(original: Any, replayed: Any, path: str = "") -> Optional[DiffNode]:
    """Recursively compare original and replayed JSON values and return a DiffNode if different.

    Returns None if the values are identical.
    """
    # Guard against huge JSON inputs for performance
    try:
        if path == "":
            orig_size = len(json.dumps(original))
            rep_size = len(json.dumps(replayed))
            if orig_size > 100 * 1024 or rep_size > 100 * 1024:
                return DiffNode(
                    path=path,
                    type=DiffType.CHANGED,
                    old_value="[JSON too large to diff]",
                    new_value="[JSON too large to diff]",
                )
    except Exception:
        pass

    # 1. Type mismatch: directly changed
    if type(original) is not type(replayed):
        return DiffNode(
            path=path,
            type=DiffType.CHANGED,
            old_value=original,
            new_value=replayed,
        )

    # 2. Dict comparison
    if isinstance(original, dict) and isinstance(replayed, dict):
        removed_keys = sorted(list(set(original.keys()) - set(replayed.keys())))
        added_keys = sorted(list(set(replayed.keys()) - set(original.keys())))
        shared_keys = sorted(list(set(original.keys()) & set(replayed.keys())))

        children: List[DiffNode] = []

        for k in removed_keys:
            children.append(
                DiffNode(
                    path=f"{path}.{k}" if path else k,
                    type=DiffType.REMOVED,
                    old_value=original[k],
                )
            )

        for k in added_keys:
            children.append(
                DiffNode(
                    path=f"{path}.{k}" if path else k,
                    type=DiffType.ADDED,
                    new_value=replayed[k],
                )
            )

        for k in shared_keys:
            child_diff = compare_json(
                original[k], replayed[k], f"{path}.{k}" if path else k
            )
            if child_diff is not None:
                children.append(child_diff)

        if children:
            return DiffNode(
                path=path,
                type=DiffType.CHANGED,
                children=children,
            )
        return None

    # 3. List comparison (index-based)
    if isinstance(original, list) and isinstance(replayed, list):
        children = []
        min_len = min(len(original), len(replayed))

        for i in range(min_len):
            child_diff = compare_json(original[i], replayed[i], f"{path}[{i}]")
            if child_diff is not None:
                children.append(child_diff)

        if len(original) > len(replayed):
            for i in range(min_len, len(original)):
                children.append(
                    DiffNode(
                        path=f"{path}[{i}]",
                        type=DiffType.REMOVED,
                        old_value=original[i],
                    )
                )
        elif len(replayed) > len(original):
            for i in range(min_len, len(replayed)):
                children.append(
                    DiffNode(
                        path=f"{path}[{i}]",
                        type=DiffType.ADDED,
                        new_value=replayed[i],
                    )
                )

        if children:
            return DiffNode(
                path=path,
                type=DiffType.CHANGED,
                children=children,
            )
        return None

    # 4. Primitive comparison
    if original != replayed:
        return DiffNode(
            path=path,
            type=DiffType.CHANGED,
            old_value=original,
            new_value=replayed,
        )

    return None


def render_diff(diff_node: DiffNode, indent_level: int = 0) -> str:
    """Renders a DiffNode tree into an inline color-coded string (Option B) using Rich markup."""
    indent = "  " * indent_level
    lines: List[str] = []

    # If it has children (dict or list changes)
    if diff_node.children:
        if diff_node.path:
            lines.append(f"{indent}[yellow]~ {diff_node.path}:[/yellow]")
        for child in diff_node.children:
            lines.append(render_diff(child, indent_level + 1))
    else:
        # Leaf changes
        path_str = f" {diff_node.path}" if diff_node.path else ""
        if diff_node.type == DiffType.CHANGED:
            lines.append(
                f"{indent}[yellow]~{path_str}:[/yellow]\n"
                f"{indent}  [red]- {json.dumps(diff_node.old_value)}[/red]\n"
                f"{indent}  [green]+ {json.dumps(diff_node.new_value)}[/green]"
            )
        elif diff_node.type == DiffType.ADDED:
            lines.append(f"{indent}[green]+{path_str}: {json.dumps(diff_node.new_value)}[/green]")
        elif diff_node.type == DiffType.REMOVED:
            lines.append(f"{indent}[red]-{path_str}: {json.dumps(diff_node.old_value)}[/red]")

    return "\n".join(lines)
