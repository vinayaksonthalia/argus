"""MCP client transport: the same `SignozTransport` seam,
served by SigNoz's MCP server instead of the REST API.

The local SigNoz MCP server (:8000/mcp) speaks JSON-RPC 2.0 over streamable
HTTP. Tool discovery is `tools/list`; every ARGUS read maps onto ONE tool —
`signoz_execute_builder_query` — which accepts a complete Query Builder v5
`query_range` payload and returns the identical response envelope (verified
live: the envelope carries the same `data.meta.rowsScanned` block), so
golden-signal, trace-search, log-search and verification reads all flow
through MCP unchanged. Select with `ARGUS_TRANSPORT=mcp` (default: rest).

Gap notes vs REST (from live tools/list): the MCP server also offers
higher-level tools (signoz_search_traces, signoz_search_logs,
signoz_aggregate_*) but their responses are LLM-shaped summaries, not the v5
envelope; ARGUS deliberately uses the builder-query tool for mechanical,
whitelisted queries. Dashboards/rules WRITES have MCP tools too
(signoz_create_dashboard/signoz_create_alert) but stay on REST here.
"""

from __future__ import annotations

import itertools
import json
from typing import Any

import httpx

from ..telemetry import tracer
from .transport import QueryStats


class McpError(RuntimeError):
    pass


class McpTransport:
    """SignozTransport implementation over the SigNoz MCP server."""

    TOOL = "signoz_execute_builder_query"

    def __init__(self, mcp_url: str, api_key: str, timeout: float = 60.0) -> None:
        self._url = mcp_url
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "Content-Type": "application/json",
                # streamable-HTTP MCP servers require both accept types
                "Accept": "application/json, text/event-stream",
                "SIGNOZ-API-KEY": api_key,
            },
        )
        self._ids = itertools.count(1)
        self.stats = QueryStats()
        self._tools: list[str] | None = None

    # ------------------------------------------------------------ JSON-RPC

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self._client.post(self._url, json={
            "jsonrpc": "2.0", "id": next(self._ids), "method": method,
            **({"params": params} if params else {}),
        })
        resp.raise_for_status()
        text = resp.text
        # Streamable HTTP may answer as SSE; extract the data frame if so.
        if text.lstrip().startswith("event:") or "\ndata:" in text[:200]:
            for line in text.splitlines():
                if line.startswith("data:"):
                    text = line[len("data:"):].strip()
                    break
        body = json.loads(text)
        if "error" in body:
            raise McpError(f"MCP {method} error: {body['error']}")
        return body.get("result") or {}

    def list_tools(self) -> list[str]:
        """Tool discovery (tools/list), cached."""
        if self._tools is None:
            result = self._rpc("tools/list")
            self._tools = [t["name"] for t in result.get("tools", [])]
            if self.TOOL not in self._tools:
                raise McpError(
                    f"MCP server does not expose '{self.TOOL}' "
                    f"(found {len(self._tools)} tools) — cannot serve ARGUS reads"
                )
        return self._tools

    # ------------------------------------------------------------ transport

    def query_range(self, payload: dict[str, Any], tag: str) -> dict[str, Any]:
        self.list_tools()  # discover once; fail fast if the tool is missing
        with tracer().start_as_current_span(f"signoz.query_range.{tag}") as span:
            span.set_attribute("argus.signoz.tag", tag)
            span.set_attribute("argus.signoz.transport", "mcp")
            span.set_attribute("argus.mcp.tool", self.TOOL)
            result = self._rpc("tools/call", {
                "name": self.TOOL,
                "arguments": {"query": payload},
            })
            if result.get("isError"):
                detail = "".join(
                    c.get("text", "") for c in result.get("content", [])
                )[:500]
                raise McpError(f"MCP tool call failed for tag '{tag}': {detail}")
            texts = [c.get("text", "") for c in result.get("content", [])
                     if c.get("type") == "text"]
            if not texts:
                raise McpError(f"MCP tool returned no text content for tag '{tag}'")
            envelope = json.loads(texts[0])
            self.stats.record(tag, envelope)
            meta = (envelope.get("data") or {}).get("meta") or {}
            span.set_attribute("argus.signoz.rows_scanned", int(meta.get("rowsScanned", 0) or 0))
            span.set_attribute("argus.signoz.bytes_scanned", int(meta.get("bytesScanned", 0) or 0))
            return envelope
