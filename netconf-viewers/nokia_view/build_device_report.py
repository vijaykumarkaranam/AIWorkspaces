#!/usr/bin/env python3
"""
Build a single-file HTML device report from ODL NETCONF responses taken from a
Nokia 7750 SR (SR OS classic mode).

Inputs (all optional except port state; files are found by name keywords in --dir):
  *portstatus*            nokia-state <port/>                         (get)
  *classic* | *customer*  alu-conf-r13 <configure><service/>          (get-config)
  *epipe*                 nokia-state <service><epipe/>               (get)
  *vpls*                  nokia-state <service><vpls/>                (get)
  *sdp*                   nokia-state <service><sdp/>                 (get)
  *interface*             nokia-state <router><interface/>            (get)
  *mpls* | *lsp*          nokia-state <router><mpls><lsp/>            (get)
  pce-lsp-inventory.csv   PCEP LSP export (ERO hops), optional

Usage:
  python build_device_report.py --dir "D:\\...\\ODL -Netconf-services"
Output:
  <DEVICE>_device_report.html in the same folder (self-contained, works offline).

Read-only: this script only reads files.
"""
import argparse
import csv
import datetime as dt
import itertools
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- helpers
def L(x):
    """Schemaless ODL output returns a single list entry as an object: normalise to list."""
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def g(o, *path, default=None):
    for p in path:
        if isinstance(o, dict) and p in o:
            o = o[p]
        else:
            return default
    return o


def n(x, default=0):
    try:
        if isinstance(x, bool):
            return int(x)
        if isinstance(x, (int, float)):
            return x
        return float(x) if "." in str(x) else int(x)
    except (TypeError, ValueError):
        return default


ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def parse_ts(s):
    try:
        return dt.datetime.strptime(s.split(".")[0].rstrip("Z"), "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None


def all_timestamps(o, out):
    if isinstance(o, dict):
        for v in o.values():
            all_timestamps(v, out)
    elif isinstance(o, list):
        for v in o:
            all_timestamps(v, out)
    elif isinstance(o, str) and ISO.match(o):
        t = parse_ts(o)
        if t:
            out.append(t)


def count_leaves(o):
    if isinstance(o, dict):
        return sum(count_leaves(v) for v in o.values())
    if isinstance(o, list):
        return sum(count_leaves(v) for v in o)
    return 1


def find_file(folder, *keyword_sets):
    names = [f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))]
    for kws in keyword_sets:
        for f in sorted(names):
            low = f.lower()
            if low.endswith((".py", ".html", ".csv")):
                continue
            if all(k in low for k in kws):
                return os.path.join(folder, f)
    return None


def load_fdb_csv(folder):
    """MAC rows written by parse_fdb.py (any *fdb*.csv in the folder). Returns [] if none found."""
    for f in sorted(os.listdir(folder)):
        if f.lower().endswith(".csv") and "fdb" in f.lower():
            with open(os.path.join(folder, f), newline="", encoding="utf-8") as fh:
                return list(csv.DictReader(fh))
    return []


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    err = None
    if "errors" in d:
        err = json.dumps(d["errors"])[:400]
    data = g(d, "ietf-netconf:output", "data", default=d)
    if data == "":
        data = {}
    return data, err


def split_sap(sap_id):
    s = str(sap_id)
    if ":" in s:
        port, tag = s.rsplit(":", 1)
    else:
        port, tag = s, ""
    outer, inner = (tag.split(".", 1) + [""])[:2] if tag else ("", "")
    return port, outer, inner


def split_bind(b):
    s = str(b)
    if ":" in s:
        a, c = s.split(":", 1)
        return n(a, a), c
    return n(s, s), ""


CLLI = re.compile(r"\b([A-Z]{6}[A-Z0-9]{2}[A-Z0-9]{3})\b")
CIRCUIT = re.compile(r"\b(\d{2,3}[A-Z]?\s*/\s*[A-Z]{2,4}\d*[A-Z]?\s*/\s*[A-Z0-9]+(?:\s*/\s*[A-Z0-9]*)*)", re.I)


def parse_ref_text(text):
    """Pull site codes (CLLI-like) and circuit IDs out of free-text labels."""
    t = str(text or "")
    codes = sorted(set(m.upper() for m in CLLI.findall(t.upper())))
    circuits = sorted(set(re.sub(r"\s+", "", c) for c in CIRCUIT.findall(t)))
    return codes, circuits


# ---------------------------------------------------------------- ports
DDM_METRICS = [
    ("temperature", "Temperature", "°C"),
    ("transmit-bias-current", "Tx bias", "mA"),
    ("transmit-output-power", "Tx power", "dBm"),
    ("received-optical-power", "Rx power", "dBm"),
    ("supply-voltage", "Supply voltage", "V"),
    ("auxiliary-1", "Aux 1", "V"),
]


def ddm_eval(m):
    cur = m.get("current")
    if cur is None:
        return None
    cur = n(cur)
    ha, hw, la, lw = (n(m.get(k), None) for k in ("high-alarm", "high-warning", "low-alarm", "low-warning"))
    status = "ok"
    if ha is not None and cur >= ha or la is not None and cur <= la:
        status = "alarm"
    elif hw is not None and cur >= hw or lw is not None and cur <= lw:
        status = "warning"
    margin = None
    if la is not None and ha is not None:
        margin = round(min(cur - la, ha - cur), 2)
    return {"current": cur, "highAlarm": ha, "highWarning": hw, "lowAlarm": la, "lowWarning": lw,
            "status": status, "margin": margin}


def build_ports(port_data, as_of):
    ports = []
    local_addr = {}
    for i, p in enumerate(L(g(port_data, "state", "port"))):
        pid = str(p.get("port-id"))
        eth = p.get("ethernet", {}) or {}
        tr = p.get("transceiver", {}) or {}
        ddm_raw = tr.get("digital-diagnostic-monitoring", {}) or {}
        st = p.get("statistics", {}) or {}
        es = eth.get("statistics", {}) or {}
        elmi = eth.get("elmi", {}) or {}
        uni = elmi.get("user-network-interface", {}) or {}
        evcs = [{"vlan": e.get("vlan-id"), "identifier": e.get("identifier"), "status": e.get("status"),
                 "statusTime": e.get("status-time"), "type": e.get("type")}
                for e in L(elmi.get("ethernet-virtual-connection"))]
        ddm = {}
        for key, label, unit in DDM_METRICS:
            v = ddm_raw.get(key)
            if isinstance(v, dict) and "current" in v:
                ev = ddm_eval(v)
                ev.update(label=label, unit=unit, type=v.get("type"))
                ddm[key] = ev
        worst = "none"
        if ddm:
            worst = "alarm" if any(x["status"] == "alarm" for x in ddm.values()) else \
                "warning" if any(x["status"] == "warning" for x in ddm.values()) else "ok"
        neighbors = []
        for dm in L(g(eth, "lldp", "dest-mac")):
            for ta in L(dm.get("tx-mgmt-address")):
                if ta.get("mgmt-address"):
                    local_addr[ta.get("mgmt-address-system-type")] = ta.get("mgmt-address")
            rs = dm.get("remote-system")
            for r in L(rs):
                mg = L(r.get("mgmt-address"))
                neighbors.append({
                    "macType": dm.get("mac-type"),
                    "systemName": r.get("system-name"),
                    "systemDescription": r.get("system-description"),
                    "chassisId": str(r.get("chassis-id", "")),
                    "chassisIdSubtype": r.get("chassis-id-subtype"),
                    "remotePortId": str(r.get("remote-port-id", "")),
                    "remotePortIdSubtype": r.get("remote-port-id-subtype"),
                    "portDescription": r.get("port-description"),
                    "capabilities": r.get("system-enabled-capabilities"),
                    "supportedCapabilities": r.get("system-supported-capabilities"),
                    "mgmtAddresses": [m.get("mgmt-address") for m in mg if m.get("mgmt-address")],
                    "ageSec": r.get("age"),
                    "rxFrames": g(dm, "statistics", "receive", "frames"),
                    "ageOuts": g(dm, "statistics", "receive", "age-outs"),
                })
        speed = n(eth.get("oper-speed"))
        in_oct, out_oct = n(es.get("in-octets")), n(es.get("out-octets"))
        disc = st.get("counter-discontinuity-time") or st.get("last-cleared-time")
        uni_id = uni.get("identifier", "")
        codes, circuits = parse_ref_text(uni_id)
        net_q = []
        for direction in ("egress", "ingress"):
            for q in L(g(p, "network", direction, "queue")):
                s = q.get("statistics", {}) or {}
                net_q.append({"dir": direction, "queue": q.get("queue-id"),
                              "fwdPkts": n(s.get("in-profile-forwarded-packets")) + n(s.get("out-profile-forwarded-packets")),
                              "fwdOctets": n(s.get("in-profile-forwarded-octets")) + n(s.get("out-profile-forwarded-octets")),
                              "dropPkts": n(s.get("in-profile-dropped-packets")) + n(s.get("out-profile-dropped-packets"))})
        mfg = tr.get("vendor-manufacture-date")
        age_years = None
        if mfg and as_of:
            t = parse_ts(mfg)
            if t:
                age_years = round((as_of - t).days / 365.25, 1)
        wl = n(tr.get("laser-wavelength"), None)
        if wl and wl > 100000:
            wl = round(wl / 1000, 1)
        ports.append({
            "id": pid, "idx": i,
            "type": p.get("type"), "class": p.get("port-class"),
            "oper": p.get("oper-state"), "portState": p.get("port-state"), "prevState": p.get("previous-state"),
            "physicalLink": p.get("physical-link"), "downReason": p.get("down-reason"),
            "mac": p.get("hardware-mac-address"), "protocols": p.get("protocols-supported"),
            "speedMbps": speed, "duplex": eth.get("oper-duplex"), "mdi": eth.get("mdi-type"),
            "flaps": n(eth.get("oper-state-change-count")), "alarms": eth.get("current-alarms"),
            "dampening": g(eth, "dampening", "oper-state"), "loop": g(eth, "down-when-looped", "loop-state"),
            "efmOam": g(eth, "efm-oam", "oper-state"), "dot1x": g(eth, "dot1x", "port-status"),
            "ssmRx": g(eth, "ssm", "received-quality-level"), "symbolErrors": n(g(eth, "symbol-monitor", "total-errors")),
            "inUtilPct": n(es.get("in-utilization")) / 100.0, "outUtilPct": n(es.get("out-utilization")) / 100.0,
            "inOctets": in_oct, "outOctets": out_oct,
            "inPkts": n(st.get("in-packets")), "outPkts": n(st.get("out-packets")),
            "inDiscards": n(st.get("in-discards")), "outDiscards": n(st.get("out-discards")),
            "inErrors": n(es.get("in-errors")), "outErrors": n(es.get("out-errors")),
            "crc": n(es.get("crc-align-errors")), "fcs": n(g(es, "ethernet-like-medium", "error", "fcs")),
            "frameTooLong": n(g(es, "ethernet-like-medium", "frame-too-long")),
            "oversize": n(es.get("oversize-packets")), "undersize": n(es.get("undersize-packets")),
            "fragments": n(es.get("fragments")), "jabbers": n(es.get("jabbers")), "collisions": n(es.get("collisions")),
            "bcast": n(es.get("total-broadcast-packets")), "mcast": n(es.get("total-multicast-packets")),
            "pktSizes": es.get("packet-size", {}),
            "counterSince": disc,
            "optic": {
                "equipped": tr.get("equipped"), "type": tr.get("type"), "connector": tr.get("connector-type"),
                "connectorCode": tr.get("connector-code"), "media": tr.get("media"),
                "vendorPart": tr.get("vendor-part-number"), "serial": str(tr.get("vendor-serial-number", "") or ""),
                "model": tr.get("model-number"), "vendorOui": tr.get("vendor-oui"), "wavelengthNm": wl,
                "mfgDate": mfg, "ageYears": age_years, "diag": tr.get("diagnostics-capable"),
                "calibrated": ddm_raw.get("calibrated"), "failedThresholds": ddm_raw.get("failed-thresholds", ""),
                "compliance": tr.get("optical-compliance"), "linkLength": tr.get("link-length-information"),
            } if tr else {},
            "ddm": ddm, "ddmWorst": worst,
            "elmi": {"linkStatus": elmi.get("link-status"), "uniId": uni_id, "uniType": uni.get("type"),
                     "evcs": evcs, "siteCodes": codes, "circuits": circuits},
            "neighbors": neighbors,
            "netQueues": net_q,
            "dwdm": p.get("dwdm"),
            "src": ["port", ["state", "port", i]],
        })
    return ports, local_addr


def infer_lags(ports):
    """LAG membership is not in the port state; infer it from counters (member sums == LAG totals)."""
    lags = [p for p in ports if p["id"].startswith("lag-")]
    phys = [p for p in ports if not p["id"].startswith("lag-") and p["inPkts"] > 0 and p["id"][0].isdigit()]
    out = {}
    for lag in lags:
        best = None
        for k in range(1, 5):
            for combo in itertools.combinations(phys, k):
                si = sum(c["inPkts"] for c in combo)
                so = sum(c["outPkts"] for c in combo)
                if not lag["inPkts"] or not lag["outPkts"]:
                    continue
                ei = abs(si - lag["inPkts"]) / lag["inPkts"]
                eo = abs(so - lag["outPkts"]) / lag["outPkts"]
                err = max(ei, eo)
                if err < 0.002 and (best is None or err < best[0]):
                    best = (err, [c["id"] for c in combo])
            if best:
                break
        out[lag["id"]] = {"members": best[1] if best else [], "matchErrorPct": round(best[0] * 100, 4) if best else None}
    return out


# ---------------------------------------------------------------- live store (nokia_view)
SEV_ORDER = {"critical": 0, "warning": 1, "info": 2}
PROTOCOLS = [("bgp", "BGP"), ("ospf", "OSPF"), ("isis", "IS-IS"), ("ldp", "LDP"), ("rsvp", "RSVP"),
             ("bfd", "BFD"), ("vrrp", "VRRP"), ("lldp", "LLDP neighbours (state)")]


def finding_refs(f):
    """Links (label, navigation ref) for one stored finding: service, port, SDP, LSP."""
    obj, path, cause, text = f.get("object", ""), f.get("path", ""), f.get("cause", ""), f.get("message", "")
    refs = []
    m = re.search(r"oper-service-id=(\d+)", obj)
    if m:
        t = re.search(r"\.(epipe|vpls|vprn)\[", path)
        refs.append((f"Service {m.group(1)}", f"svc|{t.group(1) if t else 'epipe'}:{m.group(1)}"))
    port = (re.search(r"port-id=([0-9/]+)", obj) or re.search(r"sap-id=([0-9/]+):", obj)
            or re.search(r"port ([0-9/]+) (?:down|is down)", cause + " " + text))
    if port:
        refs.append((f"Port {port.group(1)}", f"port|{port.group(1)}"))
    sdp = re.search(r"sdp-id=(\d+)", obj) or re.search(r"sdp-bind-id=(\d+):", obj)
    if sdp:
        refs.append((f"SDP {sdp.group(1)}", f"sdp|{sdp.group(1)}"))
    lsp = re.search(r"lsp-name=([^,]+)", obj)
    if lsp:
        refs.append((f"LSP {lsp.group(1).strip()}", f"lsp|{lsp.group(1).strip()}"))
    seen, out = set(), []
    for lbl, ref in refs:
        if ref not in seen:
            seen.add(ref)
            out.append({"label": lbl, "ref": ref})
    return out


PROTO_BAD_STATES = {"down", "failed", "fail", "inactive", "not-active", "idle", "init", "lower-layer-down",
                    "notconnected", "outofservice", "out-of-service"}


def protocol_summary(data):
    """Total items with an oper-state, and the names of those not up, from saved data."""
    import analyze
    total, down, stack = 0, [], [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            state_val = node.get("oper-state", node.get("session-state"))
            if state_val is not None:
                total += 1
                s = str(state_val).lower()
                if s in PROTO_BAD_STATES:
                    down.append(f"{analyze._own_id(node) or 'item'}: {state_val}")
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return total, down[:40]


def store_model(node):
    """Newest saved run of each query for this device (nokia_view store): data, findings, status."""
    sys.path.insert(0, HERE)
    import queries
    import store
    latest = {}
    for rel in store.history(node):
        name = os.path.basename(rel)
        if "_" in name:
            qid = name.split("_", 1)[1][:-5]
            if qid not in latest:
                latest[qid] = store.load(rel)
    data, qmeta, findings, routing = {}, [], [], []
    for qid, r in latest.items():
        label = queries.QUERIES.get(qid, {}).get("label", qid)
        if "error" in r:
            status = "error"
        elif not r.get("data"):
            status = "empty"
        else:
            status = "ok"
            data[qid] = r["data"]
        qmeta.append({"id": qid, "label": label, "status": status, "saved": r.get("fetchedAt", ""),
                      "error": r.get("error", "")})
        for f in r.get("findings") or []:
            findings.append(dict(f, query=label, qid=qid, refs=finding_refs(f)))
    for qid, label in PROTOCOLS:
        if qid in data:
            total, down = protocol_summary(data[qid])
            routing.append({"id": qid, "label": label, "total": total, "down": down,
                            "status": "down" if down else ("ok" if total else "no entries")})
        else:
            routing.append({"id": qid, "label": label, "total": 0, "down": [], "status": "no data"})
    findings.sort(key=lambda f: (SEV_ORDER.get(f["severity"], 9), f["query"], f["object"]))
    qmeta.sort(key=lambda q: q["label"])
    return {"data": data, "queries": qmeta, "findings": findings, "routing": routing,
            "health": health_model(data), "fdb": fdb_model(data)}


def _dicts_with(obj, key):
    """Every dict under obj that has the given key."""
    if isinstance(obj, dict):
        if key in obj:
            yield obj
        for v in obj.values():
            yield from _dicts_with(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _dicts_with(v, key)


def _response_texts(obj):
    """The CLI text blocks ('response' fields) in a stored response."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "response" and isinstance(v, str):
                yield v
            else:
                yield from _response_texts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _response_texts(v)


def fdb_model(data):
    """MAC table from the stored 'service fdb-mac' run, linked to services, ports and SDPs."""
    import parse_fdb
    out = {"total": 0, "services": [], "rows": []}
    if "cli-fdb-all" not in data:
        return out
    rows, _ = parse_fdb.parse("\n".join(_response_texts(data["cli-fdb-all"])))
    types, names = {}, {}
    for qid, typ in (("epipe-state", "epipe"), ("vpls-state", "vpls")):
        for d in _dicts_with(data.get(qid, {}), "oper-service-id"):
            sid = str(d["oper-service-id"])
            types[sid], names[sid] = typ, d.get("service-name", "")
    per, enriched = {}, []
    for r in rows:
        sid, typ = r["service_id"], types.get(r["service_id"], "")
        row = dict(r, svcType=typ, svcName=names.get(sid, ""),
                   svcRef=f"svc|{typ}:{sid}" if typ else "",
                   portRef=f"port|{r['port_or_sdp']}" if r["transport"] == "sap" else "",
                   sdpRef=f"sdp|{r['port_or_sdp']}" if r["transport"] == "sdp" else "")
        enriched.append(row)
        p = per.setdefault(sid, {"id": sid, "type": typ, "name": names.get(sid, ""), "ref": row["svcRef"],
                                 "count": 0, "learned": 0})
        p["count"] += 1
        p["learned"] += 1 if r["entry_type"].startswith("L") else 0
    out["total"] = len(enriched)
    out["services"] = sorted(per.values(), key=lambda x: -x["count"])
    out["rows"] = enriched
    return out


def _state(data, qid):
    """The data.state part of one stored response."""
    d = data.get(qid) or {}
    return (d.get("ietf-netconf:output", d).get("data", {}) or {}).get("state", {}) or {}


def health_model(data):
    """Chassis, cards, redundancy and system items, flattened for the Hardware & system tab."""
    out = {"chassis": None, "cards": [], "redundancy": None, "system": []}
    ch = _state(data, "chassis").get("chassis")
    if isinstance(ch, dict):
        hw = ch.get("hardware-data", {}) or {}
        out["chassis"] = {
            "name": str(ch.get("name", "")), "class": ch.get("chassis-class", ""), "role": ch.get("role", ""),
            "state": ch.get("state", ""), "serial": hw.get("serial-number", ""), "part": hw.get("part-number", ""),
            "clei": hw.get("common-language-equipment-identifier", ""), "lastBoot": hw.get("software-last-boot-time", ""),
            "fans": [{"slot": f.get("fan-slot"), "state": f.get("state"), "speed": f.get("speed")}
                     for f in (ch.get("fan") or [])],
            "psus": [{"id": p.get("power-supply-id"), "status": p.get("first-power-supply-status"),
                      "type": p.get("pem-type", "")} for p in (ch.get("power-supply") or [])],
        }
    for c in _as_list(_state(data, "cards").get("card")):
        hw = c.get("hardware-data", {}) or {}
        out["cards"].append({
            "slot": c.get("slot-number"), "type": c.get("equipped-type", ""), "state": hw.get("oper-state", ""),
            "temp": hw.get("temperature"), "limit": hw.get("temperature-threshold"),
            "alarm": hw.get("alarm-state", ""), "failure": hw.get("failure-reason", ""),
            "lastBoot": hw.get("software-last-boot-time", ""), "serial": hw.get("serial-number", ""),
            "mdas": len(_as_list(c.get("mda"))), "memMB": c.get("memory-size"),
        })
    red = _state(data, "redundancy").get("redundancy")
    if isinstance(red, dict):
        sync = red.get("synchronization", {}) or {}
        out["redundancy"] = {"standby": sync.get("standby-status", ""), "standbyUp": sync.get("standby-uptime", ""),
                             "standbyVersion": (sync.get("standby-version") or "").split("\n")[0],
                             "configSync": sync.get("config-file-sync-time", ""),
                             "bootSync": sync.get("boot-file-sync-time", ""), "syncStatus": sync.get("sync-status", ""),
                             "failover": sync.get("failover-time", ""),
                             "switchover": red.get("switchover-exec-status", "")}
    sysstate = _state(data, "system").get("system")
    if sysstate is not None:
        stack = [(k, v) for k, v in (sysstate.items() if isinstance(sysstate, dict) else [])]
        while stack:
            name, node = stack.pop()
            if isinstance(node, dict):
                if "oper-state" in node:
                    out["system"].append({"name": name, "state": str(node.get("oper-state"))})
                stack.extend((f"{name}.{k}", v) for k, v in node.items())
            elif isinstance(node, list):
                stack.extend((f"{name}[{i}]", v) for i, v in enumerate(node))
        out["system"].sort(key=lambda s: (s["state"] == "up", s["name"]))
    return out


def _as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


# ---------------------------------------------------------------- main build
def store_latest_raw(node):
    """Newest saved run of each query for a node, keyed by query id (nokia_view store)."""
    sys.path.insert(0, HERE)
    import store
    latest = {}
    for rel in store.history(node):
        name = os.path.basename(rel)
        if "_" in name:
            qid = name.split("_", 1)[1][:-5]
            if qid not in latest:
                latest[qid] = store.load(rel)
    return latest


def store_default_node():
    """The device folder in the store that was used most recently (empty if none)."""
    sys.path.insert(0, HERE)
    import store
    if not os.path.isdir(store.STORE):
        return ""
    folders = [f for f in os.listdir(store.STORE) if os.path.isdir(os.path.join(store.STORE, f))]
    return max(folders, key=lambda f: os.path.getmtime(os.path.join(store.STORE, f)), default="")


def build(folder, out_path=None, node=None):
    files = {
        "port": find_file(folder, ("portstatus",), ("port", "state")),
        "svccfg": find_file(folder, ("classic",), ("customer",), ("service", "config")),
        "epipe": find_file(folder, ("epipe",)),
        "vpls": find_file(folder, ("vpls",)),
        "sdp": find_file(folder, ("sdp",)),
        "rif": find_file(folder, ("interface",)),
        "mpls": find_file(folder, ("mpls",), ("lsp",)),
    }
    pcep_csv = os.path.join(folder, "pce-lsp-inventory.csv")
    src, sources = {}, []
    labels = {
        "port": "Port state (nokia-state port)", "svccfg": "Service config (alu-conf-r13 configure service)",
        "epipe": "Epipe state (nokia-state service epipe)", "vpls": "VPLS state (nokia-state service vpls)",
        "sdp": "SDP state (nokia-state service sdp)", "rif": "Router interfaces (nokia-state router interface)",
        "mpls": "MPLS LSP state (nokia-state router mpls lsp)",
    }
    # Prefer the newest stored run of each query; fall back to the response file in the folder.
    stored = store_latest_raw(node or store_default_node())
    store_for = {"port": "port-state", "svccfg": "config-services", "epipe": "epipe-state", "vpls": "vpls-state",
                 "sdp": "sdp-state", "rif": "router-interface-state", "mpls": "mpls-lsp-state"}
    for k, path in files.items():
        qid = store_for.get(k)
        if qid and "error" not in stored.get(qid, {"error": 1}) and stored.get(qid, {}).get("data"):
            rec = stored[qid]
            inner = rec["data"].get("ietf-netconf:output", rec["data"])  # same shape as the response files
            inner = inner.get("data", inner) if isinstance(inner, dict) else inner
            src[k] = inner
            sources.append({"key": k, "label": labels[k] + " (stored run)", "file": f"store: {qid}",
                            "status": "ok", "error": None, "leaves": count_leaves(inner),
                            "bytes": len(json.dumps(rec["data"], default=str)),
                            "saved": rec.get("fetchedAt", "")})
            continue
        if not path:
            sources.append({"key": k, "label": labels[k], "file": None, "status": "missing", "leaves": 0})
            src[k] = {}
            continue
        data, err = load_json(path)
        src[k] = data
        sources.append({"key": k, "label": labels[k], "file": os.path.basename(path),
                        "status": "error" if err else ("empty" if not data else "ok"), "error": err,
                        "leaves": count_leaves(data), "bytes": os.path.getsize(path),
                        "saved": dt.datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="minutes")})

    ts = []
    for v in src.values():
        all_timestamps(v, ts)
    as_of = max(ts) if ts else dt.datetime.now()

    # ---- ports
    ports, local_addr = build_ports(src["port"], as_of)
    port_by_id = {p["id"]: p for p in ports}
    lags = infer_lags(ports)
    for lag_id, info in lags.items():
        for m in info["members"]:
            port_by_id[m]["lag"] = lag_id
        port_by_id[lag_id]["members"] = info["members"]
        port_by_id[lag_id]["lagMatchErrorPct"] = info["matchErrorPct"]

    # ---- service config
    cfg = g(src["svccfg"], "configure", "service", default={}) or {}
    customers = {}
    for i, c in enumerate(L(cfg.get("customer"))):
        cid = c.get("customer-id")
        customers[str(cid)] = {"id": cid, "name": c.get("name"), "description": g(c, "description", "description-string", default=""),
                               "contact": g(c, "contact", "contact-information", default=""),
                               "phone": g(c, "phone", "phone-number", default=""), "services": [],
                               "src": ["svccfg", ["configure", "service", "customer", i]]}
    pw_templates = []
    for i, t in enumerate(L(cfg.get("pw-template"))):
        pw_templates.append({"policyId": t.get("policy-id"), "name": t.get("name"),
                             "splitHorizonGroup": g(t, "split-horizon-group", "group-name", default=""),
                             "useProvisionedSdp": t.get("use-provisioned-sdp", False),
                             "preferProvisionedSdp": t.get("prefer-provisioned-sdp", False),
                             "forceVlanVcForwarding": t.get("force-vlan-vc-forwarding", False),
                             "hashLabel": g(t, "hash-label", "signal-capability", default=False),
                             "controlWord": t.get("controlword", False), "usedBy": [],
                             "src": ["svccfg", ["configure", "service", "pw-template", i]]})
    pwt_by_id = {str(t["policyId"]): t for t in pw_templates}

    # ---- SDPs
    sdp_state = {}
    for i, s in enumerate(L(g(src["sdp"], "state", "service", "sdp"))):
        sdp_state[str(s.get("sdp-id"))] = (i, s)
    sdps = {}
    cfg_sdps = L(cfg.get("sdp"))
    ids = [str(s.get("sdp-id")) for s in cfg_sdps] + [k for k in sdp_state if k not in {str(s.get("sdp-id")) for s in cfg_sdps}]
    for sid in ids:
        ci, c = next(((i, s) for i, s in enumerate(cfg_sdps) if str(s.get("sdp-id")) == sid), (None, {}))
        si, s = sdp_state.get(sid, (None, {}))
        ka = s.get("keep-alive", {}) or {}
        req, resp = n(ka.get("hello-request-messages")), n(ka.get("hello-response-messages"))
        sdps[sid] = {
            "id": n(sid, sid), "description": g(c, "description", "description-string", default=""),
            "delivery": c.get("delivery-type"), "farEnd": g(c, "far-end", "ip-address-ipv6-address") or s.get("oper-tunnel-far-end-inet-address"),
            "lspName": g(c, "lsp", "lsp-name", default=""), "pathMtu": g(c, "path-mtu", "bytes"),
            "adminShutdown": c.get("shutdown"), "kaAdminShutdown": g(c, "keep-alive", "shutdown"),
            "oper": s.get("sdp-oper-state"), "operMtu": s.get("sdp-oper-path-mtu"), "flags": s.get("sdp-oper-flags"),
            "operBw": s.get("sdp-oper-bandwidth"), "availBw": s.get("sdp-available-bandwidth"),
            "origin": s.get("sdp-creation-origin"), "activeLspType": s.get("active-lsp-type"),
            "operFarEnd": s.get("oper-tunnel-far-end-inet-address"), "netDomain": s.get("egress-ifs-net-domain-consistent"),
            "ldpLspId": s.get("ldp-lsp-id"), "bgpLspId": s.get("bgp-tunnel-lsp-id"), "fpeLspId": s.get("fpe-lsp-id"),
            "revertCountdown": s.get("lsp-revert-time-countdown"), "controlPwActive": s.get("control-pw-is-active"),
            "kaOper": ka.get("oper-state"), "helloReq": req, "helloResp": resp, "helloLost": max(req - resp, 0),
            "helloLate": n(ka.get("late-hello-response-messages")),
            "bindings": [],
            "src": ["sdp", ["state", "service", "sdp", si]] if si is not None else None,
            "srcCfg": ["svccfg", ["configure", "service", "sdp", ci]] if ci is not None else None,
        }

    # ---- services
    window_s = None

    def sap_merge(svc_type, sid, csap, ssap, path_cfg, path_st):
        sap_id = (csap or {}).get("sap-id") or (ssap or {}).get("sap-id")
        port, outer, inner = split_sap(sap_id)
        ifs = g(ssap or {}, "ingress", "qos", "sap-ingress", "forwarding-engine", "statistics", default={}) or {}
        itm = g(ssap or {}, "ingress", "qos", "sap-ingress", "traffic-manager", "statistics", default={}) or {}
        etm = g(ssap or {}, "egress", "qos", "sap-egress", "traffic-manager", "statistics", default={}) or {}
        cleared = ifs.get("last-cleared-time") or etm.get("last-cleared-time")
        secs = None
        if cleared:
            t = parse_ts(cleared)
            if t:
                secs = max((as_of - t).total_seconds(), 1)
        rx_oct = n(ifs.get("received-valid-octets"))
        tx_oct = n(etm.get("aggregate-forwarded-octets"))
        desc = g(csap or {}, "description", "long-description-string", default="")
        codes, circuits = parse_ref_text(desc)
        return {
            "sapId": str(sap_id), "port": port, "outer": outer, "inner": inner,
            "serviceType": svc_type, "serviceId": sid, "description": desc, "siteCodes": codes, "circuits": circuits,
            "ingressQos": g(csap or {}, "ingress", "qos", "policy-id"), "egressQos": g(csap or {}, "egress", "qos", "policy-id"),
            "qinqTopOnly": g(csap or {}, "egress", "qinq-mark-top-only"),
            "dot1pMatch": g(csap or {}, "ingress", "match-qinq-dot1p", "top-bottom"),
            "collectStats": (csap or {}).get("collect-stats"),
            "adminShutdown": (csap or {}).get("shutdown"),
            "oper": (ssap or {}).get("oper-state"), "flags": (ssap or {}).get("oper-flags"),
            "mirror": (ssap or {}).get("mirror-state"), "cpuProt": (ssap or {}).get("oper-dist-cpu-prot-policy"),
            "rxPkts": n(ifs.get("received-valid-packets")), "rxOctets": rx_oct,
            "rxDropPkts": n(ifs.get("dropped-packets")) + n(itm.get("aggregate-dropped-packets")),
            "rxHiPkts": n(ifs.get("high-priority-offered-packets")), "rxLoPkts": n(ifs.get("low-priority-offered-packets")),
            "rxInProf": n(itm.get("in-profile-forwarded-packets")), "rxOutProf": n(itm.get("out-profile-forwarded-packets")),
            "cpmPkts": n(itm.get("cpm-packets")),
            "txPkts": n(etm.get("aggregate-forwarded-packets")), "txOctets": tx_oct,
            "txDropPkts": n(etm.get("aggregate-dropped-packets")),
            "macsLearned": n(g(ssap or {}, "fdb", "statistics", "learned")),
            "macViolation": g(ssap or {}, "fdb", "protected-src-mac-violation", "oper-state"),
            "countersSince": cleared,
            "rxAvgMbps": round(rx_oct * 8 / secs / 1e6, 3) if secs else None,
            "txAvgMbps": round(tx_oct * 8 / secs / 1e6, 3) if secs else None,
            "src": path_st, "srcCfg": path_cfg,
        }

    def bind_merge(kind, c, s, sid, svc_type, path_cfg, path_st):
        bid = (c or {}).get("sdp-id-vc-id") or (s or {}).get("sdp-bind-id")
        sdp_id, vc = split_bind(bid)
        ing, eg = g(s or {}, "ingress", default={}) or {}, g(s or {}, "egress", default={}) or {}
        return {"bindId": str(bid), "sdpId": sdp_id, "vcId": vc, "kind": kind, "serviceType": svc_type, "serviceId": sid,
                "adminShutdown": (c or {}).get("shutdown"), "oper": (s or {}).get("oper-state"),
                "flags": (s or {}).get("oper-flags"), "origin": (s or {}).get("creation-origin"),
                "peerStatus": (s or {}).get("pw-peer-status-bits"), "localStatus": (s or {}).get("pw-local-status-bits"),
                "vccvCv": (s or {}).get("peer-vccv-cv-bits"), "vccvCc": (s or {}).get("peer-vccv-cc-bits"),
                "controlWord": (s or {}).get("oper-control-word"), "hashLabel": (s or {}).get("oper-hash-label"),
                "minMtu": (s or {}).get("min-required-sdp-oper-mtu"), "pwFaultIp": (s or {}).get("pw-fault-ip-address"),
                "ingLabel": ing.get("oper-label"), "egLabel": eg.get("oper-label"),
                "inPkts": n(g(ing, "statistics", "forwarded-packets")), "inOctets": n(g(ing, "statistics", "forwarded-octets")),
                "inDrop": n(g(ing, "statistics", "dropped-packets")),
                "outPkts": n(g(eg, "statistics", "forwarded-packets")), "outOctets": n(g(eg, "statistics", "forwarded-octets")),
                "src": path_st, "srcCfg": path_cfg}

    services = []
    state_maps = {
        "epipe": {str(s.get("oper-service-id")): (i, s) for i, s in enumerate(L(g(src["epipe"], "state", "service", "epipe")))},
        "vpls": {str(s.get("oper-service-id")): (i, s) for i, s in enumerate(L(g(src["vpls"], "state", "service", "vpls")))},
    }
    seen = set()
    for stype in ("epipe", "vpls", "vprn"):
        cfg_list = L(cfg.get(stype))
        ids_cfg = [str(c.get("service-id")) for c in cfg_list]
        extra = [k for k in state_maps.get(stype, {}) if k not in ids_cfg]
        for sid in ids_cfg + extra:
            ci, c = next(((i, x) for i, x in enumerate(cfg_list) if str(x.get("service-id")) == sid), (None, {}))
            si, s = state_maps.get(stype, {}).get(sid, (None, {}))
            seen.add((stype, sid))
            pc = ["svccfg", ["configure", "service", stype, ci]] if ci is not None else None
            ps = [stype, ["state", "service", stype, si]] if si is not None else None
            cust = str(c.get("customer", ""))
            # SAPs
            c_saps, s_saps = L(c.get("sap")), L(s.get("sap"))
            sap_ids = [str(x.get("sap-id")) for x in c_saps] + [str(x.get("sap-id")) for x in s_saps if str(x.get("sap-id")) not in {str(y.get("sap-id")) for y in c_saps}]
            saps = []
            for sap_id in sap_ids:
                cj = next((j for j, x in enumerate(c_saps) if str(x.get("sap-id")) == sap_id), None)
                sj = next((j for j, x in enumerate(s_saps) if str(x.get("sap-id")) == sap_id), None)
                saps.append(sap_merge(stype, n(sid, sid), c_saps[cj] if cj is not None else None, s_saps[sj] if sj is not None else None,
                                      (pc[0], pc[1] + ["sap"] + ([cj] if isinstance(c.get("sap"), list) else [])) if cj is not None else None,
                                      (ps[0], ps[1] + ["sap"] + ([sj] if isinstance(s.get("sap"), list) else [])) if sj is not None else None))
            # SDP bindings
            binds = []
            for kind in ("spoke-sdp", "mesh-sdp"):
                cb, sb = L(c.get(kind)), L(s.get(kind))
                keys = [str(x.get("sdp-id-vc-id")) for x in cb] + [str(x.get("sdp-bind-id")) for x in sb if str(x.get("sdp-bind-id")) not in {str(y.get("sdp-id-vc-id")) for y in cb}]
                for b in keys:
                    cj = next((j for j, x in enumerate(cb) if str(x.get("sdp-id-vc-id")) == b), None)
                    sj = next((j for j, x in enumerate(sb) if str(x.get("sdp-bind-id")) == b), None)
                    bm = bind_merge(kind.replace("-sdp", ""), cb[cj] if cj is not None else None, sb[sj] if sj is not None else None,
                                    n(sid, sid), stype,
                                    (pc[0], pc[1] + [kind] + ([cj] if isinstance(c.get(kind), list) else [])) if cj is not None else None,
                                    (ps[0], ps[1] + [kind] + ([sj] if isinstance(s.get(kind), list) else [])) if sj is not None else None)
                    if bm["origin"] == "bgp-l2vpn":
                        bm["kind"] = "bgp-auto"
                    binds.append(bm)
            bgp = c.get("bgp", {}) or {}
            vprn_ifs = []
            for j, itf in enumerate(L(c.get("interface"))):
                vprn_ifs.append({"name": itf.get("ip-int-name"), "description": g(itf, "description", "long-description-string", default=""),
                                 "address": g(itf, "address", "ip-address-mask"), "vplsBinding": g(itf, "vpls", "service-name"),
                                 "dhcpServer": g(itf, "dhcp", "server", "server-ip-address"), "dhcpTrusted": g(itf, "dhcp", "trusted"),
                                 "dhcpShutdown": g(itf, "dhcp", "shutdown")})
            fdb = g(s, "fdb", "statistics", default={}) or {}
            name = c.get("name") or s.get("service-name") or ""
            codes, circuits = parse_ref_text(f"{name} {g(c, 'description', 'description-string', default='')}")
            svc = {
                "type": stype, "id": n(sid, sid), "name": str(name),
                "description": g(c, "description", "description-string", default=""),
                "customer": n(cust, cust) if cust else None,
                "customerDesc": customers.get(cust, {}).get("description", ""),
                "mtu": g(c, "service-mtu", "octets"), "adminShutdown": c.get("shutdown"),
                "oper": s.get("oper-state") if s else None,
                "sapCount": s.get("sap-count", len(saps)) if s else len(saps), "sdpBindCount": s.get("sdp-bind-count", len(binds)) if s else len(binds),
                "origin": s.get("creation-origin"), "l2ptTerm": s.get("l2pt-term-enabled"),
                "stpShutdown": g(c, "stp", "shutdown"), "macMove": g(c, "mac-move", "shutdown"),
                "fdbTableSize": g(c, "fdb-table-size", "table-size"), "sendFlush": c.get("send-flush-on-failure"),
                "allowIpIntBind": "allow-ip-int-bind" in c,
                "rd": g(bgp, "route-distinguisher", "rd") or g(c, "route-distinguisher", "rd"),
                "rtExport": g(bgp, "route-target", "export"), "rtImport": g(bgp, "route-target", "import"),
                "vrfTarget": g(c, "vrf-target", "ext-community"), "asn": g(c, "autonomous-system", "as-number"),
                "pwTemplate": g(bgp, "pw-template-binding", "policy-id"), "pwSplitHorizon": g(bgp, "pw-template-binding", "split-horizon-group"),
                "vplsId": g(c, "bgp-ad", "vpls-id", "vpls-id"), "bgpAdShutdown": g(c, "bgp-ad", "shutdown"),
                "vsiId": g(c, "bgp-ad", "vsi-id", "prefix", "low-order-vsi-id"),
                "operRd": g(s, "bgp", "oper-route-distinguisher"), "operRtExport": g(s, "bgp", "route-target", "oper-export"),
                "operRtImport": g(s, "bgp", "route-target", "oper-import"),
                "autoBind": {k: v for k, v in (g(c, "auto-bind-tunnel", "resolution-filter", default={}) or {}).items()},
                "macsTotal": n(fdb.get("total")), "macsLearned": n(fdb.get("learned")), "macsStatic": n(fdb.get("static")),
                "macsInUse": n(fdb.get("in-use")),
                "saps": saps, "binds": binds, "interfaces": vprn_ifs,
                "siteCodes": codes, "circuits": circuits,
                "rxOctets": sum(x["rxOctets"] for x in saps), "txOctets": sum(x["txOctets"] for x in saps),
                "rxDropPkts": sum(x["rxDropPkts"] for x in saps),
                "rxAvgMbps": round(sum(x["rxAvgMbps"] or 0 for x in saps), 3),
                "txAvgMbps": round(sum(x["txAvgMbps"] or 0 for x in saps), 3),
                "src": ps, "srcCfg": pc,
            }
            if svc["pwTemplate"] is not None and str(svc["pwTemplate"]) in pwt_by_id:
                pwt_by_id[str(svc["pwTemplate"])]["usedBy"].append(f"{stype} {sid}")
            if cust in customers:
                customers[cust]["services"].append(f"{stype}:{sid}")
            for b in binds:
                sd = sdps.get(str(b["sdpId"]))
                if sd is not None:
                    sd["bindings"].append({"serviceType": stype, "serviceId": n(sid, sid), "serviceName": str(name),
                                           "kind": b["kind"], "vcId": b["vcId"], "oper": b["oper"]})
            services.append(svc)

    # VPRN <-> VPLS (r-VPLS) links
    vpls_by_name = {s["name"]: s for s in services if s["type"] == "vpls"}
    for s in services:
        for itf in s["interfaces"]:
            v = vpls_by_name.get(itf.get("vplsBinding"))
            if v:
                v.setdefault("routedBy", []).append({"vprn": s["id"], "interface": itf["name"], "address": itf["address"]})

    saps_all = [dict(x, serviceName=s["name"], customer=s["customer"], serviceOper=s["oper"]) for s in services for x in s["saps"]]
    for p in ports:
        p["saps"] = [x["sapId"] for x in saps_all if x["port"] == p["id"]]
        p["services"] = sorted({f"{x['serviceType']}:{x['serviceId']}" for x in saps_all if x["port"] == p["id"]})

    # ---- per-MAC FDB rows from the CLI (optional, parse_fdb.py output)
    fdb_by_svc = defaultdict(list)
    for r in load_fdb_csv(folder):
        fdb_by_svc[r["service_id"]].append(r)
    for s in services:
        if s["type"] == "vpls":
            s["macRows"] = fdb_by_svc.get(str(s["id"]), [])

    # ---- router interfaces
    interfaces = []
    lldp_by_name = defaultdict(list)
    for p in ports:
        for nb in p["neighbors"]:
            if nb.get("systemName"):
                lldp_by_name[nb["systemName"]].append((p["id"], nb))
    routers_raw = g(src["rif"], "state", "router")
    for ri, r in enumerate(L(routers_raw)):
        rname = r.get("router-name")
        rpath = ["state", "router"] + ([ri] if isinstance(routers_raw, list) else [])
        for ii, itf in enumerate(L(r.get("interface"))):
            ipath = rpath + ["interface"] + ([ii] if isinstance(r.get("interface"), list) else [])
            v4 = itf.get("ipv4", {}) or {}
            icmp = g(v4, "icmp", "statistics", default={}) or {}
            arps = [{"ip": a.get("ipv4-address"), "mac": a.get("mac-address"), "state": a.get("oper-state"),
                     "type": a.get("type"), "timer": a.get("timer")} for a in L(g(v4, "neighbor-discovery", "neighbor"))]
            name = itf.get("interface-name")
            m = re.match(r"A7(\w+?)-A7(\w+)$", str(name))
            nb_name = m.group(2) if m else None
            nb_ports, nb_lag, mac_match = [], None, None
            if nb_name and nb_name in lldp_by_name:
                nb_ports = sorted({pid for pid, _ in lldp_by_name[nb_name]})
                lagset = {port_by_id[pid].get("lag") for pid in nb_ports if port_by_id[pid].get("lag")}
                nb_lag = sorted(lagset)[0] if len(lagset) == 1 else None
                chassis = {nb["chassisId"].lower().replace(":", "")[:8] for _, nb in lldp_by_name[nb_name]}
                mac_match = any(a["mac"] and a["mac"].lower().replace(":", "")[:8] in chassis for a in arps)
            ip = g(v4, "primary", "oper-address")
            interfaces.append({
                "router": rname, "name": name, "ifIndex": itf.get("if-index"), "sysIfIndex": itf.get("system-if-index"),
                "protocols": itf.get("protocol"), "mtu": itf.get("oper-ip-mtu"), "oper": itf.get("if-oper-status"),
                "v4Oper": v4.get("oper-state"), "v6Oper": g(itf, "ipv6", "oper-state"),
                "lastChange": itf.get("last-oper-change"), "origin": itf.get("creation-origin"),
                "ip": ip, "secondary": [x.get("oper-address") for x in L(v4.get("secondary"))],
                "arp": arps, "neighborName": nb_name, "neighborPorts": nb_ports, "neighborLag": nb_lag, "macMatchesLldp": mac_match,
                "icmpIn": n(icmp.get("icmp-in-msgs")), "icmpInErr": n(icmp.get("icmp-in-errors")),
                "icmpInEcho": n(icmp.get("icmp-in-echos")), "icmpInTtlExceeded": n(icmp.get("icmp-in-time-exceeds")),
                "icmpInUnreach": n(icmp.get("icmp-in-dest-unreachables")), "icmpOut": n(icmp.get("icmp-out-msgs")),
                "icmpOutEchoReply": n(icmp.get("icmp-out-echo-replies")),
                "ipInPkts": n(g(itf, "statistics", "ip", "in-packets")), "ipOutPkts": n(g(itf, "statistics", "ip", "out-packets")),
                "mplsInPkts": n(g(itf, "statistics", "mpls", "in-packets")), "mplsOutPkts": n(g(itf, "statistics", "mpls", "out-packets")),
                "src": ["rif", ipath],
            })
    local_ips = {i["ip"]: i for i in interfaces if i["ip"]}

    # ---- PCEP (optional)
    pcep_rows, ip_to_name, lo_to_name = [], {}, {}
    if os.path.exists(pcep_csv):
        with open(pcep_csv, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        for r in rows:
            nm = r["name"].split("::")[0]
            if "-" in nm:
                a, b = nm.split("-", 1)
                lo_to_name.setdefault(r["sender"], a)
                lo_to_name.setdefault(r["endpoint"], b)
        for r in rows:
            hops = [h.strip().split("/")[0] for h in r["ero"].split(">") if h.strip()]
            if hops and r["endpoint"] in lo_to_name:
                ip_to_name.setdefault(hops[-1], lo_to_name[r["endpoint"]])
        pcep_rows = rows
    device_ip = local_addr.get("system") or next((i["ip"] for i in interfaces if i["name"] == "system"), None)

    lsp_names_cfg = [str(l.get("lsp-name")) for l in L(g(src["mpls"], "state", "router", "mpls", "lsp"))]
    prefix = Counter(x.split("-")[0] for x in lsp_names_cfg if "-" in x)
    device_name = prefix.most_common(1)[0][0] if prefix else None
    if not device_name:
        dn = Counter(re.findall(r"SDP_(\w+?)-", " ".join(s["description"] for s in sdps.values())))
        device_name = dn.most_common(1)[0][0] if dn else "DEVICE"
    for i in interfaces:
        if i["ip"]:
            ip_to_name[i["ip"]] = device_name
        for a in i["arp"]:
            if i["neighborName"]:
                ip_to_name.setdefault(a["ip"], i["neighborName"])
    if device_ip:
        lo_to_name[device_ip] = device_name

    pcep_by_name = {r["name"].split("::")[0]: r for r in pcep_rows if r["pcc"] == device_ip}

    # ---- LSPs
    def cs(x):
        v = n(x, None)
        return None if v is None else round(v / 100.0)

    lsps = []
    mpls = g(src["mpls"], "state", "router", "mpls", default={}) or {}
    lsp_list = mpls.get("lsp")
    for li, l in enumerate(L(lsp_list)):
        nm = str(l.get("lsp-name"))
        pr = l.get("primary", {}) or {}
        mbb = g(pr, "mbb", "last-mbb", default={}) or {}
        far = nm.split("-", 1)[1] if "-" in nm else ""
        pc = pcep_by_name.get(nm)
        hops = []
        if pc:
            for h in [x.strip() for x in pc["ero"].split(">") if x.strip()]:
                ip = h.split("/")[0]
                hops.append({"ip": ip, "name": ip_to_name.get(ip, ""), "local": ip in local_ips})
        egress_if = None
        if hops and hops[0]["ip"] in local_ips:
            egress_if = local_ips[hops[0]["ip"]]["name"]
        sdp_users = [s for s in sdps.values() if s["lspName"] == nm]
        svc_count = sum(len(s["bindings"]) for s in sdp_users)
        lsps.append({
            "name": nm, "farEndName": far, "oper": l.get("oper-state"), "from": l.get("from-address"),
            "metric": l.get("oper-metric"), "mtu": l.get("negotiated-mtu"), "frr": l.get("oper-fast-reroute"),
            "tunnelId": l.get("tunnel-id"), "lspIndex": l.get("lsp-index"), "holdTimer": l.get("hold-timer"),
            "ageSec": cs(l.get("age")), "upSec": cs(l.get("time-up")), "downSec": cs(l.get("time-down")),
            "primaryUpSec": cs(l.get("primary-time-up")), "transitions": n(l.get("transitions")),
            "lastTransitionSec": cs(l.get("last-transition")), "pathChanges": n(l.get("path-changes")),
            "lastPathChangeSec": cs(l.get("last-path-change")),
            "paths": {"configured": l.get("configured-paths"), "standby": l.get("standby-paths"), "operational": l.get("operational-paths")},
            "entropy": g(l, "entropy-label-state", "operational"),
            "pathName": pr.get("path-name"), "pathOper": pr.get("oper-state"), "pathState": pr.get("path-state"),
            "failCode": pr.get("fail-code"), "failNode": pr.get("fail-node-address"),
            "setupPri": pr.get("setup-priority"), "holdPri": pr.get("hold-priority"), "cspf": pr.get("cspf"),
            "properties": pr.get("properties"), "bandwidth": pr.get("oper-bandwidth"), "hopLimit": pr.get("oper-hop-limit"),
            "lastResignal": pr.get("last-resignal-attempt"), "lspId": pr.get("lsp-id"),
            "mbbType": mbb.get("type"), "mbbEnd": mbb.get("end-time"), "mbbMetric": mbb.get("metric"), "mbbState": mbb.get("state"),
            "retries": n(g(pr, "statistics", "retry-attempts")), "pathTransitions": n(g(pr, "statistics", "transition-count")),
            "cspfQueries": n(g(pr, "statistics", "cspf-queries")), "nodeProtect": g(pr, "fast-reroute", "node-protect"),
            "pcep": {"plsp": pc["plsp_id"], "lspId": pc["lsp_id"], "tunnel": pc["tunnel_id"], "endpoint": pc["endpoint"],
                     "oper": pc["oper"], "admin": pc["admin"], "hops": n(pc["hops"]), "bwBps": pc["bw_bytes_per_s"],
                     "symbolic": pc["symbolic"]} if pc else None,
            "ero": hops, "egressInterface": egress_if,
            "egressLag": next((i["neighborLag"] for i in interfaces if i["name"] == egress_if), None),
            "sdps": [s["id"] for s in sdp_users], "serviceCount": svc_count,
            "src": ["mpls", ["state", "router", "mpls", "lsp"] + ([li] if isinstance(lsp_list, list) else [])],
        })
    lsp_names = {l["name"] for l in lsps}
    pcep_only = [{"name": k, **{x: v[x] for x in ("plsp_id", "endpoint", "oper", "admin", "hops", "ero")}}
                 for k, v in pcep_by_name.items() if k not in lsp_names]
    for s in sdps.values():
        lp = next((l for l in lsps if l["name"] == s["lspName"]), None)
        s["lspOper"] = lp["oper"] if lp else None
        s["farEndName"] = lo_to_name.get(s["farEnd"]) or (lp["farEndName"] if lp else "")

    # ---- neighbours (aggregate LLDP)
    nbrs = {}
    for p in ports:
        for nb in p["neighbors"]:
            key = nb.get("systemName") or nb.get("chassisId")
            d = nbrs.setdefault(key, {"name": key, "description": nb.get("systemDescription"), "chassis": nb.get("chassisId"),
                                      "capabilities": nb.get("capabilities") or nb.get("supportedCapabilities"),
                                      "mgmt": set(), "links": []})
            d["mgmt"].update(nb.get("mgmtAddresses") or [])
            d["links"].append({"localPort": p["id"], "lag": p.get("lag"), "remotePort": nb.get("remotePortId"),
                               "remoteDesc": nb.get("portDescription"), "speedMbps": p["speedMbps"], "oper": p["oper"]})
    for d in nbrs.values():
        desc = (d["description"] or "")
        d["kind"] = ("Nokia 7750 SR" if "7750" in desc else "Ciena 5142" if "Ciena" in desc else
                     "RAD ETX-203AM" if "ETX" in desc else "Calix E7" if str(d["chassis"]).startswith("E7") else "Other")
        d["release"] = (re.search(r"TiMOS-\S+", desc) or [None])[0] if desc else None
        d["mgmt"] = sorted(d["mgmt"])
        d["loopbackName"] = d["name"]
    neighbors = sorted(nbrs.values(), key=lambda x: (x["kind"] != "Nokia 7750 SR", x["name"]))

    # ---- chassis view from port ids
    slots = defaultdict(lambda: defaultdict(list))
    for p in ports:
        m = re.match(r"^(\d+)/(\d+)/(\d+)$", p["id"])
        if m:
            slots[m.group(1)][m.group(2)].append(p["id"])
        elif re.match(r"^[AB]/\d+$", p["id"]):
            slots["CPM " + p["id"][0]]["-"].append(p["id"])
    chassis = [{"slot": s, "mdas": [{"mda": m, "ports": v} for m, v in sorted(mdas.items())]} for s, mdas in sorted(slots.items())]

    # ---- issues
    issues = []

    def add(sev, area, obj, msg):
        issues.append({"sev": sev, "area": area, "object": obj, "message": msg})

    for p in ports:
        if p["id"].startswith("lag-"):
            continue
        equipped = (p.get("optic") or {}).get("equipped")
        if p["oper"] != "up":
            if p["saps"]:
                add("critical", "Port", p["id"], f"Port down with {len(p['saps'])} SAP(s): {', '.join(p['services'])}")
            elif equipped:
                add("warning", "Port", p["id"], f"Port down, optic equipped ({(p.get('optic') or {}).get('vendorPart') or 'unknown part'})")
            else:
                add("info", "Port", p["id"], "Port down, no optic (unused)")
        for k, v in p["ddm"].items():
            if v["status"] != "ok" and (p["oper"] == "up" or k == "received-optical-power"):
                add("critical" if v["status"] == "alarm" and p["oper"] == "up" else "warning", "Optics", p["id"],
                    f"{v['label']} {v['current']} {v['unit']} is in {v['status']} (alarm range {v['lowAlarm']}..{v['highAlarm']})")
        if p["flaps"] >= 50:
            add("warning", "Port", p["id"], f"{p['flaps']} oper-state changes (flapping history)")
        errs = p["inErrors"] + p["crc"] + p["fcs"] + p["symbolErrors"]
        if errs:
            add("warning", "Port", p["id"], f"Errors: in {p['inErrors']}, CRC {p['crc']}, FCS {p['fcs']}, frame-too-long {p['frameTooLong']}")
        if max(p["inUtilPct"], p["outUtilPct"]) >= 70:
            add("warning", "Capacity", p["id"], f"Utilisation in {p['inUtilPct']}% / out {p['outUtilPct']}%")
        for e in p["elmi"]["evcs"]:
            if e["status"] != "active" and p["oper"] != "up":
                add("info", "ELMI", p["id"], f"EVC VLAN {e['vlan']} '{e['identifier']}' is {e['status']}")
    for s in services:
        if s["oper"] and s["oper"] != "up":
            add("critical", "Service", f"{s['type']} {s['id']}", f"Service oper-state {s['oper']} ({s['name']})")
        for x in s["saps"]:
            if x["oper"] and x["oper"] != "up":
                add("critical", "SAP", x["sapId"], f"SAP {x['oper']} in {s['type']} {s['id']}")
            if x["rxPkts"] and x["rxDropPkts"] / max(x["rxPkts"], 1) > 0.0001:
                add("warning", "SAP", x["sapId"], f"Ingress drops {x['rxDropPkts']:,} of {x['rxPkts']:,} pkts ({x['rxDropPkts'] / x['rxPkts'] * 100:.3f}%)")
        for b in s["binds"]:
            if b["oper"] and b["oper"] != "up":
                add("critical", "SDP binding", b["bindId"], f"{b['kind']} binding {b['oper']} in {s['type']} {s['id']}")
    for s in sdps.values():
        if s["oper"] and s["oper"] != "up":
            add("critical", "SDP", str(s["id"]), f"SDP {s['oper']} to {s['farEnd']}")
        if s["helloLost"] / max(s["helloReq"], 1) > 0.0005:
            add("info", "SDP", str(s["id"]), f"Keep-alive: {s['helloLost']:,} of {s['helloReq']:,} hellos unanswered ({s['helloLost'] / max(s['helloReq'], 1) * 100:.3f}%)")
        if not s["bindings"]:
            add("info", "SDP", str(s["id"]), "SDP has no service bindings on this node")
    for l in lsps:
        if l["oper"] != "up":
            add("critical", "LSP", l["name"], f"LSP {l['oper']}, fail-code {l['failCode']}")
        if l["transitions"] >= 50:
            add("info", "LSP", l["name"], f"{l['transitions']} transitions since created")
        if pcep_rows and not l["pcep"]:
            add("info", "PCEP", l["name"], "LSP not found in the PCEP export")
    for x in pcep_only:
        add("info", "PCEP", x["name"], "In PCEP export but not in MPLS state")
    eg = Counter(l["egressInterface"] for l in lsps if l["egressInterface"])
    if eg and len(eg) == 1 and sum(eg.values()) >= 5:
        itf = next(iter(eg))
        add("warning", "Resilience", itf, f"All {sum(eg.values())} PCEP-reported LSPs leave via one interface ({itf})")
    for i in interfaces:
        if i["oper"] != "up":
            add("critical", "Interface", i["name"], f"Interface {i['oper']}")
    order = {"critical": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda x: (order[x["sev"]], x["area"], x["object"]))

    device = {
        "name": device_name, "systemIp": device_ip, "oobIp": local_addr.get("oob"),
        "routers": sorted({i["router"] for i in interfaces}),
        "asOf": as_of.isoformat(timespec="minutes") + "Z",
        "built": dt.datetime.now().isoformat(timespec="minutes"),
        "counterClear": Counter(x["countersSince"] for x in saps_all if x["countersSince"]).most_common(1)[0][0] if saps_all else None,
        "protocols": sorted({p for i in interfaces for p in str(i["protocols"] or "").split()}),
        "egressSummary": dict(eg),
    }
    live = store_model(device_ip or "")
    for qid, qdata in live["data"].items():
        src["st:" + qid] = qdata  # stored query results, viewable in the raw tab and drawers
    # Each service's MAC rows come from the stored FDB run (the CSV is only a fallback).
    stored_rows = defaultdict(list)
    for r in live["fdb"]["rows"]:
        stored_rows[r["service_id"]].append(r)
    if live["fdb"]["rows"]:
        for s in services:
            s["macRows"] = stored_rows.get(str(s["id"]), [])
    model = {"device": device, "sources": sources, "ports": ports, "lags": lags, "chassis": chassis,
             "neighbors": neighbors, "interfaces": interfaces, "services": services, "saps": saps_all,
             "sdps": list(sdps.values()), "lsps": lsps, "pcepOnly": pcep_only, "customers": list(customers.values()),
             "pwTemplates": pw_templates, "issues": issues, "pcepLoaded": bool(pcep_rows),
             "live": {k: live[k] for k in ("queries", "findings", "routing", "health", "fdb")}}

    with open(os.path.join(HERE, "device_report_template.html"), encoding="utf-8") as fh:
        tpl = fh.read()
    payload = json.dumps({"model": model, "src": src}, separators=(",", ":"), default=str).replace("</", "<\\/")
    html = tpl.replace("__DATA__", payload).replace("__TITLE__", f"{device_name} device report")
    out_path = out_path or os.path.join(folder, f"{device_name}_device_report.html")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    total = sum(s["leaves"] for s in sources)
    print(f"Device {device_name} ({device_ip}) as of {device['asOf']}")
    print(f"Sources: " + ", ".join(f"{s['key']}={s['status']}({s['leaves']} fields)" for s in sources))
    print(f"Ports {len(ports)}  services {len(services)}  SAPs {len(saps_all)}  SDPs {len(sdps)}  LSPs {len(lsps)}  "
          f"interfaces {len(interfaces)}  customers {len(customers)}  issues {len(issues)}  total fields {total}")
    print(f"Wrote {out_path} ({os.path.getsize(out_path) / 1e6:.2f} MB)")
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=HERE, help="folder holding the response files")
    ap.add_argument("--out", help="output HTML path")
    ap.add_argument("--node", help="device IP to build from the store (default: most recently used store folder)")
    ap.add_argument("--all-nodes", action="store_true", help="build one report for every device in the store")
    a = ap.parse_args()
    if a.all_nodes:
        sys.path.insert(0, HERE)
        import store
        nodes = sorted(f for f in os.listdir(store.STORE) if os.path.isdir(os.path.join(store.STORE, f)))
        for node_id in nodes:
            print(f"--- {node_id}")
            build(a.dir, None, node=node_id)
    else:
        build(a.dir, a.out, node=a.node)

