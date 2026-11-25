"""Stitch one router's services to their far-end PEs and judge each service end to end.

For each pseudowire of a local service the far end is found like this:
  1. resolve the PW peer (SDP far end / PW neighbour, a loopback) to a router with saved data
  2. on that router, find the service with a PW that has the same VC / PW id and points back
     at one of this router's loopbacks (LDP-signalled epipe, VPLS spoke/mesh, Cisco xconnect)
  3. otherwise, for BGP-AD VPLS, the service with the same VPLS-ID
  4. otherwise a service with the same VC id that points elsewhere (reported as a warning)

Status of a service:
  up          every known AC and PW is up, and every far end was found and is up
  down        a point-to-point service with anything on its path down, or a multipoint
              service that is down as a whole
  degraded    a multipoint service with some sites cut off, or a warning
              (far end mismatch, far end reports a fault)
  partial     no fault seen, but at least one far-end PE has no saved data yet
  local       no pseudowires (local switching, or an L3 VPN)
  admin-down  the service is shut down in the config
"""
import datetime as dt

from . import cisco, nokia
from .sources import Inventory
from .util import norm_state

SEV = {"critical": 0, "warning": 1, "info": 2}
FAULT_BITS = ("lac-ingress-fault", "lac-egress-fault", "psn-ingress-fault", "psn-egress-fault", "pw-not-forwarding")


def _slim(ep):
    return {k: ep.get(k) for k in ("key", "type", "id", "name", "description", "oper", "vplsId", "acs", "objKey")}


def _traced_pws(ep, trace, local_pe):
    """Pseudowires a live trace found for this service that the saved data did not have (BGP-AD VPLS
    peers from the bridge domain's oper state, or T-LDP candidates that turned out to carry it)."""
    if not trace or not trace.get("localPeers"):
        return [], []
    known = {p.get("peer") for p in ep["pws"]}
    out, others = [], []
    for lp in trace["localPeers"]:
        peer = lp.get("peer")
        t = (trace.get("peers") or {}).get(peer) or {}
        if not peer or peer in known:
            continue
        if lp.get("candidate") and t.get("status") not in ("ce_found", "no_lldp"):
            # A T-LDP (AToM) neighbour that does not carry this VPLS, or that could not be checked:
            # listed apart, not as a peer of this service.
            others.append({"ip": peer, "status": t.get("status") or "not traced", "error": t.get("error") or "",
                           "vendor": t.get("vendor")})
            continue
        fn = local_pe.get("_transport_to")
        tr = dict(fn(peer)) if fn else {"type": "", "name": f"to {peer}", "paths": [], "hops": [], "issues": []}
        tr["description"] = f"peer from the live trace ({trace.get('localPeersFrom')})"
        pw = {"id": f"{peer}:{lp.get('pwId') or 'auto'}", "kind": "bgp-auto", "vcId": str(lp.get("pwId") or ""),
              "sdpId": None, "peer": peer, "oper": norm_state(lp.get("state")) if lp.get("state") else
              ("up" if t.get("status") in ("ce_found", "no_lldp") else "unknown"),
              "flags": "", "localStatus": "", "peerStatus": "", "transport": tr,
              "tldp": (local_pe.get("_ldp") or {}).get(peer), "fromTrace": trace.get("localPeersFrom")}
        if lp.get("localLabel") is not None or lp.get("remoteLabel") is not None:
            pw["pwLabels"] = {"local": lp.get("localLabel"), "remote": lp.get("remoteLabel")}
        out.append(pw)
    return out, others


def _load_trace(node, service_key):
    from .trace import load_trace  # trace imports this module; load it when needed
    try:
        return load_trace(node, service_key)
    except (OSError, ValueError):
        return None


def _apply_trace(leg, trace, add):
    """Fill a far end from the saved live trace of this service. True when the trace had this peer."""
    fe = leg["farEnd"]
    t = ((trace or {}).get("peers") or {}).get(fe.get("ip"))
    if not t:
        return False
    fe.update(node=fe.get("node") or t.get("odlNode"), vendor=fe.get("vendor") or t.get("vendor"),
              name=fe.get("name") or t.get("peName"), traced=trace.get("tracedAt"), error=t.get("error") or None)
    st, rem = t.get("status"), t.get("remote")
    where = fe.get("name") or fe["ip"]
    if st in ("ce_found", "no_lldp") and rem:
        fe.update(status="matched", matchedBy=f"live trace: {t.get('how')}")
        leg["remote"] = rem
        if rem.get("oper") == "down":
            add("critical", f"Far end {where}: service {rem.get('name')} is down (live trace).")
        for rac in rem.get("acs") or []:
            if rac.get("oper") in ("down", "admin-down") and not rac.get("adminShutdown"):
                add("critical", f"Far end {where}: access circuit {rac['id']} is {rac['oper']} (live trace).")
    elif st == "no-service":
        fe["status"] = "no-service"
        add("warning", f"Live trace: {where} has no service matching this one ({t.get('error') or 'not found'}).")
    else:
        fe["status"] = "unreachable"
        add("warning", f"Live trace: far-end PE {where} not reachable through ODL ({t.get('error') or 'error'}).")
    return True


def walk_path(inv, start_pe, peer, max_hops=12):
    """Follow the route to `peer` router by router, as far as routers with a saved RIB reach (Cisco).

    Each hop: the router, its egress interface and port health, next hop and label stack. The next
    router is found from the LLDP neighbour's address or the next-hop address."""
    hops, cur, seen = [], start_pe, {start_pe["node"]}
    target = inv.resolve(peer)
    while cur is not None and len(hops) < max_hops:
        fn = cur.get("_transport_to")
        if not fn:
            break
        t = fn(peer)
        prim = next((p for p in t.get("paths") or [] if p["role"] == "primary"), None)
        hop = {"node": cur["node"], "name": cur["name"], "peKey": cur.get("key"), "routeKey": t.get("routeKey")}
        if not prim:
            hop["note"] = "no route" if not t.get("note") else t["note"]
            hops.append(hop)
            break
        port = prim.get("port") or {}
        hop.update(interface=prim.get("interface"), interfaceKey=prim.get("interfaceKey"), nextHop=prim.get("nextHop"),
                   nextHopName=prim.get("nextHopName"), labels=prim.get("labels"),
                   port={k: port.get(k) for k in ("key", "id", "oper", "health", "why", "neighbor")} if port else None)
        hops.append(hop)
        nxt = inv.resolve(prim.get("nextHopMgmt")) or inv.resolve(prim.get("nextHop"))
        if not nxt or nxt in seen:
            break
        if nxt == target:
            tp = inv.pe(nxt)
            hops.append({"node": nxt, "name": tp["name"], "peKey": tp.get("key"), "final": True})
            break
        seen.add(nxt)
        cur = inv.pe(nxt)
    return hops


def _refs(x, out):
    """Every object key mentioned anywhere in x (fields named *Key / key, and link cells)."""
    if isinstance(x, dict):
        for k, v in x.items():
            if isinstance(v, str) and (k == "key" or k == "k" or k.endswith("Key")) and v.count("|") >= 2:
                out.add(v)
            elif isinstance(v, (dict, list)):
                _refs(v, out)
    elif isinstance(x, list):
        for v in x:
            _refs(v, out)
    return out


def collect_objects(inv, pe, services):
    """The detail objects the page can open: all of this router's, plus the far-end and transit objects
    the services point to, and what those link to (two steps), so the report stays small."""
    objects = dict(pe.get("objects") or {})
    todo = [k for k in _refs(services, set()) if k not in objects]
    for _depth in range(3):
        nxt = []
        for k in todo:
            node = k.split("|")[1]
            src = (inv.pe(node) or {}).get("objects") or {}
            o = src.get(k)
            if o is None or k in objects:
                continue
            objects[k] = o
            nxt += [r for r in _refs({"links": o.get("links"), "tables": o.get("tables")}, set()) if r not in objects]
        todo = nxt
    return objects


def match_remote(ep, pw, local_pe, remote_pe):
    """(remote endpoint, remote pw, how it matched) or None."""
    mine = set(local_pe["loopbacks"])
    vc = str(pw.get("vcId") or "")
    if vc and pw.get("kind") != "bgp-auto":
        for rep in remote_pe["endpoints"]:
            for rpw in rep["pws"]:
                if str(rpw.get("vcId")) == vc and (rpw.get("peer") in mine or not rpw.get("peer")):
                    return rep, rpw, "VC id " + vc
    if ep.get("vplsId"):
        for rep in remote_pe["endpoints"]:
            if rep.get("vplsId") == ep["vplsId"]:
                rpw = next((r for r in rep["pws"] if r.get("peer") in mine), None)
                return rep, rpw, "VPLS-ID " + str(ep["vplsId"])
    if vc and pw.get("kind") != "bgp-auto":
        for rep in remote_pe["endpoints"]:
            for rpw in rep["pws"]:
                if str(rpw.get("vcId")) == vc:
                    return rep, rpw, f"VC id {vc} (far end points to {rpw.get('peer')})"
    return None


def stitch_endpoint(ep, local_pe, inv):
    """One end-to-end record for a local service endpoint."""
    issues = []

    def add(sev, msg):
        issues.append({"sev": sev, "msg": msg})

    if ep.get("adminShutdown"):
        add("info", "The service is shut down in the configuration.")
    if ep.get("oper") == "down" and not ep.get("adminShutdown"):
        add("critical", f"The service is down on {local_pe['name']}.")

    for ac in ep["acs"]:
        if ac["oper"] in ("down", "admin-down") and not ac.get("adminShutdown"):
            why = f", port {ac['port']} is down" if ac.get("portOper") == "down" or "port-oper-down" in ac.get("flags", "") else ""
            add("critical", f"Access circuit {ac['id']} is {ac['oper']}{why}.")
        elif ac.get("portIssue"):
            add(ac["portIssue"][0], f"{ac['portIssue'][1]} (AC {ac['id']})")
    point_to_point = ep["type"] in ("epipe", "p2p")
    if not ep["acs"] and point_to_point and len(ep["pws"]) < 2:
        add("warning", "No access circuit on this PE side: a point-to-point service needs one at each end.")
    elif not ep["acs"] and ep["type"] in ("vpls", "bridge-domain"):
        add("info", "No access circuit on this PE: it only carries the service between pseudowires (hub or transit).")
    if ep["type"] == "vprn":
        add("info", "L3 VPN: far ends are the BGP peers that share route-target "
                    f"{ep.get('routeTarget') or '?'}. Pseudowire stitching does not apply.")

    trace = _load_trace(local_pe["node"], ep["key"])
    legs = []
    bgp_ad = str(ep.get("signaling") or "").startswith("BGP-AD")
    extra, others = _traced_pws(ep, trace, local_pe)
    for pw in list(ep["pws"]) + extra:
        leg = {"pw": pw, "farEnd": {"ip": pw.get("peer"), "node": None, "vendor": None, "name": None,
                                    "status": "no-address", "matchedBy": None},
               "remote": None, "remotePw": None}
        tr = pw.get("transport") or {}
        if pw["oper"] in ("down", "admin-down"):
            add("critical", f"Pseudowire {pw['id']} to {pw.get('peer')} is {pw['oper']}.")
        if tr.get("sdpOper") == "down":
            add("critical", f"{tr.get('name')} towards {pw.get('peer')} is down (transport).")
        if tr.get("lspOper") == "down" and not tr.get("issues"):
            add("critical", f"{tr.get('name')}: the LSP is down (transport).")  # else the transport issues say it with the fail code
        if any(b in (pw.get("peerStatus") or "") for b in FAULT_BITS):
            add("warning", f"The far end of {pw['id']} reports '{pw['peerStatus']}'. Check its access circuit.")
        for i in tr.get("issues") or []:
            add(i["sev"], i["msg"])
        walk = walk_path(inv, local_pe, pw.get("peer"))
        if len(walk) > 1:
            leg["walk"] = walk

        node = inv.resolve(pw.get("peer"))
        fe = leg["farEnd"]
        if not pw.get("peer"):
            add("warning", f"Pseudowire {pw['id']}: far-end address not known (SDP missing from the saved data).")
        elif node == local_pe["node"]:
            fe.update(status="self", node=node, vendor=local_pe["vendor"], name=local_pe["name"])
        elif node is None:
            fe.update(status="not-collected")
            _apply_trace(leg, trace, add)
        else:
            rpe = inv.pe(node)
            fe.update(node=node, vendor=rpe["vendor"], name=rpe["name"], peKey=rpe.get("key"))
            m = match_remote(ep, pw, local_pe, rpe)
            if not m and _apply_trace(leg, trace, add):
                pass  # the live trace found it (it also matches by VPN-ID and bridge-domain name)
            elif not m:
                fe["status"] = "no-service"
                add("warning", f"{rpe['name']} ({node}) has no service matching {pw['id']}"
                               + (f" or VPLS-ID {ep['vplsId']}" if ep.get("vplsId") else "") + ".")
            else:
                rep, rpw, how = m
                fe.update(status="matched", matchedBy=how)
                leg["remote"], leg["remotePw"] = _slim(rep), rpw
                if "points to" in how:
                    add("warning", f"{rpe['name']}: matched by {how}, not to this PE.")
                if rep.get("oper") == "down":
                    add("critical", f"Far end: service {rep['name']} is down on {rpe['name']}.")
                if rpw and rpw.get("oper") in ("down", "admin-down"):
                    add("critical", f"Far end: pseudowire {rpw['id']} on {rpe['name']} is {rpw['oper']}.")
                for rac in rep["acs"]:
                    if rac["oper"] in ("down", "admin-down") and not rac.get("adminShutdown"):
                        add("critical", f"Far end: access circuit {rac['id']} on {rpe['name']} is {rac['oper']}.")
                    elif rac.get("portIssue"):
                        add(rac["portIssue"][0], f"Far end {rpe['name']}: {rac['portIssue'][1]}")
                for i in ((rpw or {}).get("transport") or {}).get("issues") or []:
                    add(i["sev"], f"Return path from {rpe['name']}: {i['msg']}")
        legs.append(leg)

    if not legs and bgp_ad and ep["type"] in ("bridge-domain", "vpls"):
        add("info", "BGP-AD VPLS: its peers are learned at run time and are not in the saved data. Press "
                    "'Trace far ends live' to read this bridge domain's peers and follow each one to its CE.")
    not_collected = sorted({l["farEnd"]["ip"] for l in legs if l["farEnd"]["status"] == "not-collected"})
    if not_collected:
        shown = ", ".join(not_collected[:5]) + (f" and {len(not_collected) - 5} more" if len(not_collected) > 5 else "")
        add("info", f"No saved data for far-end PE {shown}. Use 'Collect far ends' to fetch it.")

    worst = min((SEV[i["sev"]] for i in issues), default=9)
    # A multipoint service (VPLS, bridge domain) that is still up with only some sites cut off
    # is degraded; a point-to-point service is down as soon as anything on its path is down.
    bad = ("down", "admin-down")
    whole_down = (point_to_point or ep.get("oper") == "down"
                  or (ep["acs"] and all(a["oper"] in bad for a in ep["acs"]))
                  or (legs and all(l["pw"]["oper"] in bad for l in legs)))
    if ep.get("adminShutdown"):
        status = "admin-down"
    elif worst == 0 and whole_down:
        status = "down"
    elif worst == 0:
        status = "degraded"
    elif worst == 1:
        status = "degraded"
    elif not legs and bgp_ad and ep["type"] in ("bridge-domain", "vpls"):
        status = "partial"  # peers exist, but only a trace (or the L2FIB read) can list them
    elif not legs:
        status = "local"
    elif not_collected or any(l["farEnd"]["status"] != "matched" for l in legs if l["farEnd"]["status"] != "self"):
        status = "partial"
    else:
        status = "up"
    seen, unique = set(), []
    for i in issues:  # SDPs and LSPs are shared by many bindings: report each message once
        if i["msg"] not in seen:
            seen.add(i["msg"])
            unique.append(i)
    issues = sorted(unique, key=lambda i: SEV[i["sev"]])
    rec = dict(ep)
    rec.update({"legs": legs, "status": status, "issues": issues, "tracedAt": (trace or {}).get("tracedAt"),
                "traceOthers": others, "tracePeersFrom": (trace or {}).get("localPeersFrom"),
                "ces": sorted({a["ce"]["name"] for a in ep["acs"] if a.get("ce") and a["ce"].get("name")})})
    rec.pop("pws", None)
    return rec


def build_report_model(node, inv=None):
    """Everything the End-to-end tab shows for one router, or a model with an `error` field."""
    inv = inv or Inventory()
    pe = inv.pe(node)
    if pe is None:
        return {"node": node, "error": f"No saved data for {node} in the Nokia store or the Cisco results folder.",
                "services": [], "farEnds": [], "counts": {}}
    services = [stitch_endpoint(ep, pe, inv) for ep in pe["endpoints"]]
    far = {}
    for s in services:
        for l in s["legs"]:
            fe = l["farEnd"]
            if not fe["ip"] or fe["status"] == "self":
                continue
            d = far.setdefault(fe["ip"], {"ip": fe["ip"], "node": fe["node"], "vendor": fe["vendor"], "name": fe["name"],
                                          "collected": fe["status"] not in ("not-collected",),
                                          "odlNode": fe["node"] or inv.odl_node_for(fe["ip"]), "services": 0})
            d["services"] += 1
    counts = {"services": len(services)}
    for s in services:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    counts["farEnds"] = len(far)
    counts["farEndsMissing"] = sum(1 for f in far.values() if not f["collected"])
    wanted = (nokia if pe["vendor"] == "nokia" else cisco).QUERIES
    return {"node": node, "vendor": pe["vendor"], "name": pe["name"], "loopbacks": pe["loopbacks"], "peKey": pe.get("key"),
            "objects": collect_objects(inv, pe, services),
            "generated": dt.datetime.now().isoformat(timespec="minutes"), "services": services,
            "farEnds": sorted(far.values(), key=lambda f: (f["collected"], f["ip"])), "counts": counts,
            "queries": pe.get("queries", []), "missing": [q for q in wanted if q not in pe.get("queries", [])],
            "saved": pe.get("saved", {})}
