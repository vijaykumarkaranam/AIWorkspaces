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

## Reading the results
- An error like `unknown-element` or `unknown-namespace` means the model or path is not on the device.
  Keep the error and check the model in the capability list.
- "command failed" means the filter needs a key. Query the parent element instead.
- Cisco native names in `queries.py` are candidates. Confirm them with the capability list before relying on them.
