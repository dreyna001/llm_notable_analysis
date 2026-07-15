# SIEM/SOAR private intake operations

Every producer writes one complete bounded object to
`input/incoming/<finding_id>.json` or `.json.gz`. The core stack is vendor
neutral and the input storage public endpoint remains disabled.

## Select one primary profile

- **Direct private upload:** an Azure-hosted or federated producer reaches the
  Blob private endpoint over peering/VPN/ExpressRoute and has `Storage Blob Data
  Contributor` only on the `input` container.
- **Private transfer bridge:** a customer-owned worker privately uploads after
  retrieving from an approved API, webhook, SFTP, or export. It checkpoints the
  source only after upload and owns source-retry/dead-letter handling.
- **Controlled manual:** a named operator on a hardened private runner uploads
  for pilot, replay, or recovery. This may be the secondary profile.

Do not write partial data at the final name. Validate extension and size before
upload. Source credentials belong in the producer's approved secret store, not
this stack. Workload identity/managed identity is preferred; scope access to the
input container and deny output, portal, and host storage.

JSON producers should include an authoritative `finding_id`, `notable_id`, or
`sid`. When none is present, the pipeline derives a collision-safe identity from
the complete container/key location rather than trusting the basename alone.
Both the compressed object size (`MAX_COMPRESSED_INPUT_BYTES`) and decompressed
content size (`MAX_DECOMPRESSED_INPUT_BYTES`) are enforced.

## Customer intake record

Outside this repository record: primary/secondary profile; SIEM/SOAR and hosting
location; producer/bridge, network, DNS, identity, source-credential,
retry/dead-letter, monitoring, and replay owners; identity object ID and exact
RBAC scope; connector/upload configuration; synthetic test result; rollback;
and approval date. Do not commit customer names, addresses, private DNS, tokens,
or object payloads.

## Validation, replay, and rollback

From the private staging runner, prove DNS resolves the private endpoint,
public/direct access is denied, one synthetic object produces one report, a 3x
burst drains within its objective, duplicate/out-of-order delivery produces one
business outcome, and publication/analyzer/embed poison alerts fire.

For replay, first identify the failure domain and check whether a durable
analyzer job/report already exists. Correct the cause, preserve the poison
message as evidence, and replay through the matching normal path with the same
stable identity. Record operator, source ID, destination blob, timestamp,
reason, and outcome. Never replay all poison queues blindly.

Rollback disables the producer or bridge and leaves queued/durable objects for
reconciliation. It does not enable public storage or delete failed evidence.

For Splunk SOAR/Phantom, the optional producer helper is documented at
[`scripts/soar_playbook/README.md`](../../../scripts/soar_playbook/README.md).
It is customer-configurable for managed identity or runtime-injected service
principal use and contains no secret values.
