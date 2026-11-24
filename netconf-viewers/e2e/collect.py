r"""Fetch the far-end PEs of one router's services through ODL and save them in the stores.

For every far end that has no saved data yet:
  1. look it up in the ODL NETCONF topology (by its address, or by e2e\loopback_map.json)
  2. tell Nokia from Cisco by the YANG modules the node advertises
  3. run the small far-end query set (nokia.FAR_END_QUERIES or cisco.FAR_END_QUERIES)
  4. save each answer where the tools look for it:
       Nokia -> nokia_view\store\<node>\<time>_<query>.json   (same format as store.py)
       Cisco -> cisco_iosxr\results\<node>\<time>_<query>.json (same format as run_queries.py)
Every request is a read (NETCONF get / get-config or RESTCONF GET). Nothing is changed on a router.

Usage (from the netconf-viewers folder, with ODL_BASE / ODL_USER / ODL_PASSWORD set as for the viewers):
  python -m e2e.collect --node 192.0.2.10 --dry-run     list the far ends and where they would come from
  python -m e2e.collect --node 192.0.2.10               fetch them
"""
import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor

from . import cisco, nokia
from .sources import ROOT, Inventory
from .stitch import build_report_model

EMPTY_ERRORS = ("data-missing", "relevant data model content does not exist")
_lock = threading.Lock()


def _load(rel_path, name):
    """Import a module from a file under ROOT with a unique name (both tools have a queries.py)."""
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _modules():
    if not hasattr(_modules, "cache"):
        _modules.cache = (_load(os.path.join("cisco_iosxr", "odl_client.py"), "e2e_odl_client"),
                          _load(os.path.join("nokia_view", "queries.py"), "e2e_nokia_queries"),
                          _load(os.path.join("cisco_iosxr", "queries.py"), "e2e_cisco_queries"))
    return _modules.cache


def make_client(odl=None):
    """ODL client (the Cisco copy: it has netconf_get for Nokia and data_get for Cisco)."""
    return _modules()[0].OdlClient(base=odl)


def classify_vendor(node):
    """'nokia', 'cisco' or None from the capabilities ODL lists for a topology node."""
    nn = node.get("netconf-node-topology:netconf-node") or node
    cont = (nn.get("available-capabilities") or node.get("netconf-node-topology:available-capabilities")
            or node.get("available-capabilities") or {})
    caps = " ".join((c if isinstance(c, str) else (c or {}).get("capability", ""))
                    for c in cont.get("available-capability", [])).lower()
    is_cisco, is_nokia = "cisco-ios-xr" in caps or "cisco.com" in caps, "nokia" in caps or "alcatel" in caps
    if is_cisco != is_nokia:
        return "cisco" if is_cisco else "nokia"
    return None


def topology(client):
    """{node id: {"status": ..., "vendor": ...}} for every NETCONF node mounted in ODL."""
    mod = _modules()[0]
    status, body = client._request("GET", mod.TOPOLOGY + "?content=nonconfig")
    data = client._parse(status, body)
    out = {}
    for n in ((data.get("network-topology:topology") or [{}])[0].get("node") or []):
        nid = n.get("node-id")
        if not nid or nid == "controller-config":
            continue
        nn = n.get("netconf-node-topology:netconf-node") or n
        st = nn.get("connection-status") or n.get("netconf-node-topology:connection-status") or ""
        out[nid] = {"status": st, "vendor": classify_vendor(n)}
    return out


def _safe(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(text or "")).strip("_")[:80] or "item"


def _stamp():
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _write(folder, name, payload):
    with _lock:
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{_stamp()}_{name}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1, default=str)
    return path


def fetch_nokia(client, node, store_dir, qids=None, log=print):
    """Run the Nokia far-end queries for one node and save them in the Nokia store format."""
    _odl, nq, _cq = _modules()
    ok, failed = [], []
    for qid in qids or nokia.FAR_END_QUERIES:
        q = nq.QUERIES[qid]
        try:
            data = (client.cli_show(node, q["command"]) if q["kind"] == "cli"
                    else client.netconf_get(node, q["kind"], q["filter"]))
        except Exception as exc:  # OdlError or a network error: record it and carry on
            failed.append(f"{qid}: {str(exc)[:200]}")
            log(f"  {node} {qid}: ERROR {str(exc)[:160]}")
            continue
        _write(os.path.join(store_dir, _safe(node)), _safe(qid),
               {"node": node, "query": qid, "label": q["label"],
                "fetchedAt": dt.datetime.now().isoformat(timespec="seconds"), "data": data, "findings": []})
        ok.append(qid)
        log(f"  {node} {qid}: ok")
    return ok, failed


def fetch_cisco(client, node, results_dir, qids=None, log=print):
    """Run the Cisco far-end queries for one node and save them in the cisco_iosxr results format."""
    _odl, _nq, cq = _modules()
    ok, failed = [], []
    folder = os.path.join(results_dir, _safe(node))
    for qid in qids or cisco.FAR_END_QUERIES:
        label = cq.QUERIES.get(qid, {}).get("label", qid)
        try:
            data = client.data_get(node, cq.DATA_PATHS[qid])
        except Exception as exc:
            msg = str(exc)
            if any(x in msg for x in EMPTY_ERRORS):
                data = {}  # nothing configured under this path on the router: an empty answer, not a failure
            else:
                _write(folder, _safe(qid) + "-error", {"node": node, "query": qid, "error": msg})
                failed.append(f"{qid}: {msg[:200]}")
                log(f"  {node} {qid}: ERROR {msg[:160]}")
                continue
        _write(folder, _safe(qid), {"node": node, "query": qid, "label": label,
                                    "fetchedAt": dt.datetime.now().isoformat(timespec="seconds"), "data": data})
        ok.append(qid)
        log(f"  {node} {qid}: ok" + (" (nothing configured)" if data == {} else ""))
    return ok, failed


def plan(node, client, inv=None):
    """Far ends without saved data, each with the ODL node to ask and its vendor, or why it cannot be fetched."""
    inv = inv or Inventory()
    model = build_report_model(node, inv)
    if model.get("error"):
        raise ValueError(model["error"])
    topo = topology(client)
    out = []
    for f in model["farEnds"]:
        if f["collected"]:
            continue
        odl_node = inv.odl_node_for(f["ip"])
        t = topo.get(odl_node)
        item = {"ip": f["ip"], "odlNode": odl_node, "services": f["services"], "vendor": None, "action": "skip"}
        if t is None:
            item["reason"] = ("not mounted in ODL under this address. If ODL mounts it by another address, "
                              "add it to e2e/loopback_map.json")
        elif str(t["status"]).lower() != "connected":
            item["reason"] = f"mounted but {t['status'] or 'not connected'}"
        elif not t["vendor"]:
            item["reason"] = "vendor not recognised from its NETCONF capabilities"
        else:
            item.update(vendor=t["vendor"], action="fetch", reason="")
        out.append(item)
    return out


def collect_far_ends(node, client=None, inv=None, workers=4, limit=100, log=print):
    """Fetch every far end of `node` that has no saved data. Returns one result per far end."""
    inv = inv or Inventory()
    client = client or make_client()
    items = plan(node, client, inv)
    todo = [i for i in items if i["action"] == "fetch"][:limit]
    log(f"{node}: {len(items)} far end(s) without data, {len(todo)} to fetch")

    def run(item):
        if item["vendor"] == "nokia":
            ok, failed = fetch_nokia(client, item["odlNode"], inv.dirs["nokia"], log=log)
        else:
            ok, failed = fetch_cisco(client, item["odlNode"], inv.dirs["cisco"], log=log)
        item.update(ok=ok, failed=failed, action="fetched")
        return item

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(run, todo))
    return items


def main():
    ap = argparse.ArgumentParser(description="Fetch the far-end PEs of a router's services through ODL")
    ap.add_argument("--node", required=True, help="router as mounted in ODL, e.g. 192.0.2.10")
    ap.add_argument("--odl", default=None, help="ODL base URL (default: $ODL_BASE)")
    ap.add_argument("--workers", type=int, default=4, help="far-end routers fetched in parallel")
    ap.add_argument("--limit", type=int, default=100, help="at most this many far-end routers")
    ap.add_argument("--dry-run", action="store_true", help="only list the far ends and what would be fetched")
    a = ap.parse_args()
    client = make_client(a.odl)
    if a.dry_run:
        for i in plan(a.node, client):
            print(f"{i['ip']:16} {i['action']:6} {i['vendor'] or '':6} ODL node {i['odlNode']}  {i.get('reason', '')}")
        return
    res = collect_far_ends(a.node, client, workers=a.workers, limit=a.limit)
    done = [r for r in res if r["action"] == "fetched"]
    print(f"\nFetched {len(done)} far-end router(s); {sum(1 for r in res if r['action'] == 'skip')} skipped.")
    for r in res:
        if r["action"] == "skip":
            print(f"  skipped {r['ip']}: {r['reason']}")
        elif r.get("failed"):
            print(f"  {r['ip']}: {len(r['failed'])} query error(s): " + "; ".join(r["failed"])[:300])
    print("Rebuild the report to see the far ends.")


if __name__ == "__main__":
    main()
