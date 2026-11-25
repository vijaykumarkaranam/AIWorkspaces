# Cisco IOS-XR NETCONF queries (through ODL)

Separate from the Nokia viewer. Step one: find out what the IOS-XR router serves and what is configured.

## Files
- `odl_client.py`: ODL RESTCONF client (copy of the Nokia one, same settings)
- `queries.py`: candidate queries (OpenConfig first, then Cisco native)
- `run_queries.py`: runs queries, saves each response, prints what is configured
- `results\<node>\`: saved responses and capability lists

## Settings
Same as the Nokia viewer:

```powershell
$env:ODL_BASE = "http://10.137.202.20:8181"
$env:ODL_USER = "admin"
$env:ODL_PASSWORD = Read-Host "ODL password"
```

## Steps
1. Find the node: `python run_queries.py --node <router-ip> --capabilities`
   This prints the OpenConfig and Cisco models the device serves, and why the others are unavailable.
2. Run the queries: `python run_queries.py --node <router-ip> --all`
   Each query prints OK with a summary of its lists, or the ODL error.
3. Look at the saved JSON in `results\<router-ip>\`.

## L2VPN and end-to-end reads
The `e2e-*` queries are the same RESTCONF URLs as the Service-LDP-E2E dashboard:
- `e2e-xconnect-config`: `l2vpn/database/xconnect-groups`
- `e2e-bridge-config`: `l2vpn/database/bridge-domain-groups`
- `e2e-xconnect-oper`: `l2vpnv2/active/xconnects`
- `e2e-bridge-ports` and `e2e-l2fibx-cons`: L2FIB bridge ports and cross-connects
- `e2e-ldp-*`: LDP neighbours and bindings
- `e2e-mpls-*`: MPLS forwarding and LSD label summaries

Paths that need a node location are tried with `0/RP0/CPU0`, then `0/0/CPU0`, then `0/RSP0/CPU0`
(ASR 9000). The first one that answers is used, and each saved result records the URL it came from
(`"path"`). The report shows that URL under each section.

A "data-missing" answer means nothing is configured under that path, for example no xconnects on a
VPLS-only router. It is saved as an empty result, not as an error.

The viewer's router list is `ROUTERS` (in `run_viewer.bat`) plus every Cisco node mounted in ODL, so you
can pick any of them. **Run all routers** still runs only the `ROUTERS` list. Set `ODL_BASE` in
`run_viewer.bat` to the controller you use, for example your dev ODL.

## Reading the results
- An error like `unknown-element` or `unknown-namespace` means the model or path is not on the device.
  Keep the error and check the model in the capability list.
- "command failed" means the filter needs a key. Query the parent element instead.
- Cisco native names in `queries.py` are candidates. Confirm them with the capability list before relying on them.
