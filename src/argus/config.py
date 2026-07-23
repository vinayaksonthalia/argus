"""Environment-driven configuration with placeholder-secret refusal (NFR-5).

Replay mode (offline demo / evals / tests) requires no secrets at all; live
mode refuses to boot if a required secret is missing or obviously a
placeholder. The offending variable *name* is reported — never its value.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

_PLACEHOLDER_MARKERS = (
    "your-", "your_", "changeme", "change-me", "placeholder", "xxx",
    "<", ">", "todo", "example", "dummy",
)


class ConfigError(RuntimeError):
    pass


def _looks_placeholder(value: str) -> bool:
    v = value.strip().lower()
    return not v or any(m in v for m in _PLACEHOLDER_MARKERS)


@dataclass
class Settings:
    signoz_url: str = "http://localhost:8080"
    signoz_api_key: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    # auto | anthropic | claude-cli | groq | cerebras | heuristic
    # (auto -> anthropic when the API key is set, else claude-cli when the CLI
    #  is installed, else groq/cerebras when their key is set, else heuristic)
    llm_provider: str = "auto"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    cerebras_api_key: str = ""
    cerebras_model: str = "gpt-oss-120b"
    slack_bot_token: str = ""
    slack_channel: str = "#incidents"
    otlp_endpoint: str = ""  # empty -> telemetry no-ops
    listen_port: int = 7331
    max_verify_iterations: int = 2
    # incident memory SQLite path; "off" disables recall/learning
    memory_db: str = "argus-memory.sqlite3"
    # SigNoz read transport: rest (default) | mcp
    transport: str = "rest"
    mcp_url: str = "http://localhost:8000/mcp"

    # populated by validate()
    validated: bool = field(default=False, repr=False)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            signoz_url=os.getenv("SIGNOZ_URL", "http://localhost:8080").rstrip("/"),
            signoz_api_key=os.getenv("SIGNOZ_API_KEY", ""),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            anthropic_model=os.getenv("ARGUS_MODEL", "claude-sonnet-4-5"),
            llm_provider=os.getenv("ARGUS_LLM_PROVIDER", "auto").strip().lower(),
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            groq_model=os.getenv("ARGUS_GROQ_MODEL", "llama-3.3-70b-versatile"),
            cerebras_api_key=os.getenv("CEREBRAS_API_KEY", ""),
            cerebras_model=os.getenv("ARGUS_CEREBRAS_MODEL", "gpt-oss-120b"),
            slack_bot_token=os.getenv("SLACK_BOT_TOKEN", ""),
            slack_channel=os.getenv("SLACK_CHANNEL", "#incidents"),
            otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
            listen_port=int(os.getenv("ARGUS_PORT", "7331")),
            max_verify_iterations=int(os.getenv("ARGUS_MAX_ITERATIONS", "2")),
            memory_db=os.getenv("ARGUS_MEMORY_DB", "argus-memory.sqlite3").strip(),
            transport=os.getenv("ARGUS_TRANSPORT", "rest").strip().lower(),
            mcp_url=os.getenv("ARGUS_MCP_URL", "http://localhost:8000/mcp").strip(),
        )

    def memory_enabled(self) -> bool:
        return self.memory_db.lower() not in ("", "off", "none", "disabled")

    def resolved_llm_provider(self) -> str:
        """Resolve 'auto' to a concrete provider name."""
        if self.llm_provider != "auto":
            return self.llm_provider
        if self.anthropic_api_key and not _looks_placeholder(self.anthropic_api_key):
            return "anthropic"
        import shutil

        if shutil.which("claude"):
            return "claude-cli"
        if self.groq_api_key and not _looks_placeholder(self.groq_api_key):
            return "groq"
        if self.cerebras_api_key and not _looks_placeholder(self.cerebras_api_key):
            return "cerebras"
        return "heuristic"

    def validate_live(self) -> None:
        """Refuse to run live with missing/placeholder secrets. Names only, never values."""
        required = {"SIGNOZ_API_KEY": self.signoz_api_key}
        if self.resolved_llm_provider() == "anthropic":
            required["ANTHROPIC_API_KEY"] = self.anthropic_api_key
        bad = [name for name, value in required.items() if _looks_placeholder(value)]
        if bad:
            raise ConfigError(
                "Refusing to start: the following required secrets are missing or "
                f"look like placeholders: {', '.join(bad)}. Set real values in the "
                "environment (see .env.example). Values are never printed."
            )
        # Slack is optional (dry-run prints blocks), but a placeholder is still an error.
        if self.slack_bot_token and _looks_placeholder(self.slack_bot_token):
            raise ConfigError(
                "Refusing to start: SLACK_BOT_TOKEN is set but looks like a placeholder."
            )
        self.validated = True
