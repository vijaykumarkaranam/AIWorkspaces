"""Cisco IOS-XR saved data -> service endpoints, transport paths and detail objects.

Uses these cisco_iosxr queries when they are saved (each one is optional):
  cisco-l2vpn-config     Cisco-IOS-XR-l2vpn-cfg l2vpn/database: xconnect groups and bridge-domain groups
  e2e-xconnect-config    the xconnect groups on their own (same model)
  e2e-bridge-ports       L2FIB bridge ports: the pseudowires each bridge domain really has, incl. BGP-AD peers
  cisco-l2vpn            L2FIB node data: cross-connects (pseudowire next hops for P2P services)
  e2e-bridge-oper        bridge-domain oper state and PW/AC up counts
  cisco-interfaces-xr    interface state (attachment circuit and core port state, speed)
  e2e-interface-config   interface descriptions (circuit IDs) and Loopback0 address
  cisco-lldp-native      LLDP neighbours (CE and core neighbours) and this router's name and addresses
  cisco-rib-ipv4         IPv4 RIB: the route to each far-end loopback, primary and backup (TI-LFA) paths, SR labels
  cisco-ethernet-stats   Ethernet error counters and optics per lane

Pseudowire state comes from L2FIB: a PW whose next hop is valid is counted as up. The oper
xconnect container (l2vpnv2/active/xconnects) is not on every release, so it is not relied on.
"""
import ipaddress

from .transport import cisco_port, key, link, num, obj, port_issue
from .util import as_list, find_key, get, norm_state, port_of, walk_dicts

QUERIES = ["cisco-l2vpn-config", "e2e-xconnect-config", "e2e-bridge-ports", "cisco-l2vpn", "e2e-bridge-oper",
           "cisco-interfaces-xr", "e2e-interface-config", "cisco-lldp-native", "cisco-rib-ipv4", "cisco-ethernet-stats"]
FAR_END_QUERIES = ["cisco-l2vpn-config", "e2e-xconnect-config", "e2e-bridge-ports", "cisco-l2vpn",
                   "e2e-bridge-oper", "cisco-interfaces-xr", "e2e-interface-config", "cisco-lldp-native",
                   "cisco-rib-ipv4", "cisco-ethernet-stats"]
BACKUP_FLAG = 0x100


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
            out[i["interface-name"]] = i
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


def _routes(rib):
    """Every RIB route with its paths: [(network, route)]. Only the default table is in the query."""
    out = []
    for d in walk_dicts(rib):
        if "route-path" in d and d.get("address") is not None and d.get("prefix-length") is not None:
            try:
                out.append((ipaddress.ip_network(f"{d['address']}/{d['prefix-length']}", strict=False), d))
            except ValueError:
                continue
    return out


class _Ctx:
    def __init__(self, node, data):
        self.node = node
        self.lldp, self.name, self.addrs = lldp_neighbours(data.get("cisco-lldp-native") or {})
        self.ifx = _interfaces(data.get("cisco-interfaces-xr") or {})
        self.desc, self.loop = _interface_config(data.get("e2e-interface-config") or {})
        eth = get(data.get("cisco-ethernet-stats") or {}, "Cisco-IOS-XR-drivers-media-eth-oper:ethernet-interface", default={}) or {}
        self.eth_stat = {s.get("interface-name"): s for s in as_list(get(eth, "statistics", "statistic"))}
        self.eth_if = {s.get("interface-name"): s for s in as_list(get(eth, "interfaces", "interface"))}
        self.routes = _routes(data.get("cisco-rib-ipv4") or {})
        self.has_rib = data.get("cisco-rib-ipv4") is not None
        self.objects, self.ports, self.transports = {}, {}, {}

    def port(self, name):
        if name not in self.ports:
            p, o = cisco_port(self.node, name, self.ifx.get(name), self.eth_stat.get(name), self.eth_if.get(name),
                              self.lldp.get(name))
            if name.lower().startswith("bundle-ether"):
                p["why"] = p["why"] + ["bundle members are not in the saved data"]
            if self.desc.get(name):
                o["fields"].insert(1, ["Description", self.desc[name]])
            self.objects[o["key"]] = o
            self.ports[name] = p
        return self.ports[name]

    def route_to(self, ip):
        try:
            addr = ipaddress.ip_address(ip)
        except (ValueError, TypeError):
            return None
        best = None
        for net, r in self.routes:
            if addr in net and (best is None or net.prefixlen > best[0].prefixlen):
                best = (net, r)
        return best

    def transport_to(self, peer):
        """Route to a far-end loopback: primary and backup paths, labels, egress ports. Cached per peer."""
        if peer in self.transports:
            return self.transports[peer]
        t = {"type": "", "name": f"route to {peer}", "sdpOper": None, "lspOper": None, "description": "",
             "paths": [], "hops": [], "issues": [], "label": None, "lsp": None}
        found = self.route_to(peer)
        if not self.has_rib:
            t["note"] = "IPv4 RIB not saved for this router: run the cisco-rib-ipv4 query to see the path."
        elif not found:
            t["issues"].append({"sev": "critical", "msg": f"No route to far-end loopback {peer} in the RIB."})
        else:
            net, r = found
            label = r.get("route-label")
            t["label"] = label if num(label) not in (0, 1048577) else None
            proto = " ".join(str(x) for x in (r.get("protocol-name"), r.get("instance")) if x)
            t["type"] = ("SR-MPLS" if t["label"] else "IP") + (f" ({proto})" if proto else "")
            t["name"] = f"{net} via {r.get('protocol-name') or '?'} metric {r.get('metric')}"
            rows = []
            for pth in as_list(get(r, "route-path", "ipv4-rib-edm-path")):
                backup = num(pth.get("ref-cnt-of-backup")) > 0 or bool(num(pth.get("flags")) & BACKUP_FLAG)
                itf = pth.get("interface-name")
                labels = [e.get("entry") for e in as_list(pth.get("labelstk"))] or (
                    [pth.get("route-label")] if num(pth.get("route-label")) not in (0, 1048577) else [])
                port = self.port(itf) if itf else None
                nh = get(pth, "address", "ipv4")
                p = {"role": "backup (TI-LFA)" if backup else "primary", "nextHop": nh,
                     "nextHopName": port["neighbor"]["name"] if port and port.get("neighbor") else "",
                     "nextHopMgmt": port["neighbor"]["mgmt"] if port and port.get("neighbor") else "",
                     "interface": itf, "interfaceKey": port["key"] if port else None, "interfaceIp": None,
                     "portName": itf, "labels": labels, "port": port, "metric": pth.get("metric"),
                     "remoteBackup": [get(x, "ipv4") for x in as_list(pth.get("remote-backup-addr")) if get(x, "ipv4") not in (None, "0.0.0.0")]}
                t["paths"].append(p)
                rows.append([p["role"], nh, p["nextHopName"], link(itf, p["interfaceKey"]), " / ".join(map(str, labels)), pth.get("metric")])
            t["paths"].sort(key=lambda p: p["role"] != "primary")
            prim = [p for p in t["paths"] if p["role"] == "primary"]
            if not any(p["role"] != "primary" for p in t["paths"]) and len(prim) == 1:
                t["issues"].append({"sev": "info", "msg": f"Route to {peer} has a single path and no backup (TI-LFA) path."})
            for p in prim:
                pi = port_issue(p["port"], f"Egress towards {p['nextHopName'] or p['nextHop']}:")
                if pi:
                    t["issues"].append({"sev": pi[0], "msg": pi[1]})
            rk = key("route", self.node, str(net))
            t["routeKey"] = rk
            self.objects[rk] = obj("route", self.node, str(net), f"Route {net}", f"IPv4 RIB on {self.name or self.node}",
                                   "up" if r.get("active") else "down",
                                   fields=[["Prefix", str(net)], ["Protocol", f"{r.get('protocol-name')} {r.get('instance') or ''}"],
                                           ["Metric", r.get("metric")], ["Distance", r.get("distance")],
                                           ["SR label (prefix SID)", t["label"]], ["Active", r.get("active")],
                                           ["Paths", len(t["paths"])], ["Age (s)", r.get("route-age")]],
                                   tables=[{"title": "Paths", "columns": ["Role", "Next hop", "Neighbour (LLDP)", "Interface", "Label stack", "Metric"],
                                            "rows": rows}],
                                   links=[{"label": f"Interface {p['interface']}", "key": p["interfaceKey"]} for p in t["paths"] if p["interfaceKey"]],
                                   raw=r)
        self.transports[peer] = t
        return t


def pe_from_saved(node, data):
    """Build the PE view for one Cisco router. `data` maps query id -> saved data (may be partial)."""
    ctx = _Ctx(node, data)
    pw_state, bd_pws = l2fib_pseudowires(data.get("e2e-bridge-ports") or {}, data.get("cisco-l2vpn") or {})
    bd_oper = _bridge_oper(data.get("e2e-bridge-oper") or {})

    def ac(name_):
        port = port_of(name_)
        pinfo = ctx.port(port) if port in ctx.ifx or port in ctx.eth_stat else None
        return {"id": name_, "port": port, "vlan": name_.split(".", 1)[1] if "." in name_ else "",
                "oper": norm_state((ctx.ifx.get(name_) or {}).get("state")), "flags": "", "adminShutdown": False,
                "portOper": norm_state((ctx.ifx.get(port) or {}).get("state")), "description": ctx.desc.get(name_, ""),
                "interface": None, "ce": dict(ctx.lldp[port]) if port in ctx.lldp else None,
                "portKey": pinfo["key"] if pinfo else None, "portHealth": pinfo["health"] if pinfo else None,
                "portWhy": pinfo["why"] if pinfo else [], "portIssue": port_issue(pinfo, "Access port") if pinfo else None}

    def pw(peer, pwid, kind):
        st = pw_state.get((peer, str(pwid)))
        tr = dict(ctx.transport_to(peer))
        tr["description"] = "PW state from L2FIB next hop" if st else "PW not in saved L2FIB data"
        return {"id": f"{peer}:{pwid}", "kind": kind, "vcId": str(pwid), "sdpId": None, "peer": peer,
                "oper": st["oper"] if st else "unknown", "flags": "", "localStatus": "", "peerStatus": "",
                "transport": tr}

    endpoints, raws = [], {}
    groups = []
    for src in ("cisco-l2vpn-config", "e2e-xconnect-config"):
        g = find_key(data.get(src) or {}, "xconnect-group")
        if g:
            groups = as_list(g)
            break
    for grp in groups:
        for xc in as_list(get(grp, "p2p-xconnects", "p2p-xconnect")):
            k = f"{grp.get('name')}/{xc.get('name')}"
            acs = [ac(a.get("name")) for a in as_list(get(xc, "attachment-circuits", "attachment-circuit")) if a.get("name")]
            pws = [pw(p.get("neighbor"), p.get("pseudowire-id"), "pw")
                   for p in as_list(get(xc, "pseudowire-neighbor-pseudowire-ids", "pseudowire-neighbor-pseudowire-id"))]
            for p in as_list(get(xc, "pseudowires", "pseudowire")):  # older model: pseudowire-id with a neighbor list
                for nb in as_list(p.get("neighbor")):
                    pws.append(pw(nb.get("neighbor"), p.get("pseudowire-id"), "pw"))
            evpn = [f"EVI {e.get('eviid')} AC {e.get('remote-acid')}" for e in as_list(get(xc, "pseudowire-evpns", "pseudowire-evpn"))]
            endpoints.append(_endpoint("p2p", k, xc.get("name"), acs, pws, None, None, evpn))
            raws[endpoints[-1]["key"]] = {"config": xc, "group": grp.get("name")}

    bd_groups = as_list(find_key(data.get("cisco-l2vpn-config") or {}, "bridge-domain-group"))
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
            raws[ep["key"]] = {"config": bd, "group": gname, "oper": op}

    for ep in endpoints:
        ep["objKey"] = key("svc", node, ep["key"])
        c = ep.get("counts") or {}
        ctx.objects[ep["objKey"]] = obj(
            "svc", node, ep["key"], f"{ep['type']} {ep['id']}", ep.get("description") or "", ep["oper"],
            fields=[["Type", ep["type"]], ["Name", ep["name"]], ["State", ep["oper"]], ["VPLS-ID", ep.get("vplsId")],
                    ["VPN id", ep.get("vpnId")], ["Attachment circuits", len(ep["acs"])], ["Pseudowires", len(ep["pws"])],
                    ["PWs up (oper)", f"{c.get('pwsUp')} of {c.get('pws')}" if c else None],
                    ["ACs up (oper)", f"{c.get('acsUp')} of {c.get('acs')}" if c else None],
                    ["EVPN", ", ".join(ep.get("evpn") or [])]],
            tables=[{"title": "Attachment circuits", "columns": ["AC", "State", "Port", "Description", "CE (LLDP)"],
                     "rows": [[a["id"], a["oper"], link(a["port"], a["portKey"]), a["description"],
                               f"{a['ce']['name']} {a['ce']['port']}" if a["ce"] else ""] for a in ep["acs"]]},
                    {"title": "Pseudowires", "columns": ["Peer", "PW id", "Kind", "State", "Route to peer"],
                     "rows": [[p["peer"], p["vcId"], p["kind"], p["oper"],
                               link(p["transport"].get("name"), p["transport"].get("routeKey"))] for p in ep["pws"]]}],
            raw=raws.get(ep["key"]))

    loopbacks = {node} | ctx.loop | ctx.addrs
    pe_key = key("pe", node, node)
    ctx.objects[pe_key] = obj("pe", node, node, ctx.name or node, "Cisco IOS-XR PE", None,
                              fields=[["Node (ODL)", node], ["Name", ctx.name], ["Loopbacks / LLDP addresses", ", ".join(sorted(loopbacks))],
                                      ["Services", len(endpoints)], ["RIB routes saved", len(ctx.routes)],
                                      ["Saved queries", ", ".join(q for q in QUERIES if data.get(q) is not None)]],
                              tables=[{"title": "LLDP neighbours", "columns": ["Local interface", "Neighbour", "Neighbour port", "Address"],
                                       "rows": [[link(i, ctx.port(i)["key"]), n["name"], n["port"], n["mgmt"]] for i, n in sorted(ctx.lldp.items())]}])
    return {"node": node, "vendor": "cisco", "name": ctx.name or node, "loopbacks": sorted(x for x in loopbacks if x),
            "endpoints": endpoints, "queries": sorted(q for q in QUERIES if data.get(q) is not None),
            "objects": ctx.objects, "key": pe_key, "_transport_to": ctx.transport_to}


def _endpoint(stype, key_, name, acs, pws, vid, vpn, evpn):
    states = [a["oper"] for a in acs if a["interface"] is None] + [p["oper"] for p in pws]
    if states and all(s == "up" for s in states):
        oper = "up"
    elif any(s in ("down", "admin-down") for s in states):
        oper = "down"
    else:
        oper = "unknown"
    return {"key": f"{stype}:{key_}", "type": stype, "id": key_, "name": str(name or key_), "description": "",
            "customer": "", "oper": oper, "adminShutdown": False, "vplsId": vid, "vpnId": vpn,
            "routeTarget": None, "rd": None, "acs": acs, "pws": pws, "evpn": evpn}
