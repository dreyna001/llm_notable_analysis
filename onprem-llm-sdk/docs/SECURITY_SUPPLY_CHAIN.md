# Security and Supply Chain Notes

## Core controls

- Offline bundle includes immutable checksums (`SHA256SUMS`).
- Air-gapped install uses `pip --no-index` to block internet resolution.
- Release versions are pinned and auditable.
- Endpoint credentials (if any) come from env files, not source code.

## Recommended hardening

- Sign bundle artifacts with organization-approved signing tooling.
- Preserve build logs and software bill of materials where required.
- Use least-privilege file permissions for artifact and env paths.
- Limit who can publish and transfer release bundles.

## What this SDK does not claim

- It does not by itself guarantee enclave compliance.
- It does not perform malware scanning of model artifacts.
- It does not enforce host-level network policy.

Those controls must come from the platform and governance workflow.

