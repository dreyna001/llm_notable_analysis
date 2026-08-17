# Azure deployment image operations

Build, scan, and promote one immutable `linux/amd64` digest for analyzer, embed,
disposition, and portal Function Apps. Tags are build inputs only; a digest URI
is the deployment contract.

Cloud `AzureUSGovernment`, default region `usgovvirginia`. Before ACR push or
Bicep deploy, follow the live mutation gate in
[`../../../README.md`](../../../README.md#1-prerequisites) (subscription ID,
partition, region, role/profile, resource group, deployment name, explicit
customer approval).

**Path B step 6** (digest-qualified image before Bicep):
[`../../../README.md`](../../../README.md#path-b-customer-default).

## Prerequisites and decisions

Record the Azure Government subscription, `usgovvirginia`-qualified region, resource group,
naming prefix, ACR resource ID, customer capability profile, image retention,
rollback digest, and deployment owner outside the reusable repository. The
runner must have private network/DNS access to the deployment endpoints and
permission to deploy Bicep, assign roles, approve Front Door private endpoint
connections, and push to ACR. Do not enable public storage or origins as a
deployment shortcut.

Before build, obtain customer approval for the customer-owned Azure OpenAI
model boundary described in
[`../llm/LLM_INFERENCE_OPERATIONS.md`](../llm/LLM_INFERENCE_OPERATIONS.md).

## Build, scan, and resolve the digest

```bash
az login
az account set --subscription "$AZURE_SUBSCRIPTION_ID"
export CONTAINER_REGISTRY_RESOURCE_ID=<full-acr-resource-id>
export IMAGE_REPOSITORY=notable-analysis
export IMAGE_TAG="$RELEASE_VERSION"
./scripts/build-image.sh
```

Run Python/frontend tests and the organization's container vulnerability and
license gates before promotion. Capture the emitted
`<registry>.azurecr.io/notable-pipeline@sha256:<digest>` value and verify the
digest exists with `az acr repository show-manifests`. Never place ACR admin
credentials in app settings, Bicep parameters, scripts, or image layers.

## Deploy and validate

Use `scripts/setup-and-deploy.sh` or `.ps1` with the immutable image URI and the
matching ACR resource ID. The deploy helpers validate registry consistency,
UAMI-based `AcrPull`, identity-based Functions host storage, private endpoints,
Function wrapper inventory, portal origin approval/denial, and authenticated
Front Door readiness. Secret values remain in Key Vault; deployment inputs are
secret names only.

After deploy, run from the isolated staging runner:

```bash
export AZURE_RESOURCE_GROUP=<staging-resource-group>
export AZURE_DEPLOYMENT_NAME=<deployment-name>
export STAGING_SUBSCRIPTION_ID=<dedicated-staging-subscription-id>
export STAGING_CHAOS_CONFIRMATION=isolated-nonproduction
export PORTAL_TEST_BEARER_TOKEN=<short-lived-dedicated-synthetic-token>
./scripts/test-pipeline.sh --staging-gate
```

The gate refuses a subscription mismatch, generates only synthetic fixtures,
and fails if consequential Splunk or ServiceNow creation is enabled.

## Rollback

Redeploy the last qualified digest and matching portal artifact through the
same scripts. Do not retag an unqualified image and do not restore public
access. Confirm Function hosts, private intake, report production, Front Door
authentication, queues, and synthetic monitoring. Preserve the failed digest,
deployment operation ID, logs, and staging evidence until incident closure.

Image rollback does not reverse durable Cosmos/Blob schema changes. This v1
contract has no destructive schema migration; a future migration requires its
own forward/backward compatibility plan.

## Next

- **Path A step 3:** `setup-and-deploy.*` — [`../../../README.md`](../../../README.md#path-a-core-only)
- **Path B step 7:** [`AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md`](AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md)
- **Path C step 6:** Bicep deploy with profile-specific parameters — [`../../../README.md`](../../../README.md#path-c-custom-profiles)
- Post-deploy (portal SPA, KB ingest, smoke): [`AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md`](AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md#post-deploy-required-for-full-customer-default)
