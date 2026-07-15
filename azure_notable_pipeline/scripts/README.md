# Scripts

Phase 1 provides native `build-image.sh`, `setup-and-deploy.sh`, and
`setup-and-deploy.ps1`. The build helper emits the immutable ACR digest URI;
the deployment helpers reject tag-only images and registry mismatches, allow
for RBAC propagation, and fail closed unless both Function Apps prove all of
the following:

- the configured digest image is attached with exactly one UAMI and ACR managed
  identity pull enabled for that same client ID;
- Functions host storage uses that UAMI plus explicit HTTPS Blob, Queue, and
  Table service URIs, and the Functions host reports `Running`;
- production requires explicit Blob soft-delete/versioning and Cosmos continuous
  backup settings; zone redundancy and per-app host accounts are guarded opt-ins
  documented in `docs/operations/AZURE_RESILIENCE_PROFILE.md`;
- the analyzer app enumerates exactly `intake_blob` and `analyzer_queue`, while
  the embed app enumerates exactly `case_embed_queue`;
- app-setting names contain no ACR credentials, storage keys/connection strings,
  Azure Files content settings, or Foundry/Anthropic, Azure OpenAI, AI Search,
  or Cosmos keys and other secret-bearing variants.

The scripts never print app-setting values. Failed setting checks identify only
the app and offending setting name.

Run uploads and deployment validation from a private-network-connected runner.
`test-pipeline.ps1` and `.sh` default to a non-mutating offline contract gate.
Their explicit staging mode requires the named dedicated subscription and a
chaos acknowledgement, generates synthetic data only, rejects enabled external
writeback, and covers private intake, a 3x burst, three five-attempt poison
paths, duplicate delivery, portal auth/ownership/OpenAPI, chat timeout,
disposition dry run, and managed-identity service smoke.

For `analyst_portal`, both deployment helpers also build/test the same-origin
SPA, upload `$web` with Microsoft Entra authentication, approve and poll all
Front Door managed private endpoints (`web` and `Gateway`), and only
then verify both origins. The final gate rejects a successful direct Function
request, asserts disabled public access on Function/Storage, and requires
authenticated `/ready` through Front Door.
See [`ANALYST_PORTAL_DEPLOYMENT.md`](../docs/operations/ANALYST_PORTAL_DEPLOYMENT.md).
The complete staging inputs and production gate are in
[`AZURE_READINESS.md`](../docs/delivery_package/AZURE_READINESS.md).

`test-local-parity.sh` and `test-local-parity.ps1` run the opt-in account-free
Azurite/Cosmos emulator harness described in
[`LOCAL_AZURE_PARITY.md`](../docs/operations/LOCAL_AZURE_PARITY.md).
