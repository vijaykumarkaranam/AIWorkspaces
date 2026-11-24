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

SEV = {"critical": 0, "warning": 1, "info": 2}
FAULT_BITS = ("lac-ingress-fault", "lac-egress-fault", "psn-ingress-fault", "psn-egress-fault", "pw-not-forwarding")


def _slim(ep):
    return {k: ep.get(k) for k in ("key", "type", "id", "name", "description", "oper", "vplsId", "acs")}


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
    point_to_point = ep["type"] in ("epipe", "p2p")
    if not ep["acs"] and point_to_point and len(ep["pws"]) < 2:
        add("warning", "No access circuit on this PE side: a point-to-point service needs one at each end.")
    elif not ep["acs"] and ep["type"] in ("vpls", "bridge-domain"):
        add("info", "No access circuit on this PE: it only carries the service between pseudowires (hub or transit).")
    if ep["type"] == "vprn":
        add("info", "L3 VPN: far ends are the BGP peers that share route-target "
                    f"{ep.get('routeTarget') or '?'}. Pseudowire stitching does not apply.")

    legs = []
    for pw in ep["pws"]:
        leg = {"pw": pw, "farEnd": {"ip": pw.get("peer"), "node": None, "vendor": None, "name": None,
                                    "status": "no-address", "matchedBy": None},
               "remote": None, "remotePw": None}
        tr = pw.get("transport") or {}
        if pw["oper"] in ("down", "admin-down"):
            add("critical", f"Pseudowire {pw['id']} to {pw.get('peer')} is {pw['oper']}.")
        if tr.get("sdpOper") == "down":
            add("critical", f"{tr.get('name')} towards {pw.get('peer')} is down (transport).")
        if tr.get("lspOper") == "down":
            add("critical", f"{tr.get('name')}: the LSP is down (transport).")
        if any(b in (pw.get("peerStatus") or "") for b in FAULT_BITS):
            add("warning", f"The far end of {pw['id']} reports '{pw['peerStatus']}'. Check its access circuit.")

        node = inv.resolve(pw.get("peer"))
        fe = leg["farEnd"]
        if not pw.get("peer"):
            add("warning", f"Pseudowire {pw['id']}: far-end address not known (SDP missing from the saved data).")
        elif node == local_pe["node"]:
            fe.update(status="self", node=node, vendor=local_pe["vendor"], name=local_pe["name"])
        elif node is None:
            fe.update(status="not-collected")
        else:
            rpe = inv.pe(node)
            fe.update(node=node, vendor=rpe["vendor"], name=rpe["name"])
            m = match_remote(ep, pw, local_pe, rpe)
            if not m:
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
        legs.append(leg)

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
    elif not legs:
        status = "local"
    elif not_collected or any(l["farEnd"]["status"] != "matched" for l in legs if l["farEnd"]["status"] != "self"):
        status = "partial"
    else:
        status = "up"
    issues.sort(key=lambda i: SEV[i["sev"]])
    rec = dict(ep)
    rec.update({"legs": legs, "status": status, "issues": issues,
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
    return {"node": node, "vendor": pe["vendor"], "name": pe["name"], "loopbacks": pe["loopbacks"],
            "generated": dt.datetime.now().isoformat(timespec="minutes"), "services": services,
            "farEnds": sorted(far.values(), key=lambda f: (f["collected"], f["ip"])), "counts": counts,
            "queries": pe.get("queries", []), "missing": [q for q in wanted if q not in pe.get("queries", [])],
            "saved": pe.get("saved", {})}
