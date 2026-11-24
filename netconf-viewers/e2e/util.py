"""Small helpers for walking NETCONF/RESTCONF JSON."""


def as_list(x):
    """A list for any value: None -> [], dict -> [dict], list unchanged."""
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def get(obj, *path, default=None):
    """obj[path[0]][path[1]]... or default when any step is missing."""
    cur = obj
    for p in path:
        if isinstance(cur, dict):
            cur = cur.get(p)
        elif isinstance(cur, list) and isinstance(p, int) and -len(cur) <= p < len(cur):
            cur = cur[p]
        else:
            return default
        if cur is None:
            return default
    return cur


def unwrap(data):
    """Strip the RPC wrapper: {'ietf-netconf:output': {'data': X}} -> X. Other shapes are returned as is."""
    for _ in range(3):  # tolerate a saved answer that was wrapped twice
        if not isinstance(data, dict):
            return data or {}
        out = data.get("ietf-netconf:output", data)
        if isinstance(out, dict) and isinstance(out.get("data"), dict) and len(out) == 1:
            out = out["data"]
        if out is data:
            return data
        data = out
    return data


def find_key(obj, key):
    """First value stored under `key` anywhere in obj (depth first), or None."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = find_key(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = find_key(v, key)
            if found is not None:
                return found
    return None


def walk_dicts(obj):
    """Every dict inside obj, depth first."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_dicts(v)


def text(x):
    """Readable string from a value that may be a one-field wrapper dict, e.g. {'description-string': 'x'}."""
    if isinstance(x, dict):
        for v in x.values():
            if isinstance(v, (str, int, float)):
                return str(v)
        return ""
    return "" if x is None else str(x)


def norm_state(value):
    """Map vendor state strings to up / down / admin-down / unknown."""
    if value is None or value == "":
        return "unknown"
    if isinstance(value, bool):
        return "up" if value else "down"
    s = str(value).lower()
    if "admin-down" in s or s in ("shutdown", "admin-shutdown"):
        return "admin-down"
    if s in ("up", "im-state-up", "active", "bridge-up", "alive", "ok") or s.endswith("-up"):
        return "up"
    if "down" in s or s in ("inactive", "failed", "fail", "not-active", "notconnected"):
        return "down"
    return s


def port_of(ac_name):
    """Physical port behind an attachment circuit: '1/1/3:676' -> '1/1/3', 'TenGigE0/0/0/5.871' -> 'TenGigE0/0/0/5'."""
    s = str(ac_name or "")
    if ":" in s and not s.startswith(("lag-", "pw-")) and "/" in s.split(":")[0]:
        return s.split(":")[0]
    if s.startswith(("lag-", "pw-")):
        return s.split(":")[0]
    return s.split(".")[0]
