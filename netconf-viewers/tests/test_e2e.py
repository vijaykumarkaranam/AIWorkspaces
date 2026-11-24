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
            {"interface-name": "GigabitEthernet0/0/0/2.20", "state": "im-state-up"}]}},
        "e2e-interface-config": {"Cisco-IOS-XR-ifmgr-cfg:interface-configurations": {"interface-configuration": [
            {"interface-name": "Loopback0", "active": "act", "Cisco-IOS-XR-ipv4-io-cfg:ipv4-network": {
                "addresses": {"primary": {"address": "2.2.2.2", "netmask": "255.255.255.255"}}}},
            {"interface-name": "GigabitEthernet0/0/0/1.10", "active": "act", "description": "EVC-100 to CE-B"}]}},
        "cisco-lldp-native": {"Cisco-IOS-XR-ethernet-lldp-oper:lldp": {
            "global-lldp": {"lldp-info": {"system-name": "CISCO-B"}},
            "nodes": {"node": [{"neighbors": {"details": {"detail": [{"lldp-neighbor": [
                {"receiving-interface-name": "GigabitEthernet0/0/0/1", "device-id": "CE-B",
                 "port-id-detail": "eth0", "detail": {"system-name": "CE-B"}}]}]}}}]}}},
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
