"""End-to-end service view shared by the Nokia and Cisco reports.

Each router's saved NETCONF data is turned into vendor-neutral service endpoints:
  endpoint = one service on one PE: attachment circuits (SAP / AC) with their CE, and
             pseudowires (SDP binding / PW neighbour) with their far-end PE address.
The stitcher then pairs each pseudowire with the matching service on the far-end PE,
using whatever data is saved for that PE in nokia_view/store or cisco_iosxr/results.

Modules:
  util     small helpers shared by the adapters
  nokia    Nokia SR OS (classic) saved data -> endpoints
  cisco    Cisco IOS-XR saved data -> endpoints
  sources  finds the newest saved data for every router in both stores
  stitch   builds the end-to-end records for one router
  collect  fetches far-end PEs through ODL and saves them in the stores
"""
from .stitch import build_report_model  # noqa: F401
