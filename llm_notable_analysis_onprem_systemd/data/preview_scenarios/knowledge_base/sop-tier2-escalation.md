# SOP: Escalate case to SOC Tier 2

**Document ID:** SOC-SOP-003  
**Owner:** SOC Tier 1 lead  
**Applies to:** All notable alerts

## Escalate to Tier 2 when any of the following is true

- Risk score is 80 or higher and the alert involves a High Value Asset (HVA).
- Confirmed or strongly suspected lateral movement (RDP, SMB, WinRM) to a server tier.
- Privilege escalation, domain admin touch, or service account abuse.
- Multiple related notables within 30 minutes sharing host, user, or IOC.
- Tier 1 cannot complete containment within 30 minutes.

## Escalation steps

1. Set notable status to **In Progress** and assign owner to **soc-tier2-queue**.
2. Add a case comment summarizing: alert type, affected hosts/users, IOCs, actions taken.
3. Page Tier 2 using the **#soc-tier2-escalations** Slack workflow (business hours)
   or the PagerDuty service **SOC-T2-ONCALL** (after hours).
4. Attach the top three evidence bullets and one open question for Tier 2.
5. Remain on the bridge until Tier 2 acknowledges (target: 10 minutes).

## HVA cases

When an HVA is involved, mark the case **Priority: P1** and include the HVA registry
entry (owner team, data classification, approved maintenance window).
