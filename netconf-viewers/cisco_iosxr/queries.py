"""Cisco IOS-XR NETCONF queries through ODL (first candidates).

Every entry is a CANDIDATE: which ones return data depends on the models the device
really serves. Run run_queries.py --capabilities first, then run the queries and read the
errors. A "unknown-element" or "unknown-namespace" error means that model or path is not
available on the device.

kind:
  "get"    operational data (ietf-netconf:get)
  "config" running configuration (ietf-netconf:get-config, running datastore)

Namespaces:
  OpenConfig (openconfig.net) is standard and is the first thing to try.
  Cisco native (cisco.com) models are IOS-XR specific. The container names below are
  guesses; verify them against the device before relying on them.
"""

import time

OC = {
    "interfaces": "http://openconfig.net/yang/interfaces",
    "platform": "http://openconfig.net/yang/platform",
    "system": "http://openconfig.net/yang/system",
    "lldp": "http://openconfig.net/yang/lldp",
    "netinst": "http://openconfig.net/yang/network-instance",
}

CISCO = {
    "ifmgr": "http://cisco.com/ns/yang/Cisco-IOS-XR-ifmgr-oper",
    "bgp": "http://cisco.com/ns/yang/Cisco-IOS-XR-ipv4-bgp-oper",
    "ospf": "http://cisco.com/ns/yang/Cisco-IOS-XR-ipv4-ospf-oper",
    "ldp": "http://cisco.com/ns/yang/Cisco-IOS-XR-mpls-ldp-oper",
    "isis": "http://cisco.com/ns/yang/Cisco-IOS-XR-clns-isis-oper",
    "bfd": "http://cisco.com/ns/yang/Cisco-IOS-XR-ip-bfd-oper",
    "ifcfg": "http://cisco.com/ns/yang/Cisco-IOS-XR-ifmgr-cfg",
    "bgpcfg": "http://cisco.com/ns/yang/Cisco-IOS-XR-ipv4-bgp-cfg",
    "ospfcfg": "http://cisco.com/ns/yang/Cisco-IOS-XR-ipv4-ospf-cfg",
    "ldpcfg": "http://cisco.com/ns/yang/Cisco-IOS-XR-mpls-ldp-cfg",
    "pfiim": "http://cisco.com/ns/yang/Cisco-IOS-XR-pfi-im-cmd-oper",
    "inv": "http://cisco.com/ns/yang/Cisco-IOS-XR-platform-inventory-oper",
    "shutil": "http://cisco.com/ns/yang/Cisco-IOS-XR-shellutil-oper",
    "ntp": "http://cisco.com/ns/yang/Cisco-IOS-XR-ip-ntp-oper",
    "lldpnative": "http://cisco.com/ns/yang/Cisco-IOS-XR-ethernet-lldp-oper",
}

QUERIES = {
    # ---- OpenConfig, operational
    "oc-interfaces": {"label": "Interfaces (OpenConfig state)", "kind": "get",
                      "filter": f'<interfaces xmlns="{OC["interfaces"]}"/>'},
    "oc-platform": {"label": "Platform components: chassis, cards, PSUs, fans (OpenConfig)", "kind": "get",
                    "filter": f'<components xmlns="{OC["platform"]}"/>'},
    "oc-system": {"label": "System: hostname, version, NTP, AAA (OpenConfig)", "kind": "get",
                  "filter": f'<system xmlns="{OC["system"]}"/>'},
    "oc-lldp": {"label": "LLDP neighbours (OpenConfig)", "kind": "get",
                "filter": f'<lldp xmlns="{OC["lldp"]}"/>'},
    "oc-network-instances": {"label": "Network instances: BGP, OSPF, IS-IS, LDP protocol state (OpenConfig)",
                             "kind": "get", "filter": f'<network-instances xmlns="{OC["netinst"]}"/>'},

    # ---- OpenConfig, configuration (what is configured)
    "oc-config-interfaces": {"label": "Interfaces configuration (OpenConfig)", "kind": "config",
                             "filter": f'<interfaces xmlns="{OC["interfaces"]}"/>'},
    "oc-config-network-instances": {"label": "Network instance configuration: protocols (OpenConfig)",
                                    "kind": "config", "filter": f'<network-instances xmlns="{OC["netinst"]}"/>'},
    "oc-config-system": {"label": "System configuration (OpenConfig)", "kind": "config",
                         "filter": f'<system xmlns="{OC["system"]}"/>'},

    # ---- Cisco native, operational (candidates, verify the names)
    "cisco-interfaces": {"label": "Interface properties (Cisco native, candidate)", "kind": "get",
                         "filter": f'<interface-properties xmlns="{CISCO["ifmgr"]}"/>'},
    "cisco-bgp": {"label": "BGP operational data (Cisco native, candidate)", "kind": "get",
                  "filter": f'<bgp xmlns="{CISCO["bgp"]}"/>'},
    "cisco-ospf": {"label": "OSPF operational data (Cisco native, candidate)", "kind": "get",
                   "filter": f'<ospf xmlns="{CISCO["ospf"]}"/>'},
    "cisco-ldp": {"label": "LDP operational data (Cisco native, candidate)", "kind": "get",
                  "filter": f'<ldp xmlns="{CISCO["ldp"]}"/>'},
    "cisco-isis": {"label": "IS-IS operational data (Cisco native, candidate)", "kind": "get",
                   "filter": f'<isis xmlns="{CISCO["isis"]}"/>'},
    "cisco-bfd": {"label": "BFD operational data (Cisco native, candidate)", "kind": "get",
                  "filter": f'<bfd xmlns="{CISCO["bfd"]}"/>'},

    # ---- Cisco native, configuration (candidates, the model is advertised by the device)
    "cisco-interfaces-config": {"label": "Interface configuration (Cisco native, candidate)", "kind": "config",
                                "filter": f'<interface-configurations xmlns="{CISCO["ifcfg"]}"/>'},
    "cisco-bgp-config": {"label": "BGP configuration (Cisco native, candidate)", "kind": "config",
                         "filter": f'<bgp xmlns="{CISCO["bgpcfg"]}"/>'},
    "cisco-ospf-config": {"label": "OSPF configuration (Cisco native, candidate)", "kind": "config",
                          "filter": f'<ospf xmlns="{CISCO["ospfcfg"]}"/>'},
    "cisco-ldp-config": {"label": "LDP configuration (Cisco native, candidate)", "kind": "config",
                         "filter": f'<ldp xmlns="{CISCO["ldpcfg"]}"/>'},

    # ---- Cisco native, device info (candidates taken from the device capability list)
    "cisco-interfaces-xr": {"label": "Interfaces, state and counters (Cisco native, worked in the RESTCONF test)", "kind": "get",
                            "filter": f'<interfaces xmlns="{CISCO["pfiim"]}"><interface-xr/></interfaces>'},
    "cisco-platform-inventory": {"label": "Chassis, cards and inventory (Cisco native, candidate)", "kind": "get",
                                 "filter": f'<platform-inventory xmlns="{CISCO["inv"]}"/>'},
    "cisco-system-time": {"label": "System time and uptime (Cisco native, candidate)", "kind": "get",
                          "filter": f'<system-time xmlns="{CISCO["shutil"]}"/>'},
    "cisco-ntp": {"label": "NTP status (Cisco native, candidate)", "kind": "get",
                  "filter": f'<ntp xmlns="{CISCO["ntp"]}"/>'},
    "cisco-lldp-native": {"label": "LLDP neighbours (Cisco native, candidate)", "kind": "get",
                          "filter": f'<lldp xmlns="{CISCO["lldpnative"]}"/>'},
}

# Node location keys differ by platform: NCS-540/5500 use 0/RP0/CPU0 (and some containers 0/0/CPU0),
# ASR 9000 uses 0/RSP0/CPU0. Paths that need one are tried with each location in this order.
LOCATIONS = ["0%2FRP0%2FCPU0", "0%2F0%2FCPU0", "0%2FRSP0%2FCPU0"]


def at_locations(template):
    """The same path for every node location: template contains {loc}."""
    return [template.format(loc=loc) for loc in LOCATIONS]


# Queries verified by hand as RESTCONF GETs on the mount path (module:container).
# run_queries.py uses these instead of the RPC filter when a query id is listed here.
# A value may be a list of alternative paths: they are tried in order (see fetch below).
DATA_PATHS = {
    "cisco-interfaces-xr": "Cisco-IOS-XR-pfi-im-cmd-oper:interfaces/interface-xr",
    "cisco-platform-inventory": "Cisco-IOS-XR-platform-inventory-oper:platform-inventory/racks",
    "cisco-system-time": "Cisco-IOS-XR-shellutil-oper:system-time",
    "cisco-ntp": "Cisco-IOS-XR-ip-ntp-oper:ntp",
    # The whole LLDP container (has this router's name); the nodes list alone is the form the E2E dashboard uses.
    "cisco-lldp-native": ["Cisco-IOS-XR-ethernet-lldp-oper:lldp",
                          "Cisco-IOS-XR-ethernet-lldp-oper:lldp/nodes?content=nonconfig"],

    # ---- Working paths from manual tests (GET on the mount path)
    "cisco-ospf-summary": "Cisco-IOS-XR-ipv4-ospf-oper:ospf/processes/process=BSPD/default-vrf/ospf-summary",
    "cisco-ospf-sr": "Cisco-IOS-XR-ipv4-ospf-oper:ospf/processes/process=BSPD/default-vrf/segment-routing",
    "cisco-ospf-routes": "Cisco-IOS-XR-ipv4-ospf-oper:ospf/processes/process=BSPD/default-vrf/route-information/route-table",
    "cisco-ospf-neighbors": "Cisco-IOS-XR-ipv4-ospf-oper:ospf/processes/process=BSPD/default-vrf/adjacency-information/neighbors",
    "cisco-ospf-config": "Cisco-IOS-XR-ipv4-ospf-cfg:ospf?content=config",
    "cisco-bgp-neighbors": "Cisco-IOS-XR-ipv4-bgp-oper:bgp/instances/instance=default/instance-active/default-vrf/neighbors?content=nonconfig",
    "cisco-ldp": "Cisco-IOS-XR-mpls-ldp-oper:mpls-ldp",
    "cisco-bfd": "Cisco-IOS-XR-ip-bfd-oper:bfd",
    # Only the L2FIB summary: the whole node (every MAC, cross-connect and counter) times out in ODL on large
    # routers. Cross-connects and bridge ports come from e2e-l2fibx-cons and e2e-bridge-ports.
    "cisco-l2vpn": at_locations("Cisco-IOS-XR-l2vpn-oper:l2vpn-forwarding/nodes/node={loc}/l2fib-summary?content=nonconfig"),
    "cisco-sr-config": "Cisco-IOS-XR-um-segment-routing-cfg:segment-routing",

    # ---- Batch 2: device health, control plane, services (candidates, verified by the run)
    "cisco-cpu": "Cisco-IOS-XR-wdsysmon-fd-oper:system-monitoring?content=nonconfig",
    "cisco-memory": "Cisco-IOS-XR-nto-misc-oper:memory-summary?content=nonconfig",
    "cisco-platform-env": "Cisco-IOS-XR-platform-oper:platform?content=nonconfig",
    "cisco-alarms": "Cisco-IOS-XR-alarmgr-server-oper:alarms?content=nonconfig",
    "cisco-rib-ipv4": "Cisco-IOS-XR-ip-rib-ipv4-oper:rib/vrfs/vrf=default/afs/af=IPv4/safs/saf=Unicast/ip-rib-route-table-names?content=nonconfig",
    "cisco-ifcfg-config": "Cisco-IOS-XR-ifmgr-cfg:interface-configuration?content=config",
    "cisco-bgp-config": "Cisco-IOS-XR-ipv4-bgp-cfg:bgp?content=config",
    "cisco-l2vpn-config": "Cisco-IOS-XR-l2vpn-cfg:l2vpn/database?content=config",
    "cisco-aaa-config": "Cisco-IOS-XR-aaa-lib-cfg:aaa?content=config",
    "cisco-lldp-config": "Cisco-IOS-XR-ethernet-lldp-cfg:lldp?content=config",
    "cisco-ethernet-stats": "Cisco-IOS-XR-drivers-media-eth-oper:ethernet-interface?content=nonconfig",

    # ---- L2VPN detail: xconnects (point-to-point) and bridge groups/domains (candidates, verify on the device)
    "cisco-l2vpn-xconnect": "Cisco-IOS-XR-l2vpn-oper:l2vpn/xconnects?content=nonconfig",
    "cisco-l2vpn-bridges": "Cisco-IOS-XR-l2vpn-oper:l2vpn/bridges?content=nonconfig",
    "cisco-l2vpn-xconnect-config": "Cisco-IOS-XR-l2vpn-cfg:l2vpn/xconnect?content=config",
    "cisco-l2vpn-bridge-config": "Cisco-IOS-XR-l2vpn-cfg:l2vpn/bridge?content=config",

    # ---- End-to-end service paths: the same reads the Service-LDP-E2E dashboard uses (checked on 10.137.76.18)
    "e2e-xconnect-config": "Cisco-IOS-XR-l2vpn-cfg:l2vpn/database/xconnect-groups?content=config",
    "e2e-bridge-config": "Cisco-IOS-XR-l2vpn-cfg:l2vpn/database/bridge-domain-groups?content=config",
    "e2e-xconnect-oper": "Cisco-IOS-XR-l2vpn-oper:l2vpnv2/active/xconnects?content=nonconfig&depth=4",
    "e2e-bridge-oper": "Cisco-IOS-XR-l2vpn-oper:l2vpnv2/active/bridge-domains?content=nonconfig&depth=4",
    "e2e-bridge-ports": at_locations(
        "Cisco-IOS-XR-l2vpn-oper:l2vpn-forwarding/nodes/node={loc}/l2fib-bridge-ports?content=nonconfig&depth=5"),
    "e2e-l2fibx-cons": at_locations(
        "Cisco-IOS-XR-l2vpn-oper:l2vpn-forwarding/nodes/node={loc}/l2fibx-cons?content=nonconfig&depth=5"),
    "e2e-ldp-neighbors": ["Cisco-IOS-XR-mpls-ldp-oper:mpls-ldp/global/active/default-vrf/neighbors?content=nonconfig",
                          "Cisco-IOS-XR-mpls-ldp-oper:mpls-ldp/global/active/default-vrf/neighbors"],
    "e2e-ldp-bindings": ["Cisco-IOS-XR-mpls-ldp-oper:mpls-ldp/global/active/default-vrf/afs/af=ipv4/bindings?content=nonconfig&depth=4",
                         "Cisco-IOS-XR-mpls-ldp-oper:mpls-ldp/global/active/default-vrf/afs/af=ipv4/bindings?content=nonconfig&depth=3"],
    "e2e-mpls-forwarding": at_locations(
        "Cisco-IOS-XR-fib-common-oper:mpls-forwarding/nodes/node={loc}/forwarding-summary?content=nonconfig"),
    "e2e-mpls-lsd-labels": at_locations(
        "Cisco-IOS-XR-mpls-lsd-oper:mpls-lsd-nodes/mpls-lsd-node={loc}/label-summary?content=nonconfig"),
    "e2e-interface-config": "Cisco-IOS-XR-ifmgr-cfg:interface-configurations?content=config&depth=5",
    "cisco-ipv4-static": "Cisco-IOS-XR-ip-static-cfg:router-static?content=config",
}

# Every DATA_PATHS id must also be a QUERIES id so --all and --query find it.
for _qid in DATA_PATHS:
    QUERIES.setdefault(_qid, {"label": "RESTCONF data GET: " + _qid, "kind": "get", "filter": None})

# OpenConfig RPC queries failed on every run against this router (ODL returns a generic
# "Exception during remote rpc invocation"). They are switched off here; the Cisco native
# equivalents above cover the same ground. Delete this block to re-enable them.
DISABLED = [
    "oc-interfaces", "oc-platform", "oc-system", "oc-lldp", "oc-network-instances",
    "oc-config-interfaces", "oc-config-network-instances", "oc-config-system",
    # Cisco native RPC queries that fail every run (BGP/OSPF/IS-IS RPC and config RPC).
    # Their GET equivalents are in DATA_PATHS. IS-IS is not configured on this router.
    "cisco-bgp", "cisco-ospf", "cisco-isis", "cisco-interfaces-config", "cisco-bgp-config", "cisco-ldp-config",
    # ARP model Cisco-IOS-XR-ip-arp-oper is not served by this device ("Failed to lookup for module").
    "cisco-arp",
    # Module Cisco-IOS-XR-segment-routing-ms-oper is not on this device; SR is covered by cisco-ospf-sr and cisco-sr-config.
    "cisco-sr-oper",
    # Containers below do not exist on the IOS-XR release in use (schema not found on 10.54.172.1).
    "cisco-mpls-te", "cisco-install", "cisco-syslog-config", "cisco-snmp-config",
    # Interface config needs a keyed read (name plus state) and no list read works; operational interface data is in cisco-interfaces-xr.
    "cisco-ifcfg-config",
    # xconnect and bridge paths: operational l2vpn container not on this release (use cisco-l2vpn, which
    # returns the xconnect and bridge summaries via l2vpn-forwarding); xconnect config path schema not found.
    "cisco-l2vpn-xconnect", "cisco-l2vpn-bridges", "cisco-l2vpn-xconnect-config", "cisco-l2vpn-bridge-config",
    # The whole l2vpn/database is very large on routers with hundreds of bridge domains and can time out
    # in ODL; e2e-xconnect-config and e2e-bridge-config read the same data in two smaller parts.
    # Run it on its own when wanted:  run_queries.py --node X --query cisco-l2vpn-config
    "cisco-l2vpn-config",
]
for _qid in DISABLED:
    QUERIES.pop(_qid, None)

# Run order: the service and end-to-end reads first, the largest answers last. A query that times out
# makes ODL reopen the router's session, so the heavy ones should not stand in front of the L2VPN data.
FIRST = ["e2e-xconnect-config", "e2e-bridge-config", "e2e-xconnect-oper", "e2e-bridge-ports",
         "e2e-l2fibx-cons", "e2e-interface-config", "cisco-lldp-native", "cisco-interfaces-xr", "e2e-ldp-neighbors",
         "e2e-ldp-bindings", "e2e-mpls-forwarding", "e2e-mpls-lsd-labels", "cisco-l2vpn"]
# e2e-bridge-oper is slow on routers with many bridge domains; the PWs come from e2e-bridge-ports anyway.
LAST = ["e2e-bridge-oper", "cisco-platform-inventory", "cisco-ethernet-stats", "cisco-bgp-neighbors", "cisco-alarms",
        "cisco-rib-ipv4", "cisco-cpu"]
_order = [q for q in FIRST if q in QUERIES] + [q for q in QUERIES if q not in FIRST and q not in LAST] + \
         [q for q in LAST if q in QUERIES]
QUERIES = {q: QUERIES[q] for q in _order}

# A RESTCONF answer that the path exists in the model but holds nothing on this router
# (for example no xconnects on a VPLS-only router, or a node location the router does not have).
EMPTY_ERRORS = ("data-missing", "relevant data model content does not exist")


def paths_for(qid):
    p = DATA_PATHS[qid]
    return list(p) if isinstance(p, (list, tuple)) else [p]


MOUNT_MARKERS = ("Mount point does not exist", "is not mounted on ODL")
# ODL's NETCONF request timeout: the router took too long (usually a very large answer). ODL then
# drops and reopens the NETCONF session, so the mount is missing for a short while afterwards.
TIMEOUT_MARKERS = ("Task was cancelled", "Transaction(GET) failed", "TimeoutException", "timed out")
RECONNECT_WAIT_S = 120
SLEEP = time.sleep  # replaced in tests


def wait_connected(client, node, max_wait=None):
    """Wait while ODL reconnects the router after a dropped session. True once it is connected again.

    Returns False at once when the controller does not list the node at all (wrong controller), or
    when the client cannot check (the Nokia copy has no is_mounted)."""
    if not hasattr(client, "is_mounted"):
        return False
    max_wait = RECONNECT_WAIT_S if max_wait is None else max_wait
    waited, step = 0, 5
    while True:
        try:
            listed, status = client.is_mounted(node)
        except Exception:
            listed, status = True, ""  # ODL busy: keep waiting
        if not listed and waited == 0:
            return False
        if listed and status == "connected":
            return True
        if waited >= max_wait:
            return False
        SLEEP(step)
        waited += step


def fetch(client, node, qid):
    """Read one DATA_PATHS query, trying its alternative paths in order.

    Returns (data, path used, note). The first path that answers with data wins. A "data missing"
    answer moves on to the next path; if every path is missing, the result is empty (nothing is
    configured there), not an error. Any other failure on every path raises the first error, with
    the paths tried. Works with both copies of odl_client (they raise their own OdlError).

    Two ODL answers stop the alternatives instead:
      * a timeout ("Transaction(GET) failed / Task was cancelled"): the other locations would hit the
        session ODL is reopening. Wait for the router to reconnect, then raise a clear error.
      * "Mount point does not exist": if ODL is reconnecting the router, wait and retry once;
        if the controller does not have the router at all, raise at once."""
    tried, first_err, empty_path = [], None, None
    for path in paths_for(qid):
        try:
            data = client.data_get(node, path)
        except Exception as exc:  # OdlError: keep trying the other paths
            msg = str(exc)
            if any(m in msg for m in MOUNT_MARKERS):
                if not wait_connected(client, node):
                    raise  # the router is not on this controller: every other path fails the same way
                try:
                    data = client.data_get(node, path)  # the session is back: one more try
                except Exception as exc2:
                    exc, msg = exc2, str(exc2)
                else:
                    exc = None
                if exc is None:
                    if data:
                        return data, path, "retried after ODL reconnected the router"
                    empty_path = empty_path or path
                    continue
            if any(t in msg for t in TIMEOUT_MARKERS):
                back = wait_connected(client, node)
                raise type(exc)(
                    f"ODL timed out waiting for {node} on {path} (Transaction(GET) failed: Task was cancelled). "
                    f"The answer is probably too large for ODL's NETCONF request timeout: read a smaller container, "
                    f"or raise default-request-timeout-millis on this node's mount in ODL. "
                    + ("ODL has reconnected the router, so the next queries can run."
                       if back else "The router was not reconnected within the wait; later queries may fail too.")
                    + f" | {msg[:600]}") from exc
            tried.append(f"{path}: {msg[:160]}")
            if any(x in msg for x in EMPTY_ERRORS):
                empty_path = empty_path or path
            elif first_err is None:
                first_err = exc
            continue
        if data:
            return data, path, ""
        empty_path = empty_path or path
    if empty_path is not None:
        return {}, empty_path, "nothing configured under this path on the router (data-missing)"
    if first_err is not None and len(tried) > 1:
        raise type(first_err)(f"{first_err} | paths tried: " + " || ".join(tried))
    raise first_err
