"""Nokia SR OS (classic config) saved data -> service endpoints.

Uses these nokia_view queries when they are saved (each one is optional):
  config-services          configure > service: services, SAPs, SDP bindings, SDP far ends, VPLS-ID
  epipe-state, vpls-state  oper state of services, SAPs and bindings
  sdp-state                SDP oper state and far end
  lldp, port-state         LLDP neighbours (the CE on each SAP port) and port state
  mpls-lsp-state           LSP oper state (transport of each SDP)
  router-interface-state   system interface address (this PE's loopback)
  system                   system name
"""
from .util import as_list, get, norm_state, text, unwrap

QUERIES = ["config-services", "epipe-state", "vpls-state", "sdp-state", "lldp", "port-state",
           "mpls-lsp-state", "router-interface-state", "system"]
# The smaller set fetched for a far-end PE: enough to find its side of each service and its CE.
FAR_END_QUERIES = ["config-services", "epipe-state", "vpls-state", "sdp-state", "lldp",
                   "router-interface-state", "system"]
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


def _port_states(data):
    return {str(p.get("port-id")): p.get("oper-state") for p in as_list(get(unwrap(data), "state", "port"))}


def _system_address(rif):
    for r in as_list(get(unwrap(rif), "state", "router")):
        if r.get("router-name") not in (None, "Base"):
            continue
        for itf in as_list(r.get("interface")):
            if itf.get("interface-name") == "system":
                return get(itf, "ipv4", "primary", "oper-address")
    return None


def _ce_for(port, lldp):
    nbrs = lldp.get(port) or []
    # The nearest-bridge neighbour is the directly attached device.
    best = next((n for n in nbrs if n["scope"] in ("nearest-bridge", "")), nbrs[0] if nbrs else None)
    return dict(best) if best else None


def pe_from_saved(node, data):
    """Build the PE view for one Nokia router. `data` maps query id -> saved data (may be partial)."""
    cfg = _service_tree(data.get("config-services"))
    lldp = lldp_neighbours(data.get("lldp")) or lldp_neighbours(data.get("port-state"))
    port_oper = _port_states(data.get("port-state"))
    lsps = {str(l.get("lsp-name")): l for l in as_list(get(unwrap(data.get("mpls-lsp-state")), "state", "router", "mpls", "lsp"))}

    # SDPs: config gives far end, LSP and description; state gives oper and the far end in use.
    sdps = {}
    for c in as_list(cfg.get("sdp")):
        sdps[str(c.get("sdp-id"))] = {"farEnd": get(c, "far-end", "ip-address-ipv6-address"),
                                      "lsp": get(c, "lsp", "lsp-name"), "description": text(c.get("description")),
                                      "delivery": c.get("delivery-type"), "oper": None, "lspType": None}
    for s in as_list(get(unwrap(data.get("sdp-state")), "state", "service", "sdp")):
        d = sdps.setdefault(str(s.get("sdp-id")), {"farEnd": None, "lsp": None, "description": "", "delivery": None})
        d["oper"] = s.get("sdp-oper-state")
        d["lspType"] = s.get("active-lsp-type")
        d["farEnd"] = d.get("farEnd") or s.get("oper-tunnel-far-end-inet-address")

    state = {}
    for stype in SERVICE_TYPES:
        for s in _state_services(data.get(f"{stype}-state"), stype):
            state[(stype, str(s.get("oper-service-id")))] = s

    endpoints = []
    seen = set()
    for stype in SERVICE_TYPES:
        cfg_list = as_list(cfg.get(stype))
        ids = [str(c.get("service-id")) for c in cfg_list]
        ids += [sid for (t, sid) in state if t == stype and sid not in ids]
        for sid in ids:
            c = next((x for x in cfg_list if str(x.get("service-id")) == sid), {})
            s = state.get((stype, sid), {})
            seen.add((stype, sid))
            endpoints.append(_endpoint(stype, sid, c, s, sdps, lsps, lldp, port_oper))

    name = text(get(unwrap(data.get("system")), "state", "system", "oper-name"))
    if not name and lsps:
        name = next(iter(lsps)).split("-")[0]
    loopbacks = {node}
    sys_ip = _system_address(data.get("router-interface-state"))
    if sys_ip:
        loopbacks.add(sys_ip)
    loopbacks.update(l.get("from-address") for l in lsps.values() if l.get("from-address"))
    return {"node": node, "vendor": "nokia", "name": name or node, "loopbacks": sorted(x for x in loopbacks if x),
            "endpoints": endpoints, "queries": sorted(q for q in QUERIES if data.get(q) is not None)}


def _endpoint(stype, sid, c, s, sdps, lsps, lldp, port_oper):
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
        acs.append({"id": sap_id, "port": port, "vlan": sap_id.split(":", 1)[1] if ":" in sap_id else "",
                    "oper": norm_state(oper), "flags": ss.get("oper-flags") or "",
                    "adminShutdown": bool(cs.get("shutdown")), "portOper": norm_state(port_oper.get(port)),
                    "description": text(cs.get("description")), "interface": cs.get("_interface"),
                    "ce": _ce_for(port, lldp)})

    pws = []
    for kind in ("spoke-sdp", "mesh-sdp"):
        cb = {str(x.get("sdp-id-vc-id")): x for x in as_list(c.get(kind))}
        sb = {str(x.get("sdp-bind-id")): x for x in as_list(s.get(kind))}
        for bid in list(cb) + [k for k in sb if k not in cb]:
            cbx, sbx = cb.get(bid, {}), sb.get(bid, {})
            sdp_id, _, vc = bid.partition(":")
            sdp = sdps.get(sdp_id, {})
            lsp = lsps.get(str(sdp.get("lsp"))) if sdp.get("lsp") else None
            auto = sbx.get("creation-origin") == "bgp-l2vpn"
            oper = sbx.get("oper-state") or ("admin-down" if cbx.get("shutdown") else None)
            pws.append({"id": bid, "kind": "bgp-auto" if auto else kind.replace("-sdp", ""), "vcId": vc,
                        "sdpId": sdp_id, "peer": sdp.get("farEnd"), "oper": norm_state(oper),
                        "flags": sbx.get("oper-flags") or "", "localStatus": sbx.get("pw-local-status-bits") or "",
                        "peerStatus": sbx.get("pw-peer-status-bits") or "",
                        "transport": {"type": sdp.get("lspType") or sdp.get("delivery") or "",
                                      "name": f"SDP {sdp_id}" + (f" / LSP {sdp['lsp']}" if sdp.get("lsp") else ""),
                                      "sdpOper": norm_state(sdp.get("oper")),
                                      "lspOper": norm_state(lsp.get("oper-state")) if lsp else None,
                                      "description": sdp.get("description") or ""}})

    bgp = c.get("bgp") or {}
    rt = get(c, "vrf-target", "ext-community") or get(bgp, "route-target", "export")
    oper = s.get("oper-state") or ("admin-down" if c.get("shutdown") else None)
    return {"key": f"{stype}:{sid}", "type": stype, "id": sid,
            "name": text(c.get("name")) or text(s.get("service-name")) or sid,
            "description": text(c.get("description")), "customer": text(c.get("customer")),
            "oper": norm_state(oper), "adminShutdown": bool(c.get("shutdown")),
            "vplsId": get(c, "bgp-ad", "vpls-id", "vpls-id"), "routeTarget": rt,
            "rd": get(c, "route-distinguisher", "rd") or get(bgp, "route-distinguisher", "rd"),
            "acs": acs, "pws": pws}
