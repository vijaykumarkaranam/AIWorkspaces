"""Offline generator: run queries against ODL and write one self-contained HTML file.

Example:
  python generate.py --node 162.104.38.226 --query epipe-state --query vpls-state --cli "service fdb-mac"

Options:
  --save-dir DIR   also save each raw response as JSON (for the older build_device_report.py)
  --out FILE       output HTML (default: <node>_view.html next to this script)
  --odl URL        ODL base URL (default: $ODL_BASE)

Each query that fails is recorded in the file with its error, so the rest still get generated.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from odl_client import OdlClient, OdlError  # noqa: E402
import analyze  # noqa: E402
import queries  # noqa: E402
import store  # noqa: E402


def slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()


def main():
    ap = argparse.ArgumentParser(description="Generate an offline NETCONF view for one Nokia node")
    ap.add_argument("--node", required=True, help="node id, e.g. 162.104.38.226")
    ap.add_argument("--query", action="append", default=[], help="named query id (repeatable)")
    ap.add_argument("--cli", action="append", default=[], help="read-only CLI show command (repeatable)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--title", default=None)
    ap.add_argument("--odl", default=None)
    ap.add_argument("--save-dir", default=None)
    ap.add_argument("--all", action="store_true",
                    help="run every named query (config first), save all JSON, and write one report")
    a = ap.parse_args()

    if a.all:
        config_ids = [q for q, v in queries.QUERIES.items() if v["kind"] == "config"]
        other_ids = [q for q in queries.QUERIES if q not in config_ids]
        a.query = config_ids + other_ids
        if not a.save_dir:
            a.save_dir = os.path.join(HERE, "exports", slug(a.node), dt.datetime.now().strftime("%Y%m%d-%H%M%S"))

    if not a.query and not a.cli:
        ap.error("give at least one --query or --cli, or use --all")

    client = OdlClient(base=a.odl)
    requests = [{"node": a.node, "query": q} for q in a.query] + [{"node": a.node, "cli": c} for c in a.cli]
    results = []
    for req in requests:
        label = queries.QUERIES[req["query"]]["label"] if req.get("query") in queries.QUERIES else f"CLI: {req.get('cli')}"
        try:
            res = queries.run_request(client, req)
            config = store.latest_data(a.node, "config-services")
            res["findings"] = analyze.analyze(res["data"], config)
            res["savedTo"] = store.save(res)
            results.append(res)
            print(f"ok    {label}")
            if a.save_dir:
                os.makedirs(a.save_dir, exist_ok=True)
                path = os.path.join(a.save_dir, slug(label) + "-response.json")
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(res["data"], fh, indent=1)
        except (OdlError, ValueError) as exc:
            results.append({"node": a.node, "query": req.get("query"), "label": label, "error": str(exc)})
            print(f"FAIL  {label}: {exc}")

    embed = {"mode": "offline", "node": a.node,
             "generatedAt": dt.datetime.now().isoformat(timespec="minutes"), "results": results}
    with open(os.path.join(HERE, "index.html"), encoding="utf-8") as fh:
        template = fh.read()
    payload = json.dumps(embed, default=str).replace("</", "<\\/")
    title = a.title or f"Nokia Device insights: {a.node}"
    html = template.replace("/*__EMBED__*/null", payload).replace("__TITLE__", title)

    out = a.out or os.path.join(HERE, f"{a.node}_view.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    ok = sum(1 for r in results if "error" not in r)
    print(f"Wrote {out} ({os.path.getsize(out) / 1e6:.2f} MB): {ok} of {len(results)} queries ok")


if __name__ == "__main__":
    main()
