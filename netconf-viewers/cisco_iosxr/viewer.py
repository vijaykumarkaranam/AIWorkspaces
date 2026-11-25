"""Cisco IOS-XR live viewer: runs the queries one by one, shows each result as table tabs, then builds the report.

Run (run_viewer.bat does this):
  python viewer.py --port 8766
Then open http://127.0.0.1:8766/

Endpoints:
  GET  /                  the control page
  GET  /api/devices       routers from the ROUTERS list plus every Cisco node mounted in ODL
  GET  /api/queries       query ids and labels, in run order
  POST /api/run-query     {"node": "10.54.174.13", "query": "cisco-cpu"}  runs one query, saves it, returns its tables
  POST /api/build-report  builds results\\cisco_report.html from the newest saved results
  GET  /report            the last built report

Every query is a GET through ODL. Nothing is changed on the routers.
"""
import argparse
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from odl_client import OdlClient  # noqa: E402
import queries  # noqa: E402
import run_queries  # noqa: E402
import build_cisco_report as bcr  # noqa: E402

STYLE_FILE = os.path.join(HERE, "report_style.css")  # copy of the Nokia report style, kept beside this script
ROUTERS = os.environ.get("ROUTERS", "10.54.174.13 10.54.172.1").split()
ODL_NODES = {}  # Cisco nodes mounted in ODL: {node id: connection status}, filled by /api/devices


def _e2e_collect_module():
    parent = os.path.dirname(HERE)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    import e2e.collect
    return e2e.collect


def odl_cisco_nodes():
    """Cisco IOS-XR nodes mounted in ODL (vendor from their NETCONF capabilities), or {} if ODL cannot be read."""
    try:
        topo = _e2e_collect_module().topology(CLIENT)
        TOPOLOGY_ERROR["text"] = ""
    except Exception as exc:  # the page still works with the ROUTERS list
        TOPOLOGY_ERROR["text"] = str(exc)[:300]
        sys.stderr.write(f"ODL topology not read: {exc}\n")
        return {}
    return {n: t["status"] for n, t in topo.items() if t["vendor"] == "cisco"}


ODL_RE = re.compile(r"^https?://[A-Za-z0-9.\-]+(:\d{1,5})?$")
TOPOLOGY_ERROR = {"text": ""}


def devices_payload():
    """Router list for the page: ROUTERS plus the Cisco nodes mounted on the current controller."""
    ODL_NODES.clear()
    ODL_NODES.update(odl_cisco_nodes())
    extra = sorted(n for n in ODL_NODES if n not in ROUTERS)
    return {"devices": ROUTERS + extra, "routers": ROUTERS, "odl": CLIENT.base, "user": CLIENT.user,
            "mounted": sorted(ODL_NODES) if not TOPOLOGY_ERROR["text"] else None,
            "topologyError": TOPOLOGY_ERROR["text"],
            "status": {n: ODL_NODES.get(n, "") for n in ROUTERS + extra}}


def known_router(node):
    return bool(IP_RE.match(node or "")) and (node in ROUTERS or node in ODL_NODES)
IP_RE = re.compile(r"^[0-9A-Za-z.\-:_]{1,64}$")
CLIENT = None  # set in main()

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cisco IOS-XR viewer</title>
<style>__CSS__
.bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:14px 20px;height:auto;overflow:visible;background:none;border-radius:0;min-width:0;box-shadow:none}
.bar select{font:inherit;padding:6px 9px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink)}
.bar button,.tabs button,.toolbar button{font:inherit;padding:7px 12px;border:1px solid var(--glass-line);border-radius:8px;background:var(--glass-strong);color:var(--ink);cursor:pointer}
.bar button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.bar button:disabled{opacity:.5;cursor:wait}
.toolbar button.on,.tabs button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
#status{padding:0 20px;color:var(--muted)}
.tabs{display:flex;flex-wrap:wrap;gap:6px;padding:12px 20px 0}
.tabs button{padding:6px 10px;font-size:13px}
.tabs small{opacity:.75;margin-left:4px}
#view{padding:12px 20px 30px}
#view pre{background:var(--glass-strong);border:1px solid var(--glass-line);border-radius:10px;padding:12px;white-space:pre-wrap;word-break:break-word;font-size:12px;max-height:50vh;overflow:auto}
#view iframe{width:100%;height:80vh;border:1px solid var(--glass-line);border-radius:10px;background:#fff}
#view .toolbar{margin:8px 0;flex-wrap:wrap}
#view .toolbar input,#view .toolbar select{font:inherit;padding:6px 9px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink);min-width:240px}
#view tbody tr{cursor:pointer}
</style></head>
<body>
<header><h1>Cisco IOS-XR viewer</h1><span class="meta" id="meta"></span></header>
<div class="bar">
  <label>ODL <input id="odl" size="26" placeholder="http://controller:8181"></label>
  <input id="odlUser" size="8" placeholder="user">
  <input id="odlPass" type="password" size="10" placeholder="password (same if empty)">
  <button id="setOdl" title="Use this controller: the router list is reloaded from its topology">Use ODL</button>
  <label>Router <select id="dev"></select></label>
  <button class="primary" id="runOne">Run all queries</button>
  <button id="runEvery">Run all routers</button>
  <button id="build">Build report</button>
  <button id="collectFar" title="Fetch the far-end PEs (Cisco or Nokia) of this router's services, then rebuild the report">Collect far ends</button>
  <button id="clear">Clear tabs</button>
  <button id="stop" disabled title="Let the query that is running finish, then stop the run">Stop after this query</button>
</div>
<div id="status">Pick a router, then press Run all queries. Each query opens as a tab with its tables when it finishes.</div>
<div class="tabs" id="tabs"></div>
<div id="view"></div>
<script>
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));
const OK = /^(up|active|act|ok|connected|true|enabled|running|full|established|alive)$/i;
const BAD = /^(down|inactive|false|disabled|error|idle|not-active|unreachable|critical)$/i;
const MAX_ROWS = 1000;
let devices = [], routers = [], queries = [];
let tabs = [];          // {node, id, label, ok, tables:[{title,kind,columns,rows,raw,count}], ti, error, mode, q}
let active = -1;        // index into tabs
let reportReady = false, showReport = false;

function say(t){ $("status").textContent = t; }
function setBusy(b){ document.querySelectorAll("button,select").forEach(x => { if (x.id !== "stop") x.disabled = b; }); $("stop").disabled = !b; }

async function post(url, body){
  const r = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body || {})});
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
  return j;
}

function cell(v){
  if (v === null || v === undefined) return '<span class="muted">—</span>';
  if (typeof v === "boolean") v = String(v);
  if (typeof v === "number") return v.toLocaleString();
  const s = String(v);
  if (OK.test(s)) return `<span class="pill p-ok">${esc(s)}</span>`;
  if (BAD.test(s)) return `<span class="pill p-bad">${esc(s)}</span>`;
  return esc(s);
}

function curTable(t){ return t.tables[t.ti || 0]; }

function tableHTML(t){
  const T = curTable(t);
  const q = (t.q || "").toLowerCase();
  let idx = T.rows.map((r, i) => i);
  if (q) idx = idx.filter(i => T.rows[i].c.join(" ").toLowerCase().includes(q));
  const shown = idx.slice(0, MAX_ROWS);
  const head = T.columns.map(c => `<th>${esc(c)}</th>`).join("");
  const body = shown.map(i =>
    `<tr data-row="${i}">${T.rows[i].c.map(v => `<td>${cell(v)}</td>`).join("")}</tr>`).join("");
  const note = idx.length > MAX_ROWS ? ` (first ${MAX_ROWS} shown)` : "";
  return `<div class="tw"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>
    <p class="muted small">${idx.length} of ${T.rows.length} rows${note}. Click a row to see the full record below.</p>
    <pre id="detail">Click a row to see the full record.</pre>`;
}

function render(){
  const multi = new Set(tabs.map(t => t.node)).size > 1;
  let bar = tabs.map((t, i) => {
    const label = (multi ? t.node + " · " : "") + t.label;
    const n = t.ok ? `${t.tables.length} tables` : "no data";
    return `<button data-tab="${i}" class="${!showReport && i === active ? "on" : ""}">${esc(label)}
      <small>${n}</small></button>`;
  }).join("");
  if (reportReady) bar += `<button data-tab="report" class="${showReport ? "on" : ""}">Device report</button>`;
  $("tabs").innerHTML = bar;

  let view = "";
  if (showReport && reportReady) {
    view = `<iframe src="/report?ts=${Date.now()}"></iframe>`;
  } else if (active >= 0 && tabs[active]) {
    const t = tabs[active];
    if (!t.ok) {
      view = `<h3>${esc(t.node)} · ${esc(t.label)}</h3><pre>${esc(t.error)}</pre>`;
    } else {
      const mode = t.mode || "table";
      const picker = t.tables.length > 1
        ? `<select id="tsel">${t.tables.map((T, i) =>
            `<option value="${i}" ${i === (t.ti || 0) ? "selected" : ""}>${esc(T.title)} (${T.count})</option>`).join("")}</select>`
        : "";
      view = `<h3>${esc(t.node)} · ${esc(t.label)}</h3>
        <div class="toolbar">
          <button data-mode="table" class="${mode === "table" ? "on" : ""}">Table</button>
          <button data-mode="json" class="${mode === "json" ? "on" : ""}">JSON</button>
          ${picker}
          <input id="flt" placeholder="Filter rows" value="${esc(t.q || "")}">
        </div>` +
        (mode === "table"
          ? `<div id="tbl">${tableHTML(t)}</div>`
          : `<pre>${esc(JSON.stringify(t.data, null, 2).slice(0, 400000))}</pre>`);
    }
  }
  $("view").innerHTML = view;
}

let STOP = false;
async function runRouter(node){
  for (let i = 0; i < queries.length; i++) {
    const q = queries[i];
    const label = `${node}: query ${i + 1} of ${queries.length} · ${q.label}`;
    const t0 = Date.now();
    say(label);
    // A large answer can take minutes (the router is slow to build it, or ODL times out and reconnects).
    const tick = setInterval(() => {
      const s = Math.round((Date.now() - t0) / 1000);
      say(`${label} · running ${s} s` + (s > 30 ? " (still waiting for the router through ODL; a timeout or reconnect can take a few minutes, then the run continues)" : "") +
          (STOP ? " · will stop after this query" : ""));
    }, 1000);
    let r;
    try { r = await post("/api/run-query", {node, query: q.id}); }
    finally { clearInterval(tick); }
    tabs.push({node, id: q.id, label: q.label, ok: r.ok, tables: r.tables || [], ti: 0,
               data: r.data, error: r.error, mode: "table", q: "", secs: Math.round((Date.now() - t0) / 1000)});
    active = tabs.length - 1;
    showReport = false;
    render();
    if (STOP) return false;
  }
  return true;
}
$("stop").onclick = () => { STOP = true; $("stop").disabled = true; say("Stopping after the query that is running..."); };

async function buildReport(){
  say("Building report from the saved results...");
  const j = await post("/api/build-report");
  reportReady = true;
  showReport = true;
  render();
  say(`Report built (${j.megabytes} MB). Opened in the Device report tab.`);
}

function reset(){ tabs = []; active = -1; reportReady = false; showReport = false; render(); }

async function guard(fn){
  STOP = false;
  setBusy(true);
  try { await fn(); }
  catch (e) { say("Error: " + e.message); }
  finally { setBusy(false); }
}

$("runOne").onclick = () => guard(async () => {
  reset();
  const finished = await runRouter($("dev").value);
  await buildReport();
  say(`${$("dev").value} ${finished ? "done" : "stopped"}. ${tabs.filter(t => t.ok).length} queries with data, ${tabs.filter(t => !t.ok).length} without. Report is in the Device report tab.`);
});
$("runEvery").onclick = () => guard(async () => {
  reset();
  for (const n of routers) { if (!(await runRouter(n))) break; }  // the ROUTERS list only, not every node in ODL
  await buildReport();
  say("All routers done. Report is in the Device report tab.");
});
$("build").onclick = () => guard(buildReport);
$("collectFar").onclick = () => guard(async () => {
  const node = $("dev").value;
  say(`Fetching the far-end PEs of ${node}'s services through ODL. This can take several minutes...`);
  const j = await post("/api/e2e-collect", {node});
  const done = j.results.filter(x => x.action === "fetched"), skipped = j.results.filter(x => x.action === "skip");
  await buildReport();
  say(`Fetched ${done.length} far-end PE(s)` + (skipped.length ? `, skipped ${skipped.length} (` +
      skipped.slice(0, 6).map(x => `${x.ip}: ${x.reason}`).join("; ") + ")" : "") +
      ". Open the End-to-end services tab in the Device report.");
});
$("clear").onclick = () => { reset(); say("Tabs cleared."); };

$("tabs").addEventListener("click", e => {
  const b = e.target.closest("button[data-tab]");
  if (!b) return;
  if (b.dataset.tab === "report") showReport = true;
  else { active = +b.dataset.tab; showReport = false; }
  render();
});

document.addEventListener("click", e => {
  const m = e.target.closest("button[data-mode]");
  if (m && tabs[active]) { tabs[active].mode = m.dataset.mode; render(); return; }
  const tr = e.target.closest("tr[data-row]");
  if (tr && tabs[active]) {
    const t = tabs[active];
    const i = +tr.dataset.row;
    const d = $("detail");
    if (d) d.textContent = JSON.stringify(curTable(t).rows[i].raw, null, 2).slice(0, 200000);
  }
});

document.addEventListener("change", e => {
  if (e.target.id === "tsel" && tabs[active]) {
    tabs[active].ti = +e.target.value;
    tabs[active].q = "";
    render();
  }
});

document.addEventListener("input", e => {
  if (e.target.id === "flt" && tabs[active]) {
    const t = tabs[active];
    t.q = e.target.value;
    const tbl = $("tbl");
    if (tbl) tbl.innerHTML = tableHTML(t);
  }
});

function showDevices(d){
  devices = d.devices;
  routers = d.routers || d.devices;
  const st = d.status || {};
  $("dev").innerHTML = devices.map(x => `<option value="${esc(x)}">${esc(x)}${st[x] && st[x] !== "connected" ? " (" + esc(st[x]) + ")" : ""}${d.mounted && !d.mounted.includes(x) ? " (not on this ODL)" : ""}</option>`).join("");
  $("odl").value = d.odl;
  $("odlUser").value = d.user || "";
  $("meta").textContent = "ODL: " + d.odl + " · " + (d.mounted ? d.mounted.length + " Cisco nodes mounted" : "topology not read") + " · " + queries.length + " queries";
  if (d.topologyError) say("Could not read the ODL topology: " + d.topologyError);
}
$("setOdl").onclick = () => guard(async () => {
  say("Switching ODL and reading its topology...");
  const d = await post("/api/odl", {base: $("odl").value.trim(), user: $("odlUser").value.trim(), password: $("odlPass").value});
  $("odlPass").value = "";
  showDevices(d);
  say(`Using ODL ${d.odl}: ${d.mounted ? d.mounted.length : 0} Cisco nodes mounted. Pick a router.`);
});
Promise.all([fetch("/api/devices").then(r => r.json()), fetch("/api/queries").then(r => r.json())]).then(([d, q]) => {
  queries = q.queries;
  showDevices(d);
});
</script>
</body></html>
"""


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class Handler(BaseHTTPRequestHandler):
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

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, PAGE_HTML, "text/html; charset=utf-8")
        elif path == "/api/devices":
            self._json(200, devices_payload())
        elif path == "/api/queries":
            self._json(200, {"queries": [{"id": q, "label": m["label"]} for q, m in queries.QUERIES.items()]})
        elif path == "/report":
            if not os.path.isfile(bcr.OUT):
                self._json(404, {"error": "No report built yet. Run a router or press Build report first."})
            else:
                with open(bcr.OUT, "rb") as fh:
                    self._send(200, fh.read(), "text/html; charset=utf-8")
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/run-query":
                self._run_query(self._body())
            elif path == "/api/build-report":
                self._build_report()
            elif path == "/api/odl":
                self._set_odl(self._body())
            elif path == "/api/e2e-trace":
                self._e2e_trace(self._body())
            elif path == "/api/e2e-collect":
                self._e2e_collect(self._body())
            else:
                self._json(404, {"error": "not found"})
        except Exception as exc:  # return the problem to the page instead of dropping the connection
            self._json(500, {"error": str(exc)})

    def _run_query(self, req):
        node, qid = req.get("node", ""), req.get("query", "")
        if not known_router(node):
            self._json(400, {"error": f"unknown router {node!r}: not in ROUTERS and not a Cisco node mounted in ODL"})
            return
        if qid not in queries.QUERIES:
            self._json(400, {"error": f"unknown query {qid!r}"})
            return
        run_queries.run_query(CLIENT, node, qid)  # prints progress and saves the result file
        entry = bcr.latest_per_query(os.path.join(bcr.RESULTS, node))[qid]
        sec = bcr.make_section(qid, entry)  # same tables as the report
        if sec["status"] == "ok":
            tables = [{"title": t["title"], "kind": t["kind"], "count": t["count"],
                       "columns": t["columns"],
                       "rows": [{"c": r["c"]} for r in t["rows"]],
                       "raw": [r["raw"] for r in t["rows"]]}
                      for t in sec["tables"]]
            self._json(200, {"ok": True, "tables": tables, "data": read_json(entry[1]).get("data")})
        else:
            self._json(200, {"ok": False, "error": sec["error"]})

    def _set_odl(self, req):
        """Switch the controller this viewer queries (dev / prod), optionally with other credentials."""
        base = str(req.get("base") or "").strip().rstrip("/")
        if not ODL_RE.match(base):
            self._json(400, {"error": f"not a controller URL: {base!r} (expected e.g. http://10.218.66.24:8181)"})
            return
        CLIENT.base = base
        if req.get("user"):
            CLIENT.user = str(req["user"])
        if req.get("password"):
            CLIENT.password = str(req["password"])
        self._json(200, devices_payload())

    def _e2e_collect(self, req):
        """Fetch the far-end PEs of one router's services and save them for the End-to-end tab."""
        node = req.get("node", "")
        if not known_router(node):
            self._json(400, {"error": f"unknown router {node!r}: not in ROUTERS and not a Cisco node mounted in ODL"})
            return
        parent = os.path.dirname(HERE)
        if parent not in sys.path:
            sys.path.insert(0, parent)
        import e2e.collect as collect
        # CLIENT, not a new client: keeps the controller and credentials chosen with "Use ODL".
        items = collect.collect_far_ends(node, CLIENT, collect.Inventory(cisco_dir=bcr.RESULTS))
        self._json(200, {"node": node, "results": items})

    def _e2e_trace(self, req):
        """Trace one service's far ends live (the dashboard's method) and return the refreshed service."""
        node, service = str(req.get("node") or ""), str(req.get("service") or "")
        if not IP_RE.match(node) or not os.path.isdir(os.path.join(bcr.RESULTS, node)) or not service:
            self._json(400, {"error": f"no saved data for router {node!r}, or no service given"})
            return
        _e2e_collect_module()  # puts the netconf-viewers folder on the path
        import e2e.sources
        import e2e.trace
        try:
            res = e2e.trace.trace_service(node, service, CLIENT, e2e.sources.Inventory(cisco_dir=bcr.RESULTS))
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        payload = e2e.trace.traced_service_payload(node, service, e2e.sources.Inventory(cisco_dir=bcr.RESULTS))
        payload["trace"] = res
        self._json(200, payload)

    def _build_report(self):
        bcr.main()  # writes results\cisco_report.html and prints the path
        self._json(200, {"file": os.path.basename(bcr.OUT),
                         "megabytes": round(os.path.getsize(bcr.OUT) / 1e6, 2)})

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def page_html():
    with open(STYLE_FILE, encoding="utf-8-sig") as fh:
        css = fh.read()
    return PAGE.replace("__CSS__", css)


PAGE_HTML = ""


def main():
    global CLIENT, PAGE_HTML
    ap = argparse.ArgumentParser(description="Cisco IOS-XR live viewer (ODL RESTCONF backend)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--odl", default=None, help="ODL base URL (default: $ODL_BASE)")
    a = ap.parse_args()
    CLIENT = OdlClient(base=a.odl)
    PAGE_HTML = page_html()
    server = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"Viewer on http://{a.host}:{a.port}/  ODL: {CLIENT.base}  routers: {', '.join(ROUTERS)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    main()
