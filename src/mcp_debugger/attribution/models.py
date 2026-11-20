from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FailureCategory(str, Enum):
    AGENT = "agent"
    TOOL = "tool"
    PROTOCOL = "protocol"
    NONE = "none"


@dataclass
class FailureDiagnosis:
    session_id: int
    category: FailureCategory
    root_cause_step_index: int | None = None
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
