#!/usr/bin/env python3
"""
Parse the NETCONF CLI-show response for "service fdb-mac" into a CSV.

Input : the saved response JSON (ietf-netconf:output -> oper-data-format-cli-block
        -> item -> response), or a plain text file containing the CLI table.
Output: CSV with one row per MAC entry.

Usage:
  python parse_fdb.py fdb_response.json [fdb_out.csv]
"""
import csv
import json
import re
import sys
from collections import Counter

# ServId  MAC  Source-Identifier  Type/Age  Last Change(date time)
ROW = re.compile(
    r"^(\d+)\s+([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})\s+(\S+)\s+(\S+)\s+"
    r"(\d{2}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s*$"
)
ENTRIES = re.compile(r"No\. of Entries:\s*(\d+)")


def load_text(path):
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    if path.lower().endswith(".json") or raw.lstrip().startswith("{"):
        obj = json.loads(raw)
        out = obj.get("ietf-netconf:output", obj)
        return out["data"]["oper-data-format-cli-block"]["item"]["response"]
    return raw


def parse_source(source):
    """Split 'sap:1/1/1:951.*', 'sdp:197:46150', 'cpm' into transport and detail."""
    parts = source.split(":")
    kind = parts[0]
    if kind == "sap" and len(parts) >= 3:
        return kind, parts[1], parts[2]          # port, vlan/encap
    if kind == "sdp" and len(parts) >= 3:
        return kind, parts[1], parts[2]          # sdp-id, vc-id
    return kind, "", ""


def parse(text):
    rows = []
    for line in text.splitlines():
        m = ROW.match(line.strip())
        if not m:
            continue
        serv, mac, source, type_age, date, time = m.groups()
        kind, detail1, detail2 = parse_source(source)
        if "/" in type_age:
            ftype, age = type_age.split("/", 1)
        else:
            ftype, age = type_age, ""
        rows.append({
            "service_id": serv,
            "mac": mac.lower(),
            "source": source,
            "transport": kind,
            "port_or_sdp": detail1,
            "vlan_or_vc": detail2,
            "entry_type": ftype,          # L=learned, S=static, O=OAM, P=protected, C=conditional, Intf
            "age_seconds": age,
            "last_change": f"{date} {time}",
        })
    expected = ENTRIES.search(text)
    return rows, int(expected.group(1)) if expected else None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else src.rsplit(".", 1)[0] + "_fdb.csv"

    rows, expected = parse(load_text(src))
    with open(dst, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["service_id"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Parsed {len(rows)} entries -> {dst}")
    if expected is not None:
        status = "OK" if expected == len(rows) else "MISMATCH"
        print(f"Device reports {expected} entries: {status}")
    for serv, n in sorted(Counter(r["service_id"] for r in rows).items(), key=lambda x: int(x[0])):
        print(f"  service {serv}: {n}")


if __name__ == "__main__":
    main()
