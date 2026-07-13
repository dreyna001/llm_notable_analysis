# Azure Notable Pipeline

Azure-native sibling of `s3_notable_pipeline`, built to preserve product and
operator-visible behavior without reproducing AWS SDK, event, or persistence
interfaces.

Phase 0 establishes the package, portable behavior baseline, Azure runtime
contract, native boundary shells, Functions container, and Bicep module layout.
Implementation status is tracked in
[`docs/planning/AZURE_IMPLEMENTATION_TRACKER.md`](docs/planning/AZURE_IMPLEMENTATION_TRACKER.md).

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
