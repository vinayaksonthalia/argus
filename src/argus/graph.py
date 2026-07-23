"""Minimal LangGraph-style typed state machine.

Deliberately dependency-free (~100 lines): nodes are `fn(state) -> state`,
edges are static or conditional, and every node execution gets its own OTel
span plus graceful-degradation error capture (NFR-4). The node API mirrors
LangGraph's, so migrating to the real library later is mechanical.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from .models import InvestigationState
from .telemetry import node_span

logger = logging.getLogger("argus.graph")

NodeFn = Callable[[InvestigationState], InvestigationState]
RouterFn = Callable[[InvestigationState], str]

END = "__end__"


class Graph:
    """A named-node state machine with static and conditional edges."""

    def __init__(self, entry: str) -> None:
        self._entry = entry
        self._nodes: dict[str, NodeFn] = {}
        self._edges: dict[str, str] = {}
        self._routers: dict[str, RouterFn] = {}
        # Nodes whose failure should degrade (record error, continue) rather than abort.
        self._optional: set[str] = set()

    def add_node(self, name: str, fn: NodeFn, optional: bool = False) -> "Graph":
        self._nodes[name] = fn
        if optional:
            self._optional.add(name)
        return self

    def add_edge(self, src: str, dst: str) -> "Graph":
        self._edges[src] = dst
        return self

    def add_conditional_edge(self, src: str, router: RouterFn) -> "Graph":
        self._routers[src] = router
        return self

    def run(
        self,
        state: InvestigationState,
        on_node: Optional[Callable[[str, float], None]] = None,
        max_steps: int = 50,
    ) -> InvestigationState:
        """Execute from entry until END. `on_node(name, seconds)` is a progress hook."""
        current = self._entry
        steps = 0
        while current != END:
            if steps >= max_steps:
                state.errors.append(f"graph aborted: exceeded {max_steps} steps")
                break
            steps += 1
            fn = self._nodes[current]
            t0 = time.monotonic()
            with node_span(current, {"argus.investigation_id": state.investigation_id}):
                try:
                    state = fn(state)
                except Exception as exc:  # noqa: BLE001 — degradation boundary
                    msg = f"node '{current}' failed: {type(exc).__name__}: {exc}"
                    logger.warning(msg)
                    state.errors.append(msg)
                    if current not in self._optional:
                        # Hard node failure: jump straight to report for an
                        # evidence-only partial RCA instead of hanging (NFR-4).
                        if current not in ("report",) and "report" in self._nodes:
                            current = "report"
                            if on_node:
                                on_node("(degraded → report)", time.monotonic() - t0)
                            continue
                        break
            if on_node:
                on_node(current, time.monotonic() - t0)
            if current in self._routers:
                current = self._routers[current](state)
            else:
                current = self._edges.get(current, END)
        return state
