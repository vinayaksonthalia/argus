"""Tiny zero-dependency HTTP server for the ARGUS Investigations Console.

Follows the campaign's viewer pattern (GLASSPANE session-timeline): a minimal
server that binds localhost only and serves a vanilla-JS page from local data.
Read-only — it never mutates, never calls an LLM, and needs no SigNoz key
(everything renders from ``postmortems/`` + the memory SQLite). Built on the
standard library's ``http.server`` so it adds no dependency to the project.

Routes:
  GET /                      -> the single-page shell (server-rendered rail)
  GET /api/list              -> JSON summary of all investigations
  GET /api/detail/<id>       -> escaped HTML fragment for one investigation
  GET /healthz               -> 200 "ok"
"""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from . import data, render

# Investigation ids are ARGUS-generated: "inv-" + hex. Whitelist strictly so a
# path segment can never escape the id space (defense in depth; we only ever
# look ids up in an in-memory dict, never touch the filesystem with them).
_ID_RE = re.compile(r"^inv-[0-9a-fA-F]+$")


class ConsoleData:
    """Loads and holds the investigation set; reload() re-reads from disk."""

    def __init__(self, postmortem_dir: Path, memory_db: Optional[Path]):
        self.postmortem_dir = Path(postmortem_dir)
        self.memory_db = Path(memory_db) if memory_db else None
        self.investigations: list[data.Investigation] = []
        self.by_id: dict[str, data.Investigation] = {}
        self.reload()

    def reload(self) -> None:
        self.investigations = data.load_investigations(
            self.postmortem_dir, self.memory_db
        )
        self.by_id = {i.id: i for i in self.investigations}

    @property
    def stats(self) -> data.Stats:
        return data.compute_stats(self.investigations)


def make_handler(store: ConsoleData):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ARGUS-Console/1.0"

        def log_message(self, *args):  # keep the terminal quiet
            pass

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            # This is a local read-only tool; lock the browser down anyway.
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; connect-src 'self'",
            )
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _html(self, status: int, html: str) -> None:
            self._send(status, html.encode("utf-8"), "text/html; charset=utf-8")

        def _json(self, status: int, obj) -> None:
            self._send(
                status,
                json.dumps(obj).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def do_HEAD(self):  # noqa: N802
            self.do_GET()

        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0].rstrip("/") or "/"

            if path == "/":
                store.reload()  # cheap; keeps the console live as new RCAs land
                self._html(200, render.render_page(store.investigations, store.stats))
                return

            if path == "/healthz":
                self._send(200, b"ok", "text/plain; charset=utf-8")
                return

            if path == "/api/list":
                items = [
                    {
                        "id": i.id, "title": i.title, "service": i.service,
                        "alert": i.alert, "date": i.date_display,
                        "confidence": i.confidence, "status": i.status,
                        "usd": i.cost.usd,
                    }
                    for i in store.investigations
                ]
                self._json(200, {"investigations": items, "stats": {
                    "total": store.stats.total,
                    "verified_pct": store.stats.verified_pct,
                    "total_usd": store.stats.total_usd,
                }})
                return

            if path.startswith("/api/detail/"):
                inv_id = path[len("/api/detail/"):]
                if not _ID_RE.match(inv_id):
                    self._html(400, '<div class="pane-error">Invalid investigation id.</div>')
                    return
                inv = store.by_id.get(inv_id)
                if inv is None:
                    store.reload()
                    inv = store.by_id.get(inv_id)
                if inv is None:
                    self._html(404, '<div class="pane-error">Investigation not found.</div>')
                    return
                self._html(200, render.render_detail(inv))
                return

            self._send(404, b"not found", "text/plain; charset=utf-8")

    return Handler


def serve(
    postmortem_dir: Path,
    memory_db: Optional[Path] = None,
    host: str = "127.0.0.1",
    port: int = 7332,
) -> ThreadingHTTPServer:
    """Create (but do not block on) the console server, bound to localhost."""
    store = ConsoleData(postmortem_dir, memory_db)
    httpd = ThreadingHTTPServer((host, port), make_handler(store))
    return httpd
