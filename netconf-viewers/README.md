# NETCONF viewers (Nokia SR OS and Cisco IOS-XR through ODL)

Read-only tools that query routers through OpenDaylight (RESTCONF over NETCONF mounts), save every
answer, and build single-file HTML reports.

| Folder | What it does |
|---|---|
| `nokia_view/` | Nokia 7750 SR queries, live viewer (`run_viewer.bat`, port 8765), device report |
| `cisco_iosxr/` | Cisco IOS-XR queries, live viewer (`run_viewer.bat`, port 8766), device report |
| `e2e/` | **End-to-end services**, shared by both reports |
| `tests/` | Unit tests (standard library only): `python -m unittest discover -s tests` |

Saved device data (`nokia_view/store`, `cisco_iosxr/results`, `exports`) and generated reports stay on
your machine. They are excluded from git because they hold addresses, circuit IDs and customer names.

## End-to-end services

Both device reports have an **End-to-end services** tab. It shows each L2 service on the router,
followed from the customer edge, through the router and its pseudowires, to the far-end PE and its
customer edge:

```
CE ─LLDP─ SAP / AC ─ [this PE: service] ─ PW (SDP + LSP / LDP-SR) ─ [far-end PE: service] ─ SAP / AC ─LLDP─ CE
```

The Nokia **Service trace** tab also shows the far ends of the selected service.

### How the far end is found

1. Each pseudowire's far-end address comes from the SDP far end (Nokia) or the PW neighbour, or from
   the L2FIB next hop for BGP-AD VPLS (Cisco).
2. That address is resolved to a router with saved data, in either tool's store. It is matched against
   the node id, then `e2e/loopback_map.json`, then loopbacks learned from the saved data (Nokia system
   interface and LSP source; Cisco Loopback0 and LLDP addresses).
3. On that router, the matching service is the one with the same VC / PW id pointing back at this PE.
   For BGP-AD VPLS, it is the one with the same VPLS-ID. This works across vendors: a Nokia epipe to a
   Cisco xconnect, or a Nokia VPLS to a Cisco bridge domain.

### Status

| Status | Meaning |
|---|---|
| up | every AC and PW is up, and every far end was found and is up |
| down | a point-to-point service with anything on its path down, or a multipoint service down as a whole |
| degraded | a multipoint service with some sites cut off, or a warning (far end reports a fault, no matching service) |
| far end missing | no fault seen, but a far-end PE has no saved data yet |
| local only | no pseudowires (local switching, or an L3 VPN) |

### Collecting the far ends

A report can only stitch to far-end PEs whose data is saved. To fetch them:

- In either viewer, enter or pick the router, then press **Collect far ends**. The report is rebuilt
  afterwards.
- Or from this folder, with `ODL_BASE`, `ODL_USER` and `ODL_PASSWORD` set as for the viewers:

  ```
  python -m e2e.collect --node 192.0.2.10 --dry-run
  python -m e2e.collect --node 192.0.2.10
  ```

The collector looks each far end up in the ODL topology and tells Nokia from Cisco by its NETCONF
capabilities. It runs a small read-only query set and saves each answer into the matching tool's
store, in that tool's own format. Far ends that are not mounted, not connected, or of an unknown vendor
are listed with the reason. If ODL mounts routers by a management address rather than the loopback,
copy `e2e/loopback_map.example.json` to `e2e/loopback_map.json` and list them there.

A Cisco answer of "data-missing" means nothing is configured under that path (for example, no
xconnects on a VPLS-only router). The collector saves it as an empty result, not as an error.

### Limits

- L3 VPN (VPRN) services are listed with their route-target, but not stitched: their far ends are BGP
  peers, not pseudowires.
- Cisco PW state is taken from L2FIB (next hop valid). The xconnect oper container is not on every
  IOS-XR release.
- A CE behind a LAG or bundle is not resolved, because LLDP runs on the member ports.
- EVPN services are listed, but not stitched.
