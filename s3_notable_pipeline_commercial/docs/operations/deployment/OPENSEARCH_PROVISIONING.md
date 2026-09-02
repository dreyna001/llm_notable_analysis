# OpenSearch provisioning

## Path B

Use [`deploy/terraform/customer_default/`](../../../deploy/terraform/customer_default/).
Set either:

- create mode with domain name, administrator principals, VPC, private subnets,
  capacity, and optional KMS inputs; or
- existing mode with the VPC-only endpoint and domain ARN.

Existing mode is only for a dedicated product domain. Terraform replaces its
complete access policy. Set `replace_existing_opensearch_access_policy = true`
only after the customer approves that ownership and the reviewed plan contains
every required principal.

The full Terraform plan creates deterministic analyzer, case-embed,
RAG-ingestion, and portal role ARNs and places them directly in the domain access
policy. Review and apply once. There is no later role discovery or policy-edit
step for Path B.

Required controls:

- commercial `aws` partition and `us-east-1`
- VPC-only endpoint and approved private subnets
- HTTPS enforced and node-to-node encryption enabled
- encryption at rest using the approved key
- administrator principals limited to approved roles
- read access only for analyzer and portal roles
- write access only for case-embed and RAG-ingestion roles
- no public or anonymous domain access

Customer-default indexes:

| Index | Writer | Readers |
| --- | --- | --- |
| `soc_knowledge` | RAG ingestion | Analyzer, portal |
| `splunk_dictionary` | RAG ingestion | Analyzer, portal |
| `case_chunks` | Case embed | Portal |

The application creates indexes through its normal ingestion or case-embedding
path. Keep `rag_tenant_id` stable and verify tenant filtering on every query.

Validation:

```bash
terraform -chdir=deploy/terraform/customer_default validate
bash scripts/setup-and-deploy.sh
# Review domain network, encryption, capacity, access policy, and application role ARNs.
bash scripts/setup-and-deploy.sh --apply
terraform -chdir=deploy/terraform/customer_default output -json
```

After apply:

1. confirm the endpoint is unreachable from an unapproved public path;
2. confirm analyzer and portal signed reads succeed;
3. confirm case-embed and RAG-ingestion signed writes succeed;
4. confirm cross-tenant retrieval fails;
5. ingest the SOC and Splunk dictionary corpora using
   [`KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md).

## Paths A/C legacy SAM workflow

Paths A/C may use the standalone [`deploy/terraform/opensearch/`](../../../deploy/terraform/opensearch/)
module with their legacy SAM application deployment. In that split-state layout,
follow the standalone module README for its explicit application-role policy
handoff. Do not use that handoff for Path B.
