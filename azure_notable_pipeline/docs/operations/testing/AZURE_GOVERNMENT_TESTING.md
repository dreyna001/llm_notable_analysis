# Azure Government testing

## Test boundary

Unit tests never call real Azure, Splunk, Elasticsearch, ServiceNow, or model
endpoints. Inject fakes for Azure clients and HTTP/model seams. Local parity
uses Azurite and the local Cosmos emulator only when explicitly opted in. Live
testing uses a dedicated Azure Government subscription in `usgovvirginia`,
synthetic fixtures, synthetic identities, private DNS, and customer-approved
model quotas.

## Verification layers

| Layer | What it proves | Command/evidence |
| --- | --- | --- |
| Unit | Parsing, validation, policy, idempotency, failure handling | `python -m pytest tests -m 'not integration'` |
| Local parity | Blob/Queue flow, deterministic analysis, case/archive/embed composition | [`LOCAL_AZURE_PARITY.md`](../LOCAL_AZURE_PARITY.md) |
| Contract | Portal OpenAPI, Bicep shapes, endpoint and identity assumptions | Existing focused tests and Bicep compile |
| Golden | Verdict, evidence/inference boundary, TTP, query and report quality | [`GOLDEN_EVALUATION.md`](GOLDEN_EVALUATION.md) |
| Government staging | Managed identity, private DNS, Azure OpenAI, Search, Front Door/Function Private Link, poison/replay | `scripts/test-pipeline.sh --staging-gate` |

## Staging acceptance matrix

- Prove `AzureUSGovernment` context and Government endpoint suffixes; reject a
  commercial endpoint.
- Upload one synthetic gzip JSON and verify one report, one case, one run, and
  one Search generation when enabled.
- Send a 3x analyzer/embed burst and observe bounded concurrency, queue drain,
  and no duplicate business result.
- Force five independent failures for Blob publication, analyzer, and embed;
  verify the correct poison queue and one alert each.
- Replay one message only after checking for a durable outcome.
- Validate managed-identity access to Blob/Queue, Cosmos, Azure OpenAI, Search,
  and Key Vault without keys or connection strings.
- Prove authenticated portal `/ready`, cross-user ownership, chat quota, direct
  origin denial, Front Door path, and timeout chain.
- Keep Splunk writeback and ServiceNow create disabled; run fake approval and
  idempotency tests.

## Failure evidence

Record test fixture ID, subscription/resource group, region, deployment/image
digest, identity object ID, operation ID, timestamp, expected/actual result,
and residual gap. Do not record tokens, full sensitive payloads, or customer
production data in this repository.
