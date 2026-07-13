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
- the analyzer app enumerates exactly `intake_blob` and `analyzer_queue`, while
  the embed app enumerates exactly `case_embed_queue`;
- app-setting names contain no ACR credentials, storage keys/connection strings,
  Azure Files content settings, or Foundry/Anthropic, Azure OpenAI, AI Search,
  or Cosmos keys and other secret-bearing variants.

The scripts never print app-setting values. Failed setting checks identify only
the app and offending setting name.

Run uploads and deployment validation from a private-network-connected runner.
Phase 4 adds the full staging `test-pipeline.ps1`/`.sh` workflow and portal
private-origin checks.

For `analyst_portal`, both deployment helpers also build/test the same-origin
SPA, upload `$web` with Microsoft Entra authentication, approve and poll all
Front Door managed private endpoints (`web`, `Gateway`, and `sites`), and only
then disable APIM public access. The final gate rejects a successful direct
APIM request, asserts disabled public access on Function/Storage, and requires
authenticated `/ready` through Front Door.
See [`ANALYST_PORTAL_DEPLOYMENT.md`](../docs/operations/ANALYST_PORTAL_DEPLOYMENT.md).
