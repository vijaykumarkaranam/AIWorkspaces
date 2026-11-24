"""Tests for the end-to-end service stitching, using small synthetic stores (standard library only).

Run from the netconf-viewers folder:
  python -m unittest discover -s tests
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from e2e import build_report_model  # noqa: E402
from e2e.sources import Inventory, load_saved  # noqa: E402
from e2e.util import norm_state, port_of  # noqa: E402

NOKIA = "1.1.1.1"   # Nokia PE, node id = system address
CISCO = "10.0.0.2"  # Cisco PE as mounted in ODL; its loopback is 2.2.2.2
P2 = "3.3.3.2"      # a transit Cisco router between them


def nokia_data():
    cfg = {"configure": {"service": {
        "sdp": [{"sdp-id": 5, "far-end": {"ip-address-ipv6-address": "2.2.2.2"}, "lsp": {"lsp-name": "A-B"}},
                {"sdp-id": 6, "far-end": {"ip-address-ipv6-address": "2.2.2.2"}},
                {"sdp-id": 7, "far-end": {"ip-address-ipv6-address": "9.9.9.9"}}],
        "epipe": [{"service-id": 100, "name": "cust-100", "sap": {"sap-id": "1/1/1:10"},
                   "spoke-sdp": {"sdp-id-vc-id": "5:100"}},
                  {"service-id": 300, "name": "cust-300", "sap": {"sap-id": "1/1/2:30"},
                   "spoke-sdp": {"sdp-id-vc-id": "7:300"}}],
        "vpls": [{"service-id": 200, "name": "vpls-200", "sap": [{"sap-id": "1/1/3:20"}],
                  "bgp-ad": {"vpls-id": {"vpls-id": "65000:200"}}}]}}}
    return {
        "config-services": {"ietf-netconf:output": {"data": cfg}},
        "epipe-state": {"state": {"service": {"epipe": [
            {"oper-service-id": 100, "oper-state": "up", "sap": {"sap-id": "1/1/1:10", "oper-state": "up"},
             "spoke-sdp": {"sdp-bind-id": "5:100", "oper-state": "up", "pw-peer-status-bits": ""}},
            {"oper-service-id": 300, "oper-state": "up", "sap": {"sap-id": "1/1/2:30", "oper-state": "up"},
             "spoke-sdp": {"sdp-bind-id": "7:300", "oper-state": "up"}}]}}},
        "vpls-state": {"state": {"service": {"vpls": [
            {"oper-service-id": 200, "oper-state": "up", "sap": [{"sap-id": "1/1/3:20", "oper-state": "up"}],
             "spoke-sdp": [{"sdp-bind-id": "6:4294967013", "oper-state": "up", "creation-origin": "bgp-l2vpn"}]}]}}},
        "sdp-state": {"state": {"service": {"sdp": [{"sdp-id": 5, "sdp-oper-state": "up"},
                                                    {"sdp-id": 6, "sdp-oper-state": "up"},
                                                    {"sdp-id": 7, "sdp-oper-state": "up"}]}}},
        "lldp": {"state": {"port": [{"port-id": "1/1/1", "ethernet": {"lldp": {"dest-mac": [
            {"mac-type": "nearest-bridge", "remote-system": {"system-name": "CE-A", "remote-port-id": "ge-0/0/1"}}]}}}]}},
        "system": {"state": {"system": {"oper-name": "NOKIA-A"}}},
        # Transport: LSP A-B leaves on interface A7NOKIA-A-A7P1, bound to lag-1 (ports 1/1/5 and 1/1/6).
        "mpls-lsp-state": {"state": {"router": {"router-name": "Base", "mpls": {"lsp": [
            {"lsp-name": "A-B", "oper-state": "up", "from-address": NOKIA, "oper-metric": 20, "oper-fast-reroute": True,
             "transitions": 3, "primary": {"path-name": "Primary", "path-state": "active", "oper-state": "up",
                                           "fail-code": "no-error"}}]}}}},
        "rsvp": {"state": {"router": {"router-name": "Base", "rsvp": {"session": [
            {"session-type": "p2p-originate", "session-name": "A-B::Primary", "oper-state": "up", "out-label": 1000,
             "next-hop": "10.1.1.1", "out-if-index": 2, "protection-type": "facility",
             "local-protection-available": True, "local-protection-in-use": False,
             "bypass": {"avoid-node-address": "3.3.3.3"}}]}}}},
        "router-interface-state": {"state": {"router": [{"router-name": "Base", "interface": [
            {"interface-name": "system", "if-index": 1, "if-oper-status": "up", "ipv4": {"primary": {"oper-address": NOKIA}}},
            {"interface-name": "A7NOKIA-A-A7P1", "if-index": 2, "if-oper-status": "up",
             "ipv4": {"primary": {"oper-address": "10.1.1.0"},
                      "neighbor-discovery": {"neighbor": [{"ipv4-address": "10.1.1.1", "mac-address": "00:00:5e:00:53:01"}]}}}]}]}},
        "config-router-config": {"ietf-netconf:output": {"data": {"configure": {"router": {"router-name": "Base", "interface": [
            {"interface-name": "A7NOKIA-A-A7P1", "address": {"ip-address-mask": "10.1.1.0/31"}, "port": {"port-name": "lag-1:0"}}]}}}}},
        "lag": {"state": {"lag": [{"lag-index": 1, "oper-state": "up", "port": [
            {"port-id": "1/1/5", "oper-state": "up", "active-standby": "active"},
            {"port-id": "1/1/6", "oper-state": "up", "active-standby": "active"}]}]}},
        "port-state": {"state": {"port": [
            {"port-id": "1/1/1", "oper-state": "up", "ethernet": {"oper-speed": 1000}},
            {"port-id": "1/1/5", "oper-state": "up", "ethernet": {"oper-speed": 10000, "statistics": {"crc-align-errors": 0},
                                                              "lldp": {"dest-mac": [{"mac-type": "nearest-bridge", "remote-system": {
                                                                  "system-name": "P1", "remote-port-id": "2/1/1"}}]}}},
            {"port-id": "1/1/6", "oper-state": "up", "ethernet": {"oper-speed": 10000}}]}},
    }


def cisco_data(ac_state="im-state-down"):
    return {
        "cisco-l2vpn-config": {"Cisco-IOS-XR-l2vpn-cfg:database": {
            "xconnect-groups": {"xconnect-group": [{"name": "G", "p2p-xconnects": {"p2p-xconnect": [{
                "name": "X100", "attachment-circuits": {"attachment-circuit": [{"name": "GigabitEthernet0/0/0/1.10"}]},
                "pseudowire-neighbor-pseudowire-ids": {"pseudowire-neighbor-pseudowire-id": [
                    {"neighbor": NOKIA, "pseudowire-id": 100}]}}]}}]},
            "bridge-domain-groups": {"bridge-domain-group": [{"name": "BG", "bridge-domains": {"bridge-domain": [{
                "name": "BD200", "bd-attachment-circuits": {"bd-attachment-circuit": [{"name": "GigabitEthernet0/0/0/2.20"}]},
                "vfis": {"vfi": [{"name": "BD200", "vpnid": 200, "bgp-auto-discovery": {"ldp-signaling-protocol": {
                    "vpls-id": {"type": "two-byte-as", "as": 65000, "as-index": 200}}}}]}}]}}]}}},
        "e2e-bridge-ports": {"Cisco-IOS-XR-l2vpn-oper:l2fib-bridge-ports": {"l2fib-bridge-port": [
            {"group-name": "BG", "bd-name": "BD200", "segment": {"pw": {
                "next-hop-address": NOKIA, "pw-id": "999", "next-hop-valid": True}}}]}},
        "cisco-l2vpn": {"Cisco-IOS-XR-l2vpn-oper:node": [{"l2fibx-cons": {"l2fibx-con": [
            {"segment2": {"pw": {"next-hop-address": NOKIA, "pw-id": "100", "next-hop-valid": True}}}]}}]},
        "cisco-interfaces-xr": {"Cisco-IOS-XR-pfi-im-cmd-oper:interface-xr": {"interface": [
            {"interface-name": "GigabitEthernet0/0/0/1.10", "state": ac_state},
            {"interface-name": "GigabitEthernet0/0/0/1", "state": "im-state-up"},
            {"interface-name": "GigabitEthernet0/0/0/2.20", "state": "im-state-up"},
            {"interface-name": "HundredGigE0/0/0/3", "state": "im-state-up", "speed": 100000000},
            {"interface-name": "HundredGigE0/0/0/4", "state": "im-state-up", "speed": 100000000}]}},
        # Route to the Nokia loopback: primary via P2 (SR label 16001), TI-LFA backup via P3.
        "cisco-rib-ipv4": {"Cisco-IOS-XR-ip-rib-ipv4-oper:ip-rib-route-table-names": {"ip-rib-route-table-name": [{
            "route-table-name": "default", "protocol": {"ospf": {"as": [{"as": "CORE", "protocol-routes": {"protocol-route": [{
                "address": NOKIA, "prefix-length": 32, "protocol-name": "ospf", "instance": "CORE", "metric": 30,
                "distance": 110, "active": True, "route-label": 16001, "route-path": {"ipv4-rib-edm-path": [
                    {"interface-name": "HundredGigE0/0/0/3", "address": {"ipv4": "10.2.2.1"}, "metric": 30,
                     "route-label": 16001, "flags": 64, "backup-pathid": 65},
                    {"interface-name": "HundredGigE0/0/0/4", "address": {"ipv4": "10.2.3.1"}, "metric": 50,
                     "route-label": 16050, "labelstk": [{"entry": 16050}, {"entry": 16001}], "ref-cnt-of-backup": 1,
                     "flags": 384}]}}]}}]}}}]}},
        "cisco-ethernet-stats": {"Cisco-IOS-XR-drivers-media-eth-oper:ethernet-interface": {
            "statistics": {"statistic": [{"interface-name": "HundredGigE0/0/0/3", "dropped-packets-with-crc-align-errors": "5"}]},
            "interfaces": {"interface": [{"interface-name": "HundredGigE0/0/0/3", "phy-info": {"phy-details": {
                "vendor-part-number": "QSFP-100G-LR4", "lane": [
                    {"lane-id": 0, "received-laser-power": -25000, "transmit-laser-power": 15000,
                     "dig-opt-mon-alarm": {"received-laser-power": "normal"}}]}}}]}}},
        "e2e-interface-config": {"Cisco-IOS-XR-ifmgr-cfg:interface-configurations": {"interface-configuration": [
            {"interface-name": "Loopback0", "active": "act", "Cisco-IOS-XR-ipv4-io-cfg:ipv4-network": {
                "addresses": {"primary": {"address": "2.2.2.2", "netmask": "255.255.255.255"}}}},
            {"interface-name": "GigabitEthernet0/0/0/1.10", "active": "act", "description": "EVC-100 to CE-B"}]}},
        "cisco-lldp-native": {"Cisco-IOS-XR-ethernet-lldp-oper:lldp": {
            "global-lldp": {"lldp-info": {"system-name": "CISCO-B"}},
            "nodes": {"node": [{"neighbors": {"details": {"detail": [{"lldp-neighbor": [
                {"receiving-interface-name": "GigabitEthernet0/0/0/1", "device-id": "CE-B",
                 "port-id-detail": "eth0", "detail": {"system-name": "CE-B"}},
                {"receiving-interface-name": "HundredGigE0/0/0/3", "device-id": "P2", "port-id-detail": "HundredGigE0/0/0/7",
                 "detail": {"system-name": "P2", "network-addresses": {"lldp-addr-entry": [
                     {"address": {"address-type": "ipv4", "ipv4-address": P2}}]}}},
                {"receiving-interface-name": "HundredGigE0/0/0/4", "device-id": "P3", "port-id-detail": "HundredGigE0/0/0/8",
                 "detail": {"system-name": "P3"}}]}]}}}]}}},
    }


def p2_data():
    """A transit Cisco router (no services) whose route to the Nokia PE goes straight to it."""
    return {
        "cisco-lldp-native": {"Cisco-IOS-XR-ethernet-lldp-oper:lldp": {
            "global-lldp": {"lldp-info": {"system-name": "P2"}},
            "nodes": {"node": [{"neighbors": {"details": {"detail": [{"lldp-neighbor": [
                {"receiving-interface-name": "HundredGigE0/0/0/9", "device-id": "NOKIA-A", "port-id-detail": "1/1/5",
                 "detail": {"system-name": "NOKIA-A", "network-addresses": {"lldp-addr-entry": [
                     {"address": {"address-type": "ipv4", "ipv4-address": NOKIA}}]}}}]}]}}}]}}},
        "cisco-interfaces-xr": {"Cisco-IOS-XR-pfi-im-cmd-oper:interface-xr": {"interface": [
            {"interface-name": "HundredGigE0/0/0/9", "state": "im-state-up"}]}},
        "cisco-rib-ipv4": {"x": {"protocol-route": [{
            "address": NOKIA, "prefix-length": 32, "protocol-name": "ospf", "metric": 10, "active": True, "route-label": 16001,
            "route-path": {"ipv4-rib-edm-path": [{"interface-name": "HundredGigE0/0/0/9", "address": {"ipv4": "10.1.1.0"},
                                                  "metric": 10, "flags": 64}]}}]}},
    }


def write_store(base, node, data, error=None):
    folder = os.path.join(base, node)
    os.makedirs(folder, exist_ok=True)
    for qid, d in data.items():
        with open(os.path.join(folder, f"20260101-000000_{qid}.json"), "w", encoding="utf-8") as fh:
            json.dump({"node": node, "query": qid, "data": d}, fh)
    for qid, msg in (error or {}).items():
        with open(os.path.join(folder, f"20260101-000001_{qid}-error.json"), "w", encoding="utf-8") as fh:
            json.dump({"node": node, "query": qid, "error": msg}, fh)


class E2ETest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.nokia_dir = os.path.join(self.tmp.name, "store")
        self.cisco_dir = os.path.join(self.tmp.name, "results")
        write_store(self.nokia_dir, NOKIA, nokia_data())
        write_store(self.cisco_dir, CISCO, cisco_data())

    def tearDown(self):
        self.tmp.cleanup()

    def inv(self, mapping=None):
        return Inventory(self.nokia_dir, self.cisco_dir, loopback_map=mapping or {})

    def svc(self, model, key):
        return next(s for s in model["services"] if s["key"] == key)

    def test_nokia_epipe_stitched_to_cisco_xconnect_via_loopback(self):
        m = build_report_model(NOKIA, self.inv())
        s = self.svc(m, "epipe:100")
        leg = s["legs"][0]
        self.assertEqual(leg["farEnd"]["status"], "matched")   # 2.2.2.2 found as Loopback0 of the Cisco node
        self.assertEqual(leg["farEnd"]["node"], CISCO)
        self.assertEqual(leg["farEnd"]["name"], "CISCO-B")
        self.assertEqual(leg["remote"]["key"], "p2p:G/X100")
        self.assertEqual(leg["remotePw"]["oper"], "up")
        self.assertEqual(s["acs"][0]["ce"]["name"], "CE-A")
        self.assertEqual(leg["remote"]["acs"][0]["ce"]["name"], "CE-B")
        self.assertEqual(leg["remote"]["acs"][0]["description"], "EVC-100 to CE-B")
        # The far-end AC is down, so the service is down end to end.
        self.assertEqual(s["status"], "down")
        self.assertTrue(any("Far end: access circuit GigabitEthernet0/0/0/1.10" in i["msg"] for i in s["issues"]))

    def test_service_up_when_both_ends_up(self):
        write_store(self.cisco_dir, CISCO, cisco_data(ac_state="im-state-up"))
        s = self.svc(build_report_model(NOKIA, self.inv()), "epipe:100")
        self.assertEqual(s["status"], "up")

    def test_bgp_ad_vpls_matched_by_vpls_id(self):
        m = build_report_model(NOKIA, self.inv())
        s = self.svc(m, "vpls:200")
        leg = s["legs"][0]
        self.assertEqual(leg["farEnd"]["status"], "matched")
        self.assertEqual(leg["farEnd"]["matchedBy"], "VPLS-ID 65000:200")
        self.assertEqual(leg["remote"]["key"], "bridge-domain:BG/BD200")
        self.assertEqual(s["status"], "up")

    def test_reverse_direction_from_cisco(self):
        m = build_report_model(CISCO, self.inv())
        p2p = self.svc(m, "p2p:G/X100")
        self.assertEqual(p2p["legs"][0]["farEnd"]["status"], "matched")
        self.assertEqual(p2p["legs"][0]["remote"]["key"], "epipe:100")
        bd = self.svc(m, "bridge-domain:BG/BD200")
        self.assertEqual(bd["vplsId"], "65000:200")
        self.assertEqual(bd["legs"][0]["pw"]["kind"], "bgp-auto")   # peer known only from L2FIB
        self.assertEqual(bd["legs"][0]["remote"]["key"], "vpls:200")

    def test_far_end_without_saved_data_is_partial(self):
        m = build_report_model(NOKIA, self.inv())
        s = self.svc(m, "epipe:300")
        self.assertEqual(s["legs"][0]["farEnd"]["status"], "not-collected")
        self.assertEqual(s["status"], "partial")
        missing = [f for f in m["farEnds"] if not f["collected"]]
        self.assertEqual([f["ip"] for f in missing], ["9.9.9.9"])

    def test_loopback_map_resolves_far_end(self):
        write_store(self.nokia_dir, "10.9.9.9", nokia_data())  # a router mounted by a management address
        m = build_report_model(NOKIA, self.inv({"9.9.9.9": "10.9.9.9"}))
        self.assertNotEqual(self.svc(m, "epipe:300")["legs"][0]["farEnd"]["status"], "not-collected")

    def test_far_end_with_no_matching_service_is_degraded(self):
        data = cisco_data(ac_state="im-state-up")
        data["cisco-l2vpn-config"]["Cisco-IOS-XR-l2vpn-cfg:database"]["xconnect-groups"] = {"xconnect-group": []}
        write_store(self.cisco_dir, CISCO, data)
        s = self.svc(build_report_model(NOKIA, self.inv()), "epipe:100")
        self.assertEqual(s["legs"][0]["farEnd"]["status"], "no-service")
        self.assertEqual(s["status"], "degraded")

    def test_local_sap_down_with_port_down(self):
        data = nokia_data()
        ep = data["epipe-state"]["state"]["service"]["epipe"][0]
        ep["oper-state"] = "down"
        ep["sap"] = {"sap-id": "1/1/1:10", "oper-state": "down", "oper-flags": "port-oper-down"}
        write_store(self.nokia_dir, NOKIA, data)
        s = self.svc(build_report_model(NOKIA, self.inv()), "epipe:100")
        self.assertEqual(s["status"], "down")
        self.assertTrue(any("1/1/1:10 is down, port 1/1/1 is down" in i["msg"] for i in s["issues"]))

    def test_multipoint_with_one_site_down_is_degraded(self):
        data = nokia_data()
        data["config-services"]["ietf-netconf:output"]["data"]["configure"]["service"]["vpls"][0]["sap"].append(
            {"sap-id": "1/1/4:20"})
        data["vpls-state"]["state"]["service"]["vpls"][0]["sap"].append({"sap-id": "1/1/4:20", "oper-state": "down"})
        write_store(self.nokia_dir, NOKIA, data)
        write_store(self.cisco_dir, CISCO, cisco_data(ac_state="im-state-up"))
        s = self.svc(build_report_model(NOKIA, self.inv()), "vpls:200")
        self.assertEqual(s["status"], "degraded")
        self.assertTrue(any(i["sev"] == "critical" and "1/1/4:20" in i["msg"] for i in s["issues"]))

    def test_data_missing_error_counts_as_empty(self):
        write_store(self.cisco_dir, "10.0.0.3", {}, error={
            "e2e-xconnect-config": "Request could not be completed because the relevant data model content does not exist",
            "cisco-lldp-native": "HTTP 500: something else"})
        data, _when = load_saved(os.path.join(self.cisco_dir, "10.0.0.3"), ["e2e-xconnect-config", "cisco-lldp-native"])
        self.assertEqual(data, {"e2e-xconnect-config": {}})

    def test_nokia_transport_lsp_rsvp_interface_lag_ports(self):
        m = build_report_model(NOKIA, self.inv())
        tr = self.svc(m, "epipe:100")["legs"][0]["pw"]["transport"]
        self.assertEqual(tr["lsp"]["name"], "A-B")
        self.assertEqual(tr["lsp"]["oper"], "up")
        self.assertEqual(tr["label"], 1000)
        p = tr["paths"][0]
        self.assertEqual((p["interface"], p["interfaceIp"], p["portName"], p["nextHop"], p["nextHopName"]),
                         ("A7NOKIA-A-A7P1", "10.1.1.0", "lag-1:0", "10.1.1.1", "P1"))
        self.assertEqual(p["port"]["key"], f"lag|{NOKIA}|lag-1")
        self.assertEqual([x["id"] for x in p["port"]["members"]], ["1/1/5", "1/1/6"])
        self.assertEqual(p["port"]["members"][0]["neighbor"]["name"], "P1")  # LLDP from port-state merged in
        for k in (f"lsp|{NOKIA}|A-B", f"rsvp|{NOKIA}|A-B", f"sdp|{NOKIA}|5", f"lag|{NOKIA}|lag-1",
                  f"port|{NOKIA}|1/1/5", f"interface|{NOKIA}|A7NOKIA-A-A7P1", f"svc|{NOKIA}|epipe:100", f"pe|{NOKIA}|{NOKIA}"):
            self.assertIn(k, m["objects"])
        lsp = dict(m["objects"][f"lsp|{NOKIA}|A-B"]["fields"])
        self.assertEqual(lsp["Out label"], 1000)
        self.assertEqual(lsp["Bypass avoids"], "3.3.3.3")
        json.dumps(m)  # the whole model goes into the page

    def test_lag_member_down_is_a_warning(self):
        data = nokia_data()
        data["lag"]["state"]["lag"][0]["port"][1]["oper-state"] = "down"
        write_store(self.nokia_dir, NOKIA, data)
        write_store(self.cisco_dir, CISCO, cisco_data(ac_state="im-state-up"))
        s = self.svc(build_report_model(NOKIA, self.inv()), "epipe:100")
        self.assertTrue(any(i["sev"] == "warning" and "1 of 2 members down" in i["msg"] for i in s["issues"]))
        self.assertEqual(s["status"], "degraded")

    def test_cisco_route_primary_and_ti_lfa_backup(self):
        write_store(self.cisco_dir, CISCO, cisco_data(ac_state="im-state-up"))
        m = build_report_model(CISCO, self.inv())
        s = self.svc(m, "p2p:G/X100")
        tr = s["legs"][0]["pw"]["transport"]
        self.assertEqual(tr["label"], 16001)
        self.assertTrue(tr["type"].startswith("SR-MPLS"))
        prim, backup = tr["paths"]
        self.assertEqual((prim["role"], prim["nextHopName"], prim["labels"]), ("primary", "P2", [16001]))
        self.assertEqual((backup["role"], backup["nextHopName"], backup["labels"]), ("backup (TI-LFA)", "P3", [16050, 16001]))
        self.assertEqual(prim["port"]["crc"], 5)
        self.assertEqual(prim["port"]["rxPowerDbm"], -2.5)
        # Old CRC errors are reported, but only as info: the service stays up.
        self.assertTrue(any(i["sev"] == "info" and "5 CRC errors" in i["msg"] for i in s["issues"]))
        self.assertEqual(s["status"], "up")
        self.assertIn(f"route|{CISCO}|{NOKIA}/32", m["objects"])

    def test_no_route_to_far_end_is_critical(self):
        data = cisco_data(ac_state="im-state-up")
        data["cisco-rib-ipv4"] = {"x": {"protocol-route": []}}
        write_store(self.cisco_dir, CISCO, data)
        s = self.svc(build_report_model(CISCO, self.inv()), "p2p:G/X100")
        self.assertTrue(any(i["sev"] == "critical" and "No route to far-end loopback" in i["msg"] for i in s["issues"]))
        self.assertEqual(s["status"], "down")

    def test_hop_by_hop_walk_through_saved_transit_router(self):
        write_store(self.cisco_dir, P2, p2_data())
        m = build_report_model(CISCO, self.inv())
        walk = self.svc(m, "p2p:G/X100")["legs"][0]["walk"]
        self.assertEqual([h["name"] for h in walk], ["CISCO-B", "P2", "NOKIA-A"])
        self.assertEqual(walk[1]["interface"], "HundredGigE0/0/0/9")
        self.assertTrue(walk[-1]["final"])
        self.assertIn(f"route|{P2}|{NOKIA}/32", m["objects"])  # transit router objects are carried into the page

    def test_far_end_objects_carried_into_page(self):
        write_store(self.cisco_dir, CISCO, cisco_data(ac_state="im-state-up"))
        m = build_report_model(NOKIA, self.inv())
        leg = self.svc(m, "epipe:100")["legs"][0]
        self.assertIn(leg["remote"]["objKey"], m["objects"])
        self.assertIn(leg["remotePw"]["transport"]["routeKey"], m["objects"])  # return path from the Cisco side
        self.assertIn(leg["farEnd"]["peKey"], m["objects"])

    def test_unknown_node(self):
        m = build_report_model("192.0.2.1", self.inv())
        self.assertIn("error", m)

    def test_helpers(self):
        self.assertEqual(port_of("1/1/3:676"), "1/1/3")
        self.assertEqual(port_of("TenGigE0/0/0/5.871"), "TenGigE0/0/0/5")
        self.assertEqual(port_of("lag-2:100.*"), "lag-2")
        self.assertEqual(norm_state("im-state-admin-down"), "admin-down")
        self.assertEqual(norm_state("im-state-up"), "up")
        self.assertEqual(norm_state("bridge-up"), "up")


if __name__ == "__main__":
    unittest.main()
