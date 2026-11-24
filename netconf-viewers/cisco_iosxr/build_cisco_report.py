r"""Build a single-file Cisco IOS-XR device report in the same style as the Nokia report.

Reads the newest result per query per device from results\<node>\ and writes
results\cisco_report.html (self-contained, works offline). The look comes from
report_style.css, a copy of the Nokia report style, so the folder runs on its own.

Usage (stdlib only):
  python build_cisco_report.py
"""
import datetime as dt
import html
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")
OUT = os.path.join(RESULTS, "cisco_report.html")
STYLE_FILE = os.path.join(HERE, "report_style.css")  # copy of the Nokia report style, kept beside this script
NAME_RE = re.compile(r"^(\d{8}-\d{6})_(.+?)(-error)?\.json$")
MAX_ROWS = 1000

TABS = [
    ("health", "Device health", "CPU, memory, environment, alarms, chassis, time and NTP.",
     ["cisco-cpu", "cisco-memory", "cisco-platform-env", "cisco-alarms",
      "cisco-platform-inventory", "cisco-system-time", "cisco-ntp"]),
    ("routing", "Routing and control plane", "OSPF, BGP, LDP, BFD, RIB, segment routing and static routes.",
     ["cisco-ospf-summary", "cisco-ospf-neighbors", "cisco-ospf-routes", "cisco-ospf-sr",
      "cisco-ospf-config", "cisco-bgp-neighbors", "cisco-ldp", "cisco-bfd", "cisco-rib-ipv4",
      "cisco-sr-config", "cisco-ipv4-static"]),
    ("services", "Services", "L2VPN operational state and configuration.",
     ["cisco-l2vpn", "cisco-l2vpn-config", "e2e-xconnect-config", "e2e-xconnect-oper", "e2e-bridge-oper",
      "e2e-bridge-ports", "e2e-ldp-neighbors", "e2e-ldp-bindings", "e2e-mpls-forwarding", "e2e-interface-config"]),
    ("interfaces", "Interfaces and neighbours", "Interface state and counters, Ethernet statistics, LLDP.",
     ["cisco-interfaces", "cisco-interfaces-xr", "cisco-ethernet-stats", "cisco-lldp-native", "cisco-lldp-config"]),
    ("management", "Management", "AAA configuration.", ["cisco-aaa-config"]),
]
LABELS = {
    "cisco-cpu": "CPU utilisation", "cisco-memory": "Memory", "cisco-platform-env": "Environment (fans, PSUs)",
    "cisco-alarms": "Active alarms", "cisco-platform-inventory": "Chassis and cards",
    "cisco-system-time": "System time and uptime", "cisco-ntp": "NTP",
    "cisco-ospf-summary": "OSPF summary", "cisco-ospf-neighbors": "OSPF neighbours",
    "cisco-ospf-routes": "OSPF route table", "cisco-ospf-sr": "OSPF segment routing",
    "cisco-ospf-config": "OSPF configuration", "cisco-bgp-neighbors": "BGP neighbours",
    "cisco-ldp": "LDP", "cisco-bfd": "BFD", "cisco-rib-ipv4": "IPv4 RIB (unicast)",
    "cisco-sr-config": "Segment routing configuration", "cisco-ipv4-static": "Static routes",
    "cisco-l2vpn": "L2VPN (operational)", "cisco-l2vpn-config": "L2VPN configuration",
    "cisco-interfaces": "Interfaces (generic)", "cisco-interfaces-xr": "Interfaces (IOS-XR state and counters)",
    "cisco-ethernet-stats": "Ethernet statistics", "cisco-lldp-native": "LLDP neighbours",
    "cisco-lldp-config": "LLDP configuration", "cisco-aaa-config": "AAA configuration",
    "e2e-xconnect-config": "E2E: xconnect config (AC and pseudowire)", "e2e-xconnect-oper": "E2E: xconnect state",
    "e2e-bridge-oper": "E2E: bridge domain state", "e2e-bridge-ports": "E2E: bridge ports (L2FIB)",
    "e2e-ldp-neighbors": "E2E: LDP neighbours", "e2e-ldp-bindings": "E2E: LDP bindings (IPv4)",
    "e2e-mpls-forwarding": "E2E: MPLS forwarding summary", "e2e-interface-config": "E2E: interface config (descriptions)",
    "cisco-l2vpn-xconnect": "L2VPN xconnects (operational)", "cisco-l2vpn-bridges": "L2VPN bridge groups and domains (operational)",
    "cisco-l2vpn-xconnect-config": "L2VPN xconnect configuration", "cisco-l2vpn-bridge-config": "L2VPN bridge configuration",
}
# Overview KPI cards: (label, query id, tab to open when clicked)
KPI_QUERIES = [
    ("Active alarms", "cisco-alarms", "health"),
    ("OSPF neighbours", "cisco-ospf-neighbors", "routing"),
    ("BGP neighbours", "cisco-bgp-neighbors", "routing"),
    ("LDP entries", "cisco-ldp", "routing"),
    ("BFD entries", "cisco-bfd", "routing"),
    ("IPv4 RIB rows", "cisco-rib-ipv4", "routing"),
    ("Static routes", "cisco-ipv4-static", "routing"),
    ("L2VPN entries", "cisco-l2vpn", "services"),
    ("L2VPN xconnects", "cisco-l2vpn-xconnect", "services"),
    ("L2VPN bridges", "cisco-l2vpn-bridges", "services"),
    ("Interfaces", "cisco-interfaces-xr", "interfaces"),
]


def latest_per_query(node_dir):
    """Return {query_id: (status, path, timestamp)} using the newest file for each query."""
    found = {}
    for fname in os.listdir(node_dir):
        m = NAME_RE.match(fname)
        if not m:
            continue
        stamp, qid, is_err = m.group(1), m.group(2), bool(m.group(3))
        if qid == "capabilities":
            continue
        cur = found.get(qid)
        if cur is None or stamp > cur[2]:
            found[qid] = ("error" if is_err else "ok", os.path.join(node_dir, fname), stamp)
    return found


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def is_scalar(v):
    return not isinstance(v, (dict, list))


def biggest_list(obj):
    """Longest list of records anywhere in the response, or None."""
    best = None

    def visit(o):
        nonlocal best
        if isinstance(o, list):
            if o and all(isinstance(x, dict) for x in o) and (best is None or len(o) > len(best)):
                best = o
            for x in o:
                visit(x)
        elif isinstance(o, dict):
            for v in o.values():
                visit(v)

    visit(obj)
    return best


def scalar_columns(items):
    cols = []
    for x in items[:200]:
        for k, v in x.items():
            if is_scalar(v) and k not in cols:
                cols.append(k)
    return cols[:14]


def flatten(obj, prefix="", out=None):
    """Leaf values as (path, value) pairs for single-object responses."""
    if out is None:
        out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            flatten(v, f"{prefix}{k}/", out)
    elif isinstance(obj, list):
        if obj and all(is_scalar(x) for x in obj):
            out.append((prefix.rstrip("/"), ", ".join(str(x) for x in obj)))
        else:
            for i, x in enumerate(obj):
                flatten(x, f"{prefix}{i}/", out)
    else:
        out.append((prefix.rstrip("/"), obj))
    return out


def cpu_rows(data):
    rows = []
    root = data.get("Cisco-IOS-XR-wdsysmon-fd-oper:system-monitoring", {})
    for node in root.get("cpu-utilization", []):
        vals = [node.get("total-cpu-one-minute"), node.get("total-cpu-five-minute"),
                node.get("total-cpu-fifteen-minute")]
        rows.append({"c": [node.get("node-name", "?")] + vals, "raw": node})
    return rows


def scalars(obj, prefix="", out=None):
    """Scalar fields reachable through dicts only (lists are shown as their own tables)."""
    if out is None:
        out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if is_scalar(v):
                out.append((prefix + k, v))
            else:
                scalars(v, prefix + k + "/", out)
    return out


def summary_blocks(obj, out=None):
    """(name, dict) for every nested dict whose key contains 'summary' and holds scalar fields."""
    if out is None:
        out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            name = k.split(":")[-1]
            if isinstance(v, dict) and "summary" in name and scalars(v):
                out.append((name, v))
            summary_blocks(v, out)
    elif isinstance(obj, list):
        for x in obj:
            summary_blocks(x, out)
    return out


def all_lists(obj, path=(), out=None):
    """Every list of records in the response, with the key path that leads to it."""
    if out is None:
        out = []
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj):
            out.append((path, obj))
        for x in obj:
            all_lists(x, path, out)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            all_lists(v, path + (k.split(":")[-1],), out)
    return out


def table_dict(title, kind, columns, rows, count=None):
    return {"title": title, "kind": kind, "columns": columns, "rows": rows[:MAX_ROWS],
            "count": count if count is not None else len(rows)}


def build_tables(data):
    """Summary table first, then one table per list of records (largest first)."""
    tables = []
    pairs = scalars(data)
    if pairs:
        tables.append(table_dict("Summary and settings", "summary", ["Field", "Value"],
                                 [{"c": [k, v], "raw": v} for k, v in pairs[:MAX_ROWS]]))
    seen = {}
    for name, sub in summary_blocks(data):  # e.g. xconnect-summary, bridge-domain-summary, inside node records
        n = seen.get(name, 0) + 1
        seen[name] = n
        title = name if n == 1 else f"{name} ({n})"
        tables.append(table_dict(title, "summary", ["Field", "Value"],
                                 [{"c": [k, v], "raw": v} for k, v in scalars(sub)[:MAX_ROWS]]))
    lists = sorted(all_lists(data), key=lambda p: -len(p[1]))
    for path, items in lists[:20]:
        cols = scalar_columns(items)
        rows = [{"c": [x.get(c) if is_scalar(x.get(c)) else None for c in cols], "raw": x}
                for x in items[:MAX_ROWS]]
        title = " / ".join(path[-3:]) if path else "Records"
        tables.append(table_dict(title, "list", cols, rows, len(items)))
    return tables


def make_section(qid, entry):
    status, path, stamp = entry
    when = dt.datetime.strptime(stamp, "%Y%m%d-%H%M%S").strftime("%Y-%m-%d %H:%M")
    sec = {"id": qid, "title": LABELS.get(qid, qid), "status": status, "when": when,
           "error": "", "columns": [], "rows": [], "count": None, "tables": []}
    if status == "error":
        sec["error"] = load(path).get("error", "")
        return sec
    data = load(path).get("data", {})
    if qid == "cisco-cpu":
        sec["columns"] = ["Node", "1 min %", "5 min %", "15 min %"]
        sec["rows"] = cpu_rows(data)
        sec["tables"] = [table_dict("CPU per node", "list", sec["columns"], sec["rows"])]
    else:
        sec["tables"] = build_tables(data)
        lists = [t for t in sec["tables"] if t["kind"] == "list"]
        sec["count"] = lists[0]["count"] if lists else None  # largest list, used for the overview cards
        first = sec["tables"][0] if sec["tables"] else {"columns": [], "rows": []}
        sec["columns"], sec["rows"] = first["columns"], first["rows"]
    return sec


def cpu_kpis(secs):
    sec = secs.get("cisco-cpu")
    if not sec or sec["status"] != "ok":
        return []
    out = []
    for r in sec["rows"]:
        name = str(r["c"][0])
        role = "RP" if "RP" in name else ("LC" if "CPU" in name else name)
        out.append({"label": f"CPU {role} (1 min)", "value": f"{r['c'][1]}%",
                    "sub": f"5 min {r['c'][2]}% · 15 min {r['c'][3]}% · {name}", "tab": "health"})
    return out


def count_kpi(secs, qid, label, tab):
    s = secs.get(qid)
    if s is None:
        value, sub = "not run", ""
    elif s["status"] == "error":
        value, sub = "error", "see section"
    elif s["count"] is None:
        value, sub = "data", "single object"
    else:
        value, sub = s["count"], "rows in response"
    return {"label": label, "value": value, "sub": sub, "tab": tab}


def build_device(node, node_dir):
    found = latest_per_query(node_dir)
    secs = {q: make_section(q, e) for q, e in found.items()}
    ok = sum(1 for s in secs.values() if s["status"] == "ok")
    err = sum(1 for s in secs.values() if s["status"] == "error")
    kpis = cpu_kpis(secs) + [count_kpi(secs, q, lbl, tab) for lbl, q, tab in KPI_QUERIES]
    kpis.append({"label": "Queries", "value": f"{ok} ok", "sub": f"{err} errors", "tab": "overview"})
    summary = [{"id": s["id"], "title": s["title"], "status": s["status"], "when": s["when"],
                "count": s["count"], "tab": tab_of(s["id"])} for s in secs.values()]
    summary.sort(key=lambda x: (x["tab"], x["title"]))
    tabs = [{"id": "overview", "label": "Overview", "count": ok, "lead": "Key figures for this device.",
             "sections": []}]
    used = set()
    for tid, label, lead, ids in TABS:
        sections = [secs[q] for q in ids if q in secs]
        used.update(ids)
        tabs.append({"id": tid, "label": label, "count": sum(1 for s in sections if s["status"] == "ok"),
                     "lead": lead, "sections": sections})
    extra = [secs[q] for q in sorted(secs) if q not in used]
    if extra:
        tabs.append({"id": "other", "label": "Other", "count": len(extra), "lead": "Queries not in a group.",
                     "sections": extra})
    return {"node": node, "kpis": kpis, "summary": summary, "tabs": tabs}


def tab_of(qid):
    for tid, _label, _lead, ids in TABS:
        if qid in ids:
            return tid
    return "other"


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cisco IOS-XR device report</title>
<style>__CSS__</style></head>
<body>
<header>
  <h1>Cisco IOS-XR device report</h1>
  <div class="meta" id="meta"></div>
  <div style="flex:1"></div>
  <button class="btn" id="theme">Theme</button>
</header>
<div class="toolbar" id="dev" style="padding:10px 20px 0"></div>
<nav id="nav"></nav>
<main id="main"></main>
<aside id="drawer"><div class="hd"><h2 id="d-title"></h2><button class="x" id="d-close">Close</button></div>
<div class="bd" id="d-body"></div></aside>

<script>
const D = __DATA__;
const MAX_ROWS = __MAX_ROWS__;
const S = {};       // table state per section key
const SECS = {};    // section lookup per section key
let di = 0, ti = "overview";
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));
const OK = /^(up|active|act|ok|connected|true|enabled|running|full|established|alive)$/i;
const BAD = /^(down|inactive|false|disabled|error|idle|not-active|unreachable|critical)$/i;

function cell(v){
  if (v === null || v === undefined) return '<span class="muted">—</span>';
  if (typeof v === "boolean") v = String(v);
  if (typeof v === "number") return v.toLocaleString();
  const s = String(v);
  if (OK.test(s)) return `<span class="pill p-ok">${esc(s)}</span>`;
  if (BAD.test(s)) return `<span class="pill p-bad">${esc(s)}</span>`;
  return esc(s);
}

function tableState(key){ return S[key] || (S[key] = {q: "", col: -1, dir: 1}); }

function visibleRows(sec, key){
  const st = tableState(key);
  let rows = sec.rows.map((r, i) => ({r, i}));
  if (st.q) {
    const q = st.q.toLowerCase();
    rows = rows.filter(x => x.r.c.join(" ").toLowerCase().includes(q));
  }
  if (st.col >= 0) {
    rows.sort((a, b) => {
      const x = a.r.c[st.col], y = b.r.c[st.col];
      if (typeof x === "number" && typeof y === "number") return (x - y) * st.dir;
      return String(x ?? "").localeCompare(String(y ?? ""), undefined, {numeric: true}) * st.dir;
    });
  }
  return rows;
}

function tableBody(sec, key){
  const st = tableState(key);
  const rows = visibleRows(sec, key);
  const head = sec.columns.map((c, j) =>
    `<th data-col="${j}" data-key="${key}">${esc(c)}${st.col === j ? (st.dir > 0 ? " ▲" : " ▼") : ""}</th>`).join("");
  const body = rows.slice(0, MAX_ROWS).map(x =>
    `<tr data-key="${key}" data-row="${x.i}">${x.r.c.map(v => `<td>${cell(v)}</td>`).join("")}</tr>`).join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function countText(sec, key){
  const n = visibleRows(sec, key).length;
  return `${n} of ${sec.rows.length} rows${n > MAX_ROWS ? " (first " + MAX_ROWS + " shown)" : ""}`;
}

function sectionHTML(sec, key){
  const pill = sec.status === "error" ? '<span class="pill p-bad">error</span>' : '<span class="pill p-ok">data</span>';
  const head = `<h3>${esc(sec.title)} ${pill} <small>${esc(sec.when)}</small></h3>`;
  if (sec.status === "error") return `<div class="card" style="margin:12px 0">${head}<pre>${esc(sec.error)}</pre></div>`;
  if (!sec.tables || !sec.tables.length) return `<div class="card" style="margin:12px 0">${head}<p class="muted">no rows</p></div>`;
  const parts = sec.tables.map((t, ti) => {
    const k = key + "_" + ti;          // one state entry per table
    SECS[k] = t;
    const label = t.kind === "summary" ? `${t.rows.length} fields` : `${t.count} rows`;
    const body = t.rows.length
      ? `<div class="toolbar"><input placeholder="Filter rows" value="${esc(tableState(k).q)}" data-q="${k}">
          <span class="count" id="ct-${k}">${countText(t, k)}</span></div>
         <div class="tw" id="tw-${k}">${tableBody(t, k)}</div>`
      : '<p class="muted">no rows</p>';
    return `<h4 style="margin:16px 0 4px">${esc(t.title)} <span class="muted small">${label}</span></h4>${body}`;
  }).join("");
  return `<div class="card" style="margin:12px 0">${head}${parts}</div>`;
}

function overviewHTML(d){
  const cards = d.kpis.map(k =>
    `<div class="card kpi link" data-goto="${k.tab}"><div class="l">${esc(k.label)}</div>
     <div class="v">${esc(k.value)}</div><div class="s muted">${esc(k.sub || "")}</div></div>`).join("");
  const rows = d.summary.map(s =>
    `<tr data-goto="${s.tab}"><td>${esc(s.title)}</td><td>${s.status === "error" ? '<span class="pill p-bad">error</span>' : '<span class="pill p-ok">data</span>'}</td><td class="num">${s.count ?? ""}</td><td>${esc(s.when)}</td></tr>`).join("");
  return `<h2>${esc(d.node)}</h2><p class="lead">Click a card or a row to open that area.</p>
    <div class="grid kpis">${cards}</div>
    <h3>Query status</h3><div class="tw"><table><thead><tr><th>Query</th><th>Status</th><th class="num">Rows</th><th>Taken</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

function render(){
  const d = D.devices[di];
  document.getElementById("meta").innerHTML = `Generated <b>${esc(D.generated)}</b> · ${D.devices.length} device(s)`;
  document.getElementById("dev").innerHTML = D.devices.map((x, i) =>
    `<button class="btn" data-dev="${i}" style="${i === di ? "font-weight:650;border-color:var(--accent)" : ""}">${esc(x.node)}</button>`).join(" ");
  document.getElementById("nav").innerHTML = d.tabs.map(t =>
    `<button class="${t.id === ti ? "on" : ""}" data-t="${t.id}">${esc(t.label)}<span class="ct">${t.count}</span></button>`).join("");
  const t = d.tabs.find(x => x.id === ti) || d.tabs[0];
  if (t.id === "overview") {
    document.getElementById("main").innerHTML = overviewHTML(d);
  } else {
    document.getElementById("main").innerHTML = `<h2>${esc(t.label)}</h2><p class="lead">${esc(t.lead)}</p>` +
      t.sections.map(s => sectionHTML(s, di + "_" + s.id)).join("");
  }
}

function refreshTable(key){
  const sec = SECS[key];
  document.getElementById("tw-" + key).innerHTML = tableBody(sec, key);
  document.getElementById("ct-" + key).textContent = countText(sec, key);
}

function openDrawer(key, i){
  const sec = SECS[key];
  const row = sec.rows[i];
  document.getElementById("d-title").textContent = sec.title + " · row " + (i + 1);
  document.getElementById("d-body").innerHTML = `<pre>${esc(JSON.stringify(row.raw, null, 2))}</pre>`;
  document.getElementById("drawer").classList.add("on");
}

document.addEventListener("click", e => {
  const dv = e.target.closest("[data-dev]");
  if (dv) { di = +dv.dataset.dev; ti = "overview"; render(); return; }
  const tb = e.target.closest("[data-t]");
  if (tb) { ti = tb.dataset.t; render(); return; }
  const gt = e.target.closest("[data-goto]");
  if (gt) { ti = gt.dataset.goto; render(); window.scrollTo(0, 0); return; }
  const th = e.target.closest("th[data-col]");
  if (th) {
    const st = tableState(th.dataset.key), col = +th.dataset.col;
    st.dir = st.col === col ? -st.dir : 1;
    st.col = col;
    refreshTable(th.dataset.key);
    return;
  }
  const tr = e.target.closest("tr[data-row]");
  if (tr) { openDrawer(tr.dataset.key, +tr.dataset.row); return; }
  if (e.target.id === "d-close") { document.getElementById("drawer").classList.remove("on"); return; }
  if (e.target.id === "theme") {
    const r = document.documentElement;
    const dark = r.dataset.theme ? r.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    r.dataset.theme = dark ? "light" : "dark";
  }
});

document.addEventListener("input", e => {
  if (e.target.matches && e.target.matches("input[data-q]")) {
    tableState(e.target.dataset.q).q = e.target.value;
    refreshTable(e.target.dataset.q);
  }
});

render();
</script>
</body></html>
"""


def main():
    nodes = sorted(n for n in os.listdir(RESULTS) if os.path.isdir(os.path.join(RESULTS, n)))
    if not nodes:
        raise SystemExit(f"No device folders found in {RESULTS}")
    with open(STYLE_FILE, encoding="utf-8-sig") as fh:
        css = fh.read()
    data = {"generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "devices": [build_device(n, os.path.join(RESULTS, n)) for n in nodes]}
    payload = json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/")
    page = PAGE.replace("__CSS__", css).replace("__DATA__", payload)
    page = page.replace("__MAX_ROWS__", str(MAX_ROWS))
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
