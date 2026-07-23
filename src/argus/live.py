"""Live-mode dependency wiring shared by the CLI and the webhook server.

One place decides: which SigNoz read transport (REST or MCP), which LLM
provider, and whether incident memory / dashboards / draft rules are active.
"""

from __future__ import annotations

from .config import Settings
from .llm import make_provider
from .nodes import Deps
from .signoz.client import SignozClient
from .signoz.dashboards import DashboardClient
from .signoz.links import LinkFactory
from .signoz.rules import RuleClient
from .signoz.transport import HttpTransport, SignozTransport


def make_transport(settings: Settings) -> SignozTransport:
    if settings.transport == "rest":
        return HttpTransport(settings.signoz_url, settings.signoz_api_key)
    if settings.transport == "mcp":
        from .signoz.mcp_transport import McpTransport

        return McpTransport(settings.mcp_url, settings.signoz_api_key)
    raise ValueError(
        f"unknown ARGUS_TRANSPORT '{settings.transport}' (expected rest|mcp)"
    )


def make_live_deps(settings: Settings) -> Deps:
    memory = None
    if settings.memory_enabled():
        from .memory import IncidentMemory

        memory = IncidentMemory(settings.memory_db)
    return Deps(
        signoz=SignozClient(make_transport(settings)),
        links=LinkFactory(settings.signoz_url),
        llm=make_provider(settings),
        dashboards=DashboardClient(settings.signoz_url, settings.signoz_api_key),
        memory=memory,
        rules=RuleClient(settings.signoz_url, settings.signoz_api_key),
    )
