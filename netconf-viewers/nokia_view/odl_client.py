"""Minimal ODL RESTCONF client for NETCONF mounts. Standard library only.

Settings come from arguments or environment variables:
  ODL_BASE      controller URL, e.g. http://10.137.202.20:8181
  ODL_USER      basic-auth user (empty if the controller uses only a session cookie)
  ODL_PASSWORD  basic-auth password
  ODL_COOKIE    full Cookie header value, e.g. JSESSIONID=...
"""
import base64
import json
import os
import urllib.error
import urllib.request

TOPOLOGY = "/rests/data/network-topology:network-topology/topology=topology-netconf"
MOUNT_RPC = ("/rests/operations/network-topology:network-topology/"
             "topology=topology-netconf/node={node}/yang-ext:mount/{op}")
NETCONF_BASE_NS = "urn:ietf:params:xml:ns:netconf:base:1.0"  # RFC 6241 base namespace, as the device advertises it


class OdlError(Exception):
    """ODL is unreachable, rejected the request, or returned NETCONF errors."""


class OdlClient:
    def __init__(self, base=None, user=None, password=None, cookie=None, timeout=180):
        self.base = (base or os.environ.get("ODL_BASE") or "http://10.137.202.20:8181").rstrip("/")
        self.user = os.environ.get("ODL_USER", "") if user is None else user
        self.password = os.environ.get("ODL_PASSWORD", "") if password is None else password
        self.cookie = os.environ.get("ODL_COOKIE", "") if cookie is None else cookie
        self.timeout = timeout

    def _request(self, method, path, body=None, content_type=None):
        headers = {"Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        if self.user:
            token = base64.b64encode(f"{self.user}:{self.password}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        if self.cookie:
            headers["Cookie"] = self.cookie
        data = body.encode("utf-8") if isinstance(body, str) else body
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")
        except urllib.error.URLError as exc:
            raise OdlError(f"cannot reach ODL at {self.base}: {exc.reason}") from exc

    @staticmethod
    def _parse(status, text):
        try:
            data = json.loads(text) if text.strip() else {}
        except ValueError:
            raise OdlError(f"HTTP {status}, response is not JSON: {text[:300]}")
        if isinstance(data, dict):
            container = data.get("errors") or data.get("ietf-restconf:errors") or {}
            errs = container.get("error") if isinstance(container, dict) else None
            if errs:
                msgs = []
                for e in errs:
                    if isinstance(e, dict):
                        msg = (e.get("error-message") or "").strip()
                        info = (e.get("error-info") or "").strip()
                        msgs.append(" ".join(x for x in (msg, info) if x))
                raise OdlError("; ".join(m for m in msgs if m) or json.dumps(errs)[:300])
        if status >= 400:
            raise OdlError(f"HTTP {status}: {text[:300]}")
        return data

    def nodes(self):
        """Mounted NETCONF nodes with their connection status."""
        status, text = self._request("GET", TOPOLOGY + "?content=nonconfig")
        data = self._parse(status, text)
        topo = (data.get("network-topology:topology") or [{}])[0]
        return [{"id": n.get("node-id"), "status": n.get("netconf-node-topology:connection-status", "")}
                for n in topo.get("node", [])]

    def rpc(self, node, op, xml_input=None, json_input=None):
        """Call an operation on a mounted device. Send XML or JSON input, not both."""
        path = MOUNT_RPC.format(node=node, op=op)
        if xml_input is not None:
            status, text = self._request("POST", path, xml_input, "application/xml")
        else:
            status, text = self._request("POST", path, json.dumps(json_input), "application/json")
        return self._parse(status, text)

    def netconf_get(self, node, kind, inner_xml):
        """kind 'state' uses ietf-netconf:get; kind 'config' uses get-config on the running datastore."""
        if kind == "config":
            body = (f'<input xmlns="{NETCONF_BASE_NS}"><source><running/></source>'
                    f"<filter>{inner_xml}</filter></input>")
            return self.rpc(node, "ietf-netconf:get-config", xml_input=body)
        body = f'<input xmlns="{NETCONF_BASE_NS}"><filter>{inner_xml}</filter></input>'
        return self.rpc(node, "ietf-netconf:get", xml_input=body)

    def cli_show(self, node, command):
        """Run a read-only SR OS show command through the NETCONF CLI-show filter."""
        body = {"input": {"filter": {"oper-data-format-cli-block": {"cli-show": command}}}}
        return self.rpc(node, "ietf-netconf:get", json_input=body)
