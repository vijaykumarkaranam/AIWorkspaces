r"""Run Cisco IOS-XR NETCONF queries through ODL, save each response, and print what is configured.

Examples (PowerShell, after setting ODL_USER / ODL_PASSWORD as for the Nokia viewer):
  python run_queries.py --node <router-ip> --capabilities    which models the device serves
  python run_queries.py --list                               the query catalogue
  python run_queries.py --node <router-ip> --query oc-interfaces --query oc-lldp
  python run_queries.py --node <router-ip> --all             every query in queries.py

Responses are saved under results\<node>\<time>_<query>.json.
Capabilities are saved as results\<node>\<time>_capabilities.json.
"""
import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from odl_client import NotMountedError, OdlClient, OdlError, TOPOLOGY  # noqa: E402
import queries  # noqa: E402

RESULTS = os.path.join(HERE, "results")
NAME_KEYS = ("name", "interface-name", "neighbor-id", "neighbor-address", "address", "vrf-name",
             "instance-name", "component-name", "id")


def stamp():
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def safe(text):
    return "".join(c if c.isalnum() or c in "-._" else "_" for c in str(text))[:80]


def save(node, name, payload):
    folder = os.path.join(RESULTS, safe(node))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{stamp()}_{safe(name)}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, default=str)
    return path


def walk_lists(obj, path="", out=None):
    """Every list of records in a response: (path, rows)."""
    if out is None:
        out = []
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj):
            out.append((path or "(root)", obj))
        for i, x in enumerate(obj):
            walk_lists(x, path, out)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            walk_lists(v, f"{path}/{k}" if path else k, out)
    return out


def sample_names(rows, limit=6):
    names = []
    for r in rows:
        for k in NAME_KEYS:
            if k in r and not isinstance(r[k], (dict, list)):
                names.append(str(r[k]))
                break
        if len(names) >= limit:
            break
    return names


def print_summary(data):
    """What is in the response: each list with its count and a few names."""
    lists = walk_lists(data)
    lists = [(p, rows) for p, rows in lists if len(rows) >= 1]
    if not lists:
        print("    no list data (the response may be a single object or empty)")
        return
    for path, rows in lists[:25]:
        names = sample_names(rows)
        more = f" ... (+{len(rows) - len(names)})" if len(rows) > len(names) else ""
        print(f"    {path}: {len(rows)} item(s)  e.g. {', '.join(names)}{more}")
    if len(lists) > 25:
        print(f"    ... {len(lists) - 25} more lists in the saved file")


def run_query(client, node, qid):
    q = queries.QUERIES[qid]
    kind = "config" if q["kind"] == "config" else "state"
    print(f"\n== {qid}: {q['label']}")
    used, note = None, ""
    try:
        if qid in queries.DATA_PATHS:
            data, used, note = queries.fetch(client, node, qid)  # tries each alternative path in order
        else:
            data = client.netconf_get(node, kind, q["filter"])
    except NotMountedError:
        raise  # nothing to save: the router is not on this controller, so every query would fail
    except OdlError as exc:
        print(f"    ERROR: {exc}")
        save(node, qid + "-error", {"node": node, "query": qid, "error": str(exc)})
        return False
    path = save(node, qid, {"node": node, "query": qid, "label": q["label"], "path": used, "note": note,
                            "fetchedAt": dt.datetime.now().isoformat(timespec="seconds"), "data": data})
    print(f"    OK, saved {os.path.relpath(path, HERE)}" + (f"  [{note}]" if note else ""))
    if used and len(queries.paths_for(qid)) > 1:
        print(f"    path used: {used}")
    print_summary(data)
    return True


def capabilities(client, node):
    """Models ODL loaded for the device, and the ones it could not load, with the reason."""
    status, text = client._request("GET", f"{TOPOLOGY}/node={node}?content=nonconfig")
    data = client._parse(status, text)
    nodes = (data.get("network-topology:topology") or [{}])[0].get("node", [])
    if not nodes:
        raise OdlError(f"node {node} is not mounted in ODL")
    n = nodes[0]
    avail = [c.get("capability", "") for c in
             (n.get("netconf-node-topology:available-capabilities", {}) or {}).get("available-capability", [])]
    unavail = [c for c in
               (n.get("netconf-node-topology:unavailable-capabilities", {}) or {}).get("unavailable-capability", [])]
    path = save(node, "capabilities", {"node": node, "status": n.get("netconf-node-topology:connection-status"),
                                       "available": avail, "unavailable": unavail})
    print(f"Node {node}: {n.get('netconf-node-topology:connection-status', '?')}")
    print(f"Available models: {len(avail)}   unavailable: {len(unavail)}   saved {os.path.relpath(path, HERE)}")
    cisco_or_oc = [c for c in avail if "openconfig" in c.lower() or "cisco" in c.lower()]
    print(f"\nOpenConfig or Cisco models available ({len(cisco_or_oc)}):")
    for c in sorted(cisco_or_oc):
        print("  " + c.split("?")[0])
    reasons = {}
    for u in unavail:
        reasons.setdefault(u.get("failure-reason", "?"), 0)
        reasons[u.get("failure-reason", "?")] += 1
    print("\nUnavailable models by reason:", reasons)


def main():
    ap = argparse.ArgumentParser(description="Cisco IOS-XR NETCONF queries through ODL")
    ap.add_argument("--node", help="device IP or node id as mounted in ODL")
    ap.add_argument("--capabilities", action="store_true", help="show the models the device serves")
    ap.add_argument("--list", action="store_true", help="list the query catalogue and exit")
    ap.add_argument("--query", action="append", default=[], help="query id (repeatable)")
    ap.add_argument("--all", action="store_true", help="run every query")
    ap.add_argument("--odl", default=None, help="ODL base URL (default: $ODL_BASE)")
    ap.add_argument("--pause", action="store_true", help="wait for Enter before each query")
    a = ap.parse_args()

    if a.list:
        for qid, q in queries.QUERIES.items():
            print(f"{qid:28} {q['kind']:6} {q['label']}")
        return
    if not a.node:
        ap.error("--node is required")
    client = OdlClient(base=a.odl)
    if a.capabilities:
        try:
            capabilities(client, a.node)
        except OdlError as exc:
            print(f"ERROR: {exc}")
    ids = list(queries.QUERIES) if a.all else a.query
    if ids:
        try:
            mounted, status = client.is_mounted(a.node)
        except OdlError as exc:
            print(f"ERROR: {exc}")
            sys.exit(2)
        if not mounted:
            print(f"ERROR: node {a.node} is not mounted on ODL {client.base}.\n"
                  f"  Check ODL_BASE: dev and prod controllers mount different routers. Use the controller whose\n"
                  f"  RESTCONF URLs work for this router (the same base URL as in Postman or the E2E dashboard).")
            sys.exit(2)
        if status and status != "connected":
            print(f"WARNING: node {a.node} is mounted on {client.base} but its NETCONF session is '{status}'.")
    ok = 0
    failed = []
    for qid in ids:
        if qid not in queries.QUERIES:
            print(f"unknown query: {qid}")
            continue
        if a.pause:
            input(f"\nPress Enter to run {qid} (Ctrl+C to stop)...")
        try:
            done = run_query(client, a.node, qid)
        except NotMountedError as exc:
            print(f"    ERROR: {exc}\nStopped: the remaining queries would fail the same way.")
            sys.exit(2)
        if done:
            ok += 1
        else:
            failed.append(qid)
    if failed:
        print("\nNOT RETURNING DATA: " + ", ".join(failed))
    if ids:
        print(f"\n{ok} of {len(ids)} queries returned data. Results are in {os.path.relpath(RESULTS, HERE)}\\{safe(a.node)}")


if __name__ == "__main__":
    main()
