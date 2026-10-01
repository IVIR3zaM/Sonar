"""Serve a live view of a plan.

Read-only: every request rebuilds the §12 data from the plan files and `git log` through
`status.load_report`; nothing is cached and nothing is written (FORMAT §9, §12).
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from planzilla.commands._common import ResolveError, fail, resolve_plan
from planzilla.commands.status import load_report
from planzilla.plan import PlanError
from planzilla.report import Report
from planzilla.state import StateError

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PAGE = Path(__file__).resolve().parent.parent / "web" / "index.html"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("plan", help="plan path or slug fragment")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"port on 127.0.0.1 (default {DEFAULT_PORT})"
    )


def state_json(report: Report) -> dict:
    """The §12 live-view body for `report`."""
    return {
        "plan": report.slug,
        "title": report.title,
        "status": report.status,
        "tier": report.tier,
        "updated": report.updated,
        "done": report.done,
        "total": report.total,
        "elapsed": report.elapsed,
        "waves": [
            {
                "wave": wave,
                "nodes": [
                    {
                        "id": v.id,
                        "title": v.title,
                        "type": v.type,
                        "status": v.status,
                        "view": v.view,
                        "try": v.tries,
                        "rp": v.rp,
                        "note": v.note,
                        "last": v.last,
                        "elapsed": v.elapsed,
                    }
                    for v in views
                ],
            }
            for wave, views in report.waves
        ],
    }


class Handler(BaseHTTPRequestHandler):
    plan_path: Path

    def _send(self, code: int, kind: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path == "/":
            self._send(200, "text/html; charset=utf-8", PAGE.read_bytes())
        elif path == "/state.json":
            try:
                report = load_report(str(self.plan_path), self.plan_path.parent.parent)
            except (ResolveError, PlanError, StateError, OSError) as error:
                self._send(500, "text/plain; charset=utf-8", f"error: {error}\n".encode())
                return
            body = json.dumps(state_json(report), ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found\n")

    def log_message(self, format: str, *args) -> None:
        pass


def make_server(plan_path: Path, port: int) -> ThreadingHTTPServer:
    """A server for `plan_path` bound to 127.0.0.1:`port` (0 picks a free port)."""
    handler = type("PlanHandler", (Handler,), {"plan_path": plan_path.resolve()})
    server = ThreadingHTTPServer((HOST, port), handler)
    server.daemon_threads = True
    return server


def run(args: argparse.Namespace) -> int:
    try:
        plan_path = resolve_plan(args.plan, Path.cwd())
        report = load_report(str(plan_path.resolve()), Path.cwd())
    except (ResolveError, PlanError, StateError) as error:
        return fail(str(error), 2)
    try:
        server = make_server(plan_path, args.port)
    except OSError as error:
        return fail(f"cannot listen on {HOST}:{args.port}: {error.strerror or error}", 3)
    with server:
        print(f"serving {report.slug} on http://{HOST}:{server.server_address[1]}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0
