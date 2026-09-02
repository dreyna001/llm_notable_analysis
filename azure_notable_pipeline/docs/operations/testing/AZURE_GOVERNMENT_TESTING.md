# Azure Government testing

Canonical commands for unit, local parity, contract, golden, and Azure
Government staging validation. **Deploy path terminus:** all paths in
[`../../../README.md`](../../../README.md#3-validate-all-paths-end-here) section 3 end
here.

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

## Required live-cloud release gate

Run this gate in a dedicated Azure Government staging resource group from a
runner that uses the same private DNS and network path as production. Local
emulators, Bicep compilation, and mocked SDK tests cannot pass this gate.

| Check | Pass condition | Evidence to keep |
| --- | --- | --- |
| Cloud and region | CLI reports `AzureUSGovernment`; every endpoint has the expected Government suffix; selected model/Search features and quota are available in the deployed region | Subscription/resource group, region, safe endpoint list, quota approval |
| Managed identity and RBAC | All Function hosts start and access ACR, host storage, Blob/Queue, Cosmos, Azure OpenAI, Search, and Key Vault where enabled without keys or connection strings | Identity and role-assignment export plus deployment report |
| Private networking and DNS | Private names resolve on the runner; storage and Function direct origins deny access; authenticated Front Door `/ready` succeeds | DNS results and HTTP status summary without tokens |
| End-to-end workload | One synthetic input produces exactly one report/case/run and the enabled Search updates; duplicates and out-of-order messages do not create a second business result | Synthetic fixture ID, output IDs, timestamps, queue observations |
| Failure and recovery | Each poison path is triggered separately, its alert reaches the customer action group, a durable-outcome check is performed, and one corrected message replays successfully | Poison snapshot metadata, alert ID, replay approval/result |
| Upgrade and rollback | A new digest passes the gate, then the last qualified digest and matching portal artifact are redeployed and pass the minimum smoke set | Both deployment reports, digests, operation IDs, smoke results |

Production acceptance requires every applicable row to pass. Record any
exception with an owner, expiry, risk, and tested rollback; never use public
access or static Azure service keys as a workaround.

## Failure evidence

Record test fixture ID, subscription/resource group, region, deployment/image
digest, identity object ID, operation ID, timestamp, expected/actual result,
and residual gap. Do not record tokens, full sensitive payloads, or customer
production data in this repository.

## Deploy path — next

Path validation complete. Return to
[`../../../README.md`](../../../README.md#3-validate-all-paths-end-here) section 3 to
start another path or confirm the active path is finished.
