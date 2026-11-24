"""Named NETCONF queries and request handling, shared by the live server and the offline generator."""
import datetime as dt
import re

STATE_NS = "urn:nokia.com:sros:ns:yang:sr:state"
CONF_NS = "urn:alcatel-lucent.com:sros:ns:yang:conf-r13"

QUERIES = {
    "epipe-state": {"label": "Epipe services (state)", "kind": "state",
                    "filter": f'<state xmlns="{STATE_NS}"><service><epipe/></service></state>'},
    "vpls-state": {"label": "VPLS services (state)", "kind": "state",
                   "filter": f'<state xmlns="{STATE_NS}"><service><vpls/></service></state>'},
    "vpls-fdb-counts": {"label": "VPLS FDB counts (state)", "kind": "state",
                        "filter": f'<state xmlns="{STATE_NS}"><service><vpls><fdb/></vpls></service></state>'},
    "sdp-state": {"label": "SDP state (state)", "kind": "state",
                  "filter": f'<state xmlns="{STATE_NS}"><service><sdp/></service></state>'},
    "port-state": {"label": "Port state (state)", "kind": "state",
                   "filter": f'<state xmlns="{STATE_NS}"><port/></state>'},
    "router-interface-state": {"label": "Router interfaces (state)", "kind": "state",
                               "filter": f'<state xmlns="{STATE_NS}"><router><interface/></router></state>'},
    "mpls-lsp-state": {"label": "MPLS LSPs (state)", "kind": "state",
                       "filter": f'<state xmlns="{STATE_NS}"><router><mpls><lsp/></mpls></router></state>'},
    # Device info and troubleshooting (state namespace)
    "chassis": {"label": "Chassis: serial, part, fans, power", "kind": "state",
                "filter": f'<state xmlns="{STATE_NS}"><chassis/></state>'},
    "cards": {"label": "Cards and MDAs: state, temperature, boot", "kind": "state",
              "filter": f'<state xmlns="{STATE_NS}"><card/></state>'},
    "redundancy": {"label": "Redundancy: standby CPM and sync", "kind": "state",
                   "filter": f'<state xmlns="{STATE_NS}"><redundancy/></state>'},
    "system": {"label": "System information", "kind": "state",
               "filter": f'<state xmlns="{STATE_NS}"><system/></state>'},
    "event-log": {"label": "Event log counters", "kind": "state",
                  "filter": f'<state xmlns="{STATE_NS}"><log/></state>'},
    "lag": {"label": "LAG state", "kind": "state",
            "filter": f'<state xmlns="{STATE_NS}"><lag/></state>'},
    "bgp": {"label": "BGP (state)", "kind": "state",
            "filter": f'<state xmlns="{STATE_NS}"><router><bgp/></router></state>'},
    "ospf": {"label": "OSPF (state)", "kind": "state",
             "filter": f'<state xmlns="{STATE_NS}"><router><ospf/></router></state>'},
    "isis": {"label": "IS-IS (state)", "kind": "state",
             "filter": f'<state xmlns="{STATE_NS}"><router><isis/></router></state>'},
    "ldp": {"label": "LDP (state)", "kind": "state",
            "filter": f'<state xmlns="{STATE_NS}"><router><ldp/></router></state>'},
    "rsvp": {"label": "RSVP (state)", "kind": "state",
             "filter": f'<state xmlns="{STATE_NS}"><router><rsvp/></router></state>'},
    "bfd": {"label": "BFD (state)", "kind": "state",
            "filter": f'<state xmlns="{STATE_NS}"><bfd/></state>'},
    "vrrp": {"label": "VRRP (state)", "kind": "state",
             "filter": f'<state xmlns="{STATE_NS}"><vrrp/></state>'},
    "lldp": {"label": "LLDP neighbours (state)", "kind": "state",
             "filter": f'<state xmlns="{STATE_NS}"><port><ethernet><lldp/></ethernet></port></state>'},
    "config-services": {"label": "All services (config, classic model)", "kind": "config",
                        "filter": f'<configure xmlns="{CONF_NS}"><service/></configure>'},
    "config-router-config": {"label": "Router config, all interfaces (classic model)", "kind": "config",
                             "filter": f'<configure xmlns="{CONF_NS}"><router/></configure>'},
    "cli-fdb-all": {"label": "FDB, all services (CLI: service fdb-mac)", "kind": "cli",
                    "command": "service fdb-mac"},
    "cli-lldp-neighbor": {"label": "LLDP neighbours (CLI: system lldp neighbor)", "kind": "cli",
                          "command": "system lldp neighbor"},
}

NODE_RE = re.compile(r"^[0-9A-Za-z._:-]{1,64}$")
# Free-text CLI is limited to read-only show-style commands on a few top-level areas.
CLI_RE = re.compile(r"^(service|port|router|system|log|card|chassis)(\s[A-Za-z0-9_.:/*\-\s]{0,100})?$")


def catalog():
    return [{"id": k, "label": v["label"], "kind": v["kind"]} for k, v in QUERIES.items()]


def validate_node(node):
    node = str(node or "").strip()
    if not NODE_RE.match(node):
        raise ValueError(f"invalid node id: {node!r}")
    return node


def validate_cli(command):
    command = " ".join(str(command or "").split())
    if not CLI_RE.match(command):
        raise ValueError("CLI command not allowed. Use a show-style command that starts with "
                         "service, port, router, system, log, card or chassis.")
    return command


def run_request(client, req):
    """Run one query or CLI command and return a result dict. Raises ValueError or OdlError."""
    node = validate_node(req.get("node"))
    if req.get("cli"):
        command = validate_cli(req["cli"])
        data = client.cli_show(node, command)
        qid, label = None, f"CLI: {command}"
    else:
        qid = req.get("query")
        if qid not in QUERIES:
            raise ValueError(f"unknown query: {qid!r}")
        q = QUERIES[qid]
        label = q["label"]
        if q["kind"] == "cli":
            data = client.cli_show(node, q["command"])
        else:
            data = client.netconf_get(node, q["kind"], q["filter"])
    return {"node": node, "query": qid, "label": label,
            "fetchedAt": dt.datetime.now().isoformat(timespec="seconds"), "data": data}
