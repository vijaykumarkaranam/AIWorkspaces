"""Cisco IOS-XR saved data -> service endpoints.

Uses these cisco_iosxr queries when they are saved (each one is optional):
  cisco-l2vpn-config     Cisco-IOS-XR-l2vpn-cfg l2vpn/database: xconnect groups and bridge-domain groups
  e2e-xconnect-config    the xconnect groups on their own (same model)
  e2e-bridge-ports       L2FIB bridge ports: the pseudowires each bridge domain really has, incl. BGP-AD peers
  cisco-l2vpn            L2FIB node data: cross-connects (pseudowire next hops for P2P services)
  e2e-bridge-oper        bridge-domain oper state and PW/AC up counts
  cisco-interfaces-xr    interface state (attachment circuit state)
  e2e-interface-config   interface descriptions (circuit IDs) and Loopback0 address
  cisco-lldp-native      LLDP neighbours (the CE on each AC port) and this router's name and addresses

Pseudowire state comes from L2FIB: a PW whose next hop is valid is counted as up. The oper
xconnect container (l2vpnv2/active/xconnects) is not on every release, so it is not relied on.
"""
from .util import as_list, find_key, get, norm_state, port_of, walk_dicts

QUERIES = ["cisco-l2vpn-config", "e2e-xconnect-config", "e2e-bridge-ports", "cisco-l2vpn", "e2e-bridge-oper",
           "cisco-interfaces-xr", "e2e-interface-config", "cisco-lldp-native"]
FAR_END_QUERIES = ["cisco-l2vpn-config", "e2e-xconnect-config", "e2e-bridge-ports", "cisco-l2vpn",
                   "e2e-bridge-oper", "cisco-interfaces-xr", "e2e-interface-config", "cisco-lldp-native"]


def vpls_id(v):
    """Cisco VPLS-ID container -> 'as:index' or 'address:index' (the form Nokia shows as bgp-ad vpls-id)."""
    if not isinstance(v, dict):
        return None
    if v.get("as") is not None and v.get("as-index") is not None:
        return f"{v['as']}:{v['as-index']}"
    addr = v.get("address") or v.get("ipv4-address")
    idx = v.get("address-index") or v.get("index")
    if addr is not None and idx is not None:
        return f"{addr}:{idx}"
    return None


def lldp_neighbours(data):
    """{local interface: neighbour} and this router's LLDP name and advertised addresses."""
    nbrs, addrs = {}, set()
    for node in as_list(get(data, "Cisco-IOS-XR-ethernet-lldp-oper:lldp", "nodes", "node")):
        for itf in as_list(get(node, "interfaces", "interface")):
            for e in as_list(get(itf, "local-network-addresses", "lldp-addr-entry")):
                ip = get(e, "address", "ipv4-address")
                if ip:
                    addrs.add(ip)
        for d in as_list(get(node, "neighbors", "details", "detail")):
            for n in as_list(d.get("lldp-neighbor")):
                det = n.get("detail") or {}
                mgmt = [get(e, "address", "ipv4-address") for e in as_list(get(det, "network-addresses", "lldp-addr-entry"))]
                local = n.get("receiving-interface-name") or d.get("interface-name")
                if local:
                    nbrs[local] = {"name": det.get("system-name") or n.get("device-id") or "",
                                   "port": n.get("port-id-detail") or "", "portDescription": det.get("port-description") or "",
                                   "description": (det.get("system-description") or "").strip(), "chassis": n.get("chassis-id") or "",
                                   "mgmt": next((m for m in mgmt if m), ""), "scope": ""}
    name = get(data, "Cisco-IOS-XR-ethernet-lldp-oper:lldp", "global-lldp", "lldp-info", "system-name")
    return nbrs, name, addrs


def l2fib_pseudowires(*datasets):
    """Every L2FIB pseudowire: {(next hop, pw id): state} and {(group, bd name): [pw]} for bridge ports."""
    by_key, by_bd = {}, {}
    for data in datasets:
        for d in walk_dicts(data):
            pw = get(d, "segment", "pw") or get(d, "segment1", "pw") or get(d, "segment2", "pw")
            if not isinstance(pw, dict) or not pw.get("next-hop-address"):
                continue
            rec = {"peer": pw.get("next-hop-address"), "pwId": str(pw.get("pw-id") or ""),
                   "oper": "up" if pw.get("next-hop-valid") else "down",
                   "type": pw.get("pseudo-wire-id-type") or "", "groupState": pw.get("group-state"),
                   "flowLabel": pw.get("pw-flow-label-tx")}
            by_key.setdefault((rec["peer"], rec["pwId"]), rec)
            if d.get("bd-name"):
                lst = by_bd.setdefault((str(d.get("group-name") or ""), str(d.get("bd-name"))), [])
                if not any(x["peer"] == rec["peer"] and x["pwId"] == rec["pwId"] for x in lst):
                    lst.append(rec)
    return by_key, by_bd


def _interfaces(data):
    out = {}
    for i in as_list(find_key(data, "interface")):
        if isinstance(i, dict) and i.get("interface-name"):
            out[i["interface-name"]] = i.get("state") or i.get("line-state")
    return out


def _interface_config(data):
    desc, loop = {}, set()
    for i in as_list(find_key(data, "interface-configuration")):
        name = i.get("interface-name")
        if not name:
            continue
        if i.get("description"):
            desc[name] = i["description"]
        if name.lower().startswith("loopback"):
            addr = get(i, "Cisco-IOS-XR-ipv4-io-cfg:ipv4-network", "addresses", "primary", "address")
            if addr:
                loop.add(addr)
    return desc, loop


def _bridge_oper(data):
    out = {}
    for bd in as_list(find_key(data, "bridge-domain")):
        if isinstance(bd, dict) and bd.get("bridge-domain-name"):
            info = bd.get("bridge-domain-info") or {}
            out[(str(bd.get("bridge-domain-group-name") or info.get("group-name") or ""), str(bd["bridge-domain-name"]))] = {
                "state": info.get("bridge-state"), "pws": info.get("number-pseudowires"), "pwsUp": info.get("number-p-ws-up"),
                "acs": info.get("number-a-cs"), "acsUp": info.get("number-a-cs-up")}
    return out


def pe_from_saved(node, data):
    """Build the PE view for one Cisco router. `data` maps query id -> saved data (may be partial)."""
    lldp, name, addrs = lldp_neighbours(data.get("cisco-lldp-native") or {})
    if_state = _interfaces(data.get("cisco-interfaces-xr") or {})
    desc, loop = _interface_config(data.get("e2e-interface-config") or {})
    pw_state, bd_pws = l2fib_pseudowires(data.get("e2e-bridge-ports") or {}, data.get("cisco-l2vpn") or {})
    bd_oper = _bridge_oper(data.get("e2e-bridge-oper") or {})

    def ac(name_):
        port = port_of(name_)
        return {"id": name_, "port": port, "vlan": name_.split(".", 1)[1] if "." in name_ else "",
                "oper": norm_state(if_state.get(name_)), "flags": "", "adminShutdown": False,
                "portOper": norm_state(if_state.get(port)), "description": desc.get(name_, ""),
                "interface": None, "ce": dict(lldp[port]) if port in lldp else None}

    def pw(peer, pwid, kind):
        st = pw_state.get((peer, str(pwid)))
        return {"id": f"{peer}:{pwid}", "kind": kind, "vcId": str(pwid), "sdpId": None, "peer": peer,
                "oper": st["oper"] if st else "unknown", "flags": "", "localStatus": "", "peerStatus": "",
                "transport": {"type": "mpls", "name": "LDP/SR to " + str(peer), "sdpOper": None, "lspOper": None,
                              "description": "PW state from L2FIB next hop" if st else "PW not in saved L2FIB data"}}

    endpoints = []
    groups = []
    for src in ("cisco-l2vpn-config", "e2e-xconnect-config"):
        g = find_key(data.get(src) or {}, "xconnect-group")
        if g:
            groups = as_list(g)
            break
    for grp in groups:
        for xc in as_list(get(grp, "p2p-xconnects", "p2p-xconnect")):
            key = f"{grp.get('name')}/{xc.get('name')}"
            acs = [ac(a.get("name")) for a in as_list(get(xc, "attachment-circuits", "attachment-circuit")) if a.get("name")]
            pws = [pw(p.get("neighbor"), p.get("pseudowire-id"), "pw")
                   for p in as_list(get(xc, "pseudowire-neighbor-pseudowire-ids", "pseudowire-neighbor-pseudowire-id"))]
            for p in as_list(get(xc, "pseudowires", "pseudowire")):  # older model: pseudowire-id with a neighbor list
                for nb in as_list(p.get("neighbor")):
                    pws.append(pw(nb.get("neighbor"), p.get("pseudowire-id"), "pw"))
            evpn = [f"EVI {e.get('eviid')} AC {e.get('remote-acid')}" for e in as_list(get(xc, "pseudowire-evpns", "pseudowire-evpn"))]
            endpoints.append(_endpoint("p2p", key, xc.get("name"), acs, pws, None, None, evpn))

    bd_groups = []
    for src in ("cisco-l2vpn-config",):
        g = find_key(data.get(src) or {}, "bridge-domain-group")
        if g:
            bd_groups = as_list(g)
    for grp in bd_groups:
        for bd in as_list(get(grp, "bridge-domains", "bridge-domain")):
            gname, bname = str(grp.get("name")), str(bd.get("name"))
            acs = [ac(a.get("name")) for a in as_list(get(bd, "bd-attachment-circuits", "bd-attachment-circuit")) if a.get("name")]
            acs += [dict(ac(r.get("interface-name")), interface="routed (BVI)")
                    for r in as_list(get(bd, "routed-interfaces", "routed-interface")) if r.get("interface-name")]
            pws = [pw(p.get("neighbor"), p.get("pseudowire-id"), "pw")
                   for p in as_list(get(bd, "bd-pseudowires", "bd-pseudowire"))]
            vid, vpn = None, None
            for vfi in as_list(get(bd, "vfis", "vfi")):
                vpn = vpn or vfi.get("vpnid")
                vid = vid or vpls_id(get(vfi, "bgp-auto-discovery", "ldp-signaling-protocol", "vpls-id"))
                pws += [pw(p.get("neighbor"), p.get("pseudowire-id"), "vfi")
                        for p in as_list(get(vfi, "vfi-pseudowires", "vfi-pseudowire"))]
            known = {(p["peer"], p["vcId"]) for p in pws}
            for x in bd_pws.get((gname, bname), []):  # BGP-AD peers exist only in oper data
                if (x["peer"], x["pwId"]) not in known:
                    pws.append(pw(x["peer"], x["pwId"], "bgp-auto"))
            evpn = [f"EVI {e.get('vpn-id')}" for e in as_list(get(bd, "bridge-domain-evis", "bridge-domain-evi"))]
            ep = _endpoint("bridge-domain", f"{gname}/{bname}", bname, acs, pws, vid, vpn, evpn)
            op = bd_oper.get((gname, bname))
            if op:
                ep["oper"] = norm_state(op["state"])
                ep["counts"] = op
            ep["description"] = bd.get("bridge-description") or ""
            endpoints.append(ep)

    loopbacks = {node} | loop | addrs
    return {"node": node, "vendor": "cisco", "name": name or node, "loopbacks": sorted(x for x in loopbacks if x),
            "endpoints": endpoints, "queries": sorted(q for q in QUERIES if data.get(q) is not None)}


def _endpoint(stype, key, name, acs, pws, vid, vpn, evpn):
    states = [a["oper"] for a in acs if a["interface"] is None] + [p["oper"] for p in pws]
    if states and all(s == "up" for s in states):
        oper = "up"
    elif any(s in ("down", "admin-down") for s in states):
        oper = "down"
    else:
        oper = "unknown"
    return {"key": f"{stype}:{key}", "type": stype, "id": key, "name": str(name or key), "description": "",
            "customer": "", "oper": oper, "adminShutdown": False, "vplsId": vid, "vpnId": vpn,
            "routeTarget": None, "rd": None, "acs": acs, "pws": pws, "evpn": evpn}
