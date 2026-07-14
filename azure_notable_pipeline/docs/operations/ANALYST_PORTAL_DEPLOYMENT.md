# Analyst portal private deployment

Enable the portal with `CAPABILITY_PROFILES=core,analyst_portal`. Supply a
dedicated portal UI storage account name, the UI deployer principal object ID,
JWT issuer/audience, the required analyst role/scope, OIDC SPA client ID,
authority and delegated API scope, Azure
OpenAI endpoint/resource/deployments, APIM publisher email, and a short-lived
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
Storage `web` and APIM `Gateway` origins. The scripts approve only the request
whose description matches each declared Front Door origin and poll both target
connections and Front Door origin status. APIM public access is disabled only
after both report `Approved`. APIM reaches the private Function backend through
its dedicated VNet-integration subnet. That subnet has an attached NSG with
explicit HTTPS egress for APIM's Storage and Key Vault dependencies, Entra OIDC
metadata, and the private VNet backend. The NSG intentionally retains Azure's
default Internet outbound rule because TLS revocation and APIM platform egress
have not yet been converted to a complete explicit allowlist; do not add a blanket
deny until those dependencies are validated for the target cloud. The gate then
confirms storage and Function public access remain disabled, a direct APIM
request does not succeed, and
authenticated `/ready` succeeds through Front Door. A private deployment runner
can legitimately reach the Function and `$web` private endpoints, so their
public denial is asserted from their control-plane `publicNetworkAccess` state.

All `/api/*` requests follow the same Front Door-to-APIM path. APIM retains a
30-second API-level backend timeout and overrides only `POST /api/chat` to 230
seconds. The browser stops at 220 seconds, the Function host at 225 seconds,
and Front Door at 240 seconds. This preserves the synchronous chat contract
without bypassing centralized API authentication and policy.

All portal routes are authenticated, including `/health` and `/ready`.
Single-origin Front Door health probes are intentionally absent because they
cannot present an analyst token. Production availability requires a
customer-owned authenticated synthetic monitor against Front Door `/ready`;
the reusable stack stores no monitor credential or long-lived token.

All backend tests, frontend tests/build, OpenAPI contract tests, Bicep compile,
and production container build complete before the scripts mutate Azure. On a
later failure, cleanup disables APIM public access before returning failure.

Rollback is a Bicep redeployment using the prior immutable image digest and UI
artifact. Do not restore public origin access. If any managed private endpoint
is pending or rejected, leave APIM public access enabled only during the
initial deployment gate, correct approval permissions, and rerun the gate
before production use.
