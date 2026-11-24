r"""Save every query result as a JSON file, one file per run, so runs can be reopened later.

Layout:  store\<node>\<YYYYmmdd-HHMMSS>_<query>.json
Set NOKIA_VIEW_STORE to use a different folder.
"""
import datetime as dt
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.abspath(os.environ.get("NOKIA_VIEW_STORE") or os.path.join(HERE, "store"))


def _safe(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(text or "")).strip("_")[:80] or "item"


def save(result):
    """Write one run to disk. Returns its path relative to the store, e.g. '162.104.38.226/x.json'."""
    node = _safe(result.get("node"))
    name = result.get("query") or result.get("label")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = os.path.join(STORE, node)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{stamp}_{_safe(name)}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, default=str)
    return f"{node}/{os.path.basename(path)}"


def history(node):
    """Saved runs for one node, newest first, as relative paths."""
    folder = os.path.join(STORE, _safe(node))
    if not os.path.isdir(folder):
        return []
    names = sorted((f for f in os.listdir(folder) if f.endswith(".json")), reverse=True)
    return [f"{_safe(node)}/{n}" for n in names[:200]]


def latest_data(node, query):
    """Data from the newest saved run of one query for a node, or None."""
    suffix = f"_{_safe(query)}.json"
    for rel in history(node):
        if rel.endswith(suffix):
            return load(rel).get("data")
    return None


def load(rel):
    """Read one saved run. Only paths inside the store are allowed."""
    path = os.path.normpath(os.path.join(STORE, rel))
    if not path.startswith(STORE + os.sep):
        raise ValueError("path is outside the store")
    if not os.path.isfile(path):
        raise FileNotFoundError(rel)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
