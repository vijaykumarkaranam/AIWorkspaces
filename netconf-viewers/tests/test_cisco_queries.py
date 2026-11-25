"""Cisco query paths: alternatives by node location, data-missing handling, and the dashboard's reads."""
import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_e2e import NOKIA, cisco_data  # noqa: E402
from e2e import cisco  # noqa: E402


def load(rel, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


Q = load(os.path.join("cisco_iosxr", "queries.py"), "cq_test")


class OdlError(Exception):
    pass


MISSING = "Request could not be completed because the relevant data model content does not exist"


class FakeClient:
    """data_get answers from a dict of path -> data or exception text."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def data_get(self, node, path):
        self.calls.append(path)
        a = self.answers.get(path, MISSING)
        if isinstance(a, str):
            raise OdlError(a)
        return a


class FetchTest(unittest.TestCase):
    def test_dashboard_urls_are_in_the_tool(self):
        """Every URL the working E2E dashboard uses is one of the tool's paths (with the RP0 location)."""
        working = [
            "Cisco-IOS-XR-ethernet-lldp-oper:lldp/nodes?content=nonconfig",
            "Cisco-IOS-XR-ifmgr-cfg:interface-configurations?content=config&depth=5",
            "Cisco-IOS-XR-mpls-ldp-oper:mpls-ldp/global/active/default-vrf/neighbors",
            "Cisco-IOS-XR-mpls-ldp-oper:mpls-ldp/global/active/default-vrf/afs/af=ipv4/bindings?content=nonconfig&depth=4",
            "Cisco-IOS-XR-mpls-lsd-oper:mpls-lsd-nodes/mpls-lsd-node=0%2FRP0%2FCPU0/label-summary?content=nonconfig",
            "Cisco-IOS-XR-l2vpn-oper:l2vpnv2/active/xconnects?content=nonconfig&depth=4",
            "Cisco-IOS-XR-l2vpn-oper:l2vpn-forwarding/nodes/node=0%2FRP0%2FCPU0/l2fib-bridge-ports?content=nonconfig&depth=5",
            "Cisco-IOS-XR-l2vpn-oper:l2vpn-forwarding/nodes/node=0%2FRP0%2FCPU0/l2fibx-cons?content=nonconfig&depth=5",
            "Cisco-IOS-XR-mpls-ldp-oper:mpls-ldp/global/active/default-vrf/afs/af=ipv4/bindings?content=nonconfig&depth=3",
            "Cisco-IOS-XR-fib-common-oper:mpls-forwarding/nodes/node=0%2FRP0%2FCPU0/forwarding-summary?content=nonconfig",
            "Cisco-IOS-XR-l2vpn-cfg:l2vpn/database/xconnect-groups?content=config",
            "Cisco-IOS-XR-l2vpn-cfg:l2vpn/database/bridge-domain-groups?content=config",
        ]
        tool = {p for qid in Q.DATA_PATHS for p in Q.paths_for(qid)}
        self.assertEqual([w for w in working if w not in tool], [])
        for qid in ("e2e-bridge-config", "e2e-l2fibx-cons", "e2e-mpls-lsd-labels"):
            self.assertIn(qid, Q.QUERIES)  # enabled: run by --all and by the viewer

    def test_falls_through_missing_locations(self):
        rp0, cpu0 = Q.paths_for("e2e-l2fibx-cons")[:2]
        c = FakeClient({cpu0: {"x": 1}})  # this router has its L2FIB on 0/0/CPU0
        data, used, note = Q.fetch(c, "n", "e2e-l2fibx-cons")
        self.assertEqual((data, used, note), ({"x": 1}, cpu0, ""))
        self.assertEqual(c.calls[:2], [rp0, cpu0])

    def test_first_location_wins_when_it_answers(self):
        rp0 = Q.paths_for("e2e-bridge-ports")[0]
        c = FakeClient({rp0: {"ok": 1}})
        self.assertEqual(Q.fetch(c, "n", "e2e-bridge-ports")[1], rp0)
        self.assertEqual(len(c.calls), 1)

    def test_all_missing_is_empty_not_error(self):
        data, used, note = Q.fetch(FakeClient({}), "n", "e2e-xconnect-config")
        self.assertEqual(data, {})
        self.assertIn("nothing configured", note)

    def test_real_error_on_every_path_raises_with_paths(self):
        paths = Q.paths_for("cisco-l2vpn")
        c = FakeClient({p: "HTTP 500: timeout" for p in paths})
        with self.assertRaises(OdlError) as ctx:
            Q.fetch(c, "n", "cisco-l2vpn")
        self.assertIn("paths tried", str(ctx.exception))
        self.assertEqual(len(c.calls), len(paths))

    def test_error_then_success_uses_the_working_path(self):
        whole, nodes = Q.paths_for("cisco-lldp-native")
        c = FakeClient({whole: "HTTP 500: too big", nodes: {"Cisco-IOS-XR-ethernet-lldp-oper:nodes": {"node": []}}})
        self.assertEqual(Q.fetch(c, "n", "cisco-lldp-native")[1], nodes)


MOUNT_ERROR = {"errors": {"error": [{"error-tag": "resource-denied-transport", "error-message": "Mount point does not exist",
                                     "error-path": "/network-topology:network-topology/topology[topology-id='topology-netconf']"
                                                   "/node[node-id='10.137.76.18']", "error-type": "protocol"}]}}


class NotMountedTest(unittest.TestCase):
    """The error seen when the tool talks to a controller that does not have the router (dev vs prod)."""

    @classmethod
    def setUpClass(cls):
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        class Odl(BaseHTTPRequestHandler):
            def do_GET(self):
                if "yang-ext:mount" in self.path or "node=10.137.76.18" in self.path:
                    code, body = (409, MOUNT_ERROR) if "yang-ext:mount" in self.path else (409, {"errors": {"error": [
                        {"error-tag": "data-missing", "error-message": "Request could not be completed because the relevant data model content does not exist"}]}})
                else:  # node 10.0.0.2 is mounted here
                    code, body = 200, {"network-topology:node": [{"node-id": "10.0.0.2",
                                                                  "netconf-node-topology:connection-status": "connected"}]}
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Odl)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        cls.mod = load(os.path.join("cisco_iosxr", "odl_client.py"), "odl_client_nm")

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def client(self):
        return self.mod.OdlClient(base=self.base, user="", password="")

    def test_error_names_node_and_controller(self):
        with self.assertRaises(self.mod.NotMountedError) as ctx:
            self.client().data_get("10.137.76.18", "Cisco-IOS-XR-l2vpn-cfg:l2vpn/database/xconnect-groups?content=config")
        msg = str(ctx.exception)
        self.assertIn("node 10.137.76.18 is not mounted on ODL " + self.base, msg)
        self.assertIn("dev and prod", msg)
        self.assertIsInstance(ctx.exception, self.mod.OdlError)  # existing handlers still catch it

    def test_fetch_stops_at_the_first_not_mounted_answer(self):
        c = self.client()
        calls = []
        orig = c.data_get
        c.data_get = lambda n, p: (calls.append(p), orig(n, p))[1]
        with self.assertRaises(self.mod.NotMountedError):
            Q.fetch(c, "10.137.76.18", "e2e-l2fibx-cons")  # three location alternatives, but one call is enough
        self.assertEqual(len(calls), 1)

    def test_is_mounted(self):
        self.assertEqual(self.client().is_mounted("10.0.0.2"), (True, "connected"))
        self.assertEqual(self.client().is_mounted("10.137.76.18"), (False, ""))


TIMEOUT = ('Transaction(GET) failed Task was cancelled. | raw response: {"errors": {"error": [{"error-tag": '
           '"operation-failed", "error-info": "Task was cancelled.", "error-message": "Transaction(GET) failed"}]}}')


class ReconnectClient(FakeClient):
    """A router whose session ODL drops after a timeout and reopens a few checks later."""

    def __init__(self, answers, states):
        super().__init__(answers)
        self.states = list(states)  # what is_mounted reports, one entry per check

    def is_mounted(self, node):
        st = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return (st is not None), (st or "")


class TimeoutReconnectTest(unittest.TestCase):
    def setUp(self):
        self.slept = []
        self._sleep = Q.SLEEP
        Q.SLEEP = self.slept.append

    def tearDown(self):
        Q.SLEEP = self._sleep

    def test_timeout_waits_for_reconnect_and_does_not_try_other_locations(self):
        paths = Q.paths_for("cisco-l2vpn")
        c = ReconnectClient({paths[0]: TIMEOUT}, ["connecting", "connecting", "connected"])
        with self.assertRaises(OdlError) as ctx:
            Q.fetch(c, "10.137.76.18", "cisco-l2vpn")
        msg = str(ctx.exception)
        self.assertIn("ODL timed out waiting for 10.137.76.18", msg)
        self.assertIn("ODL has reconnected the router", msg)
        self.assertEqual(c.calls, [paths[0]])      # 0/0/CPU0 and 0/RSP0/CPU0 were not tried
        self.assertEqual(self.slept, [5, 5])       # waited two checks for the session to come back

    def test_mount_missing_during_reconnect_is_retried(self):
        path = Q.paths_for("e2e-bridge-config")[0]

        class Flaky(ReconnectClient):
            def data_get(self, node, p):
                self.calls.append(p)
                if len(self.calls) == 1:
                    raise OdlError("node 10.137.76.18 is not mounted on ODL http://odl (Mount point does not exist)")
                return {"bd": 1}

        c = Flaky({}, ["connecting", "connected"])
        data, used, note = Q.fetch(c, "10.137.76.18", "e2e-bridge-config")
        self.assertEqual((data, used), ({"bd": 1}, path))
        self.assertIn("retried", note)

    def test_router_not_on_controller_fails_at_once(self):
        c = ReconnectClient({p: "Mount point does not exist" for p in Q.paths_for("e2e-bridge-config")}, [None])
        with self.assertRaises(OdlError):
            Q.fetch(c, "10.137.76.18", "e2e-bridge-config")
        self.assertEqual(self.slept, [])           # no waiting when ODL does not list the node at all

    def test_heavy_queries_run_last_and_service_queries_first(self):
        order = list(Q.QUERIES)
        self.assertEqual(order[0], "e2e-xconnect-config")
        self.assertEqual(order[-1], "cisco-cpu")
        self.assertLess(order.index("e2e-l2fibx-cons"), order.index("cisco-bgp-neighbors"))
        self.assertNotIn("cisco-l2vpn-config", Q.QUERIES)       # whole database: only on request
        self.assertTrue(all("l2fib-summary" in p for p in Q.paths_for("cisco-l2vpn")))


class MergedListsTest(unittest.TestCase):
    """Hundreds of bridge-domain groups give one table of bridge domains, with the group in an 'In' column."""

    def setUp(self):
        sys.path.insert(0, os.path.join(ROOT, "cisco_iosxr"))
        self.bcr = load(os.path.join("cisco_iosxr", "build_cisco_report.py"), "bcr_test")
        self.data = {"Cisco-IOS-XR-l2vpn-cfg:bridge-domain-groups": {"bridge-domain-group": [
            {"name": f"G{i}", "bridge-domains": {"bridge-domain": [{"name": f"BD{i}-{j}", "bridge-domain-mtu": 9100}
                                                                   for j in range(2)]}} for i in range(300)]}}

    def test_one_table_per_path(self):
        merged = {p: (items, owners) for p, items, owners in self.bcr.merged_lists(self.data)}
        items, owners = merged[("bridge-domain-groups", "bridge-domain-group", "bridge-domains", "bridge-domain")]
        self.assertEqual(len(items), 600)
        self.assertEqual(owners[0], "G0")
        lists = [t for t in self.bcr.build_tables(self.data) if t["kind"] == "list"]
        self.assertEqual(len(lists), 2)                         # groups, and all bridge domains
        bd = next(t for t in lists if t["count"] == 600)
        self.assertEqual(bd["columns"][0], "In")
        self.assertEqual(bd["rows"][599]["c"][:2], ["G299", "BD299-1"])

    def test_console_summary_is_short_and_named(self):
        import contextlib
        import io
        rq = load(os.path.join("cisco_iosxr", "run_queries.py"), "rq_test")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rq.print_summary(self.data)
        lines = buf.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("bridge-domain-group: 300  e.g. G0, G1", lines[0])
        self.assertIn("bridge-domain: 600  e.g. BD0-0", lines[1])


class AdapterTest(unittest.TestCase):
    def test_bridge_domains_from_bridge_domain_groups_query(self):
        d = cisco_data(ac_state="im-state-up")
        db = d.pop("cisco-l2vpn-config")["Cisco-IOS-XR-l2vpn-cfg:database"]
        d["e2e-bridge-config"] = {"Cisco-IOS-XR-l2vpn-cfg:bridge-domain-groups": db["bridge-domain-groups"]}
        d["e2e-xconnect-config"] = {"Cisco-IOS-XR-l2vpn-cfg:xconnect-groups": db["xconnect-groups"]}
        pe = cisco.pe_from_saved("10.0.0.2", d)
        self.assertEqual(sorted(e["key"] for e in pe["endpoints"]), ["bridge-domain:BG/BD200", "p2p:G/X100"])

    def test_xconnect_oper_state_and_vc_labels(self):
        d = cisco_data(ac_state="im-state-up")
        d.pop("cisco-l2vpn")  # no L2FIB: the PW state must come from the xconnect oper data
        d["e2e-xconnect-oper"] = {"Cisco-IOS-XR-l2vpn-oper:xconnects": {"xconnect": [{
            "group-name": "G", "xconnect-name": "X100", "state": "l2vpn-xc-state-down",
            "segment1": {"attachment-circuit": {"interface": {"name": "GigabitEthernet0/0/0/1.10"}, "state": "l2vpn-segment-state-up"}},
            "segment2": {"pseudo-wire": {"peer-id": {"ipv4": NOKIA}, "pseudo-wire-id": 100, "state": "l2vpn-pw-state-down",
                                         "local-label": 24001, "remote-label": 524000}}}]}}
        pe = cisco.pe_from_saved("10.0.0.2", d)
        x = next(e for e in pe["endpoints"] if e["key"] == "p2p:G/X100")
        self.assertEqual(x["oper"], "down")
        self.assertEqual(x["pws"][0]["oper"], "down")
        self.assertEqual(x["pws"][0]["pwLabels"], {"local": 24001, "remote": 524000})
        import json
        json.dumps(pe["objects"])  # the raw oper record must be JSON for the page

    def test_lldp_nodes_form(self):
        d = cisco_data(ac_state="im-state-up")
        whole = d["cisco-lldp-native"]["Cisco-IOS-XR-ethernet-lldp-oper:lldp"]
        d["cisco-lldp-native"] = {"Cisco-IOS-XR-ethernet-lldp-oper:nodes": whole["nodes"]}
        pe = cisco.pe_from_saved("10.0.0.2", d)
        x = next(e for e in pe["endpoints"] if e["key"] == "p2p:G/X100")
        self.assertEqual(x["acs"][0]["ce"]["name"], "CE-B")


if __name__ == "__main__":
    unittest.main()


class L2fibBridgeTest(unittest.TestCase):
    """Per-bridge-domain pseudowires from L2FIB cross-connects only (the dashboard's 'XConnects (L2FIB)' data)."""

    def test_bridge_id_mapped_by_its_ac_when_no_names_are_saved(self):
        d = cisco_data(ac_state="im-state-up")
        d.pop("e2e-bridge-ports")  # the big reads did not finish: only the cross-connects are saved
        d.pop("cisco-l2vpn")
        d["e2e-l2fibx-cons"] = {"Cisco-IOS-XR-l2vpn-oper:l2fibx-cons": {"l2fibx-con": [
            {"xcid": "1", "segment1": {"data-type": "mgmt-l2fib-data-type-ac", "ac": {"interface-name": "GigabitEthernet0/0/0/2.20"}},
             "segment2": {"data-type": "mgmt-l2fib-data-type-bridge-port", "bp": {"bridge-id": 7}}},
            {"xcid": "2", "segment1": {"data-type": "mgmt-l2fib-data-type-atom", "pw": {
                "next-hop-address": "10.9.9.1", "pw-id": "555", "next-hop-valid": True}},
             "segment2": {"data-type": "mgmt-l2fib-data-type-bridge-port", "bp": {"bridge-id": 7}}},
            {"xcid": "3", "segment1": {"data-type": "mgmt-l2fib-data-type-atom", "pw": {
                "next-hop-address": "10.9.9.2", "pw-id": "556", "next-hop-valid": False}},
             "segment2": {"data-type": "mgmt-l2fib-data-type-bridge-port", "bp": {"bridge-id": 8}}}]}}
        pe = cisco.pe_from_saved("10.0.0.2", d)
        bd = next(e for e in pe["endpoints"] if e["key"] == "bridge-domain:BG/BD200")
        self.assertEqual([(p["peer"], p["oper"]) for p in bd["pws"]], [("10.9.9.1", "up")])  # bridge 8 is another BD
