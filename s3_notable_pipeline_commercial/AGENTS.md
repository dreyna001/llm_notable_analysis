# Commercial AWS product boundary

These instructions apply to all work under `s3_notable_pipeline_commercial/`.

## Scope and safety

- This directory is an independent commercial AWS product for partition `aws` in `us-east-1`.
- Treat `../s3_notable_pipeline/` as an out-of-scope production GovCloud product.
- Never edit, import from, symlink to, deploy, migrate, delete, or clean up resources for `../s3_notable_pipeline/`.
- Do not introduce dual-partition behavior. Deployment code in this project must fail closed outside `aws` and `us-east-1`.
- Do not copy data, secrets, identifiers, endpoints, or runtime state from a GovCloud environment.
- Never run `sam delete`, `aws cloudformation delete-stack`, recursive S3 deletion, or an equivalent destructive AWS command for this work.
- Before any live AWS mutation, verify and report the AWS account ID, partition, region, role/profile, stack name, and intended resources. Obtain explicit user approval for the live deployment step.

## Implementation defaults

- Follow `docs/planning/COMMERCIAL_AWS_FORK_PLAN.md` and keep its status current.
- Preserve the copied architecture, behavior, external contracts, and capability-profile system unless a verified commercial-AWS difference requires a change.
- Keep the internal Python package name `s3_notable_pipeline` unless the user explicitly approves a rename.
- Keep changes small and independently testable. Document every intentional difference from the fork baseline.
- Keep customer values such as account IDs, resource names, KMS keys, model IDs, identity settings, endpoints, retention, and capacity in validated deployment configuration.
- Treat dependency remediation as a separate pre-production hardening gate, not as an undocumented part of the AWS partition work.

## Subagents

- Use subagents for bounded, independent, read-heavy work when they materially help.
- Prefer the read-only `default` custom agent (`gpt-5.6-luna` with `medium` reasoning) for focused exploration, retrieval, and verification.
- If Luna is unavailable as a child agent, use `gpt-5.6-terra` with `low` or `medium` reasoning for the same bounded work.
- Keep write-heavy implementation owned by the primary agent unless tasks touch disjoint files and coordination risk is low.
- Subagents must follow the same commercial-only and GovCloud no-touch boundary.
