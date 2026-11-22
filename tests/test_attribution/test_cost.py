"""Unit tests for token cost attribution engine."""

from __future__ import annotations

from typer.testing import CliRunner

from mcp_debugger.attribution.cost import CostCalculator
from mcp_debugger.cli import app
from mcp_debugger.storage.database import Database


def test_pricing_registry() -> None:
    """Pricing registry looks up known models and supports custom registration."""
    calc = CostCalculator()

    pricing_gpt4o = calc.get_pricing("gpt-4o")
    assert pricing_gpt4o.input_per_million == 2.50
    assert pricing_gpt4o.output_per_million == 10.00

    pricing_claude = calc.get_pricing("claude-3-5-sonnet")
    assert pricing_claude.input_per_million == 3.00

    # Fallback for unknown models
    pricing_unknown = calc.get_pricing("unknown-special-model-v9")
    assert pricing_unknown.input_per_million > 0

    # Custom registration
    calc.register_pricing("deepseek-v3", input_per_million=0.14, output_per_million=0.28)
    pricing_deepseek = calc.get_pricing("deepseek-v3")
    assert pricing_deepseek.input_per_million == 0.14
    assert pricing_deepseek.output_per_million == 0.28


def test_step_cost_calculation() -> None:
    """Step cost accurately calculates USD cost based on token volumes."""
    calc = CostCalculator()

    # 1,000,000 input tokens + 500,000 output tokens on gpt-4o
    # 1 * 2.50 + 0.5 * 10.00 = 2.50 + 5.00 = 7.50 USD
    step_cost = calc.compute_step_cost(
        model="gpt-4o",
        tokens_input=1_000_000,
        tokens_output=500_000,
        step_index=1,
    )

    assert step_cost.total_tokens == 1_500_000
    assert round(step_cost.cost_usd, 2) == 7.50
    assert step_cost.step_index == 1


def test_session_cost_aggregation_and_agent_rollups() -> None:
    """Session cost aggregates step costs and computes per-agent rollups."""
    calc = CostCalculator()

    agents = [
        {
            "id": 1,
            "name": "PlannerAgent",
            "role": "Orchestrator",
            "framework": "crewai",
            "parent_agent_id": None,
        },
        {
            "id": 2,
            "name": "ResearcherAgent",
            "role": "Worker",
            "framework": "crewai",
            "parent_agent_id": 1,
        },
    ]

    steps = [
        {
            "step_index": 1,
            "step_type": "thought",
            "agent_id": 1,
            "agent_name": "PlannerAgent",
            "tokens_input": 100_000,
            "tokens_output": 50_000,
            "input": '{"model": "gpt-4o"}',
        },
        {
            "step_index": 2,
            "step_type": "llm_call",
            "agent_id": 2,
            "agent_name": "ResearcherAgent",
            "tokens_input": 400_000,
            "tokens_output": 200_000,
            "input": '{"model": "gpt-4o"}',
        },
    ]

    report = calc.compute_session_costs(
        session_id=99,
        steps=steps,
        agents=agents,
    )

    assert report.session_id == 99
    assert report.total_tokens == 750_000
    assert len(report.step_costs) == 2
    assert len(report.agent_costs) == 2

    # Agent 1: 100k in + 50k out on gpt-4o -> 0.1 * 2.5 + 0.05 * 10 = 0.25 + 0.50 = 0.75 USD
    agent1 = next(a for a in report.agent_costs if a.agent_id == 1)
    assert agent1.is_orchestrator is True
    assert round(agent1.total_cost_usd, 2) == 0.75

    # Agent 2: 400k in + 200k out on gpt-4o -> 0.4 * 2.5 + 0.2 * 10 = 1.00 + 2.00 = 3.00 USD
    agent2 = next(a for a in report.agent_costs if a.agent_id == 2)
    assert agent2.is_orchestrator is False
    assert round(agent2.total_cost_usd, 2) == 3.00

    # Total = 3.75 USD
    assert round(report.total_cost_usd, 2) == 3.75
    assert agent1.cost_percentage == 20.0
    assert agent2.cost_percentage == 80.0


def test_budget_exceeded_and_token_spike_anomalies() -> None:
    """Anomalies are detected for budget threshold exceedances and token spikes."""
    calc = CostCalculator()

    steps = [
        {"step_index": 1, "step_type": "llm_call", "tokens_input": 1_000, "tokens_output": 500},
        {"step_index": 2, "step_type": "llm_call", "tokens_input": 1_200, "tokens_output": 600},
        # Extreme spike: 50x larger than average
        {"step_index": 3, "step_type": "llm_call", "tokens_input": 200_000, "tokens_output": 100_000},
    ]

    report = calc.compute_session_costs(
        session_id=1,
        steps=steps,
        max_budget=0.50,  # $0.50 max budget
    )

    # Spike at step 3 should be flagged in anomalies
    assert any("Step #3" in a or "token spike" in a.lower() for a in report.anomalies)

    # Total cost exceeds 0.50 on default pricing
    assert report.budget_exceeded is True
    assert report.max_budget == 0.50


def test_cli_stats_cost_json(mock_db_path: str, runner: CliRunner) -> None:
    """mcp-debugger stats --json surfaces token cost attribution data."""
    import asyncio

    async def _setup() -> int:
        db = Database(mock_db_path)
        await db.connect()
        try:
            sid = await db.create_session("stats-cost-target")
            agent_id = await db.create_agent(
                session_id=sid,
                name="CostAgent",
                role="Analyzer",
            )
            await db.log_step(
                session_id=sid,
                step_index=1,
                step_type="llm_call",
                agent_name="CostAgent",
                agent_id=agent_id,
                input_data='{"model": "gpt-4o"}',
                output_data='{"text": "Done"}',
                tokens_input=50_000,
                tokens_output=25_000,
            )
            return sid
        finally:
            await db.close()

    sid = asyncio.run(_setup())

    result = runner.invoke(app, ["stats", str(sid), "--json"])
    assert result.exit_code == 0, result.output
    import json
    data = json.loads(result.stdout)
    assert "token_costs" in data
    assert data["token_costs"]["total_cost_usd"] > 0
    assert len(data["token_costs"]["agents"]) == 1


def test_cli_ci_max_cost_flag(mock_db_path: str, runner: CliRunner) -> None:
    """mcp-debugger ci flags sessions exceeding --max-cost."""
    import asyncio

    async def _setup() -> int:
        db = Database(mock_db_path)
        await db.connect()
        try:
            sid = await db.create_session("ci-cost-target")
            await db.log_step(
                session_id=sid,
                step_index=1,
                step_type="llm_call",
                agent_name="Worker",
                input_data='{"model": "gpt-4o"}',
                output_data='{"text": "Large payload"}',
                tokens_input=2_000_000,
                tokens_output=1_000_000,
            )
            return sid
        finally:
            await db.close()

    sid = asyncio.run(_setup())

    # Budget of $0.10, but 2M in + 1M out on gpt-4o costs $15.00
    result = runner.invoke(app, ["ci", str(sid), "--max-cost", "0.10"])
    assert "Budget threshold exceeded" in result.output or "exceeded" in result.output.lower()
