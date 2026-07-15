# Local Azure parity harness

This opt-in harness exercises the Azure pipeline's real application boundaries without
calling Azure. Azurite provides Blob Storage and Storage Queues. Deterministic injected
substitutes provide analysis, embeddings, Cosmos persistence, portal authentication/chat,
and ServiceNow disposition input because those services do not have faithful emulators in
this repository.

## Safety contract

The test is skipped unless `RUN_LOCAL_AZURE_PARITY=1` and
`AZURITE_CONNECTION_STRING` is set. The connection string must be
`UseDevelopmentStorage=true` or contain only loopback/local Azurite endpoints. A non-local
endpoint fails the test before a client is constructed. The harness never creates
`DefaultAzureCredential` and does not read developer Azure credentials.

## Prerequisites

- Python 3.12 with the project and test dependencies installed.
- Azurite listening on its standard Blob and Queue ports, or an explicit local Azurite
  connection string. Docker is optional; the harness does not start or manage containers.

For a standard local Azurite process, run:

```bash
export AZURITE_CONNECTION_STRING='UseDevelopmentStorage=true'
./scripts/test-local-parity.sh
```

On PowerShell:

```powershell
$env:AZURITE_CONNECTION_STRING = 'UseDevelopmentStorage=true'
.\scripts\test-local-parity.ps1
```

The scripts enable the opt-in flag and default to the standard development-storage
connection string. If Azurite is not reachable, pytest reports a clean skip and exits
successfully.

An additional Cosmos emulator test is enabled when both
`COSMOS_ENDPOINT` and `COSMOS_EMULATOR_KEY` are present. It accepts only a local
endpoint, creates an isolated temporary database, and deletes it after the test:

```bash
export COSMOS_ENDPOINT='http://localhost:8081'
export COSMOS_EMULATOR_KEY='<local emulator key>'
./scripts/test-local-parity.sh
```

## Covered path

The core test uploads a gzip JSON notable to Azurite, publishes and consumes the strict
analyzer queue contract, performs deterministic analysis, writes Markdown and JSON reports,
archives a case, publishes and consumes the embed job, writes deterministic vector chunks,
and marks retrieval ready. It then exercises portal token rejection and authenticated chat,
plus a disposition dry-run that proves the underlying persistence state is unchanged.

The same scenario checks replay behavior, a stale source ETag, and malformed queue payload
rejection. Queue messages are deleted only after the harness has received them, matching the
successful-worker boundary.

## Intentional gaps

- The Azure Functions host and its retry-to-poison transfer are not started. Malformed jobs
  are validated at the same strict handler boundary, but poison-queue movement remains a
  Functions-host integration concern.
- The core path uses deterministic in-memory Cosmos persistence. When the optional Cosmos
  emulator variables are supplied, a focused test additionally verifies duplicate create,
  stale ETag rejection, and chat-session partition ownership through `CosmosStore`.
- Azure OpenAI, Azure AI Search, Key Vault, ServiceNow, and Splunk are never
  contacted. Their live identity, quota, TLS, and service-specific behavior belongs in an
  explicitly authorized Azure development environment.
- The chat response is deterministic and validates routing/authentication composition, not
  model quality. Ownership and Cosmos conditional-write behavior remain covered by their
  focused offline test suites.

Run the normal offline suite separately; it remains the source of detailed negative-path
coverage:

```bash
python -m pytest -m 'not integration'
```
