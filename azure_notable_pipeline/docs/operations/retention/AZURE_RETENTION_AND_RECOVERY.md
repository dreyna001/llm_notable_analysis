# Azure retention and recovery

## Retention is a customer decision

The shipped starting values are `incoming/` 2 days, `reports/` 30 days, and
`cases/`/`case_chunks/` 30 days when portal indexing is enabled. Chat history
and disposition retention have separate settings. Confirm legal, privacy,
investigative, and records requirements before changing them. Queue residence,
poison investigation, replay, and external reconciliation windows must fit
inside the chosen retention period.

| Data | Product starting point | Recovery/ownership note |
| --- | --- | --- |
| Input Blob | 2 days | Producer owns source replay; preserve an approved evidence copy if required. |
| Report Blob | 30 days | Durable application result; immutable run identity prevents overwrite. |
| Case and chunks | 30 days | Case archive is the portal source; Search is a rebuildable projection. |
| Chat sessions/messages | 30 days when enabled | User ownership and TTL are enforced in Cosmos. |
| Dispositions | 365 days by default | Customer records owner confirms legal hold and reconciliation policy. |
| Queue/poison evidence | Customer decision | Snapshot metadata safely; never log secrets or unrestricted payloads. |

## Recovery controls

The customer may explicitly enable Blob soft delete, container soft delete, Blob
versioning, bounded previous-version cleanup, Cosmos continuous backup, zone
redundancy, and an approved multi-region design. These are deployment choices
that require service/region qualification, cost, RTO/RPO, access, and restore
testing. This repository contains no committed backup or DR guarantee, and
enabling a protection setting does not by itself establish one.

Cosmos's current application design is single-region serverless with Strong
point reads. A multi-region target requires a separate migration and cutover
plan covering throughput, consistency, private DNS, failover behavior, and
rehearsed data movement. Do not imply regional failover from same-region zone
redundancy.

## Recovery procedure

1. Stop or rate-limit the producer; do not purge queues or delete evidence.
2. Identify the boundary: Blob publication, analyzer, embed, portal, Search,
   Cosmos, model, network, or external integration.
3. Check for an existing durable report, case, run, pointer, or external side
   effect before replaying.
4. Correct the cause, snapshot safe metadata, and replay one validated message
   through the normal idempotent path.
5. Reconcile Blob, Cosmos, Search generation, Splunk/ServiceNow state, and
   portal visibility.
6. Record operation ID, digest, run IDs, replay identity, timestamps, owner,
   and residual risk. Re-enable only after synthetic validation.
