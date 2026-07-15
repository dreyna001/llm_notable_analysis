# Executive workflow and readiness

## One-page workflow

1. **Ingest:** A customer SIEM/SOAR or approved operator uploads a complete
   notable to private Blob Storage in Azure Government `usgovvirginia`.
2. **Analyze:** Azure Functions consumes a strict queue job and calls the
   customer-owned Azure OpenAI deployment. Output is validated before storage.
3. **Ground:** Optional Azure AI Search retrieval adds source-attributed,
   advisory knowledge or case context. It does not replace direct evidence.
4. **Review:** Analysts use the private portal or reports to inspect verdict,
   evidence gaps, MITRE mapping, queries, and recommended actions.
5. **Act:** Splunk writeback and ServiceNow create remain disabled unless the
   customer's capability profile, identity, approval, idempotency, and
   reconciliation gates are complete.
6. **Operate:** Monitor poison paths, backlog, dependencies, authenticated
   readiness, retention, and rollback evidence.

## Readiness decisions

| Executive question | Required answer |
| --- | --- |
| Where does data run? | Azure US Government, default `usgovvirginia`, with customer-qualified services and private paths. |
| Who owns access? | Customer identities, RBAC, Key Vault, private DNS, integration credentials, and approval owners. |
| What is enabled? | A named capability profile with explicit read-only versus write/action boundaries. |
| How is quality measured? | Offline tests, local parity, Azure Government staging, and golden evaluation with synthetic data. |
| How is failure handled? | Independent poison queues, durable outcomes, manual idempotent replay, and named escalation. |

## Go/no-go evidence

- [ ] Customer configuration and endpoint/identity record approved.
- [ ] Azure OpenAI model/quota and Azure AI Search schema/retrieval qualified in
  `usgovvirginia`.
- [ ] Private-origin, managed-identity, authentication, and RBAC tests pass.
- [ ] Golden evaluation and evidence/inference review pass the customer rubric.
- [ ] Poison recovery, replay, retention, rollback, and monitoring are rehearsed.
- [ ] Splunk/ServiceNow write capabilities are either disabled or have explicit
  approval and reconciliation evidence.
- [ ] Residual deployment risks have an owner and review date in the customer system.

Production intake remains disabled until the applicable evidence is complete or
a time-bounded, owner-approved exception defines rollback and residual risk.
