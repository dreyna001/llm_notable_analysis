# SOP: Host isolation (emergency containment)

**Document ID:** SOC-SOP-014  
**Owner:** SOC Tier 1  
**Applies to:** Windows and Linux endpoints with suspected compromise

## When to use

Use this procedure when EDR, network, or notable alerts indicate active malware,
beaconing, credential theft, or unauthorized remote access on a single host.

## Steps

1. Confirm the host hostname and logged-on user with the analyst assigned to the case.
2. Open the EDR console and select **Respond > Network Isolate** for the host.
   Do not power off the machine unless EDR isolation is unavailable.
3. If EDR is unavailable, contact IT Ops on-call and request an emergency ACL block
   for the host MAC/IP at the access switch. Record the ticket number in the case.
4. Preserve evidence: ensure EDR live response or disk snapshot is queued before
   any reboot.
5. Notify the asset owner team listed in CMDB within 15 minutes.
6. Document isolation time, method (EDR vs network block), and approver in the case.

## Do not

- Reimage or wipe the host until Tier 2 and Legal approve evidence retention.
- Disable isolation without Tier 2 approval when C2 or lateral movement is suspected.
