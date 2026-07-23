import pytest

from argus.signoz import queries as q


def test_p99_payload_shape(window):
    payload = q.p99_latency_payload("catalog", window)
    assert payload["schemaVersion"] == "v1"
    assert payload["requestType"] == "time_series"
    assert payload["start"] == window.start_ms and payload["end"] == window.end_ms
    spec = payload["compositeQuery"]["queries"][0]["spec"]
    assert spec["signal"] == "traces"
    assert spec["aggregations"] == [{"expression": "p99(duration_nano)"}]
    assert spec["filter"]["expression"] == "service.name = 'catalog'"


def test_error_rate_payload_has_two_queries(window):
    payload = q.error_rate_payload("catalog", window)
    specs = [x["spec"] for x in payload["compositeQuery"]["queries"]]
    assert [s["name"] for s in specs] == ["A", "B"]
    assert "has_error = true" in specs[0]["filter"]["expression"]


def test_raw_traces_payload(window):
    payload = q.raw_traces_payload("trace_id = 'abc'", window, limit=5)
    assert payload["requestType"] == "raw"
    assert payload["compositeQuery"]["queries"][0]["spec"]["limit"] == 5


def test_series_values_parses_real_envelope(deps):
    env = deps.signoz._t.query_range({}, "golden.p99.after")
    values = q.series_values(env)
    assert len(values) == 6
    assert values == sorted(values)
    assert max(v for _, v in values) == pytest.approx(3100e6)


def test_series_values_tolerates_null_aggregations():
    env = {"status": "success", "data": {"data": {"results": [{"queryName": "A", "aggregations": None}]}}}
    assert q.series_values(env) == []


def test_raw_rows_parses_fixture(deps):
    env = deps.signoz._t.query_range({}, "traces.search")
    rows = q.raw_rows(env)
    assert len(rows) == 2
    assert all("trace_id" in r for r in rows)


def test_validate_verification_params_whitelist():
    q.validate_verification_params("traces", "p99(duration_nano)", "service.name = 'x'")
    with pytest.raises(ValueError):
        q.validate_verification_params("nonsense", "count()", "")
    with pytest.raises(ValueError):
        q.validate_verification_params("traces", "drop_table()", "")
    with pytest.raises(ValueError):
        q.validate_verification_params("traces", "count()", "x = 'a'; DROP TABLE spans; --")
