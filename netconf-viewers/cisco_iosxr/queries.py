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

# Queries verified by hand as RESTCONF GETs on the mount path (module:container).
# run_queries.py uses these instead of the RPC filter when a query id is listed here.
DATA_PATHS = {
    "cisco-interfaces-xr": "Cisco-IOS-XR-pfi-im-cmd-oper:interfaces/interface-xr",
    "cisco-platform-inventory": "Cisco-IOS-XR-platform-inventory-oper:platform-inventory/racks",
    "cisco-system-time": "Cisco-IOS-XR-shellutil-oper:system-time",
    "cisco-ntp": "Cisco-IOS-XR-ip-ntp-oper:ntp",
    "cisco-lldp-native": "Cisco-IOS-XR-ethernet-lldp-oper:lldp",

    # ---- Working paths from manual tests (GET on the mount path)
    "cisco-ospf-summary": "Cisco-IOS-XR-ipv4-ospf-oper:ospf/processes/process=BSPD/default-vrf/ospf-summary",
    "cisco-ospf-sr": "Cisco-IOS-XR-ipv4-ospf-oper:ospf/processes/process=BSPD/default-vrf/segment-routing",
    "cisco-ospf-routes": "Cisco-IOS-XR-ipv4-ospf-oper:ospf/processes/process=BSPD/default-vrf/route-information/route-table",
    "cisco-ospf-neighbors": "Cisco-IOS-XR-ipv4-ospf-oper:ospf/processes/process=BSPD/default-vrf/adjacency-information/neighbors",
    "cisco-ospf-config": "Cisco-IOS-XR-ipv4-ospf-cfg:ospf?content=config",
    "cisco-bgp-neighbors": "Cisco-IOS-XR-ipv4-bgp-oper:bgp/instances/instance=default/instance-active/default-vrf/neighbors?content=nonconfig",
    "cisco-ldp": "Cisco-IOS-XR-mpls-ldp-oper:mpls-ldp",
    "cisco-bfd": "Cisco-IOS-XR-ip-bfd-oper:bfd",
    "cisco-l2vpn": "Cisco-IOS-XR-l2vpn-oper:l2vpn-forwarding/nodes/node=0%2F0%2FCPU0?content=nonconfig",
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

    # ---- End-to-end service paths: the same reads the Service-LDP-E2E dashboard uses (verify on the device)
    "e2e-xconnect-config": "Cisco-IOS-XR-l2vpn-cfg:l2vpn/database/xconnect-groups?content=config",
    "e2e-xconnect-oper": "Cisco-IOS-XR-l2vpn-oper:l2vpnv2/active/xconnects?content=nonconfig&depth=4",
    "e2e-bridge-oper": "Cisco-IOS-XR-l2vpn-oper:l2vpnv2/active/bridge-domains?content=nonconfig&depth=4",
    "e2e-bridge-ports": "Cisco-IOS-XR-l2vpn-oper:l2vpn-forwarding/nodes/node=0%2FRP0%2FCPU0/l2fib-bridge-ports?content=nonconfig&depth=5",
    "e2e-ldp-neighbors": "Cisco-IOS-XR-mpls-ldp-oper:mpls-ldp/global/active/default-vrf/neighbors?content=nonconfig",
    "e2e-ldp-bindings": "Cisco-IOS-XR-mpls-ldp-oper:mpls-ldp/global/active/default-vrf/afs/af=ipv4/bindings?content=nonconfig&depth=4",
    "e2e-mpls-forwarding": "Cisco-IOS-XR-fib-common-oper:mpls-forwarding/nodes/node=0%2FRP0%2FCPU0/forwarding-summary?content=nonconfig",
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
]
for _qid in DISABLED:
    QUERIES.pop(_qid, None)
