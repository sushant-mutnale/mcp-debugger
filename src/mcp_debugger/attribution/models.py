"""Data models for causal failure attribution and step ablation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FailureCategory(str, Enum):
    AGENT = "agent"
    TOOL = "tool"
    PROTOCOL = "protocol"
    NONE = "none"


class PerturbationType(str, Enum):
    EMPTY_RESULT = "empty_result"
    TOOL_ERROR = "tool_error"
    CUSTOM = "custom"


@dataclass
class FailureDiagnosis:
    session_id: int
    category: FailureCategory
    root_cause_step_index: int | None = None
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)


@dataclass
class AblationResult:
    step_index: int
    perturbation: PerturbationType | str
    original_diagnosis: FailureDiagnosis
    counterfactual_diagnosis: FailureDiagnosis
    outcome_changed: bool
    divergence_score: float = 0.0


@dataclass
class PointOfCommitment:
    step_index: int
    step_type: str
    agent_name: str | None = None
    tool_name: str | None = None
    perturbation: PerturbationType | str = PerturbationType.TOOL_ERROR
    description: str = ""


@dataclass
class AttributionReport:
    session_id: int
    original_diagnosis: FailureDiagnosis
    point_of_commitment: PointOfCommitment | None = None
    ablation_results: list[AblationResult] = field(default_factory=list)
