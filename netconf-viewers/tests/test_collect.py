"""Far-end collection against a fake ODL (standard library HTTP server, no network needed)."""
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_e2e import CISCO, NOKIA, cisco_data, nokia_data, write_store  # noqa: E402
from e2e import build_report_model  # noqa: E402
from e2e.collect import collect_far_ends, make_client, plan  # noqa: E402
from e2e.sources import Inventory  # noqa: E402

NOKIA_CAPS = [{"capability": "urn:nokia.com:sros:ns:yang:sr:state?module=nokia-state"}]
CISCO_CAPS = [{"capability": "http://cisco.com/ns/yang/Cisco-IOS-XR-l2vpn-cfg?module=Cisco-IOS-XR-l2vpn-cfg"}]
DATA_MISSING = {"errors": {"error": [{"error-tag": "data-missing", "error-message":
                "Request could not be completed because the relevant data model content does not exist"}]}}


class FakeOdl(BaseHTTPRequestHandler):
    calls = []

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        FakeOdl.calls.append(("GET", self.path))
        if "yang-ext:mount" not in self.path:
            nodes = [{"node-id": NOKIA, "netconf-node-topology:connection-status": "connected",
                      "netconf-node-topology:available-capabilities": {"available-capability": NOKIA_CAPS}},
                     {"node-id": CISCO, "netconf-node-topology:netconf-node": {
                         "connection-status": "connected", "available-capabilities": {"available-capability": CISCO_CAPS}}},
                     {"node-id": "9.9.9.9", "netconf-node-topology:connection-status": "connecting"}]
            return self._send(200, {"network-topology:topology": [{"node": nodes}]})
        data = cisco_data(ac_state="im-state-up")
        if "xconnect-groups" in self.path:
            return self._send(409, DATA_MISSING)
        for qid, key in (("cisco-l2vpn-config", "l2vpn-cfg:l2vpn/database"), ("e2e-bridge-ports", "l2fib-bridge-ports"),
                         ("cisco-l2vpn", "l2vpn-forwarding/nodes"), ("cisco-rib-ipv4", "ip-rib-ipv4-oper"),
                         ("cisco-ethernet-stats", "drivers-media-eth-oper"),
                         ("cisco-interfaces-xr", "pfi-im-cmd-oper"), ("e2e-interface-config", "ifmgr-cfg"),
                         ("cisco-lldp-native", "ethernet-lldp-oper")):
            if key in self.path:
                return self._send(200, data[qid])
        return self._send(200, {})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        FakeOdl.calls.append(("POST", self.path))
        d = nokia_data()
        for marker, qid in (("<service/></configure>", "config-services"), ("<router/></configure>", "config-router-config"),
                            ("<epipe/>", "epipe-state"), ("<vpls/>", "vpls-state"), ("<sdp/>", "sdp-state"),
                            ("<lldp/>", "lldp"), ("<lsp/>", "mpls-lsp-state"), ("<rsvp/>", "rsvp"),
                            ("<router><interface/>", "router-interface-state"), ("<lag/>", "lag"),
                            ("<port/></state>", "port-state"), ("<system/>", "system")):
            if marker in body:
                return self._send(200, {"ietf-netconf:output": {"data": d.get(qid, {})}})
        return self._send(200, {"ietf-netconf:output": {"data": {}}})

    def log_message(self, *a):
        pass


class CollectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeOdl)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.nokia_dir = os.path.join(self.tmp.name, "store")
        self.cisco_dir = os.path.join(self.tmp.name, "results")
        write_store(self.nokia_dir, NOKIA, nokia_data())  # only the local router is saved
        self.map = {"2.2.2.2": CISCO}                     # the Cisco far end is mounted by another address
        self.client = make_client(self.url)
        self.client.user = ""

    def tearDown(self):
        self.tmp.cleanup()

    def inv(self):
        return Inventory(self.nokia_dir, self.cisco_dir, loopback_map=self.map)

    def test_plan_lists_vendor_and_skip_reasons(self):
        p = {i["ip"]: i for i in plan(NOKIA, self.client, self.inv())}
        self.assertEqual(p["2.2.2.2"]["action"], "fetch")
        self.assertEqual(p["2.2.2.2"]["vendor"], "cisco")
        self.assertEqual(p["2.2.2.2"]["odlNode"], CISCO)
        self.assertEqual(p["9.9.9.9"]["action"], "skip")
        self.assertIn("connecting", p["9.9.9.9"]["reason"])

    def test_collect_then_far_end_is_matched(self):
        before = build_report_model(NOKIA, self.inv())
        s = next(x for x in before["services"] if x["key"] == "epipe:100")
        self.assertEqual(s["legs"][0]["farEnd"]["status"], "not-collected")

        res = collect_far_ends(NOKIA, self.client, self.inv(), log=lambda *_: None)
        fetched = [r for r in res if r["action"] == "fetched"]
        self.assertEqual([r["ip"] for r in fetched], ["2.2.2.2"])
        self.assertEqual(fetched[0]["failed"], [])
        saved = os.listdir(os.path.join(self.cisco_dir, CISCO))
        self.assertTrue(any(f.endswith("_e2e-xconnect-config.json") for f in saved))  # data-missing saved as empty
        self.assertFalse(any(f.endswith("-error.json") for f in saved))

        after = build_report_model(NOKIA, self.inv())
        s = next(x for x in after["services"] if x["key"] == "epipe:100")
        self.assertEqual(s["legs"][0]["farEnd"]["status"], "matched")
        self.assertEqual(s["legs"][0]["remote"]["key"], "p2p:G/X100")
        self.assertEqual(s["legs"][0]["remotePw"]["oper"], "up")  # far-end PW state from its L2FIB data
        self.assertEqual(s["status"], "up")
        self.assertTrue(all(m == "GET" for m, p in FakeOdl.calls if "yang-ext:mount" in p and CISCO in p))

    def test_nokia_far_end_saved_in_store_format(self):
        cisco_local = os.path.join(self.tmp.name, "results2")
        write_store(cisco_local, CISCO, cisco_data(ac_state="im-state-up"))
        inv = Inventory(os.path.join(self.tmp.name, "store2"), cisco_local, loopback_map={})
        res = collect_far_ends(CISCO, self.client, inv, log=lambda *_: None)
        self.assertEqual([r["ip"] for r in res if r["action"] == "fetched"], [NOKIA])
        rec_files = os.listdir(os.path.join(self.tmp.name, "store2", NOKIA))
        self.assertTrue(any(f.endswith("_config-services.json") for f in rec_files))
        m = build_report_model(CISCO, Inventory(os.path.join(self.tmp.name, "store2"), cisco_local, loopback_map={}))
        p2p = next(x for x in m["services"] if x["key"] == "p2p:G/X100")
        self.assertEqual(p2p["legs"][0]["farEnd"]["status"], "matched")
        self.assertEqual(p2p["legs"][0]["remote"]["name"], "cust-100")


if __name__ == "__main__":
    unittest.main()
