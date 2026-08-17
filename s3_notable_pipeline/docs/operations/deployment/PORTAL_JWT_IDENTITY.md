# GovCloud AWS portal JWT identity

Configure an OIDC identity source for the analyst portal when
`PortalEnabled=true` and `PortalAuthMode=jwt` (default). The product **validates**
JWTs at API Gateway and again in the portal Lambda — it does **not** host login
pages, user directories, or token issuance.

Region: `us-gov-east-1`. Partition: `aws-us-gov`.

**Path B step 5** (before SAM when portal JWT mode is enabled):
[`../../../README.md`](../../../README.md#path-b-customer-default).

## What you must provide

| SAM parameter | Purpose |
| --- | --- |
| `PortalJwtIssuer` | OIDC issuer URL (HTTPS, no credentials in URL) |
| `PortalJwtAudience` | API audience (`aud`) expected on every token |
| `PortalRequiredAnalystRole` **or** `PortalRequiredAnalystScope` | Analyst grant — at least one required when portal JWT is enabled |
| `PortalCorsAllowedOrigins` | Exact browser origins allowed to call the API |
| `RagTenantId` | Tenant id used in application checks (align with token claims if you enforce tenant in app layer) |

Optional: `PortalAuthMode=iam` for SigV4-only clients (no JWT authorizer).

## Token contract (what the product checks)

API Gateway JWT authorizer validates issuer and audience on `/api/*` routes.

Portal Lambda additionally requires:

- Valid signature via issuer JWKS
- Claims: `exp`, `iss`, `aud` (required)
- **`sub`** — portal user id for chat idempotency and audit
- **Analyst grant** — configured **role** and/or **scope**:

| SAM parameter | Accepted claim names |
| --- | --- |
| `PortalRequiredAnalystRole` | `roles`, `role`, `app_role`, `application_role`, Keycloak `realm_access.roles`, nested `resource_access.*.roles` |
| `PortalRequiredAnalystScope` | `scope`, `scp`, `scopes` |

Static SPA assets are served without JWT; only `/api/*` requires authentication.

## Reference: Amazon Cognito user pool (GovCloud)

1. **Create user pool** in `us-gov-east-1`
2. **Create app client** (PKCE for public SPA when appropriate)
3. **Issuer:** `https://cognito-idp.us-gov-east-1.amazonaws.com/<user-pool-id>`
4. **Analyst grant** — scope or role claim (same patterns as commercial doc)
5. **Set SAM parameters** at deploy
6. **Build/upload portal SPA** to `PortalUiBucketName`

Corporate IdP (Okta, Azure AD Gov, Keycloak) works when JWKS and claims match.

## Map claims to SAM parameters (examples)

| IdP style | `PortalJwtIssuer` | `PortalJwtAudience` | Grant |
| --- | --- | --- | --- |
| Cognito user pool | `https://cognito-idp.us-gov-east-1.amazonaws.com/us-gov-east-1_abc123` | App client id | `PortalRequiredAnalystScope=portal/read` |
| Keycloak | `https://auth.customer.example/realms/soc` | `notable-portal` | `PortalRequiredAnalystRole=analyst` |

Use comma-separated values for multiple allowed roles or scopes.

## Browser and CORS

`PortalCorsAllowedOrigins` must list the **exact origin** the browser uses.
The product does not provision CloudFront, ALB, or WAF.

## Validation

1. **Without token** — `GET /api/cases` returns 401
2. **Valid token, wrong scope/role** — 403
3. **Valid analyst token** — 200 with case list JSON
4. **CORS** — browser preflight from configured origin succeeds

Do not commit tokens to git or store in SPA assets.

## Next

- **Path B step 6:** [`DEPLOYMENT_IMAGE_STEPS.md`](DEPLOYMENT_IMAGE_STEPS.md)
- **Path C:** same when `analyst_portal` is in the profile set — [`../../../README.md`](../../../README.md#path-c-custom-profiles)
- Day-two portal ops: [`../analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md)
