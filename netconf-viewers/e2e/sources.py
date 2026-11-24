r"""Find the newest saved data for every router in the Nokia store and the Cisco results folder.

Layouts (unchanged from the two tools):
  nokia_view\store\<node>\<YYYYmmdd-HHMMSS>_<query>.json           {"data": ..., or "error": ...}
  cisco_iosxr\results\<node>\<YYYYmmdd-HHMMSS>_<query>[-error].json {"data": ...} / {"error": ...}

Locations can be changed with E2E_NOKIA_STORE and E2E_CISCO_RESULTS (NOKIA_VIEW_STORE also works).

Far-end addresses (SDP far end, PW neighbour) are loopbacks, while ODL mounts routers by the
address it was given. The Inventory maps a loopback to a node with, in order:
  1. the node id itself, 2. e2e\loopback_map.json {"<loopback>": "<odl node id>"} if present,
  3. loopbacks learned from each saved router (system interface, LSP source, Loopback0, LLDP).
"""
import json
import os
import re

from . import cisco, nokia

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME_RE = re.compile(r"^(\d{8}-\d{6})_(.+?)(-error)?\.json$")
EMPTY_ERRORS = ("data-missing", "relevant data model content does not exist")


def nokia_store():
    return os.path.abspath(os.environ.get("E2E_NOKIA_STORE") or os.environ.get("NOKIA_VIEW_STORE")
                           or os.path.join(ROOT, "nokia_view", "store"))


def cisco_results():
    return os.path.abspath(os.environ.get("E2E_CISCO_RESULTS") or os.path.join(ROOT, "cisco_iosxr", "results"))


def mapping_file():
    return os.environ.get("E2E_LOOPBACK_MAP") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "loopback_map.json")


def _latest_files(folder, wanted):
    """{query: (path, is_error_file)} with the newest file per query, for the queries in `wanted`."""
    best = {}
    if not os.path.isdir(folder):
        return best
    for name in os.listdir(folder):
        m = NAME_RE.match(name)
        if not m or m.group(2) not in wanted:
            continue
        cur = best.get(m.group(2))
        if cur is None or m.group(1) > cur[0]:
            best[m.group(2)] = (m.group(1), os.path.join(folder, name), bool(m.group(3)))
    return {q: (p, e) for q, (_s, p, e) in best.items()}


def load_saved(folder, wanted):
    """{query: data} for the newest run of each wanted query.

    A failed run is left out, except a "data missing" answer: the device has nothing configured
    under that path, so it counts as an empty result rather than an unknown one.
    Also returns {query: saved time} for the source list in the report.
    """
    data, when = {}, {}
    for qid, (path, is_err) in _latest_files(folder, set(wanted)).items():
        try:
            with open(path, encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        err = rec.get("error") if isinstance(rec, dict) else None
        stamp = os.path.basename(path)[:15]
        if is_err or err:
            if any(x in str(err or "") for x in EMPTY_ERRORS):
                data[qid], when[qid] = {}, stamp
            continue
        data[qid], when[qid] = rec.get("data") or {}, stamp
    return data, when


class Inventory:
    """All routers with saved data in either store, built lazily into PE views."""

    def __init__(self, nokia_dir=None, cisco_dir=None, loopback_map=None):
        self.dirs = {"nokia": nokia_dir or nokia_store(), "cisco": cisco_dir or cisco_results()}
        self.vendor = {}
        for vendor, base in self.dirs.items():
            if os.path.isdir(base):
                for n in sorted(os.listdir(base)):
                    if os.path.isdir(os.path.join(base, n)):
                        self.vendor.setdefault(n, vendor)
        self.manual = loopback_map if loopback_map is not None else self._read_map()
        self._pe = {}
        self._index = None

    @staticmethod
    def _read_map():
        path = mapping_file()
        if not os.path.isfile(path):
            return {}
        with open(path, encoding="utf-8") as fh:
            return {str(k): str(v) for k, v in json.load(fh).items() if not str(k).startswith("_")}

    def nodes(self):
        return dict(self.vendor)

    def pe(self, node):
        """PE view for a node with saved data, or None."""
        if node not in self.vendor:
            return None
        if node not in self._pe:
            vendor = self.vendor[node]
            adapter = nokia if vendor == "nokia" else cisco
            data, when = load_saved(os.path.join(self.dirs[vendor], node), adapter.QUERIES)
            pe = adapter.pe_from_saved(node, data)
            pe["saved"] = when
            self._pe[node] = pe
        return self._pe[node]

    def resolve(self, ip):
        """ODL node id with saved data for a loopback or node address, or None."""
        if not ip:
            return None
        if ip in self.vendor:
            return ip
        mapped = self.manual.get(ip)
        if mapped in self.vendor:
            return mapped
        if self._index is None:
            self._index = {}
            for n in self.vendor:
                for lo in self.pe(n)["loopbacks"]:
                    self._index.setdefault(lo, n)
        return self._index.get(ip)

    def odl_node_for(self, ip):
        """The node id to ask ODL for: a manual mapping if one exists, else the address itself."""
        return self.manual.get(ip, ip)
