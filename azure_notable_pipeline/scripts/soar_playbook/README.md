# Splunk SOAR/Phantom to Azure Blob

`phantom_to_blob.py` is an optional producer helper. It accepts one complete
JSON payload from a Phantom playbook or stdin and writes it to a customer-owned
Azure Government Blob input endpoint, normally `input/incoming/<finding_id>.json.gz`.
It does not call Splunk APIs, create queues, enable writeback, or modify the
pipeline runtime.

## Credential boundary

Managed identity is the default and is appropriate when the playbook runner is
an Azure-hosted workload. Use `--managed-identity-client-id` or
`AZURE_STORAGE_MANAGED_IDENTITY_CLIENT_ID` only for a customer user-assigned
identity. The identity needs `Storage Blob Data Contributor` scoped to the
input container, and no output, host-storage, portal, or action permissions.

For a customer-managed service principal, set `--auth-mode service-principal`.
The helper reads `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, and
`AZURE_CLIENT_SECRET` only from the process environment at execution time, and
uses the Azure Government authority. Inject the secret from the Phantom vault,
an approved runner secret store, or equivalent. Never put it in a playbook,
command line, repository, fixture, or log.

## Example

```bash
export AZURE_STORAGE_ACCOUNT_URL=https://<account>.blob.core.usgovcloudapi.net
export AZURE_STORAGE_CONTAINER=input
export AZURE_STORAGE_PREFIX=incoming
export AZURE_STORAGE_AUTH_MODE=managed-identity
python scripts/soar_playbook/phantom_to_blob.py --input-file notable.json
```

Service-principal mode:

```bash
export AZURE_STORAGE_AUTH_MODE=service-principal
export AZURE_TENANT_ID=<customer-government-tenant>
export AZURE_CLIENT_ID=<customer-app-client-id>
# Inject AZURE_CLIENT_SECRET from the approved runtime secret store.
python scripts/soar_playbook/phantom_to_blob.py --input-file notable.json
```

The account URL must be HTTPS and end in
`.blob.core.usgovcloudapi.net`. The helper bounds the serialized payload to
1 MiB, rejects unsafe container/prefix values, uses a deterministic finding ID,
and uploads with `overwrite=False`. A retry with identical content returns
`already_exists`; a different payload at the same deterministic name fails
closed.

The customer must separately record private DNS/network path, identity object
ID, RBAC scope, source retry/dead-letter owner, synthetic test result, and
rollback procedure. The helper does not provide a backup or disaster-recovery
guarantee.
