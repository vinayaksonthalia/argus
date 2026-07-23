import pytest

from argus.config import ConfigError, Settings
from argus.signoz.links import LinkFactory


def test_trace_link(window):
    links = LinkFactory("http://localhost:8080/")
    assert links.trace("abc123", "span9") == "http://localhost:8080/trace/abc123?spanId=span9"


def test_logs_explorer_link_pins_time_range(window):
    links = LinkFactory("http://localhost:8080")
    url = links.logs_explorer("service.name = 'catalog'", window)
    assert url.startswith("http://localhost:8080/logs/logs-explorer?")
    assert f"startTime={window.start_ms}" in url
    assert f"endTime={window.end_ms}" in url
    assert "filter=" in url and " " not in url


def test_config_refuses_placeholder_secrets(monkeypatch):
    monkeypatch.setenv("SIGNOZ_API_KEY", "your-signoz-api-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real-looking-key-123")
    settings = Settings.from_env()
    with pytest.raises(ConfigError) as exc:
        settings.validate_live()
    assert "SIGNOZ_API_KEY" in str(exc.value)
    assert "your-signoz-api-key" not in str(exc.value)  # value never printed


def test_config_refuses_missing_secrets(monkeypatch):
    monkeypatch.delenv("SIGNOZ_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        Settings.from_env().validate_live()


def test_config_accepts_real_looking_secrets(monkeypatch):
    monkeypatch.setenv("SIGNOZ_API_KEY", "JTRIaOOL3Ag1PW=")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-abc123")
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    settings = Settings.from_env()
    settings.validate_live()
    assert settings.validated
