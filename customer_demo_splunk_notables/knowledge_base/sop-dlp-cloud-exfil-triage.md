# SOP: DLP and cloud exfiltration triage

**Document ID:** SOC-SOP-DEMO-023  
**Owner:** SOC Tier 2  
**Applies to:** DLP, CASB, and proxy notables for cloud uploads

## Initial assessment

1. Identify `upload_vector` (browser, sync client, CLI tool) and `cloud_tenant_type` (corporate vs personal).
2. Review `staging_behavior`, `file_classification`, and `sensitive_categories` before escalation.
3. Check `dlp_exception_ticket`, `change_ticket`, and `migration_project` for approved bulk transfers.

## Insider-threat signals

- `user_departure_date` within 30 days
- `historical_baseline_deviation=true`
- Personal Gmail or non-corporate tenant uploads of restricted data

## Hunting queries

- **Splunk:** correlate `index=endpoint` archive creation with `index=proxy` or `index=casb` upload bytes by user.
- **CASB:** filter on `cloud_app`, `casb_action`, and `dlp_policy`.

## Response

For confirmed personal-cloud exfil of restricted data: preserve endpoint artifacts, notify HR/Legal per insider-threat playbook, and revoke active cloud sessions for the identity.

## Benign indicators

Corporate tenant IDs, signed OneDrive sync client, verified DLP migration exceptions, and internal-only file classifications during documented IT projects.
