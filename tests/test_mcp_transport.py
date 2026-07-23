"""McpTransport: JSON-RPC framing, tool discovery, envelope passthrough,
error surfacing. No network — the JSON-RPC layer is stubbed."""

from __future__ import annotations

import json

import pytest

from argus.signoz.mcp_transport import McpError, McpTransport

ENVELOPE = {
    "status": "success",
    "data": {
        "type": "time_series",
        "meta": {"rowsScanned": 1234, "bytesScanned": 5678, "durationMs": 9},
        "data": {"results": [{"queryName": "A", "aggregations": []}]},
    },
}


def _transport(monkeypatch, responses: dict[str, object]) -> McpTransport:
    t = McpTransport("http://localhost:8000/mcp", "test-key")
    calls: list[tuple[str, dict | None]] = []

    def fake_rpc(method, params=None):
        calls.append((method, params))
        result = responses[method]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(t, "_rpc", fake_rpc)
    t._calls = calls  # type: ignore[attr-defined]
    return t


def test_query_range_maps_to_builder_query_tool(monkeypatch):
    t = _transport(monkeypatch, {
        "tools/list": {"tools": [{"name": "signoz_execute_builder_query"}]},
        "tools/call": {"content": [{"type": "text", "text": json.dumps(ENVELOPE)}]},
    })
    payload = {"schemaVersion": "v1", "requestType": "raw"}
    env = t.query_range(payload, tag="traces.search")
    assert env == ENVELOPE
    method, params = t._calls[-1]
    assert method == "tools/call"
    assert params["name"] == "signoz_execute_builder_query"
    assert params["arguments"]["query"] is payload
    # cost accounting flows exactly like REST
    assert t.stats.queries == 1
    assert t.stats.rows_scanned == 1234
    assert t.stats.by_tag["traces.search"] == 1234


def test_missing_tool_fails_fast(monkeypatch):
    t = _transport(monkeypatch, {"tools/list": {"tools": [{"name": "other_tool"}]}})
    with pytest.raises(McpError, match="does not expose"):
        t.query_range({}, tag="x")


def test_tool_error_result_raises(monkeypatch):
    t = _transport(monkeypatch, {
        "tools/list": {"tools": [{"name": "signoz_execute_builder_query"}]},
        "tools/call": {"isError": True,
                       "content": [{"type": "text", "text": "bad filter"}]},
    })
    with pytest.raises(McpError, match="bad filter"):
        t.query_range({}, tag="verify.0")


def test_tools_list_is_cached(monkeypatch):
    t = _transport(monkeypatch, {
        "tools/list": {"tools": [{"name": "signoz_execute_builder_query"}]},
        "tools/call": {"content": [{"type": "text", "text": json.dumps(ENVELOPE)}]},
    })
    t.query_range({}, tag="a")
    t.query_range({}, tag="b")
    assert [m for m, _ in t._calls].count("tools/list") == 1


def test_transport_config_selects_mcp(monkeypatch):
    from argus.config import Settings
    from argus.live import make_transport
    from argus.signoz.transport import HttpTransport

    s = Settings(signoz_api_key="k")
    assert isinstance(make_transport(s), HttpTransport)
    s.transport = "mcp"
    t = make_transport(s)
    assert isinstance(t, McpTransport)
    s.transport = "bogus"
    with pytest.raises(ValueError, match="ARGUS_TRANSPORT"):
        make_transport(s)
