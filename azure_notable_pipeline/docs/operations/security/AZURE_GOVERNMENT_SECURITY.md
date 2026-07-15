# Azure Government security operations

## Security objective

The deployment is designed for Azure US Government and `usgovvirginia` first,
but this document does not make a compliance, authorization, backup, or
disaster-recovery claim. The customer remains responsible for mission,
classification, records, privacy, boundary, and accreditation decisions.

## Control layers

| Layer | Required control |
| --- | --- |
| Sovereignty | Use `AzureUSGovernment`, Government resource audiences and DNS suffixes, and customer-qualified service/model availability. Reject commercial endpoints. |
| Identity | Use distinct user-assigned managed identities for analyzer, embed, disposition, and portal. Grant only the required data-plane roles at the narrowest scope. |
| Secrets | Keep external integration secrets in customer Key Vault. Store names, not values, in configuration. Prefer workload identity for Splunk, SOAR, and ServiceNow where supported. |
| Network | Use private endpoints, private DNS, restricted egress, private origins, and authenticated Front Door access. Direct origin access must fail. |
| Data | Bound compressed/decompressed input, question, query, context, and stored message sizes. Encrypt with the approved platform or customer-managed key decision. |
| Application | Validate external input, model output, generated SPL/Query DSL, URLs, paths, identifiers, and side-effect payloads before persistence or execution. |
| Audit | Emit operation IDs, profile, run ID, capability outcome, dependency status, and replay metadata without tokens or raw sensitive payloads. |
| Recovery | Preserve uncertain external outcomes and reconcile them. Do not purge queues, overwrite immutable runs, or claim a product-level backup/DR guarantee. |

## External integration boundary

Read-only Splunk/Elasticsearch investigation, Splunk writeback, ServiceNow
draft/create, and ServiceNow disposition sync use separate credentials and
capabilities. A read credential must not be reused for create. Write actions
require a human approval boundary, deterministic allowlists, bounded payloads,
stable idempotency keys, and a reconciliation path for timeout-after-commit.

## Review checklist

- [ ] Government cloud and `usgovvirginia` context are visible in deployment evidence.
- [ ] Public network access is disabled for data resources and direct origins fail.
- [ ] RBAC assignments are scoped and reviewed against the capability profile.
- [ ] Key Vault contains only approved external secrets; no secret appears in logs or artifacts.
- [ ] Portal tokens validate issuer, audience, expiry, signature, `sub`, and required role/scope.
- [ ] Generated queries are read-only, allowlisted, bounded by time and rows, and attributed as model output.
- [ ] Writeback/create is disabled in staging and has a separate approval record for production.
- [ ] Retention, legal hold, soft delete/versioning, and any optional backup setting have named owners.
- [ ] Incident operators have tested poison recovery without making origins public.
