# Corp.local network architecture (reference)

**Document ID:** NET-REF-001  
**Owner:** Enterprise Architecture  
**Classification:** Internal — SOC advisory context only

## Overview

Corp.local uses a hub-and-spoke design with tiered VLANs. This document is advisory
for investigation pivoting; live topology may differ after change windows.

## Segments

| VLAN | CIDR | Purpose | Example hosts |
|------|------|---------|---------------|
| User workstations | 10.44.0.0/16 | Employee laptops/desktops | laptop-*.corp.local |
| Jump / admin | 10.10.5.0/24 | Privileged access workstations | jump-01.corp.local |
| Application | 10.20.0.0/16 | Line-of-business app servers | app-server-*.corp.local |
| Database (prod) | 10.30.8.0/24 | Production databases (HVA) | db-prod-01.corp.local |
| DMZ | 10.50.0.0/24 | Internet-facing services | web-edge-*.corp.local |

## Expected paths

- Users reach application servers via standard corporate routing; direct RDP from
  workstations to database tier is **not** approved.
- Service accounts may authenticate to application tier only unless documented in
  the service account registry.
- Jump hosts (jump-01) are the approved entry for admin RDP to servers; paths must
  match the jump-path matrix in IAM-REF-012.

## Investigation notes

When lateral movement crosses VLAN boundaries (for example jump tier to database
tier), treat as high severity and consult HVA registry and Tier 2 escalation SOP.
