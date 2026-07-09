"""
Shared MCP client for Dynatrace AI Observability services.

Wraps the async MCP tool-use loop in a sync call (`call_llm_with_mcp`) so
each FastAPI service can invoke it without async plumbing changes.

Requirements:
    mcp>=1.0.0
    anthropic>=0.40.0

Environment variables:
    DT_APPS_ENDPOINT   — e.g. https://abc12345.apps.live.dynatrace.com
                         If unset, derived from DT_ENDPOINT by inserting
                         .apps. before dynatracelabs.com / dynatrace.com
    DT_PLATFORM_TOKEN  — platform token with MCP-required scopes
"""

import asyncio
import os
import uuid

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from opentelemetry import trace as _otel_trace

from llm_client import LLMResponse

_tracer = _otel_trace.get_tracer("mcp_client")

# ── Endpoint derivation ───────────────────────────────────────────────────────

def _derive_apps_endpoint(dt_endpoint: str) -> str:
    """Insert .apps. before the TLD portion of the DT endpoint hostname."""
    # e.g. https://suz7562h.sprint.dynatracelabs.com
    #   -> https://suz7562h.sprint.apps.dynatracelabs.com
    for tld in ("dynatracelabs.com", "dynatrace.com"):
        if tld in dt_endpoint:
            return dt_endpoint.replace(tld, f"apps.{tld}")
    # Fallback: just return the original
    return dt_endpoint


def _get_apps_endpoint() -> str:
    explicit = os.environ.get("DT_APPS_ENDPOINT", "").rstrip("/")
    if explicit:
        return explicit
    dt_endpoint = os.environ.get("DT_ENDPOINT", "").rstrip("/")
    if dt_endpoint:
        return _derive_apps_endpoint(dt_endpoint)
    return ""


# ── MCP server parameters ─────────────────────────────────────────────────────

def _make_server_params() -> StdioServerParameters:
    apps_endpoint = _get_apps_endpoint()
    platform_token = os.environ.get("DT_PLATFORM_TOKEN", "")
    env = {**os.environ, "DT_ENVIRONMENT": apps_endpoint, "DT_PLATFORM_TOKEN": platform_token}
    return StdioServerParameters(
        command="node",
        args=["/usr/lib/node_modules/@dynatrace-oss/dynatrace-mcp-server/index.js"],
        env=env,
    )


# ── Async tool-use loop ───────────────────────────────────────────────────────

async def _run_mcp_loop(anthropic_client, model: str, prompt: str) -> LLMResponse:
    """Open a stdio MCP session, register tools, and drive an Anthropic tool-use loop."""
    server_params = _make_server_params()

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # List available tools and build Anthropic tool definitions
            tools_result = await session.list_tools()
            anthropic_tools = [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "input_schema": t.inputSchema if hasattr(t, "inputSchema") else {"type": "object", "properties": {}},
                }
                for t in tools_result.tools
            ]

            messages = [{"role": "user", "content": prompt}]
            total_input = 0
            total_output = 0
            final_text = ""
            final_model = model

            # Tool-use loop
            while True:
                resp = anthropic_client.messages.create(
                    model=model,
                    max_tokens=2048,
                    tools=anthropic_tools,
                    messages=messages,
                )
                total_input += resp.usage.input_tokens
                total_output += resp.usage.output_tokens
                final_model = resp.model

                if resp.stop_reason != "tool_use":
                    final_text = next(
                        (b.text for b in resp.content if b.type == "text"), ""
                    )
                    break

                # Serialize assistant content to plain dicts (avoids instrumentation wrapper issues)
                assistant_content = []
                for block in resp.content:
                    if block.type == "tool_use":
                        assistant_content.append(
                            {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                        )
                    elif block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})

                messages.append({"role": "assistant", "content": assistant_content})

                # Execute all tool calls
                tool_results = []
                for block in resp.content:
                    if block.type != "tool_use":
                        continue

                    request_id = str(uuid.uuid4())
                    with _tracer.start_as_current_span("mcp.tool.call") as span:
                        span.set_attribute("mcp.method.name", "tools/call")
                        span.set_attribute("mcp.server.name", "dynatrace")
                        span.set_attribute("mcp.transport", "stdio")
                        span.set_attribute("mcp.tool.name", block.name)
                        span.set_attribute("mcp.request.id", request_id)

                        tool_response = await session.call_tool(block.name, block.input)

                    # Extract text from tool result content items
                    result_text = ""
                    for item in tool_response.content:
                        if hasattr(item, "text"):
                            result_text += item.text
                        else:
                            result_text += str(item)

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_text,
                        }
                    )

                messages.append({"role": "user", "content": tool_results})

            return LLMResponse(
                content=final_text,
                model=final_model,
                input_tokens=total_input,
                output_tokens=total_output,
            )


# ── Public sync wrapper ───────────────────────────────────────────────────────

def call_llm_with_mcp(anthropic_client, model: str, prompt: str) -> LLMResponse:
    """Sync wrapper: runs the async MCP loop and returns an LLMResponse."""
    return asyncio.run(_run_mcp_loop(anthropic_client, model, prompt))
