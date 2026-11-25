"""Live per-service trace (the dashboard's method) against a fake ODL: Nokia CLI and Cisco RESTCONF far ends."""
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_e2e import CISCO, NOKIA, cisco_data, write_store  # noqa: E402
from e2e import build_report_model  # noqa: E402
from e2e.collect import make_client  # noqa: E402
from e2e.sources import Inventory  # noqa: E402
from e2e.trace import trace_service, traced_service_payload  # noqa: E402

CISCO2 = "4.4.4.4"   # another Cisco PE in the same VPLS (same VPN-ID 200, different bridge-domain name)
GONE = "9.9.9.9"     # a peer that is not mounted in ODL

NOKIA_LLDP = """Link Layer Discovery Protocol (LLDP) System Information

===============================================================================
NB = nearest-bridge   NTPMR = nearest-non-tpmr   NC = nearest-customer
===============================================================================
Lcl Port      Scope Remote Chassis ID  Index  Remote Port     Remote Sys Name
-------------------------------------------------------------------------------
1/1/3         NB    00:20:D2:63:64:BE  24     ETH-1/1         CE-NOKIA-SITE
2/2/1         NB    0C:A4:02:23:20:01  150    1/2/1, 10-Gig * P-ROUTER
==============================================================================="""
NOKIA_SAP = """PortId                          SvcId      Ing.  Ing.    Egr.  Egr.   Adm  Opr
                                           QoS   Fltr    QoS   Fltr
-------------------------------------------------------------------------------
1/1/3:20                        200        1     none    1     none   Up   Up
-------------------------------------------------------------------------------"""
NOKIA_BASE = """Service Id        : 200                 Vpn Id            : 200
Service Type      : VPLS
Name              : vpls-200
Admin State       : Up                  Oper State        : Up"""
MISSING = {"errors": {"error": [{"error-tag": "data-missing", "error-message":
                                 "Request could not be completed because the relevant data model content does not exist"}]}}


class Odl(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if "yang-ext:mount" not in self.path:
            return self._send(200, {"network-topology:topology": [{"node": [
                {"node-id": NOKIA, "netconf-node-topology:connection-status": "connected",
                 "netconf-node-topology:available-capabilities": {"available-capability": [{"capability": "urn:nokia.com:sros"}]}},
                {"node-id": CISCO2, "netconf-node-topology:connection-status": "connected",
                 "netconf-node-topology:available-capabilities": {"available-capability": [{"capability": "http://cisco.com/ns/yang/Cisco-IOS-XR-l2vpn-cfg"}]}}]}]})
        if f"node={CISCO2}" not in self.path:
            return self._send(409, MISSING)
        if "ethernet-lldp-oper:lldp" in self.path:
            return self._send(200, {"Cisco-IOS-XR-ethernet-lldp-oper:lldp": {
                "global-lldp": {"lldp-info": {"system-name": "CISCO-C"}},
                "nodes": {"node": [{"neighbors": {"details": {"detail": [{"lldp-neighbor": [
                    {"receiving-interface-name": "GigabitEthernet0/0/0/7", "device-id": "CE-CISCO-SITE",
                     "port-id-detail": "ge-0/0/0", "detail": {"system-name": "CE-CISCO-SITE"}}]}]}}}]}}})
        if "bridge-domain-groups" in self.path:
            return self._send(200, {"Cisco-IOS-XR-l2vpn-cfg:bridge-domain-groups": {"bridge-domain-group": [{
                "name": "OTHER", "bridge-domains": {"bridge-domain": [{
                    "name": "SITE-C-200", "bd-attachment-circuits": {"bd-attachment-circuit": [{"name": "GigabitEthernet0/0/0/7.200"}]},
                    "vfis": {"vfi": [{"name": "SITE-C-200", "vpnid": 200}]}}]}}]}})
        return self._send(409, MISSING)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        cmd = json.dumps(body)
        resp = (NOKIA_SAP if "service id 200 sap" in cmd else NOKIA_BASE if "service id 200 base" in cmd
                else NOKIA_LLDP if "system lldp neighbor" in cmd else "")
        return self._send(200, {"ietf-netconf:output": {"data": {"oper-data-format-cli-block": {"item": {"response": resp}}}}})

    def log_message(self, *a):
        pass


class TraceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Odl)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["E2E_TRACES"] = os.path.join(self.tmp.name, "traces")
        data = cisco_data(ac_state="im-state-up")
        ports = data["e2e-bridge-ports"]["Cisco-IOS-XR-l2vpn-oper:l2fib-bridge-ports"]["l2fib-bridge-port"]
        for peer in (CISCO2, GONE):  # two more BGP-AD peers in BD200
            ports.append({"group-name": "BG", "bd-name": "BD200", "segment": {"pw": {
                "next-hop-address": peer, "pw-id": "999", "next-hop-valid": True}}})
        data["e2e-ldp-neighbors"] = {"Cisco-IOS-XR-mpls-ldp-oper:neighbors": {"neighbor": [
            {"lsr-id": NOKIA, "protocol-information": {"ta-state": "Oper", "ta-up-time-seconds": 3139200},
             "detailed-information": {"client": [{"name": "AToM"}]}}]}}
        self.cisco_dir = os.path.join(self.tmp.name, "results")
        write_store(self.cisco_dir, CISCO, data)  # only the local router is saved: no far-end data at all
        self.client = make_client(self.url)
        self.client.user = ""

    def tearDown(self):
        os.environ.pop("E2E_TRACES", None)
        self.tmp.cleanup()

    def inv(self):
        return Inventory(os.path.join(self.tmp.name, "store"), self.cisco_dir, loopback_map={})

    def test_trace_finds_far_end_ces_on_both_vendors(self):
        key = "bridge-domain:BG/BD200"
        before = next(s for s in build_report_model(CISCO, self.inv())["services"] if s["key"] == key)
        self.assertEqual({l["farEnd"]["status"] for l in before["legs"]}, {"not-collected"})

        res = trace_service(CISCO, key, self.client, self.inv(), log=lambda *_: None)
        self.assertEqual(res["peers"][NOKIA]["status"], "ce_found")
        self.assertEqual(res["peers"][NOKIA]["how"], "Nokia service id 200")       # the Cisco VPN-ID
        self.assertEqual(res["peers"][CISCO2]["status"], "ce_found")
        self.assertEqual(res["peers"][CISCO2]["peName"], "CISCO-C")
        self.assertEqual(res["peers"][GONE]["status"], "unreachable")

        svc = traced_service_payload(CISCO, key, self.inv())["service"]
        legs = {l["farEnd"]["ip"]: l for l in svc["legs"]}
        n = legs[NOKIA]
        self.assertEqual(n["farEnd"]["status"], "matched")
        self.assertEqual(n["farEnd"]["vendor"], "nokia")
        self.assertEqual(n["remote"]["acs"][0]["ce"]["name"], "CE-NOKIA-SITE")
        self.assertEqual(n["remote"]["acs"][0]["ce"]["port"], "ETH-1/1")
        self.assertEqual(n["pw"]["tldp"]["uptime"], "36d 8h")                        # T-LDP from the LDP neighbours
        c = legs[CISCO2]
        self.assertEqual(c["remote"]["acs"][0]["ce"]["name"], "CE-CISCO-SITE")
        self.assertIn("VPN-ID", c["farEnd"]["matchedBy"])                            # the dashboard's fallback match
        self.assertEqual(c["farEnd"]["name"], "CISCO-C")
        self.assertEqual(legs[GONE]["farEnd"]["status"], "unreachable")
        self.assertTrue(any("not reachable" in i["msg"] for i in svc["issues"]))
        self.assertIsNotNone(svc["tracedAt"])
        self.assertEqual(svc["signaling"], "BGP-AD + LDP")  # VFI with BGP auto-discovery and LDP signaling

    def test_unknown_service(self):
        with self.assertRaises(ValueError):
            trace_service(CISCO, "bridge-domain:NOPE/NOPE", self.client, self.inv(), log=lambda *_: None)


if __name__ == "__main__":
    unittest.main()


BD_OPER = {"Cisco-IOS-XR-l2vpn-oper:bridge-domain": [{
    "bridge-domain-group-name": "BG", "bridge-domain-name": "BD200",
    "bridge-vfis": {"bridge-vfi": [{"vfi-name": "BD200", "bridge-pws": {"bridge-pw": [
        {"neighbor": NOKIA, "pw-id": 4294967013, "pseudowire": {"state": "l2vpn-pw-state-up", "peer-id": {"ipv4": NOKIA},
                                                                 "local-signalling": {"local-label": 24010},
                                                                 "remote-signalling": {"remote-label": 524000}}},
        {"neighbor": CISCO2, "pw-id": 200, "pseudowire": {"state": "l2vpn-pw-state-up"}}]}}]}}]}


class BgpAdNoSavedPeers(Odl):
    """The local router's own bridge-domain oper read; everything else as the base fake ODL."""
    oper_works = True

    def do_GET(self):
        if f"node={CISCO}/" in self.path and "bridge-domain=BG,BD200" in self.path:
            return self._send(200, BD_OPER) if self.oper_works else self._send(500, {"errors": {"error": [
                {"error-tag": "operation-failed", "error-message": "schema not found"}]}})
        return Odl.do_GET(self)


class BgpAdTraceTest(unittest.TestCase):
    """The screenshot case: a BGP-AD bridge domain whose peers are not in the saved data (no L2FIB read)."""

    def start(self, oper_works):
        handler = type("H", (BgpAdNoSavedPeers,), {"oper_works": oper_works})
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.client = make_client(f"http://127.0.0.1:{self.srv.server_address[1]}")
        self.client.user = ""

    def setUp(self):
        self.srv = None
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["E2E_TRACES"] = os.path.join(self.tmp.name, "traces")
        data = cisco_data(ac_state="im-state-up")
        data.pop("e2e-bridge-ports")  # the big L2FIB read did not finish: no peers saved
        data["e2e-ldp-neighbors"] = {"Cisco-IOS-XR-mpls-ldp-oper:neighbors": {"neighbor": [
            {"lsr-id": ip, "protocol-information": {"ta-state": "Oper", "ta-up-time-seconds": 86400},
             "detailed-information": {"client": [{"name": "AToM"}]}} for ip in (NOKIA, CISCO2, "5.5.5.5")]}}
        self.cisco_dir = os.path.join(self.tmp.name, "results")
        write_store(self.cisco_dir, CISCO, data)

    def tearDown(self):
        if self.srv is not None:  # only a started server can be shut down (shutdown waits for its loop)
            self.srv.shutdown()
            self.srv.server_close()
        os.environ.pop("E2E_TRACES", None)
        self.tmp.cleanup()

    def inv(self):
        return Inventory(os.path.join(self.tmp.name, "store"), self.cisco_dir, loopback_map={})

    def svc(self):
        return next(s for s in build_report_model(CISCO, self.inv())["services"] if s["key"] == "bridge-domain:BG/BD200")

    def test_untraced_bgp_ad_says_why_not_local_only(self):
        s = self.svc()
        self.assertEqual(s["legs"], [])
        self.assertEqual(s["status"], "partial")
        self.assertTrue(any("BGP-AD VPLS" in i["msg"] for i in s["issues"]))

    def test_peers_from_the_bridge_domain_oper_read(self):
        self.start(oper_works=True)
        res = trace_service(CISCO, "bridge-domain:BG/BD200", self.client, self.inv(), log=lambda *_: None)
        self.assertEqual(res["localPeersFrom"], "bridge-domain oper (2) + T-LDP AToM neighbours (1 more)")
        self.assertEqual(sorted(p["peer"] for p in res["localPeers"] if not p["candidate"]), sorted([NOKIA, CISCO2]))
        self.assertIn("bridge-domain", res["localOper"])  # the raw answer is kept for troubleshooting
        s = self.svc()
        legs = {l["farEnd"]["ip"]: l for l in s["legs"]}
        self.assertEqual(set(legs), {NOKIA, CISCO2})
        self.assertEqual(legs[NOKIA]["remote"]["acs"][0]["ce"]["name"], "CE-NOKIA-SITE")
        self.assertEqual(legs[NOKIA]["pw"]["pwLabels"], {"local": 24010, "remote": 524000})
        self.assertEqual(legs[NOKIA]["pw"]["oper"], "up")
        self.assertEqual(legs[CISCO2]["remote"]["acs"][0]["ce"]["name"], "CE-CISCO-SITE")
        # The fixture RIB has no route to 4.4.4.4: one site without transport makes the VPLS degraded.
        self.assertEqual(s["status"], "degraded")
        self.assertTrue(any("No route to far-end loopback 4.4.4.4" in i["msg"] for i in s["issues"]))

    def test_candidates_from_tldp_when_the_oper_read_fails(self):
        self.start(oper_works=False)
        res = trace_service(CISCO, "bridge-domain:BG/BD200", self.client, self.inv(), log=lambda *_: None)
        self.assertTrue(all(p["candidate"] for p in res["localPeers"]))
        self.assertEqual(res["peers"]["5.5.5.5"]["status"], "unreachable")  # not mounted: cannot confirm
        s = self.svc()
        # Only candidates that really carry VPN-ID 200 become peer rows; the others are listed apart.
        self.assertEqual(sorted(l["farEnd"]["ip"] for l in s["legs"]), sorted([NOKIA, CISCO2]))
        self.assertEqual([o["ip"] for o in s["traceOthers"]], ["5.5.5.5"])

    def test_screenshot_case_oper_lists_one_connecting_peer(self):
        """10.137.76.18 / 51726: the oper read named one peer (connecting), the members came from T-LDP AToM."""
        one = {"Cisco-IOS-XR-l2vpn-oper:bridge-domain": [{"bridge-domain-name": "BD200", "bridge-vfis": {"bridge-vfi": [
            {"bridge-pws": {"bridge-pw": [{"neighbor": GONE, "pw-id": 1}]}}]}}]}
        handler = type("H", (BgpAdNoSavedPeers,), {"oper_works": True})
        orig = handler.do_GET

        def do_GET(h):
            if f"node={CISCO}/" in h.path and "bridge-domain=BG,BD200" in h.path:
                return h._send(200, one)
            return orig(h)
        handler.do_GET = do_GET
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.client = make_client(f"http://127.0.0.1:{self.srv.server_address[1]}")
        self.client.user = ""
        trace_service(CISCO, "bridge-domain:BG/BD200", self.client, self.inv(), log=lambda *_: None)
        s = self.svc()
        legs = {l["farEnd"]["ip"]: l["farEnd"]["status"] for l in s["legs"]}
        self.assertEqual(legs, {GONE: "unreachable", NOKIA: "matched", CISCO2: "matched"})  # as the dashboard finds them
        self.assertEqual([o["ip"] for o in s["traceOthers"]], ["5.5.5.5"])
