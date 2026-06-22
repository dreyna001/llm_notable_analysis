# High Value Asset (HVA) registry — excerpt

**Document ID:** GRC-HVA-REG-2026-Q2  
**Owner:** GRC / Asset Management  
**Note:** SOC advisory list for escalation and containment priority. Not live CMDB.

## Registered HVAs

| Asset | Type | Owner team | Data class | Notes |
|-------|------|------------|------------|-------|
| db-prod-01.corp.local | Production SQL Server | DBA-Production | Restricted / PCI adjacent | Primary finance ledger DB; RDP only via jump-01 with break-glass approval |
| dc-01.corp.local | Domain controller | Identity-Ops | Critical | Tier 0; never isolate without Identity-Ops on bridge |
| payment-gateway-01.corp.local | Payment API | FinTech-Platform | PCI | Change freeze except P1 incidents |
| app-server-03.corp.local | Finance application server | finance-apps | Confidential | Hosts month-end batch jobs; local admin changes require finance-apps approval |

## SOC handling

- Any notable involving an HVA host as **source or destination** requires Tier 2
  escalation per SOC-SOP-003.
- Default containment for HVA endpoints: network isolate via EDR where supported;
  do not power off database HVAs without DBA-Production approval.
- Cross-reference VLAN and jump-path rules in NET-REF-001 when movement touches
  db-prod-01 or other database-tier assets.
