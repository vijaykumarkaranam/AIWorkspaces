"""Nokia SR OS (classic config) saved data -> service endpoints, transport paths and detail objects.

Uses these nokia_view queries when they are saved (each one is optional):
  config-services          configure > service: services, SAPs, SDP bindings, SDP far ends, VPLS-ID
  epipe-state, vpls-state  oper state of services, SAPs and bindings
  sdp-state                SDP oper state, far end and the LSP type in use
  lldp, port-state         LLDP neighbours (CE and core neighbours), port state, errors and optics
  mpls-lsp-state           LSP oper state, metric, FRR, transitions, path state and fail code
  rsvp                     RSVP sessions: out-label, next hop, egress interface, FRR protection in use
  router-interface-state   router interfaces (if-index, address, ARP) and the system address
  config-router-config     the port or LAG each router interface is bound to
  lag                      LAG member ports and their state
  system                   system name
Hop-by-hop LSP paths come from nokia_view/pce-lsp-inventory.csv when it is there (PCEP export).
"""
from .transport import PceIndex, hop_list, key, link, nokia_port, num, obj, port_issue
from .util import as_list, get, norm_state, text, unwrap, walk_dicts

QUERIES = ["config-services", "epipe-state", "vpls-state", "sdp-state", "lldp", "port-state",
           "mpls-lsp-state", "rsvp", "router-interface-state", "config-router-config", "lag", "system"]
# The set fetched for a far-end PE: its side of each service, its CE, and its transport back.
FAR_END_QUERIES = ["config-services", "epipe-state", "vpls-state", "sdp-state", "lldp", "port-state",
                   "mpls-lsp-state", "rsvp", "router-interface-state", "config-router-config", "lag", "system"]
SERVICE_TYPES = ("epipe", "vpls", "vprn")


def _service_tree(cfg):
    return get(unwrap(cfg), "configure", "service", default={}) or {}


def _state_services(data, stype):
    return as_list(get(unwrap(data), "state", "service", stype))


def lldp_neighbours(data):
    """{port-id: [neighbour]} from the nokia-state port > ethernet > lldp tree (lldp or port-state query)."""
    out = {}
    for port in as_list(get(unwrap(data), "state", "port")):
        pid = str(port.get("port-id"))
        for dm in as_list(get(port, "ethernet", "lldp", "dest-mac")):
            for rs in as_list(dm.get("remote-system")):
                # tx-mgmt-address is what this router sends, not the neighbour's address, so it is not used.
                mgmt = [m.get("remote-mgmt-address") or m.get("mgmt-address")
                        for m in as_list(rs.get("remote-mgmt-address")) if isinstance(m, dict)]
                out.setdefault(pid, []).append({
                    "name": rs.get("system-name") or rs.get("chassis-id") or "",
                    "port": rs.get("remote-port-id") or "",
                    "portDescription": rs.get("port-description") or "",
                    "description": rs.get("system-description") or "",
                    "chassis": rs.get("chassis-id") or "",
                    "mgmt": next((m for m in mgmt if m), ""),
                    "scope": dm.get("mac-type") or "",
                })
    return out


def _router_interfaces(rif):
    """{name: interface} for the Base router, with if-index, address and ARP entries."""
    out = {}
    for r in as_list(get(unwrap(rif), "state", "router")):
        if r.get("router-name") not in (None, "Base"):
            continue
        for itf in as_list(r.get("interface")):
            v4 = itf.get("ipv4") or {}
            arp = [{"ip": a.get("ipv4-address"), "mac": a.get("mac-address"), "state": a.get("oper-state")}
                   for a in as_list(get(v4, "neighbor-discovery", "neighbor")) if isinstance(a, dict)]
            out[itf.get("interface-name")] = {"name": itf.get("interface-name"), "ifIndex": itf.get("if-index"),
                                              "ip": get(v4, "primary", "oper-address"), "oper": norm_state(itf.get("if-oper-status")),
                                              "mtu": itf.get("oper-ip-mtu"), "protocols": itf.get("protocol"),
                                              "lastChange": itf.get("last-oper-change"), "arp": arp, "raw": itf}
    return out


def _interface_ports(cfg_router):
    """{interface name: (port or lag name, prefix)} from configure > router > interface."""
    out = {}
    for d in walk_dicts(unwrap(cfg_router)):
        if d.get("interface-name") and isinstance(d.get("port"), dict):
            out[d["interface-name"]] = (get(d, "port", "port-name"), get(d, "address", "ip-address-mask"))
    return out


def _lags(data):
    out = {}
    for lg in as_list(get(unwrap(data), "state", "lag")):
        lid = f"lag-{lg.get('lag-index')}"
        out[lid] = {"id": lid, "oper": norm_state(lg.get("oper-state")), "raw": lg,
                    "members": [{"port": str(p.get("port-id")), "oper": norm_state(p.get("oper-state")),
                                 "role": p.get("active-standby") or ""} for p in as_list(lg.get("port"))]}
    return out


def _system_address(rifs):
    sys_if = rifs.get("system")
    return sys_if["ip"] if sys_if else None


def _ce_for(port, lldp):
    nbrs = lldp.get(port) or []
    # The nearest-bridge neighbour is the directly attached device.
    best = next((n for n in nbrs if n["scope"] in ("nearest-bridge", "")), nbrs[0] if nbrs else None)
    return dict(best) if best else None


class _Ctx:
    """Everything one Nokia router's saved data says, indexed for the transport and the detail objects."""

    def __init__(self, node, data):
        self.node = node
        self.cfg = _service_tree(data.get("config-services"))
        self.lldp = lldp_neighbours(data.get("port-state"))
        self.lldp.update(lldp_neighbours(data.get("lldp")))  # the lldp query wins where both have a port
        self.ports_raw = {str(p.get("port-id")): p for p in as_list(get(unwrap(data.get("port-state")), "state", "port"))}
        self.lsps = {str(l.get("lsp-name")): l for l in as_list(get(unwrap(data.get("mpls-lsp-state")), "state", "router", "mpls", "lsp"))}
        self.rifs = _router_interfaces(data.get("router-interface-state"))
        self.if_by_index = {i["ifIndex"]: i for i in self.rifs.values() if i.get("ifIndex") is not None}
        self.if_ports = _interface_ports(data.get("config-router-config"))
        self.lags = _lags(data.get("lag"))
        self.lag_of = {m["port"]: lid for lid, lg in self.lags.items() for m in lg["members"]}
        self.rsvp = {}
        for s in as_list(get(unwrap(data.get("rsvp")), "state", "router", "rsvp", "session")):
            if s.get("session-type") == "p2p-originate" and s.get("session-name"):
                lsp, _, path = str(s["session-name"]).partition("::")
                cur = self.rsvp.get(lsp)
                if cur is None or (s.get("oper-state") == "up" and cur.get("oper-state") != "up"):
                    self.rsvp[lsp] = dict(s, _path=path)
        self.objects = {}
        self.port_cache = {}

    def port(self, pid):
        """Port summary (and its detail object) for a port or LAG id."""
        if pid in self.port_cache:
            return self.port_cache[pid]
        if pid.startswith("lag-") and pid in self.lags:
            lg = self.lags[pid]
            members = [self.port(m["port"]) for m in lg["members"]]
            up = sum(1 for m in lg["members"] if m["oper"] == "up")
            worst = "alarm" if lg["oper"] != "up" else ("warning" if up < len(members) or any(m["health"] != "ok" for m in members) else "ok")
            p = {"key": key("lag", self.node, pid), "id": pid, "oper": lg["oper"], "members": members,
                 "membersUp": up, "health": worst,
                 "why": ([f"{len(members) - up} of {len(members)} members down"] if up < len(members) else [])
                        + [f"{m['id']}: {', '.join(m['why'])}" for m in members if m["why"]],
                 "neighbor": next((m["neighbor"] for m in members if m.get("neighbor")), None)}
            self.objects[p["key"]] = obj(
                "lag", self.node, pid, f"LAG {pid}", "Nokia LAG", lg["oper"],
                fields=[["State", lg["oper"]], ["Members up", f"{up} of {len(members)}"],
                        ["Bandwidth", f"{num(lg['raw'].get('bandwidth')) // 1000:,} Mb/s" if lg["raw"].get("bandwidth") else None],
                        ["Partner system", lg["raw"].get("partner-system-id")],
                        ["Health", "; ".join(p["why"]) or "ok"]],
                tables=[{"title": "Member ports", "columns": ["Port", "State", "Role", "LLDP neighbour", "Errors / CRC", "Rx dBm", "Health"],
                         "rows": [[link(m["id"], m["key"]), m["oper"], lm["role"],
                                   f"{m['neighbor']['name']} {m['neighbor']['port']}" if m.get("neighbor") else "",
                                   f"{m['inErrors']} / {m['crc']}", m.get("rxPowerDbm"), m["health"]]
                                  for m, lm in zip(members, lg["members"])]}],
                links=[{"label": f"Port {m['id']}", "key": m["key"]} for m in members], raw=lg["raw"])
        else:
            p, o = nokia_port(self.node, pid, self.ports_raw.get(pid), self.lldp, self.lag_of.get(pid))
            self.objects[o["key"]] = o
        self.port_cache[pid] = p
        return p

    def interface_obj(self, itf, port_name):
        k = key("interface", self.node, itf["name"])
        if k not in self.objects:
            nb = itf["name"].split("-A7", 1)[1] if "-A7" in str(itf["name"]) else ""
            self.objects[k] = obj(
                "interface", self.node, itf["name"], f"Interface {itf['name']}", "Nokia router interface (Base)", itf["oper"],
                fields=[["State", itf["oper"]], ["Address", itf["ip"]], ["Port / LAG", port_name], ["Neighbour (from name)", nb],
                        ["MTU", itf["mtu"]], ["Protocols", itf["protocols"]], ["Last change", itf["lastChange"]],
                        ["if-index", itf["ifIndex"]]],
                tables=[{"title": "ARP", "columns": ["Neighbour IP", "MAC", "State"],
                         "rows": [[a["ip"], a["mac"], a["state"]] for a in itf["arp"]]}],
                links=[{"label": f"Port {port_name}", "key": key("lag" if str(port_name).startswith("lag-") else "port", self.node, port_name)}]
                if port_name else [], raw=itf["raw"])
        return k


def _lsp_transport(ctx, lsp_name, far_end, loopbacks):
    """LSP detail, the RSVP session out of this router, the egress interface and ports, and the hops."""
    l = ctx.lsps.get(lsp_name) or {}
    pr = l.get("primary") or {}
    s = ctx.rsvp.get(lsp_name) or {}
    issues = []
    lsp_key = key("lsp", ctx.node, lsp_name)

    itf = ctx.if_by_index.get(s.get("out-if-index")) if s else None
    port_name = ctx.if_ports.get(itf["name"], (None, None))[0] if itf else None
    phys = str(port_name).split(":")[0] if port_name else None
    port = ctx.port(phys) if phys else None
    nh_name = itf["name"].split("-A7", 1)[1] if itf and "-A7" in str(itf["name"]) else ""
    pce = PceIndex.load()
    if not nh_name and s.get("next-hop"):
        nh_name = pce.ip_name.get(s["next-hop"], "")
    path = {"role": "primary", "nextHop": s.get("next-hop"), "nextHopName": nh_name,
            "interface": itf["name"] if itf else None, "interfaceKey": ctx.interface_obj(itf, port_name) if itf else None,
            "interfaceIp": itf["ip"] if itf else None, "portName": port_name,
            "labels": [s["out-label"]] if s.get("out-label") else [], "port": port, "metric": l.get("oper-metric")}
    local_ips = {i["ip"] for i in ctx.rifs.values() if i.get("ip")}
    row = pce.ero(sorted(loopbacks), lsp_name, s.get("_path") or pr.get("path-name") or "Primary")
    names = dict(pce.ip_name)
    if s.get("next-hop") and nh_name:
        names[s["next-hop"]] = nh_name  # the far side of the egress link, named by the interface
    hops = hop_list(row["ero"], names, local_ips) if row else []

    oper = norm_state(l.get("oper-state")) if l else "unknown"
    if l and oper != "up":
        issues.append({"sev": "critical", "msg": f"LSP {lsp_name} is {oper} (fail code {pr.get('fail-code') or '?'}"
                                                 f"{', failed at ' + pr['fail-node-address'] if pr.get('fail-node-address') not in (None, '0.0.0.0') else ''})."})
    elif pr.get("path-state") and pr.get("path-state") != "active":
        issues.append({"sev": "warning", "msg": f"LSP {lsp_name}: primary path is {pr.get('path-state')}."})
    if s.get("local-protection-in-use"):
        issues.append({"sev": "warning", "msg": f"LSP {lsp_name} is running on its FRR bypass "
                                                f"(avoiding {get(s, 'bypass', 'avoid-node-address') or '?'})."})
    elif l.get("oper-fast-reroute") and s and not s.get("local-protection-available"):
        issues.append({"sev": "info", "msg": f"LSP {lsp_name}: FRR is configured but no bypass is available."})
    pi = port_issue(port, f"Egress towards {nh_name or s.get('next-hop')}:")
    if pi:
        issues.append({"sev": pi[0], "msg": pi[1]})

    if lsp_key not in ctx.objects:
        rs_key = key("rsvp", ctx.node, lsp_name) if s else None
        ctx.objects[lsp_key] = obj(
            "lsp", ctx.node, lsp_name, f"LSP {lsp_name}", "RSVP-TE LSP", oper,
            fields=[["State", oper], ["From", l.get("from-address")], ["To (SDP far end)", far_end],
                    ["Metric", l.get("oper-metric")], ["MTU", l.get("negotiated-mtu")],
                    ["Fast reroute", "yes" if l.get("oper-fast-reroute") else "no"],
                    ["Protection", (s.get("protection-type") or "") + (" · in use" if s.get("local-protection-in-use") else
                                                                     (" · available" if s.get("local-protection-available") else ""))],
                    ["Bypass avoids", get(s, "bypass", "avoid-node-address")],
                    ["Out label", s.get("out-label")], ["Next hop", f"{s.get('next-hop') or ''} {nh_name}".strip()],
                    ["Egress interface", itf["name"] if itf else None], ["Egress port / LAG", port_name],
                    ["Primary path", f"{pr.get('path-name') or ''} {pr.get('path-state') or ''} {pr.get('oper-state') or ''}".strip()],
                    ["Fail code", pr.get("fail-code")], ["Fail node", pr.get("fail-node-address")],
                    ["CSPF", pr.get("cspf")], ["Setup / hold priority", f"{pr.get('setup-priority')} / {pr.get('hold-priority')}" if pr else None],
                    ["Transitions", l.get("transitions")], ["Path changes", l.get("path-changes")],
                    ["Up for (s)", round(num(l.get("time-up")) / 100) if l.get("time-up") else None],
                    ["Last resignal", pr.get("last-resignal-attempt")], ["Tunnel id", l.get("tunnel-id")],
                    ["PCEP hops", row.get("hops") if row else None]],
            tables=[{"title": "Hop-by-hop path (PCEP explicit route)", "columns": ["#", "Hop address", "Router", "Note"],
                     "rows": [[i + 1, h["ip"], h["name"], "this router" if h["local"] else ""] for i, h in enumerate(hops)]}],
            links=[x for x in ([{"label": "RSVP session", "key": rs_key}] if rs_key else []) +
                   ([{"label": f"Interface {itf['name']}", "key": path['interfaceKey']}] if itf else []) +
                   ([{"label": f"{'LAG' if phys.startswith('lag-') else 'Port'} {phys}", "key": port['key']}] if port else [])],
            raw=l or None)
        if s:
            ctx.objects[rs_key] = obj("rsvp", ctx.node, lsp_name, f"RSVP session {s.get('session-name')}", "RSVP ingress session",
                                      norm_state(s.get("oper-state")),
                                      fields=[[k, v] for k, v in s.items() if not isinstance(v, (dict, list)) and not k.startswith("_")],
                                      links=[{"label": f"LSP {lsp_name}", "key": lsp_key}],
                                      raw={k: v for k, v in s.items() if not k.startswith("_")})
    return {"lsp": {"name": lsp_name, "key": lsp_key, "oper": oper, "metric": l.get("oper-metric"),
                    "frr": bool(l.get("oper-fast-reroute")), "protectionInUse": bool(s.get("local-protection-in-use")),
                    "pathState": pr.get("path-state"), "transitions": l.get("transitions"), "failCode": pr.get("fail-code")},
            "label": s.get("out-label"), "paths": [path] if s or itf else [], "hops": hops, "issues": issues,
            "hopSource": "PCEP export (pce-lsp-inventory.csv)" if hops else ""}


def pe_from_saved(node, data):
    """Build the PE view for one Nokia router. `data` maps query id -> saved data (may be partial)."""
    ctx = _Ctx(node, data)
    cfg = ctx.cfg
    loopbacks = {node}
    sys_ip = _system_address(ctx.rifs)
    if sys_ip:
        loopbacks.add(sys_ip)
    loopbacks.update(l.get("from-address") for l in ctx.lsps.values() if l.get("from-address"))
    loopbacks.discard(None)

    # SDPs: config gives far end, LSP and description; state gives oper and the far end in use.
    sdps = {}
    for c in as_list(cfg.get("sdp")):
        sdps[str(c.get("sdp-id"))] = {"farEnd": get(c, "far-end", "ip-address-ipv6-address"),
                                      "lsp": get(c, "lsp", "lsp-name"), "description": text(c.get("description")),
                                      "delivery": c.get("delivery-type"), "oper": None, "lspType": None, "cfg": c, "st": {}}
    for s in as_list(get(unwrap(data.get("sdp-state")), "state", "service", "sdp")):
        d = sdps.setdefault(str(s.get("sdp-id")), {"farEnd": None, "lsp": None, "description": "", "delivery": None, "cfg": {}})
        d["oper"] = s.get("sdp-oper-state")
        d["lspType"] = s.get("active-lsp-type")
        d["farEnd"] = d.get("farEnd") or s.get("oper-tunnel-far-end-inet-address")
        d["st"] = s
    for sid, d in sdps.items():
        d["transport"] = _sdp_transport(ctx, sid, d, loopbacks)

    state = {}
    for stype in SERVICE_TYPES:
        for s in _state_services(data.get(f"{stype}-state"), stype):
            state[(stype, str(s.get("oper-service-id")))] = s

    endpoints = []
    for stype in SERVICE_TYPES:
        cfg_list = as_list(cfg.get(stype))
        ids = [str(c.get("service-id")) for c in cfg_list]
        ids += [sid for (t, sid) in state if t == stype and sid not in ids]
        for sid in ids:
            c = next((x for x in cfg_list if str(x.get("service-id")) == sid), {})
            s = state.get((stype, sid), {})
            endpoints.append(_endpoint(ctx, stype, sid, c, s, sdps))

    name = text(get(unwrap(data.get("system")), "state", "system", "oper-name"))
    if not name and ctx.lsps:
        name = next(iter(ctx.lsps)).split("-")[0]
    pe_key = key("pe", node, node)
    ctx.objects[pe_key] = obj("pe", node, node, name or node, "Nokia SR OS PE", None,
                              fields=[["Node (ODL)", node], ["Name", name], ["Loopbacks", ", ".join(sorted(loopbacks))],
                                      ["Services", len(endpoints)], ["SDPs", len(sdps)], ["LSPs", len(ctx.lsps)],
                                      ["Saved queries", ", ".join(q for q in QUERIES if data.get(q) is not None)]],
                              tables=[{"title": "Router interfaces", "columns": ["Interface", "Address", "Port / LAG", "State"],
                                       "rows": [[link(i["name"], ctx.interface_obj(i, ctx.if_ports.get(i["name"], (None,))[0])),
                                                 i["ip"], ctx.if_ports.get(i["name"], (None,))[0], i["oper"]] for i in ctx.rifs.values()]}])
    return {"node": node, "vendor": "nokia", "name": name or node, "loopbacks": sorted(loopbacks),
            "endpoints": endpoints, "queries": sorted(q for q in QUERIES if data.get(q) is not None),
            "objects": ctx.objects, "key": pe_key}


def _sdp_transport(ctx, sid, sdp, loopbacks):
    t = {"type": sdp.get("lspType") or sdp.get("delivery") or "", "name": f"SDP {sid}" + (f" / LSP {sdp['lsp']}" if sdp.get("lsp") else ""),
         "sdpOper": norm_state(sdp.get("oper")), "lspOper": None, "description": sdp.get("description") or "",
         "sdpKey": key("sdp", ctx.node, sid), "lsp": None, "paths": [], "hops": [], "issues": [], "label": None}
    if sdp.get("lsp"):
        lt = _lsp_transport(ctx, sdp["lsp"], sdp.get("farEnd"), loopbacks)
        t.update({k: lt[k] for k in ("lsp", "paths", "hops", "issues", "label", "hopSource")})
        t["lspOper"] = lt["lsp"]["oper"] if sdp["lsp"] in ctx.lsps else None
    elif t["type"] == "ldp":
        t["note"] = "LDP transport: the per-hop path is not in the saved data."
    st, cfg = sdp.get("st") or {}, sdp.get("cfg") or {}
    ka = st.get("keep-alive") or {}
    req, resp = num(ka.get("hello-request-messages")), num(ka.get("hello-response-messages"))
    if req and (req - resp) / req > 0.0005:
        t["issues"].append({"sev": "info", "msg": f"SDP {sid} keep-alive: {req - resp:,} of {req:,} hellos unanswered."})
    ctx.objects[t["sdpKey"]] = obj(
        "sdp", ctx.node, sid, f"SDP {sid}", sdp.get("description") or "Nokia SDP", norm_state(sdp.get("oper")),
        fields=[["State", norm_state(sdp.get("oper"))], ["Far end", sdp.get("farEnd")], ["Delivery", sdp.get("delivery")],
                ["Active LSP type", sdp.get("lspType")], ["LSP", sdp.get("lsp")], ["Description", sdp.get("description")],
                ["Path MTU (oper)", st.get("sdp-oper-path-mtu")], ["Oper flags", st.get("sdp-oper-flags")],
                ["Keep-alive", f"{ka.get('oper-state') or ''} · {resp:,} of {req:,} hellos answered" if ka else None],
                ["Admin shutdown", cfg.get("shutdown")]],
        links=[{"label": f"LSP {sdp['lsp']}", "key": key("lsp", ctx.node, sdp["lsp"])}] if sdp.get("lsp") else [],
        raw={"config": cfg, "state": st})
    return t


def _endpoint(ctx, stype, sid, c, s, sdps):
    saps_cfg = {str(x.get("sap-id")): x for x in as_list(c.get("sap"))}
    saps_st = {str(x.get("sap-id")): x for x in as_list(s.get("sap"))}
    # VPRN SAPs sit under its interfaces.
    for itf in as_list(c.get("interface")):
        for x in as_list(itf.get("sap")):
            saps_cfg.setdefault(str(x.get("sap-id")), dict(x, _interface=itf.get("ip-int-name")))
    for itf in as_list(s.get("interface")):
        for x in as_list(itf.get("sap")):
            saps_st.setdefault(str(x.get("sap-id")), x)
    acs = []
    for sap_id in list(saps_cfg) + [k for k in saps_st if k not in saps_cfg]:
        cs, ss = saps_cfg.get(sap_id, {}), saps_st.get(sap_id, {})
        port = sap_id.split(":")[0]
        oper = ss.get("oper-state")
        if not oper and cs.get("shutdown"):
            oper = "admin-down"
        pinfo = ctx.port(port) if (port in ctx.ports_raw or port in ctx.lags) else None
        acs.append({"id": sap_id, "port": port, "vlan": sap_id.split(":", 1)[1] if ":" in sap_id else "",
                    "oper": norm_state(oper), "flags": ss.get("oper-flags") or "",
                    "adminShutdown": bool(cs.get("shutdown")), "portOper": norm_state(ctx.ports_raw.get(port, {}).get("oper-state")),
                    "description": text(cs.get("description")), "interface": cs.get("_interface"),
                    "ce": _ce_for(port, ctx.lldp), "portKey": pinfo["key"] if pinfo else None,
                    "portHealth": pinfo["health"] if pinfo else None, "portWhy": pinfo["why"] if pinfo else [],
                    "portIssue": port_issue(pinfo, "Access port") if pinfo else None})

    pws = []
    for kind in ("spoke-sdp", "mesh-sdp"):
        cb = {str(x.get("sdp-id-vc-id")): x for x in as_list(c.get(kind))}
        sb = {str(x.get("sdp-bind-id")): x for x in as_list(s.get(kind))}
        for bid in list(cb) + [k for k in sb if k not in cb]:
            cbx, sbx = cb.get(bid, {}), sb.get(bid, {})
            sdp_id, _, vc = bid.partition(":")
            sdp = sdps.get(sdp_id, {})
            auto = sbx.get("creation-origin") == "bgp-l2vpn"
            oper = sbx.get("oper-state") or ("admin-down" if cbx.get("shutdown") else None)
            tr = dict(sdp.get("transport") or {"type": "", "name": f"SDP {sdp_id}", "sdpOper": "unknown", "lspOper": None,
                                               "description": "", "paths": [], "hops": [], "issues": []})
            pws.append({"id": bid, "kind": "bgp-auto" if auto else kind.replace("-sdp", ""), "vcId": vc,
                        "sdpId": sdp_id, "peer": sdp.get("farEnd"), "oper": norm_state(oper),
                        "flags": sbx.get("oper-flags") or "", "localStatus": sbx.get("pw-local-status-bits") or "",
                        "peerStatus": sbx.get("pw-peer-status-bits") or "", "transport": tr})

    bgp = c.get("bgp") or {}
    rt = get(c, "vrf-target", "ext-community") or get(bgp, "route-target", "export")
    oper = s.get("oper-state") or ("admin-down" if c.get("shutdown") else None)
    svc_key = key("svc", ctx.node, f"{stype}:{sid}")
    name = text(c.get("name")) or text(s.get("service-name")) or sid
    ctx.objects[svc_key] = obj(
        "svc", ctx.node, f"{stype}:{sid}", f"{stype} {sid} · {name}", text(c.get("description")), norm_state(oper),
        fields=[["Type", stype], ["Service id", sid], ["Name", name], ["Customer", text(c.get("customer"))],
                ["State", norm_state(oper)], ["MTU", get(c, "service-mtu", "octets")], ["VPLS-ID", get(c, "bgp-ad", "vpls-id", "vpls-id")],
                ["Route target", rt], ["SAPs", len(acs)], ["SDP bindings", len(pws)]],
        tables=[{"title": "SAPs", "columns": ["SAP", "State", "Port", "Description", "CE (LLDP)"],
                 "rows": [[a["id"], a["oper"], link(a["port"], a["portKey"]), a["description"],
                           f"{a['ce']['name']} {a['ce']['port']}" if a["ce"] else ""] for a in acs]},
                {"title": "SDP bindings", "columns": ["Binding", "Kind", "State", "Far end", "SDP", "LSP"],
                 "rows": [[p["id"], p["kind"], p["oper"], p["peer"], link(f"SDP {p['sdpId']}", p["transport"].get("sdpKey")),
                           link(p["transport"]["lsp"]["name"], p["transport"]["lsp"]["key"]) if p["transport"].get("lsp") else ""]
                          for p in pws]}],
        raw={"config": c, "state": s})
    return {"key": f"{stype}:{sid}", "type": stype, "id": sid, "name": name, "objKey": svc_key,
            "description": text(c.get("description")), "customer": text(c.get("customer")),
            "oper": norm_state(oper), "adminShutdown": bool(c.get("shutdown")),
            "vplsId": get(c, "bgp-ad", "vpls-id", "vpls-id"), "routeTarget": rt,
            "rd": get(c, "route-distinguisher", "rd") or get(bgp, "route-distinguisher", "rd"),
            "acs": acs, "pws": pws}
