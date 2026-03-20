# Packaging Rationale

## Why package this as an SDK

For one repo, direct module imports are often fine. For multiple unrelated projects, packaging is safer and more maintainable.

## Benefits of packaging

- Version pinning (`onprem-llm-sdk==X.Y.Z`) for deterministic behavior.
- Controlled upgrades and rollbacks without copying source files.
- Consistent dependency management across projects.
- Cleaner auditability for regulated and air-gapped workflows.
- Reusable testable contract with stable exception and config interfaces.

## Why offline wheelhouse distribution

- Air-gapped deployments cannot depend on internet package indexes.
- Bundle includes SDK wheel + dependency wheels + checksums.
- Install command uses `--no-index` and `--find-links` to prevent network fetches.
- Integrity checks provide evidence for supply-chain control.

## What this avoids

- `PYTHONPATH` drift between apps.
- Source copy/paste divergence.
- Hidden dependency mismatches.
- Untraceable “works on one host only” module behavior.

