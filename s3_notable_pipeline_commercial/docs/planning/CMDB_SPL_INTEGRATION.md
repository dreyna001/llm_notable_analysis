# CMDB integration for SPL accuracy and notable enrichment

## Status

**Backlog — planning only.** No CMDB adapter, lookup sync, or notable-enrichment
step is implemented in `s3_notable_pipeline` today. This note captures customer
integration patterns for a **future** capability aligned with the cross-cutting
**Asset, identity, and ownership context** item in
[`../../../llm_notable_analysis_onprem_systemd/docs/planning/FUTURE_ENHANCEMENTS_ROADMAP.md`](../../../llm_notable_analysis_onprem_systemd/docs/planning/FUTURE_ENHANCEMENTS_ROADMAP.md).

It is **not** a runtime contract until promoted into a technical spec after
review. Shipped AWS parity work (SPL investigation, query-result enrichment,
Splunk writeback) is documented separately — see [Related docs](#related-docs).

## Scope

**In scope (future intent):**

- How a CMDB fits beside Splunk investigations and S3 notable intake.
- Patterns to replicate CMDB fields into Splunk (for SPL) and onto the notable
  JSON before upload (for pipeline handoff).

**Out of scope (today):**

- Lambda-time CMDB queries or a first-party CMDB adapter in this repository.
- Splunk lookup table design or CMDB vendor export mechanics (customer-owned).

---

This note describes how a **CMDB** (configuration / asset source of truth) fits
next to **Splunk** investigations and how to **inject** CMDB-derived context so
**SPL** and the **`s3_notable_pipeline`** notable payload stay aligned.

## What the CMDB is (in this workflow)

A **CMDB** is typically the **system of record for assets and configuration
metadata**: identifiers, ownership, environment, tier, business service,
relationships (app → cluster → owner), sanctioned baselines where curated, etc.

- **Splunk** is strong for **time-series telemetry** (what happened when).
- **CMDB** is strong for **authoritative inventory context** (what *is* this
  asset in the approved catalogue).

Splunk searches can only use fields that exist **inside Splunk** (raw events,
indexed fields, or replicated CMDB data). The pipeline analyzes **whatever is
in the notable JSON** uploaded to S3 under `incoming/` (see
[`../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md));
it does not query CMDB at inference time unless you build that separately.

## Goal: inject CMDB so SPL stays accurate

**Inject** means CMDB-backed fields become **Splunk-visible** for
`lookup`/`join`, and optionally **copied onto the notable** before upload so
analysts and automation see the same context.

---

## Option A — Expose CMDB inside Splunk (for SPL)

Use one or a combination of:

| Approach | Typical use |
|----------|--------------|
| **Lookup tables** | Scheduled CMDB export → CSV / transform, or DB Connect → `lookup` / `join` on stable keys. |
| **KV Store / collections** | Vendor TA, scripted input, or custom sync when you need richer refresh semantics or larger tables than static CSVs. |
| **Indexed CMDB snapshot** | Dedicated sourcetype for very large or high-cardinality joins and `tstats`-style workflows; tolerate documented sync lag. |

**Join keys:** normalize identically across events and CMDB (FQDN vs short
hostname, casing, DNS suffixes, IPv4/IPv6, "asset id" vs hostname).
Misaligned keys produce silent misses and false "missing" enrichment.

---

## Option B — Use enriched fields in SPL

Pattern:

1. Base search on **security-relevant indexes/sourcetypes**.
2. **Enrich** with CMDB-derived fields via `lookup` or `join` (e.g. owner,
   environment, tier, business service, CI id).
3. Filter and aggregate using those fields so hunts align with **prod vs dev**,
   **ownership**, **expected network zones**, etc.

CMDB informs **classification and scope** of investigations; it does not replace
telemetry for proving **behavior**. Shipped read-only SPL investigation in this
repo is bounded and separate — see
[`../operations/investigation/SPL_OPERATIONS.md`](../operations/investigation/SPL_OPERATIONS.md).

---

## Option C — Inject CMDB into the notable (pipeline handoff)

For **`s3_notable_pipeline`** to see the same truth without calling CMDB at
Lambda time:

- In **SOAR or a pre-upload transform**: resolve entities in the notable
  (host, user, app, CI id) → **fetch CMDB row** → **append normalized fields**
  to the JSON placed under `incoming/`.

Reference delivery pattern (S3 upload from Splunk SOAR; CMDB enrichment would
extend the pre-upload step):
[`../integrations/SOAR_PLAYBOOK_PHANTOM.md`](../integrations/SOAR_PLAYBOOK_PHANTOM.md).

Suggested fields (examples only — match your CMDB schema and privacy policy):

- `cmdb_ci_id`, `business_service`, `environment`, `owner` / `support_group`,
  `tier`, `network_zone`, `sync_timestamp`

Treat these as **advisory inventory context**, not incident evidence unless the
notable's security data explicitly supports them.

---

## Operational notes

| Topic | Guidance |
|-------|----------|
| **Freshness** | Document sync cadence (e.g. hourly). Stale CMDB makes SPL **consistent with the wrong world**. |
| **Evidence discipline** | Do not claim CMDB facts as observed attacker behavior; keep inventory context distinct from telemetry. |
| **Failure modes** | Unmatched lookups should be explicit in playbooks ("no CMDB match") vs silently empty fields. |

---

## Summary

| Layer | Role |
|-------|------|
| **Splunk + CMDB lookups** | Accurate **SPL** using replicated or synced CMDB fields. |
| **Notable JSON enrichment** | Same context available to **`s3_notable_pipeline`** and human review offline of live Splunk. |

**TL;DR:** sync CMDB into Splunk (**lookups, KV store, or indexed snapshots**)
with strict key normalization for accurate SPL; optionally **mirror those fields
onto the notable** before S3 so pipeline output matches investigation
assumptions.

---

## Related docs

| Doc | Relevance |
|-----|-----------|
| [`FUTURE_ENHANCEMENTS_ROADMAP.md`](../../../llm_notable_analysis_onprem_systemd/docs/planning/FUTURE_ENHANCEMENTS_ROADMAP.md) | Backlog owner for asset / CMDB context (AWS and on-prem). |
| [`AWS_ONPREM_PARITY_TECHNICAL_SPEC.md`](../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md) | Shipped AWS parity scope; CMDB is not a Wave 1–3 deliverable. |
| [`../operations/investigation/SPL_OPERATIONS.md`](../operations/investigation/SPL_OPERATIONS.md) | Shipped bounded read-only SPL investigation. |
| [`../operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](../operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md) | Splunk notable comment writeback after analysis. |
| [`../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md) | S3 `incoming/` intake contract for notable JSON. |
| [`../integrations/SOAR_PLAYBOOK_PHANTOM.md`](../integrations/SOAR_PLAYBOOK_PHANTOM.md) | SOAR → S3 upload pattern (pre-upload enrichment hook). |
| [`../../README.md`](../../README.md) | Package overview and deploy fast path. |
