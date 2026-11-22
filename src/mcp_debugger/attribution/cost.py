"""Per-step and per-agent token cost attribution engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ModelPricing:
    """Pricing rates per 1 Million tokens in USD."""

    input_per_million: float
    output_per_million: float


# Default standard model pricing registry (USD per 1M tokens)
DEFAULT_PRICING: dict[str, ModelPricing] = {
    # OpenAI
    "gpt-4o": ModelPricing(input_per_million=2.50, output_per_million=10.00),
    "gpt-4o-mini": ModelPricing(input_per_million=0.15, output_per_million=0.60),
    "gpt-4-turbo": ModelPricing(input_per_million=10.00, output_per_million=30.00),
    "gpt-3.5-turbo": ModelPricing(input_per_million=0.50, output_per_million=1.50),
    "o1": ModelPricing(input_per_million=15.00, output_per_million=60.00),
    "o1-mini": ModelPricing(input_per_million=3.00, output_per_million=12.00),
    # Anthropic
    "claude-3-5-sonnet": ModelPricing(input_per_million=3.00, output_per_million=15.00),
    "claude-3-opus": ModelPricing(input_per_million=15.00, output_per_million=75.00),
    "claude-3-haiku": ModelPricing(input_per_million=0.25, output_per_million=1.25),
    # Google Gemini
    "gemini-1.5-pro": ModelPricing(input_per_million=1.25, output_per_million=5.00),
    "gemini-1.5-flash": ModelPricing(input_per_million=0.075, output_per_million=0.30),
    "gemini-2.0-flash": ModelPricing(input_per_million=0.10, output_per_million=0.40),
    # DeepSeek
    "deepseek-v3": ModelPricing(input_per_million=0.14, output_per_million=0.28),
    "deepseek-r1": ModelPricing(input_per_million=0.55, output_per_million=2.19),
    # Fallback
    "default": ModelPricing(input_per_million=2.00, output_per_million=8.00),
}


@dataclass
class StepCost:
    step_index: int
    step_type: str
    agent_id: int | None
    agent_name: str | None
    model: str
    tokens_input: int
    tokens_output: int
    total_tokens: int
    cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentCost:
    agent_id: int | None
    agent_name: str
    role: str | None = None
    framework: str | None = None
    is_orchestrator: bool = False
    total_steps: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    cost_percentage: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SessionCostReport:
    session_id: int
    total_cost_usd: float
    total_tokens: int
    total_tokens_input: int
    total_tokens_output: int
    step_costs: list[StepCost] = field(default_factory=list)
    agent_costs: list[AgentCost] = field(default_factory=list)
    budget_exceeded: bool = False
    max_budget: float | None = None
    anomalies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "total_tokens": self.total_tokens,
            "total_tokens_input": self.total_tokens_input,
            "total_tokens_output": self.total_tokens_output,
            "budget_exceeded": self.budget_exceeded,
            "max_budget": self.max_budget,
            "anomalies": self.anomalies,
            "agents": [a.to_dict() for a in self.agent_costs],
            "steps": [s.to_dict() for s in self.step_costs],
        }


class CostCalculator:
    """Calculates token costs, multi-agent rollups, and detects cost anomalies."""

    def __init__(self, custom_pricing: dict[str, ModelPricing] | None = None) -> None:
        self._pricing: dict[str, ModelPricing] = dict(DEFAULT_PRICING)
        if custom_pricing:
            self._pricing.update(custom_pricing)

    def register_pricing(
        self,
        model_name: str,
        input_per_million: float,
        output_per_million: float,
    ) -> None:
        """Register or override pricing for a specific model."""
        key = model_name.strip().lower()
        self._pricing[key] = ModelPricing(
            input_per_million=input_per_million,
            output_per_million=output_per_million,
        )

    def get_pricing(self, model_name: str) -> ModelPricing:
        """Look up pricing for a model with normalized key matching."""
        key = model_name.strip().lower()
        if key in self._pricing:
            return self._pricing[key]

        # Strip vendor prefix if present: openai/gpt-4o -> gpt-4o
        if "/" in key:
            sub_key = key.split("/")[-1]
            if sub_key in self._pricing:
                return self._pricing[sub_key]

        # Prefix matching: claude-3-5-sonnet-20241022 -> claude-3-5-sonnet
        for p_key, pricing in self._pricing.items():
            if p_key != "default" and key.startswith(p_key):
                return pricing

        return self._pricing["default"]

    def extract_model_from_step(self, step: dict[str, Any]) -> str:
        """Attempt to extract the LLM model name from step attributes or payload."""
        if step.get("model"):
            return str(step["model"])

        raw_input = step.get("input") or step.get("input_data")
        if raw_input:
            if isinstance(raw_input, dict) and "model" in raw_input:
                return str(raw_input["model"])
            if isinstance(raw_input, str) and raw_input.strip().startswith("{"):
                try:
                    parsed = json.loads(raw_input)
                    if isinstance(parsed, dict) and "model" in parsed:
                        return str(parsed["model"])
                except Exception:
                    pass

        return "default"

    def compute_step_cost(
        self,
        model: str,
        tokens_input: int = 0,
        tokens_output: int = 0,
        step_index: int = 0,
        agent_id: int | None = None,
        agent_name: str | None = None,
        step_type: str = "llm_call",
    ) -> StepCost:
        """Compute the USD cost for a single trajectory step."""
        pricing = self.get_pricing(model)
        cost_in = (tokens_input / 1_000_000.0) * pricing.input_per_million
        cost_out = (tokens_output / 1_000_000.0) * pricing.output_per_million
        total_cost = cost_in + cost_out

        return StepCost(
            step_index=step_index,
            step_type=step_type,
            agent_id=agent_id,
            agent_name=agent_name,
            model=model,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            total_tokens=tokens_input + tokens_output,
            cost_usd=total_cost,
        )

    def compute_session_costs(
        self,
        session_id: int,
        steps: list[dict[str, Any]],
        agents: list[dict[str, Any]] | None = None,
        max_budget: float | None = None,
    ) -> SessionCostReport:
        """Aggregate per-step costs, build multi-agent rollups, and flag anomalies."""
        step_costs: list[StepCost] = []
        total_tokens_in = 0
        total_tokens_out = 0
        total_cost_usd = 0.0

        # Build agent map if agents provided
        agent_meta_map: dict[int, dict[str, Any]] = {}
        if agents:
            for a in agents:
                aid = a.get("id")
                if aid is not None:
                    agent_meta_map[aid] = a

        # Step costs
        for step in steps:
            s_idx = step.get("step_index", 0)
            s_type = step.get("step_type", "llm_call")
            aid = step.get("agent_id")
            aname = step.get("agent_name")
            model = self.extract_model_from_step(step)

            t_in = step.get("tokens_input") or 0
            t_out = step.get("tokens_output") or 0

            sc = self.compute_step_cost(
                model=model,
                tokens_input=t_in,
                tokens_output=t_out,
                step_index=s_idx,
                agent_id=aid,
                agent_name=aname,
                step_type=s_type,
            )
            step_costs.append(sc)
            total_tokens_in += t_in
            total_tokens_out += t_out
            total_cost_usd += sc.cost_usd

        # Per-agent rollups
        agent_cost_map: dict[tuple[int | None, str], AgentCost] = {}

        # Pre-seed from agents list so all agents appear even with 0 steps
        if agents:
            for a in agents:
                aid = a.get("id")
                aname = a.get("name", f"Agent-{aid}")
                role = a.get("role")
                framework = a.get("framework")
                parent_id = a.get("parent_agent_id")
                is_orch = parent_id is None or any(
                    k in (role or "").lower() for k in ["orchestrator", "planner", "manager", "lead"]
                )
                key = (aid, aname)
                agent_cost_map[key] = AgentCost(
                    agent_id=aid,
                    agent_name=aname,
                    role=role,
                    framework=framework,
                    is_orchestrator=is_orch,
                )

        # Aggregate step metrics into agents
        for sc in step_costs:
            key = (sc.agent_id, sc.agent_name or "unassigned")
            if key not in agent_cost_map:
                meta = agent_meta_map.get(sc.agent_id) if sc.agent_id else None
                role = meta.get("role") if meta else None
                framework = meta.get("framework") if meta else None
                parent_id = meta.get("parent_agent_id") if meta else None
                is_orch = (
                    (parent_id is None and sc.agent_id is not None)
                    or any(k in (role or "").lower() for k in ["orchestrator", "planner", "manager", "lead"])
                )
                agent_cost_map[key] = AgentCost(
                    agent_id=sc.agent_id,
                    agent_name=sc.agent_name or "unassigned",
                    role=role,
                    framework=framework,
                    is_orchestrator=is_orch,
                )

            ag = agent_cost_map[key]
            ag.total_steps += 1
            ag.tokens_input += sc.tokens_input
            ag.tokens_output += sc.tokens_output
            ag.total_tokens += sc.total_tokens
            ag.total_cost_usd += sc.cost_usd

        agent_costs = list(agent_cost_map.values())

        # Calculate cost percentages
        for ag in agent_costs:
            if total_cost_usd > 0:
                ag.cost_percentage = round((ag.total_cost_usd / total_cost_usd) * 100.0, 2)
            else:
                ag.cost_percentage = 0.0

        # Sort agents: orchestrator first, then highest cost
        agent_costs.sort(key=lambda a: (not a.is_orchestrator, -a.total_cost_usd))

        # Anomaly detection
        anomalies: list[str] = []

        # 1. Token spike anomalies (per step)
        if len(step_costs) >= 2:
            for sc in step_costs:
                other_tokens = [s.total_tokens for s in step_costs if s.step_index != sc.step_index]
                if other_tokens:
                    avg_others = sum(other_tokens) / len(other_tokens)
                    if sc.total_tokens > 5_000 and (avg_others == 0 or sc.total_tokens > 3.0 * avg_others):
                        anomalies.append(
                            f"Step #{sc.step_index} ({sc.agent_name or 'unassigned'}): "
                            f"Significant token spike detected ({sc.total_tokens:,} tokens, ${sc.cost_usd:.4f})."
                        )

        # 2. Budget exceedance
        budget_exceeded = False
        if max_budget is not None and total_cost_usd > max_budget:
            budget_exceeded = True
            anomalies.append(
                f"Budget threshold exceeded: ${total_cost_usd:.4f} > ${max_budget:.4f}."
            )

        return SessionCostReport(
            session_id=session_id,
            total_cost_usd=total_cost_usd,
            total_tokens=total_tokens_in + total_tokens_out,
            total_tokens_input=total_tokens_in,
            total_tokens_output=total_tokens_out,
            step_costs=step_costs,
            agent_costs=agent_costs,
            budget_exceeded=budget_exceeded,
            max_budget=max_budget,
            anomalies=anomalies,
        )
