"""Transport detail shared by the adapters: hop paths, port health and the clickable detail objects.

Detail objects (shown in the report's detail panel) all have this shape:
  {"key": "lsp|<node>|<name>", "kind": "lsp", "title": ..., "subtitle": ..., "status": "up"/"down"/...,
   "fields": [[label, value], ...],                       summary shown first
   "tables": [{"title":, "columns": [...], "rows": [[cell, ...]]}],   a cell may be {"t": text, "k": key} (a link)
   "links": [{"label":, "key":}],                         related objects
   "raw": {...}}                                          every field as the router returned it
"""
import csv
import os

from .util import as_list, get, norm_state

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def key(kind, node, ident):
    return f"{kind}|{node}|{ident}"


def link(text, k):
    """A table cell that opens another object."""
    return {"t": str(text), "k": k} if k else str(text)


def obj(kind, node, ident, title, subtitle="", status=None, fields=None, tables=None, links=None, raw=None):
    return {"key": key(kind, node, ident), "kind": kind, "node": node, "title": title, "subtitle": subtitle,
            "status": status, "fields": [f for f in (fields or []) if f[1] not in (None, "", [], {})],
            "tables": [t for t in (tables or []) if t.get("rows")], "links": links or [], "raw": raw}


def fmt_uptime(seconds):
    """'36d 7h' or '15h 34m', as the dashboard shows LDP session uptime."""
    try:
        sec = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    if sec <= 0:
        return ""
    d, h, m = sec // 86400, (sec % 86400) // 3600, (sec % 3600) // 60
    return f"{d}d {h}h" if d else f"{h}h {m}m"


def num(x, default=0):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- PCE export (Nokia RSVP-TE hop paths)

class PceIndex:
    """pce-lsp-inventory.csv: the explicit route (ERO) of every PCEP-reported LSP, and router names for
    hop addresses (the sender and endpoint loopbacks, and the first and last hop of each path)."""

    _cache = {}

    def __init__(self, path):
        self.path = path
        self.rows, self.ip_name = {}, {}
        if not path or not os.path.isfile(path):
            return
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        for r in rows:
            name = (r.get("name") or "").split("::")[0]
            a, _, b = name.partition("-")
            hops = [h.strip().split("/")[0] for h in (r.get("ero") or "").split(">") if h.strip()]
            if a:
                self.ip_name.setdefault(r.get("sender"), a)
                if hops:
                    self.ip_name.setdefault(hops[0], a)   # first hop: the sender's own egress interface
            if b:
                self.ip_name.setdefault(r.get("endpoint"), b)
                if hops:
                    self.ip_name.setdefault(hops[-1], b)  # last hop: the endpoint's ingress interface
            self.rows.setdefault((r.get("pcc"), r.get("name")), r)

    @classmethod
    def load(cls, path=None):
        path = path or os.environ.get("E2E_PCE_CSV") or os.path.join(ROOT, "nokia_view", "pce-lsp-inventory.csv")
        if path not in cls._cache:
            cls._cache[path] = cls(path)
        return cls._cache[path]

    def ero(self, pccs, lsp_name, path_name="Primary"):
        for pcc in pccs:
            r = self.rows.get((pcc, f"{lsp_name}::{path_name}")) or self.rows.get((pcc, lsp_name))
            if r:
                return r
        return None


def hop_list(ero_text, names, local_ips):
    """ERO text 'a/32 > b/32 > ...' -> [{ip, name, local}] in path order."""
    out = []
    for h in [x.strip().split("/")[0] for x in (ero_text or "").split(">") if x.strip()]:
        out.append({"ip": h, "name": names.get(h, ""), "local": h in local_ips})
    return out


# ---------------------------------------------------------------- port health

def health(p):
    """ok / warning / alarm for a port summary, with the reasons."""
    why, level = [], "ok"
    if p.get("oper") not in ("up", "unknown", None):
        why.append(f"port {p['oper']}")
        level = "alarm"
    for k, label in (("crc", "CRC errors"), ("inErrors", "input errors"), ("outErrors", "output errors"),
                     ("symbolErrors", "symbol errors")):
        if num(p.get(k)) > 0:
            why.append(f"{num(p[k]):,} {label}")
            level = "warning" if level == "ok" else level
    if p.get("opticStatus") in ("alarm", "warning"):
        why.append(f"optics {p['opticStatus']}" + (f" (Rx {p.get('rxPowerDbm')} dBm)" if p.get("rxPowerDbm") is not None else ""))
        level = "alarm" if p["opticStatus"] == "alarm" else ("warning" if level == "ok" else level)
    return level, why


def port_issue(p, where):
    """(severity, message) for a port or LAG on the path, or None when it is healthy.

    A port that is down is critical; an optics warning or a LAG member down is a warning; error
    counters alone are info, because they count since the last clear and may be old."""
    if not p or not p.get("why"):
        return None
    reasons = "; ".join(p["why"])
    if p.get("health") == "alarm":
        return "critical", f"{where} {p['id']}: {reasons}."
    members = p.get("members") or []
    if (p.get("opticStatus") in ("warning", "alarm") or (members and p.get("membersUp", 0) < len(members))
            or any(m.get("opticStatus") in ("warning", "alarm") or m.get("health") == "alarm" for m in members)):
        return "warning", f"{where} {p['id']}: {reasons}."
    return "info", f"{where} {p['id']}: {reasons} (counted since the last clear: check whether they still increase)."


def nokia_port(node, pid, raw, nbrs, lag_of=None):
    """Port summary and detail object from a nokia-state port record (port-state query)."""
    raw = raw or {}
    eth = raw.get("ethernet") or {}
    es = eth.get("statistics") or {}
    tr = raw.get("transceiver") or {}
    ddm = tr.get("digital-diagnostic-monitoring") or {}

    def ddm_val(k):
        v = ddm.get(k)
        return v if isinstance(v, dict) and "current" in v else None

    worst, rx, tx = None, ddm_val("received-optical-power"), ddm_val("transmit-output-power")
    for k in ("received-optical-power", "transmit-output-power", "temperature", "transmit-bias-current"):
        v = ddm_val(k)
        if not v:
            continue
        cur = float(v.get("current"))
        ha, hw, la, lw = (v.get(x) for x in ("high-alarm", "high-warning", "low-alarm", "low-warning"))
        if (ha is not None and cur >= float(ha)) or (la is not None and cur <= float(la)):
            worst = "alarm"
        elif worst != "alarm" and ((hw is not None and cur >= float(hw)) or (lw is not None and cur <= float(lw))):
            worst = "warning"
    if ddm and worst is None:
        worst = "ok"
    nb = (nbrs.get(pid) or [None])[0]
    p = {"key": key("port", node, pid), "id": pid, "oper": norm_state(raw.get("oper-state")) if raw else "unknown",
         "speedMbps": num(eth.get("oper-speed"), None), "lag": lag_of,
         "neighbor": {"name": nb["name"], "port": nb["port"], "mgmt": nb.get("mgmt", "")} if nb else None,
         "inErrors": num(es.get("in-errors")), "outErrors": num(es.get("out-errors")),
         "crc": num(es.get("crc-align-errors")), "symbolErrors": num(get(eth, "symbol-monitor", "total-errors")),
         "flaps": num(eth.get("oper-state-change-count")), "downReason": raw.get("down-reason") or "",
         "rxPowerDbm": rx.get("current") if rx else None, "txPowerDbm": tx.get("current") if tx else None,
         "opticStatus": worst, "optic": tr.get("vendor-part-number") or tr.get("model-number") or "",
         "inUtilPct": round(num(es.get("in-utilization")) / 100.0, 2), "outUtilPct": round(num(es.get("out-utilization")) / 100.0, 2)}
    p["health"], p["why"] = health(p)
    ddm_rows = [[k, v.get("current"), v.get("low-alarm"), v.get("low-warning"), v.get("high-warning"), v.get("high-alarm")]
                for k, v in ddm.items() if isinstance(v, dict) and "current" in v]
    o = obj("port", node, pid, f"Port {pid}", "Nokia port" + (f" · member of {lag_of}" if lag_of else ""), p["oper"],
            fields=[["State", p["oper"]], ["Speed", f"{p['speedMbps']:,} Mb/s" if p["speedMbps"] else None],
                    ["Health", f"{p['health']}: " + "; ".join(p["why"]) if p["why"] else "ok"],
                    ["LLDP neighbour", f"{nb['name']} port {nb['port']}" if nb else "none seen"],
                    ["Neighbour mgmt", nb.get("mgmt") if nb else None],
                    ["Down reason", p["downReason"]], ["State changes", p["flaps"]],
                    ["Input errors", p["inErrors"]], ["Output errors", p["outErrors"]], ["CRC / align errors", p["crc"]],
                    ["Symbol errors", p["symbolErrors"]], ["Utilisation in / out %", f"{p['inUtilPct']} / {p['outUtilPct']}"],
                    ["Optic", p["optic"]], ["Rx power dBm", p["rxPowerDbm"]], ["Tx power dBm", p["txPowerDbm"]],
                    ["Optics status", p["opticStatus"]]],
            tables=[{"title": "Optics (DDM)", "columns": ["Metric", "Current", "Low alarm", "Low warn", "High warn", "High alarm"],
                     "rows": ddm_rows}],
            links=[{"label": f"LAG {lag_of}", "key": key("lag", node, lag_of)}] if lag_of else [],
            raw={k: v for k, v in raw.items() if k not in ("network",)} if raw else None)
    return p, o


def cisco_port(node, name, ifx, eth_stat, eth_if, nbr):
    """Port summary and detail object for an IOS-XR interface (interfaces-xr, ethernet stats and PHY, LLDP)."""
    ifx, eth_stat, eth_if = ifx or {}, eth_stat or {}, eth_if or {}
    lanes = as_list(get(eth_if, "phy-info", "phy-details", "lane"))
    rx = [round(num(l.get("received-laser-power"), 0) / 10000.0, 2) for l in lanes if l.get("received-laser-power") is not None]
    tx = [round(num(l.get("transmit-laser-power"), 0) / 10000.0, 2) for l in lanes if l.get("transmit-laser-power") is not None]
    alarms = {a for l in lanes for a in (l.get("dig-opt-mon-alarm") or {}).values()}
    optic = "alarm" if any("alarm" in str(a) and "normal" not in str(a) for a in alarms) else (
        "warning" if any("warning" in str(a) for a in alarms) else ("ok" if lanes else None))
    p = {"key": key("port", node, name), "id": name, "oper": norm_state(ifx.get("state") or ifx.get("line-state")),
         "speedMbps": num(ifx.get("speed"), 0) // 1000 or None, "lag": None,
         "neighbor": {"name": nbr["name"], "port": nbr["port"], "mgmt": nbr.get("mgmt", "")} if nbr else None,
         "inErrors": num(eth_stat.get("dropped-miscellaneous-error-packets")) + num(eth_stat.get("dropped-giant-packets-greaterthan-mru")),
         "outErrors": num(eth_stat.get("miscellaneous-output-errors")),
         "crc": num(eth_stat.get("dropped-packets-with-crc-align-errors") or eth_stat.get("rfc2819-ether-stats-crc-align-errors")),
         "symbolErrors": num(eth_stat.get("symbol-errors")), "flaps": num(ifx.get("state-transition-count")),
         "downReason": "", "rxPowerDbm": min(rx) if rx else None, "txPowerDbm": min(tx) if tx else None,
         "opticStatus": optic, "optic": get(eth_if, "phy-info", "phy-details", "vendor-part-number") or get(eth_if, "phy-info", "media-type") or "",
         "inUtilPct": None, "outUtilPct": None}
    p["health"], p["why"] = health(p)
    lane_rows = [[l.get("lane-id"), round(num(l.get("received-laser-power"), 0) / 10000.0, 2),
                  round(num(l.get("transmit-laser-power"), 0) / 10000.0, 2),
                  ", ".join(f"{k}: {v}" for k, v in (l.get("dig-opt-mon-alarm") or {}).items())] for l in lanes]
    err_rows = [[k, v] for k, v in eth_stat.items() if any(t in k for t in ("error", "crc", "drop", "symbol", "abort")) and str(v) not in ("0", "")]
    o = obj("port", node, name, name, "IOS-XR interface", p["oper"],
            fields=[["State", p["oper"]], ["Line state", norm_state(ifx.get("line-state"))],
                    ["Speed", f"{p['speedMbps']:,} Mb/s" if p["speedMbps"] else None], ["MTU", ifx.get("mtu")],
                    ["Health", f"{p['health']}: " + "; ".join(p["why"]) if p["why"] else "ok"],
                    ["LLDP neighbour", f"{nbr['name']} port {nbr['port']}" if nbr else "none seen"],
                    ["Neighbour address", nbr.get("mgmt") if nbr else None],
                    ["State changes", p["flaps"]], ["CRC / align errors", p["crc"]], ["Symbol errors", p["symbolErrors"]],
                    ["Optic", p["optic"]], ["Lowest lane Rx dBm", p["rxPowerDbm"]], ["Optics status", optic]],
            tables=[{"title": "Optics per lane", "columns": ["Lane", "Rx dBm", "Tx dBm", "Alarms"], "rows": lane_rows},
                    {"title": "Non-zero error and drop counters", "columns": ["Counter", "Value"], "rows": err_rows}],
            raw={"interface": ifx, "ethernet-statistics": eth_stat, "ethernet-phy": eth_if} if (ifx or eth_stat or eth_if) else None)
    return p, o
