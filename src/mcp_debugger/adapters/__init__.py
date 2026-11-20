"""Framework adapters package for MCP Debugger."""

from mcp_debugger.adapters.openai import OpenAIAgentTracker, trace_openai_agent

__all__ = ["OpenAIAgentTracker", "trace_openai_agent"]
