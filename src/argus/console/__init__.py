"""ARGUS Investigations Console — a small, read-only, zero-dependency web UI
that renders the investigations ARGUS has already produced (from
``postmortems/`` + the incident-memory SQLite). See ``server.py``."""

from .data import (
    Cost,
    Evidence,
    Hypothesis,
    Investigation,
    Stats,
    compute_stats,
    load_investigation,
    load_investigations,
)
from .server import ConsoleData, serve

__all__ = [
    "Cost", "Evidence", "Hypothesis", "Investigation", "Stats",
    "compute_stats", "load_investigation", "load_investigations",
    "ConsoleData", "serve",
]
