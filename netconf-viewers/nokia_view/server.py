"""Live viewer: serves index.html and a small JSON API that calls ODL.

Run:
  python server.py --port 8765
Then open http://127.0.0.1:8765/

Endpoints:
  GET  /               the page
  GET  /api/queries    named queries
  GET  /api/nodes      mounted NETCONF nodes from ODL
  POST /api/run        {"node": "162.104.38.226", "query": "epipe-state"}
                       or {"node": "...", "cli": "service fdb-mac"}
"""
import argparse
import json
import os
import shutil
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


from odl_client import OdlClient, OdlError  # noqa: E402
import queries  # noqa: E402
import analyze  # noqa: E402
import store  # noqa: E402


REPORT = {"path": None}  # the last device report built from the stored runs


class Handler(BaseHTTPRequestHandler):
    client = None  # set in main()

    def _build_report(self):
        """Build the device report from the stored runs (same as build_device_report.py)."""
        try:
            import build_device_report as bdr
            out = bdr.build(HERE)  # writes <device>_device_report.html here, from the newest stored device
            REPORT["path"] = out
            self._json(200, {"file": os.path.basename(out), "location": out,
                             "megabytes": round(os.path.getsize(out) / 1e6, 2)})
        except Exception as exc:  # report the problem to the page instead of dropping the connection
            self._json(500, {"error": f"report build failed: {exc}"})

    def _send(self, code, body, content_type="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, default=str))

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), encoding="utf-8") as fh:
                page = fh.read().replace("__TITLE__", "Nokia Device insights")
            self._send(200, page, "text/html; charset=utf-8")
        elif path == "/api/queries":
            self._json(200, queries.catalog())
        elif path == "/api/nodes":
            try:
                self._json(200, {"nodes": self.client.nodes()})
            except OdlError as exc:
                self._json(502, {"error": str(exc)})
        elif path == "/report":
            p = REPORT.get("path")
            if not p or not os.path.isfile(p):
                self._json(404, {"error": "no report built yet. Press Build report first."})
            else:
                with open(p, "rb") as fh:
                    self._send(200, fh.read(), "text/html; charset=utf-8")
        elif path == "/api/history":
            node = parse_qs(urlparse(self.path).query).get("node", [""])[0]
            try:
                queries.validate_node(node)
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            self._json(200, {"files": store.history(node)})
        elif path == "/api/saved":
            rel = parse_qs(urlparse(self.path).query).get("path", [""])[0]
            try:
                self._json(200, store.load(rel))
            except (ValueError, FileNotFoundError) as exc:
                self._json(404, {"error": str(exc)})
        else:
            self._json(404, {"error": "not found"})

    def _run_all(self):
        """Run every named query for one node (config first), saving each result."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
            node = queries.validate_node(json.loads(self.rfile.read(length) or b"{}").get("node"))
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        config_ids = [q for q, v in queries.QUERIES.items() if v["kind"] == "config"]
        other_ids = [q for q in queries.QUERIES if q not in config_ids]
        results = []
        for qid in config_ids + other_ids:
            try:
                r = queries.run_request(self.client, {"node": node, "query": qid})
                config = store.latest_data(node, "config-services")
                r["findings"] = analyze.analyze(r["data"], config)
                r["savedTo"] = store.save(r)
                results.append(r)
            except (OdlError, ValueError) as exc:
                results.append({"node": node, "query": qid, "label": queries.QUERIES[qid]["label"],
                                "error": str(exc)})
        self._json(200, {"results": results})

    def do_POST(self):
        if urlparse(self.path).path == "/api/run-all":
            self._run_all()
            return
        if urlparse(self.path).path == "/api/build-report":
            self._build_report()
            return
        if urlparse(self.path).path != "/api/run":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(length) or b"{}")
            result = queries.run_request(self.client, req)
            config = store.latest_data(result["node"], "config-services")
            result["findings"] = analyze.analyze(result["data"], config)
            result["savedTo"] = store.save(result)
            self._json(200, result)
        except ValueError as exc:  # bad JSON or bad input
            self._json(400, {"error": str(exc)})
        except OdlError as exc:
            self._json(502, {"error": str(exc)})

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main():
    ap = argparse.ArgumentParser(description="Live Nokia NETCONF viewer (ODL RESTCONF backend)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--odl", default=None, help="ODL base URL (default: $ODL_BASE)")
    a = ap.parse_args()
    Handler.client = OdlClient(base=a.odl)
    server = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"Viewer on http://{a.host}:{a.port}/  ODL: {Handler.client.base}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    main()
