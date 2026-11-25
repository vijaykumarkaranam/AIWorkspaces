"""Live end-to-end trace of ONE service, the way the Service-LDP-E2E dashboard does it.

For each far-end PE of the service (each pseudowire peer), ask only what this service needs:
  Nokia far end  (NETCONF CLI over ODL, ietf-netconf:get with a cli-show filter)
                   show service id <N> base   -> type, name, state
                   show service id <N> sap    -> its SAPs and their state
                   show system lldp neighbor  -> the CE on each SAP port
  Cisco far end  (RESTCONF GET over ODL, the same URLs the dashboard uses)
                   Cisco-IOS-XR-ethernet-lldp-oper:lldp            -> the CE on each AC port
                   l2vpn/database/bridge-domain-groups (VPLS) or
                   l2vpn/database/xconnect-groups (point to point) -> the matching service and its ACs
The service is matched like the report does (same VC/PW id back to this PE, or same VPLS-ID), with the
dashboard's fallbacks: the Nokia service id equal to the Cisco VPN-ID, or the same bridge-domain name.

The result is saved in e2e_traces/<node>/<service>.json and merged into the End-to-end view
(far ends that have no full saved data are shown from the trace). Every request is a read.
"""
import datetime as dt
import json
import os
import re
from urllib.parse import quote

from . import cisco
from .collect import _modules, make_client, topology
from .sources import ROOT, Inventory
from .stitch import _slim, build_report_model, match_remote
from .util import find_key, norm_state

STATUS_TEXT = {"ce_found": "CE found", "no_lldp": "service found, no CE seen by LLDP",
               "no-service": "PE reached, service not found", "unreachable": "PE not reachable through ODL"}


def traces_dir():
    return os.path.abspath(os.environ.get("E2E_TRACES") or os.path.join(ROOT, "e2e_traces"))


def _safe(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(text or "")).strip("_")[:120] or "item"


def trace_path(node, service_key):
    return os.path.join(traces_dir(), _safe(node), _safe(service_key) + ".json")


def load_trace(node, service_key):
    p = trace_path(node, service_key)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- Nokia CLI parsing

LLDP_COLUMNS = ("Lcl Port", "Scope", "Remote Chassis ID", "Index", "Remote Port", "Remote Sys Name")


def parse_nokia_lldp(text):
    """'show system lldp neighbor' -> {local port: {name, port, chassis, scope}} using the header's column positions
    (labels are found by name: some are separated by a single space, so splitting on words would merge them)."""
    lines = (text or "").splitlines()
    head = next((i for i, l in enumerate(lines) if l.strip().startswith("Lcl Port")), None)
    out = {}
    if head is None:
        return out
    cols = [lines[head].find(c) for c in LLDP_COLUMNS]
    if any(c < 0 for c in cols):
        return out
    for l in lines[head + 1:]:
        if not re.match(r"^(\d+/\d+/\d+|lag-\d+|esat-\S+|pxc-\S+)\s", l):
            continue
        cells = [l[cols[i]:cols[i + 1] if i + 1 < len(cols) else None].strip() for i in range(len(cols))]
        if len(cells) < 6:
            continue
        port = cells[0].split()[0]
        nb = {"name": cells[5].rstrip("*").strip(), "port": cells[4].rstrip("*").strip(), "chassis": cells[2],
              "scope": {"NB": "nearest-bridge", "NC": "nearest-customer", "NTPMR": "nearest-non-tpmr"}.get(cells[1], cells[1]),
              "truncated": cells[5].endswith("*"), "mgmt": "", "description": ""}
        if port not in out or nb["scope"] == "nearest-bridge":
            out[port] = nb
    return out


def parse_nokia_saps(text):
    """'show service id N sap' -> [{id, port, vlan, admin, oper}]. Admin and oper are the last two columns."""
    out = []
    for l in (text or "").splitlines():
        t = l.split()
        if len(t) >= 3 and re.match(r"^(\d+/\d+/\d+|lag-\d+|pw-\d+|esat-\S+)(:\S*)?$", t[0]) and t[-1].lower() in ("up", "down"):
            sap = t[0]
            out.append({"id": sap, "port": sap.split(":")[0], "vlan": sap.split(":", 1)[1] if ":" in sap else "",
                        "admin": t[-2].lower() if t[-2].lower() in ("up", "down") else "", "oper": t[-1].lower()})
    return out


def parse_nokia_base(text):
    """'show service id N base' -> {type, name, description, admin, oper} (whatever is present)."""
    def field(label):
        # A label starts a line or follows a wide gap (two fields can share a line, e.g. Admin State / Oper State).
        m = re.search(rf"(?:^|\s{{2,}}){label}\s*:\s*(.*?)(?=\s{{2,}}\S|$)", text or "", re.M)
        return m.group(1).strip() if m else ""
    return {"type": field("Service Type").lower(), "name": field("Name"), "description": field("Description"),
            "admin": field("Admin State").lower(), "oper": field("Oper State").lower()}


def _cli(client, node, command):
    resp = client.cli_show(node, command)
    r = find_key(resp, "response")
    return r if isinstance(r, str) else ""


# ---------------------------------------------------------------- per-vendor far-end lookups

def _service_ids(ep, pw):
    """Nokia service ids to try for a far end: the same id (Nokia to Nokia), the VPN-ID (Cisco VPLS),
    or the VC id (point to point), as the dashboard does."""
    ids = []
    for v in (ep.get("id") if ep.get("type") in ("epipe", "vpls", "vprn") else None, ep.get("vpnId"), pw.get("vcId"),
              (re.sub(r"\D", "", str(ep.get("name") or "")) or None)):
        if v not in (None, "") and str(v).isdigit() and int(v) < 2 ** 31 and str(v) not in ids:
            ids.append(str(v))
    return ids


def trace_nokia(client, odl_node, ep, pw):
    """The far end on a Nokia PE: (status, remote endpoint or None, how, error)."""
    lldp = None
    for sid in _service_ids(ep, pw):
        saps = parse_nokia_saps(_cli(client, odl_node, f"service id {sid} sap"))
        base = parse_nokia_base(_cli(client, odl_node, f"service id {sid} base"))
        if not saps and not base.get("type"):
            continue
        if lldp is None:
            lldp = parse_nokia_lldp(_cli(client, odl_node, "system lldp neighbor"))
        acs = [{"id": s["id"], "port": s["port"], "vlan": s["vlan"], "oper": norm_state(s["oper"]),
                "adminShutdown": s["admin"] == "down", "portOper": "unknown", "flags": "", "description": "",
                "interface": None, "ce": lldp.get(s["port"]), "portKey": None, "portHealth": None, "portWhy": []} for s in saps]
        rep = {"key": f"{base.get('type') or 'service'}:{sid}", "type": base.get("type") or "service", "id": sid,
               "name": base.get("name") or f"service {sid}", "description": base.get("description"),
               "oper": norm_state(base.get("oper")) if base.get("oper") else
               ("up" if any(a["oper"] == "up" for a in acs) else "unknown"), "vplsId": None, "acs": acs, "objKey": None}
        return ("ce_found" if any(a["ce"] for a in acs) else "no_lldp"), rep, f"Nokia service id {sid}", ""
    return "no-service", None, "", f"no Nokia service with id {' / '.join(_service_ids(ep, pw)) or '?'}"


def trace_cisco(client, odl_node, ep, pw, local_pe):
    """The far end on a Cisco PE: (status, remote endpoint or None, how, error)."""
    _odl, _nq, cq = _modules()
    data = {}
    want = "e2e-bridge-config" if ep.get("type") in ("vpls", "bridge-domain") else "e2e-xconnect-config"
    for qid in ("cisco-lldp-native", want):
        data[qid], _used, _note = cq.fetch(client, odl_node, qid)
    rpe = cisco.pe_from_saved(odl_node, data)
    m = match_remote(ep, pw, local_pe, rpe)
    if not m:  # the dashboard's fallback: same VPN-ID or bridge-domain name
        for rep in rpe["endpoints"]:
            if (ep.get("vpnId") and str(rep.get("vpnId")) == str(ep.get("vpnId"))) or \
                    (ep.get("name") and rep.get("name") == ep.get("name")) or \
                    (ep.get("type") in ("vpls", "epipe") and str(rep.get("vpnId")) == str(ep.get("id"))):
                m = (rep, None, f"VPN-ID / name {rep.get('vpnId') or rep.get('name')}")
                break
    if not m:
        return "no-service", None, "", "no bridge domain or xconnect matching this service"
    rep, _rpw, how = m
    rec = _slim(rep)
    rec["peName"] = rpe.get("name")
    return ("ce_found" if any(a.get("ce") for a in rep["acs"]) else "no_lldp"), rec, how, ""


# ---------------------------------------------------------------- the local bridge domain's peers

IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def _ip(v):
    """An IPv4 address from a peer field that may be a string or a {ipv4 / ipv4-peer-id: ...} container."""
    if isinstance(v, dict):
        v = v.get("ipv4") or v.get("ipv4-peer-id") or v.get("ipv4-address") or v.get("neighbor")
    return v if isinstance(v, str) and IPV4.match(v) and v != "0.0.0.0" else None


def bd_oper_peers(data):
    """Pseudowire peers in a bridge domain's oper detail (l2vpnv2 bridge-domain): VFI PWs, BGP-AD
    discovered peers and access PWs, with PW id, state and VC labels where the router gives them."""
    from .util import walk_dicts
    peers = {}
    for d in walk_dicts(data or {}):
        peer = None
        for k in ("neighbor", "peer-id", "vpls-peer-id", "neighbor-address", "peer-address", "next-hop-address"):
            peer = _ip(d.get(k))
            if peer:
                break
        if not peer:
            continue
        pw = d.get("pseudowire") if isinstance(d.get("pseudowire"), dict) else d
        rec = peers.setdefault(peer, {"peer": peer, "pwId": "", "state": "", "localLabel": None, "remoteLabel": None})
        rec["pwId"] = rec["pwId"] or str(d.get("pw-id") or d.get("pseudo-wire-id") or d.get("pseudowire-id")
                                         or pw.get("pw-id") or pw.get("pseudo-wire-id") or "")
        rec["state"] = rec["state"] or str(d.get("state") or pw.get("state") or d.get("pseudowire-state") or "")
        for k, f in (("localLabel", "local-label"), ("remoteLabel", "remote-label")):
            rec[k] = rec[k] if rec[k] is not None else (d.get(f) if d.get(f) is not None else
                                                        (pw.get(f) if pw.get(f) is not None else get_label(d, f)))
    return list(peers.values())


def get_label(d, field):
    for sub in ("local-signalling", "remote-signalling", "label-information"):
        v = (d.get(sub) or {}).get(field) if isinstance(d.get(sub), dict) else None
        if v is not None:
            return v
    return None


def local_vpls_peers(client, node, ep, pe, log=print):
    """(peers, source) for a Cisco bridge domain whose peers are not in the saved data.

    1. this bridge domain's own oper state (one keyed read, l2vpnv2/active/bridge-domains/bridge-domain=G,N);
    2. else, as the dashboard does, the T-LDP neighbours whose client is AToM (candidates: the far-end
       trace then shows which of them carry this VPLS)."""
    if pe.get("vendor") != "cisco" or ep.get("type") != "bridge-domain" or not ep.get("group"):
        return [], ""
    path = ("Cisco-IOS-XR-l2vpn-oper:l2vpnv2/active/bridge-domains/bridge-domain="
            f"{quote(str(ep['group']), safe='')},{quote(str(ep['name']), safe='')}?content=nonconfig")
    try:
        found = bd_oper_peers(client.data_get(node, path))
    except Exception as exc:  # older releases have no keyed read: fall back below
        log(f"  bridge-domain oper read failed: {str(exc)[:160]}")
        found = []
    mine = set(pe.get("loopbacks") or [])
    found = [p for p in found if p["peer"] not in mine]
    if found:
        return found, "bridge-domain oper state"
    cands = [{"peer": ip, "pwId": "", "state": "", "localLabel": None, "remoteLabel": None}
             for ip, n in sorted((pe.get("_ldp") or {}).items()) if "AToM" in (n.get("clients") or []) and ip not in mine]
    return cands, "T-LDP neighbours with AToM (candidates)" if cands else ""


# ---------------------------------------------------------------- the trace

def trace_service(node, service_key, client=None, inv=None, log=print, max_peers=40):
    """Trace one service's far ends live through ODL, save the result, and return it."""
    inv = inv or Inventory()
    client = client or make_client()
    pe = inv.pe(node)
    if pe is None:
        raise ValueError(f"No saved data for {node}: run its queries first.")
    ep = next((e for e in pe["endpoints"] if e["key"] == service_key), None)
    if ep is None:
        raise ValueError(f"Service {service_key} is not in the saved data for {node}.")
    topo = topology(client)
    peers = {}
    for pw in ep["pws"]:
        if pw.get("peer") and pw["peer"] not in peers and inv.resolve(pw["peer"]) != node:
            peers[pw["peer"]] = pw
    local_peers, local_src = [], ""
    if ep.get("type") == "bridge-domain" and (not ep["pws"] or str(ep.get("signaling", "")).startswith("BGP-AD")):
        local_peers, local_src = local_vpls_peers(client, node, ep, pe, log)
        log(f"  {len(local_peers)} peer(s) from {local_src or 'nowhere'}")
        for lp in local_peers:
            peers.setdefault(lp["peer"], {"peer": lp["peer"], "vcId": lp["pwId"], "kind": "bgp-auto", "oper": lp["state"]})
    ordered = sorted(peers, key=lambda ip: (topo.get(inv.odl_node_for(ip), {}).get("status") != "connected", ip))
    result = {"node": node, "service": service_key, "tracedAt": dt.datetime.now().isoformat(timespec="seconds"),
              "peers": {}, "skipped": max(0, len(ordered) - max_peers),
              "localPeers": local_peers, "localPeersFrom": local_src, "candidates": "candidates" in local_src}
    for ip in ordered[:max_peers]:
        pw = peers[ip]
        odl_node = inv.odl_node_for(ip)
        t = topo.get(odl_node)
        rec = {"ip": ip, "odlNode": odl_node, "vendor": t.get("vendor") if t else None, "status": "unreachable",
               "remote": None, "how": "", "error": ""}
        if t is None:
            rec["error"] = "not mounted in ODL under this address (add it to e2e/loopback_map.json if ODL uses another)"
        elif str(t.get("status")).lower() != "connected":
            rec["error"] = f"mounted but {t.get('status') or 'not connected'}"
        elif not t.get("vendor"):
            rec["error"] = "vendor not recognised from its NETCONF capabilities"
        else:
            try:
                fn = trace_nokia if t["vendor"] == "nokia" else (lambda c, n, e, p: trace_cisco(c, n, e, p, pe))
                rec["status"], rec["remote"], rec["how"], rec["error"] = fn(client, odl_node, ep, pw)
                if rec["remote"] and rec["remote"].get("peName"):
                    rec["peName"] = rec["remote"].pop("peName")
            except Exception as exc:  # one far end failing must not stop the others
                rec["status"], rec["error"] = "unreachable", str(exc)[:400]
        log(f"  {ip} ({rec['vendor'] or '?'}): {STATUS_TEXT.get(rec['status'], rec['status'])}"
            + (f" - {rec['error']}" if rec["error"] else ""))
        result["peers"][ip] = rec
    p = trace_path(node, service_key)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, default=str)
    return result


def traced_service_payload(node, service_key, inv=None):
    """The service as the page shows it after a trace: its record, plus the objects and counts to refresh."""
    model = build_report_model(node, inv or Inventory())
    rec = next((s for s in model["services"] if s["key"] == service_key), None)
    return {"service": rec, "objects": model.get("objects", {}), "counts": model.get("counts", {}),
            "farEnds": model.get("farEnds", [])}
