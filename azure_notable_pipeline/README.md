# Azure Government Notable Pipeline

Azure Government-native sibling of `s3_notable_pipeline`, built to preserve
product and operator-visible behavior without reproducing AWS SDK, event, or
persistence interfaces. The deployment target is `AzureUSGovernment`, with
`usgovvirginia` as the default qualified region.

Phase 0 establishes the package, portable behavior baseline, Azure runtime
contract, native boundary shells, Functions container, and Bicep module layout.
Implementation status is tracked in
[`docs/planning/AZURE_IMPLEMENTATION_TRACKER.md`](docs/planning/AZURE_IMPLEMENTATION_TRACKER.md).
The sovereign-cloud parity work is tracked in
[`docs/planning/AZURE_GOVERNMENT_PARITY_IMPLEMENTATION_PLAN.md`](docs/planning/AZURE_GOVERNMENT_PARITY_IMPLEMENTATION_PLAN.md).
Start operator handoff at [`docs/README.md`](docs/README.md) and use the
[`Azure readiness checklist`](docs/delivery_package/AZURE_READINESS.md) before
production intake.

Analyzer, portal chat, and embedding deployment names are customer inputs. The
Government deployment uses customer-owned Azure OpenAI deployments and Azure AI
Search; it does not call commercial Foundry Claude endpoints. Customer model
availability, quota, data-zone choice, retention, encryption keys, Entra app
values, and external-integration secrets are validated during operationalization.

The locked private intake path is a polling Blob trigger on
`input/incoming/{name}`. Application code publishes a strict v1 job to
`notable-analysis-jobs` in the output storage account, and the analyzer queue
wrapper validates that job before orchestration. All storage public network
access remains disabled. The input account exposes private Blob and Queue
endpoints to the analyzer identity; its queue service holds Blob-trigger
receipts and `webjobs-blobtrigger-poison`, while analyzer and embed poison
queues remain separate on output storage.

## Local verification

```bash
python3 -m pytest tests -q
az bicep build --file deploy/azure/main.bicep
```

Default unit tests do not call live Azure services.

For account-free integration coverage, start Azurite and the Cosmos DB Linux
emulator with [`deploy/local/bootstrap.sh`](deploy/local/bootstrap.sh) or
[`deploy/local/bootstrap.ps1`](deploy/local/bootstrap.ps1), then run the
[`local parity harness`](docs/operations/LOCAL_AZURE_PARITY.md).

Emulators validate application contracts only. Production acceptance requires
an explicit Azure Government staging deployment to validate managed identity,
private DNS, model quota, Azure AI Search vectors, poison recovery, and rollback.
