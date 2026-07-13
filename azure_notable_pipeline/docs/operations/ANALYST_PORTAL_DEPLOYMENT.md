# Analyst portal private deployment

Enable the portal with `CAPABILITY_PROFILES=core,analyst_portal`. Supply a
dedicated portal UI storage account name, the UI deployer principal object ID,
JWT issuer/audience (and the required Entra app role for `iam` mode), Azure
OpenAI endpoint/resource/deployments, APIM publisher email, and a short-lived
validation bearer token. Never store that token in source or a committed env
file.

Run `scripts/setup-and-deploy.sh` or `.ps1` from a private-network-connected
runner with private DNS. The scripts deploy one immutable image digest to the
analyzer, embed, and portal apps, verify UAMI-based ACR and Functions host
storage, build/test the same-origin SPA, and upload `$web` with Microsoft Entra
authentication.

Front Door Premium creates managed private endpoint connections for the
Storage `web`, APIM `Gateway`, and Function `sites` origins. The scripts approve
every pending connection on those three dedicated origins and poll both target
connections and Front Door origin status. APIM public access is disabled only
after all three report `Approved`. The gate then confirms storage and Function
public access remain disabled, a direct APIM request does not succeed, and
authenticated `/ready` succeeds through Front Door. A private deployment runner
can legitimately reach the Function and `$web` private endpoints, so their
public denial is asserted from their control-plane `publicNetworkAccess` state.

All portal routes are authenticated, including `/health` and `/ready`.
Single-origin Front Door health probes are intentionally absent because they
cannot present an analyst token. Production availability requires a
customer-owned authenticated synthetic monitor against Front Door `/ready`;
the reusable stack stores no monitor credential or long-lived token.

Rollback is a Bicep redeployment using the prior immutable image digest and UI
artifact. Do not restore public origin access. If any managed private endpoint
is pending or rejected, leave APIM public access enabled only during the
initial deployment gate, correct approval permissions, and rerun the gate
before production use.
