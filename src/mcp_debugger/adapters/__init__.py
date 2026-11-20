"""Framework adapters package for MCP Debugger."""

from mcp_debugger.adapters.crewai import CrewAITracker, trace_crewai
from mcp_debugger.adapters.langchain import MCPDebuggerCallbackHandler
from mcp_debugger.adapters.openai import OpenAIAgentTracker, trace_openai_agent

__all__ = [
    "CrewAITracker",
    "MCPDebuggerCallbackHandler",
    "OpenAIAgentTracker",
    "trace_crewai",
    "trace_openai_agent",
]
