# MITRE ATT&CK operations

## Evidence rule

MITRE ATT&CK mapping is an analyst aid, not proof of adversary behavior. A
technique or sub-technique may be emitted only when direct case evidence
supports it. Model inference, Azure AI Search knowledge, and a generic tactic
description are advisory context and must not be recorded as current-alert
evidence.

The shipped validator uses the local `enterprise_attack_v17.1_ids.json`
catalog. The catalog version is part of the evaluation and release record.
Keep unknown or unsupported IDs as `unknown`/omitted rather than guessing.

## Required output discipline

For every mapped technique, preserve:

- technique ID and optional sub-technique ID in the accepted format;
- tactic assigned for this alert;
- direct evidence references, such as event ID, field, timestamp, or source blob;
- confidence and evidence gaps;
- alternative plausible tactics when the technique is many-to-many;
- whether the mapping is observed, inferred, or suppressed.

Do not create a response action from a technique mapping alone. Actions remain
behind the capability and approval gates described in
[`CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md).

## Review workflow

1. Confirm the alert evidence is present in the case and not only in a RAG
   document.
2. Validate the ID against the pinned local catalog and normalize casing.
3. Check tactic span and sub-technique semantics.
4. Review evidence gaps and competing hypotheses.
5. Persist source attribution with the report and include the mapping in golden
   evaluation where the case is representative.
6. Re-run the catalog compatibility and golden tests when the catalog changes.

MITRE content is versioned advisory material. A catalog refresh requires an
owner, effective version, diff review, regression results, and a rollback copy;
it does not silently rewrite historical case evidence.
