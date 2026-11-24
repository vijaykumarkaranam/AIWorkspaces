r"""Troubleshoot one service from saved NETCONF data. No live ODL connection needed.

It reads the newest saved runs for the node from the store (epipe-state, vpls-state,
sdp-state, port-state, config-services), finds the service, and explains why it is up
or down, with the next check to run.

Usage:
  python troubleshoot.py --node 162.104.38.226 --service 32396

The report is printed and saved to exports\<node>\troubleshoot_<service>_<time>.txt
"""
import argparse
import datetime as dt
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import store  # noqa: E402
from analyze import _as_list, _find_service_tree  # noqa: E402

TYPE_RE = re.compile(r"\.(epipe|vpls|vprn)\[")


def walk(obj, path, pred, out):
    """Collect (path, dict) for every dict that matches pred."""
    if isinstance(obj, dict):
        if pred(obj):
            out.append((path, obj))
        for k, v in obj.items():
            walk(v, f"{path}.{k}" if path else k, pred, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            walk(v, f"{path}[{i}]", pred, out)
    return out


def find(data, pred):
    hits = []
    if data:
        walk(data, "", pred, hits)
    return hits


def state_service(sid, *datasets):
    for data in datasets:
        hits = find(data, lambda d: str(d.get("oper-service-id")) == str(sid))
        if hits:
            path, svc = hits[0]
            m = TYPE_RE.search(path)
            return (m.group(1) if m else "?"), svc
    return None, None


def config_service(cfg, sid):
    tree = _find_service_tree(cfg) if cfg else None
    if not tree:
        return None, None, None
    customers = {str(c.get("customer-id")): c for c in _as_list(tree.get("customer"))}
    for stype in ("epipe", "vpls", "vprn"):
        for s in _as_list(tree.get(stype)):
            if str(s.get("service-id")) == str(sid):
                return stype, s, customers
    return None, None, customers


def latest_config(node):
    """Newest saved config-services run that really holds a configure section (skips state-only saves)."""
    for rel in store.history(node):
        if rel.endswith("_config-services.json"):
            data = store.load(rel).get("data")
            if data and find(data, lambda d: "configure" in d):
                return data
    return None


def text(x):
    """Readable value from a NETCONF field that may be a dict wrapper."""
    if isinstance(x, dict):
        for v in x.values():
            if isinstance(v, (str, int)):
                return str(v)
        return ""
    return "" if x is None else str(x)


def port_state(data, port):
    hits = find(data, lambda d: str(d.get("port-id")) == port)
    return hits[0][1] if hits else None


def sdp_state(data, sdp):
    hits = find(data, lambda d: str(d.get("sdp-id")) == str(sdp))
    return hits[0][1] if hits else None


def main():
    ap = argparse.ArgumentParser(description="Troubleshoot one service from saved data")
    ap.add_argument("--node", required=True)
    ap.add_argument("--service", required=True, help="service ID, e.g. 32396")
    a = ap.parse_args()
    sid = str(a.service)

    epipe = store.latest_data(a.node, "epipe-state")
    vpls = store.latest_data(a.node, "vpls-state")
    sdp = store.latest_data(a.node, "sdp-state")
    ports = store.latest_data(a.node, "port-state")
    cfg = latest_config(a.node)

    out = []
    say = out.append
    say(f"Service {sid} on {a.node}")
    say(f"Saved data used: epipe-state={'yes' if epipe else 'NO'}, vpls-state={'yes' if vpls else 'NO'}, "
        f"sdp-state={'yes' if sdp else 'NO'}, port-state={'yes' if ports else 'NO'}, "
        f"config={'yes' if cfg else 'NO'}")
    say("")

    stype, st = state_service(sid, epipe, vpls)
    ctype, cf, customers = config_service(cfg, sid)
    if st is None and cf is None:
        say("Not found in the saved state or config. Run the service queries for this node first.")
        return finish(a, sid, out)

    stype = stype or ctype
    name = text(st.get("service-name") if st else None) or text(cf.get("name") if cf else None)
    say(f"Type: {stype}    Name: {name}")
    if cf:
        cid = text(cf.get("customer"))
        c = (customers or {}).get(cid, {})
        cdesc = text(c.get("description")) or "(no description)"
        contact = text(c.get("contact") or "")
        say(f"Customer: {cid} - {cdesc}" + (f" - contact: {contact}" if contact else ""))
        desc = text(cf.get("description"))
        if desc:
            say(f"Description: {desc}")
    say(f"Oper state: {st.get('oper-state') if st else 'not in saved state'}"
        f"    Config admin shutdown: {bool(cf.get('shutdown')) if cf else 'not in saved config'}")
    say("")

    findings = []
    if cf and cf.get("shutdown"):
        findings.append(("INFO", "The service is admin shutdown in the config. Check whether that is intended."))
    if st is None:
        findings.append(("WARNING", "The service is in the config but not in the saved state. "
                                    "Re-run the Epipe or VPLS state query."))
    elif st.get("oper-state") == "up":
        findings.append(("OK", "The service is up on this node."))
    else:
        findings.extend(diagnose(st, cf, ports, sdp, say))

    say("SAPs (access side)")
    saps = _as_list(st.get("sap")) if st else []
    cfg_saps = {str(x.get("sap-id")): x for x in _as_list(cf.get("sap"))} if cf else {}
    if not saps:
        say("  none in state" + (" (none in config either)" if not cfg_saps else " (configured but not up)"))
    for sap in saps:
        sid_sap = str(sap.get("sap-id"))
        cs = cfg_saps.get(sid_sap, {})
        say(f"  {sid_sap}: oper {sap.get('oper-state')}  flags '{sap.get('oper-flags') or ''}'"
            f"  admin shutdown {bool(cs.get('shutdown')) if cs else 'n/a'}")
    say("")

    say("Spoke and mesh SDP bindings (network side)")
    binds = _as_list(st.get("spoke-sdp")) + _as_list(st.get("mesh-sdp")) if st else []
    if not binds:
        say("  none in state")
    for b in binds:
        bind = str(b.get("sdp-bind-id") or "")
        sdp_id = bind.split(":")[0]
        s_state = sdp_state(sdp, sdp_id)
        s_oper = s_state.get("sdp-oper-state", "?") if s_state else "not in saved SDP state"
        say(f"  bind {bind}: oper {b.get('oper-state')}  local '{b.get('pw-local-status-bits') or ''}'"
            f"  peer '{b.get('pw-peer-status-bits') or ''}'  SDP {sdp_id} oper {s_oper}")
    say("")

    say("Findings")
    if not findings:
        say("  nothing to report")
    for level, msg in findings:
        say(f"  [{level}] {msg}")

    return finish(a, sid, out)


def diagnose(st, cf, ports, sdp, say):
    """Reasons a down service is down, most likely first."""
    found = []
    saps = _as_list(st.get("sap"))
    binds = _as_list(st.get("spoke-sdp")) + _as_list(st.get("mesh-sdp"))
    if not saps:
        found.append(("CRITICAL", "No SAP is up on this service. The access circuit is missing or down."
                                  " Check the SAP in the config and the port it uses."))
    for sap in saps:
        if sap.get("oper-state") == "up":
            continue
        port = str(sap.get("sap-id")).split(":")[0]
        if "port-oper-down" in str(sap.get("oper-flags") or ""):
            p = port_state(ports, port)
            pstate = p.get("oper-state") if p else "not in saved port state"
            found.append(("CRITICAL", f"SAP {sap.get('sap-id')} is down because port {port} is down "
                                      f"(port state: {pstate}). Check the cable, optic and port on the router."))
        else:
            found.append(("CRITICAL", f"SAP {sap.get('sap-id')} is down, flags '{sap.get('oper-flags') or 'none'}'."
                                      " Check the SAP config, VLAN and QoS."))
    for b in binds:
        local = str(b.get("pw-local-status-bits") or "")
        peer = str(b.get("pw-peer-status-bits") or "")
        if "lac-ingress-fault" in peer or "lac-egress-fault" in peer:
            found.append(("WARNING", f"Bind {b.get('sdp-bind-id')}: the far end reports an attachment-circuit fault "
                                     f"('{peer}'). Check the far-end SAP or port."))
        if b.get("oper-state") != "up":
            found.append(("CRITICAL", f"Bind {b.get('sdp-bind-id')} is {b.get('oper-state')}. Check the SDP and its LSP."))
        if local:
            found.append(("INFO", f"Bind {b.get('sdp-bind-id')} local status bits: '{local}'."))
    return found


def finish(a, sid, out):
    text_out = "\n".join(out)
    print(text_out)
    folder = os.path.join(HERE, "exports", store._safe(a.node))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"troubleshoot_{store._safe(sid)}_{dt.datetime.now():%Y%m%d-%H%M%S}.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text_out + "\n")
    print(f"\nSaved: {path}")


if __name__ == "__main__":
    main()
