"""Derive findings (critical, warning and info items) from any NETCONF response.

The rules are generic: they look at every object in the response, so they apply to any
query. Each finding names the object (from its id fields, e.g. "slot-number=3"), the
field, the value and a plain-language message.

Rules:
  - operational state down/failed in state fields (oper-state, sdp-oper-state, ...)
    * if the saved service config shows the service, SAP or spoke-SDP as admin shutdown,
      the finding is info ("expected"), not a warning
  - alarm-state other than alarm-cleared
  - non-empty failure-reason
  - temperature at or above the threshold (critical), or within 10 C of it (warning)
  - configuration never synced to the standby CPM

Pass the config response (data from a saved "config-services" run) as `config` to
check admin shutdowns. Without it, the findings say the check was not done.
"""

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}

ID_KEYS = ("slot-number", "mda-slot", "fan-slot", "power-supply-id", "sap-id", "sdp-id",
           "sdp-bind-id", "sdp-id-vc-id", "service-name", "oper-service-id", "service-id",
           "interface-name", "lsp-name", "router-name", "port-id", "name")

STATE_KEYS = ("oper-state", "oper-status", "sdp-oper-state", "if-oper-status", "state",
              "ac-status", "dc-status", "input-status", "output-status",
              "first-power-supply-status", "second-power-supply-status", "temp-status")

BAD_STATES = {
    "down": "warning", "lower-layer-down": "warning", "inactive": "warning", "notconnected": "warning",
    "failed": "critical", "fail": "critical", "outofservice": "critical", "out-of-service": "critical",
}


def _as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _find_service_tree(node):
    """The configure > service subtree: the first dict that holds epipe, vpls or vprn."""
    if isinstance(node, dict):
        if any(k in node for k in ("epipe", "vpls", "vprn")):
            return node
        for v in node.values():
            found = _find_service_tree(v)
            if found is not None:
                return found
    elif isinstance(node, list):
        for v in node:
            found = _find_service_tree(v)
            if found is not None:
                return found
    return None


def config_maps(config_data):
    """Admin-shutdown flags from the service config: services, SAPs and spoke/mesh SDP binds."""
    tree = _find_service_tree(config_data)
    maps = {"svc": {}, "sap": {}, "bind": {}}
    if tree is None:
        return maps
    for stype in ("epipe", "vpls", "vprn"):
        for svc in _as_list(tree.get(stype)):
            sid = str(svc.get("service-id"))
            maps["svc"][sid] = bool(svc.get("shutdown"))
            for sap in _as_list(svc.get("sap")):
                maps["sap"][(sid, str(sap.get("sap-id")))] = bool(sap.get("shutdown"))
            for kind in ("spoke-sdp", "mesh-sdp"):
                for b in _as_list(svc.get(kind)):
                    maps["bind"][(sid, str(b.get("sdp-id-vc-id")))] = bool(b.get("shutdown"))
    return maps


def _own_id(node):
    """Up to two id fields from this object, e.g. 'slot-number=3'."""
    parts = []
    for k in ID_KEYS:
        v = node.get(k)
        if v in (None, "") or isinstance(v, (dict, list)):
            continue
        parts.append(f"{k}={v}")
        if len(parts) == 2:
            break
    return ", ".join(parts)


def _admin_down(node, svc, maps):
    """True if the config says admin shutdown, False if enabled, None if unknown."""
    if maps is None:
        return None
    if svc is not None and maps["svc"].get(svc) is True:
        return True  # the whole service is admin shutdown, so its SAPs and binds are down for that reason
    if "sap-id" in node and svc is not None:
        return maps["sap"].get((svc, str(node["sap-id"])))
    if "sdp-bind-id" in node and svc is not None:
        return maps["bind"].get((svc, str(node["sdp-bind-id"])))
    if "oper-service-id" in node:
        return maps["svc"].get(str(node["oper-service-id"]))
    return None


def _explain_down(node, key, value):
    """Plain-language reason for a down state, plus a root-cause key where one is known."""
    msg, cause = f"{key} is {value}", ""
    flags = str(node.get("oper-flags") or "")
    if "sap-id" in node and "port-oper-down" in flags:
        port = str(node["sap-id"]).split(":")[0]
        msg += f": port {port} is down"
        cause = f"port {port} down"
    elif key == "oper-state" and node.get("sap-count") == 0:
        msg += ": no SAP is up on this service"
    spoke = node.get("spoke-sdp")
    if isinstance(spoke, dict) and "lac-ingress-fault" in str(spoke.get("pw-peer-status-bits") or ""):
        msg += " (far end reports an attachment-circuit fault)"
    return msg, cause


def _check(node, ident, path, svc, maps, out):
    def add(sev, field, value, msg, cause=""):
        out.append({"severity": sev, "object": ident or path, "field": field,
                    "value": value, "message": msg, "path": path, "cause": cause})

    for k in STATE_KEYS:
        v = node.get(k)
        if isinstance(v, str) and v.lower() in BAD_STATES:
            if _admin_down(node, svc, maps) is True:
                add("info", k, v, f"{k} is {v}, but the config has it as admin shutdown (expected)")
            else:
                msg, cause = _explain_down(node, k, v)
                add(BAD_STATES[v.lower()], k, v, msg, cause)

    alarm = node.get("alarm-state")
    if isinstance(alarm, str) and alarm not in ("", "alarm-cleared"):
        add("warning", "alarm-state", alarm, f"alarm-state is {alarm}")

    reason = node.get("failure-reason")
    if isinstance(reason, str) and reason.strip():
        add("warning", "failure-reason", reason, f"failure reason: {reason}")

    temp, limit = node.get("temperature"), node.get("temperature-threshold")
    if isinstance(temp, (int, float)) and isinstance(limit, (int, float)) and limit > 0:
        if temp >= limit:
            add("critical", "temperature", temp, f"temperature {temp} C is at or above the {limit} C threshold")
        elif temp >= limit - 10:
            add("warning", "temperature", temp, f"temperature {temp} C is within 10 C of the {limit} C threshold")

    if node.get("config-file-sync-time") == "never" and "standby-status" in node:
        add("warning", "config-file-sync-time", "never",
            "the standby CPM has never received the configuration file")


def _walk(node, path, ident, svc, maps, out):
    if isinstance(node, dict):
        own = _own_id(node)
        here = f"{ident} / {own}" if ident and own else (own or ident)
        if "oper-service-id" in node:
            svc = str(node["oper-service-id"])
        _check(node, here, path, svc, maps, out)
        for k, v in node.items():
            _walk(v, f"{path}.{k}" if path else k, here, svc, maps, out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk(v, f"{path}[{i}]", ident, svc, maps, out)


def analyze(data, config=None):
    """Return findings for a response's data, most severe first, duplicates removed."""
    maps = config_maps(config) if config is not None else None
    raw = []
    _walk(data, "", "", None, maps, raw)

    if config is None and any(f["field"] in STATE_KEYS and f["severity"] != "info" for f in raw):
        raw.append({"severity": "info", "object": "admin shutdown", "field": "config", "value": "",
                    "path": "", "cause": "", "message":"admin shutdown not checked: no service config saved for this node. "
                                           "Run the 'All services (config)' query to enable the check."})

    seen, findings = set(), []
    for f in raw:
        key = (f["severity"], f["object"], f["field"], str(f["value"]))
        if key in seen:
            continue
        seen.add(key)
        findings.append(f)
    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), f["object"]))
    return findings


def summary(findings):
    counts = {"critical": 0, "warning": 0, "info": 0}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return counts
