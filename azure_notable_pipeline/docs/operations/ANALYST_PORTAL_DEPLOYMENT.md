# Azure Government analyst portal private deployment

This portal deployment is for Azure US Government, defaulting to
`usgovvirginia`. Use Government endpoints and audiences, including the
customer-qualified Azure OpenAI endpoint and Azure AI Search endpoint; do not
fall back to commercial origins or identity authorities. Record the selected
region, private DNS zones, Front Door/Function resource IDs, and Entra application
values in the customer deployment record rather than this repository.

Enable the portal with `CAPABILITY_PROFILES=core,analyst_portal`. Supply a
dedicated portal UI storage account name, the UI deployer principal object ID,
JWT issuer/audience, the required analyst role/scope, OIDC SPA client ID,
authority and delegated API scope, Azure
OpenAI endpoint/resource/deployments, Azure AI Search values, and a short-lived
validation bearer token. Never store that token in source or a committed env
file.

For JWT browser authentication, set `PORTAL_ENTRA_REQUIRED_APP_ROLE` to the
final delegated-scope segment in `PORTAL_OIDC_API_SCOPE` (for example,
`Portal.Access`). The deployment scripts fail before Azure mutation when these
values drift.

Run `scripts/setup-and-deploy.sh` or `.ps1` from a private-network-connected
runner with private DNS. The scripts deploy one immutable image digest to the
analyzer, embed, and portal apps, verify UAMI-based ACR and Functions host
storage, build/test the same-origin SPA, and upload `$web` with Microsoft Entra
authentication.

Front Door Premium creates managed private endpoint connections for the
Storage `web` and portal Function `sites` origins. The scripts approve only the
request whose description matches each declared Front Door origin and poll both
target connections and Front Door origin status. The gate then confirms storage
and Function public access remain disabled, a direct Function request does not
succeed, and
authenticated `/ready` succeeds through Front Door. A private deployment runner
can legitimately reach the Function and `$web` private endpoints, so their
public denial is asserted from their control-plane `publicNetworkAccess` state.

All `/api/*` requests follow the same Front Door-to-Function path. The browser
stops at 220 seconds, the Function host at 225 seconds, and Front Door at 240
seconds. Authentication and authorization remain server-side in the Function.

All portal routes are authenticated, including `/health` and `/ready`.
Single-origin Front Door health probes are intentionally absent because they
cannot present an analyst token. Production availability requires a
customer-owned authenticated synthetic monitor against Front Door `/ready`;
the reusable stack stores no monitor credential or long-lived token.

All backend tests, frontend tests/build, OpenAPI contract tests, Bicep compile,
and production container build complete before the scripts mutate Azure.

Rollback is a Bicep redeployment using the prior immutable image digest and UI
artifact. Do not restore public origin access. If any managed private endpoint
is pending or rejected, correct approval permissions and rerun the gate before
production use.
