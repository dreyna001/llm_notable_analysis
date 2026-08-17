# Commercial AWS OpenSearch provisioning

Run **before** the main SAM stack when `rag`, `RagIngestionEnabled`,
`SplQueryRagEnabled`, or `analyst_portal` case Q&A is enabled. The product stack
does **not** create an OpenSearch domain — provision a customer-managed VPC-only
domain in `us-east-1`, wire network access, then pass endpoint and ARN values into
SAM (`OpenSearchEndpoint`, `OpenSearchDomainArn`, `CustomerVpcSubnetIds`,
`CustomerSecurityGroupIds`, `RagTenantId`). AWS commercial uses OpenSearch per
[`../../internal/COMMERCIAL_AWS_APPROVED_DIFFERENCES.md`](../../internal/COMMERCIAL_AWS_APPROVED_DIFFERENCES.md) (CAWS-004).

**Path B steps 3 (Phase A) and 8 (Phase B):**
[`../../../README.md`](../../../README.md#path-b-customer-default).
Customer-default preset: [`COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md).

## Domain requirements

| Requirement | Notes |
| --- | --- |
| Region | `us-east-1` only for this product |
| Network | VPC-only; disable public access — layout in [`VPC_NETWORK_PREREQUISITES.md`](VPC_NETWORK_PREREQUISITES.md#target-layout) |
| Endpoint | HTTPS URL for `OpenSearchEndpoint` (no credentials in URL) |
| ARN | `OpenSearchDomainArn` for IAM least privilege |
| k-NN | Required; indexes use `knn_vector` at 1024 dimensions (Titan V2) |
| Encryption | At rest with customer CMK recommended; create domain with same CMK as `CustomerKmsKeyArn` |
| Fine-grained access control | **Off** for v1 unless your security team validates IAM role mapping separately |

The application creates indexes and k-NN mappings on first write via
`ensure_vector_index()` in `src/s3_notable_pipeline/opensearch_client.py`. Do
**not** hand-create index mappings unless you are debugging; use the product
ingestion and case-embed paths instead.

OpenSearch cost is separate from Bedrock embedding and Lambda. Start small in
staging; scale from observed corpus size and query latency. Snapshot and ISM
retention policies are customer-owned.

## Indexes (customer-default)

| SAM parameter | Default | Created when |
| --- | --- | --- |
| `OpenSearchSocIndex` | `soc_knowledge` | First SOC manifest ingestion |
| `OpenSearchSplunkIndex` | `splunk_dictionary` | First Splunk dictionary ingestion |
| `OpenSearchCaseIndex` | `case_chunks` | First case embed job |

Optional `OpenSearchElasticIndex` (`elastic_dictionary`) applies only when
`ElasticsearchGroundingEnabled=true`.

## IAM: product Lambda roles and OpenSearch actions

The SAM template grants these **IAM role** permissions (SigV4 to the domain):

| Lambda (default name) | CloudFormation logical role id (pattern) | OpenSearch IAM actions |
| --- | --- | --- |
| `notable-analyzer-s3` | `NotableAnalyzerFunctionRole` | `es:ESHttpGet`, `es:ESHttpPost` |
| `notable-portal-api` | `PortalApiFunctionRole` | `es:ESHttpGet`, `es:ESHttpPost` |
| `notable-case-embed` | `CaseEmbedFunctionRole` | `es:ESHttpGet`, `es:ESHttpPost`, `es:ESHttpPut`, `es:ESHttpDelete` |
| `notable-rag-ingestion` | `RagIngestionFunctionRole` | `es:ESHttpGet`, `es:ESHttpPost`, `es:ESHttpPut`, `es:ESHttpDelete` |

You must also allow those **role ARNs** in the OpenSearch **domain access
policy** (resource-based policy on the domain). IAM on the Lambda side alone is
not sufficient.

### Two-phase access policy (required)

SAM creates Lambda execution roles during deploy. The OpenSearch domain access
policy must trust those roles in a second step.

**Phase A — create domain:** use your deployment role or a break-glass admin
principal to create the domain and validate cluster health. The access policy may
list only admin principals.

**Phase B — after `sam deploy`:** copy **physical** IAM role names from the stack
(not logical ids alone). Vector SigV4 calls can return **403** until Phase B is
applied, even when Lambda IAM policies already allow `es:*` to the domain.

Lookup physical role names:

```bash
aws cloudformation describe-stack-resources \
  --stack-name notable-analyzer-stack \
  --region us-east-1 \
  --query "StackResources[?ResourceType=='AWS::IAM::Role'].[LogicalResourceId,PhysicalResourceId]" \
  --output table
```

Match `LogicalResourceId` values such as `NotableAnalyzerFunctionRole`,
`PortalApiFunctionRole`, `CaseEmbedFunctionRole`, and `RagIngestionFunctionRole`
to the `PhysicalResourceId` role names. Use those physical names in the domain
policy `Principal.AWS` ARNs.

Example Phase B policy (replace `<physical-role-name>` with values from the table
above):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": [
          "arn:aws:iam::<account-id>:role/<physical-role-name-for-NotableAnalyzerFunctionRole>",
          "arn:aws:iam::<account-id>:role/<physical-role-name-for-PortalApiFunctionRole>",
          "arn:aws:iam::<account-id>:role/<physical-role-name-for-CaseEmbedFunctionRole>",
          "arn:aws:iam::<account-id>:role/<physical-role-name-for-RagIngestionFunctionRole>"
        ]
      },
      "Action": [
        "es:ESHttpGet",
        "es:ESHttpPost",
        "es:ESHttpPut",
        "es:ESHttpDelete"
      ],
      "Resource": "arn:aws:es:us-east-1:<account-id>:domain/<domain-name>/*"
    }
  ]
}
```

Use read-only actions only for analyzer and portal roles if your policy engine
requires least privilege per principal. The template currently grants write
actions only to case-embed and rag-ingestion roles.

## Create domain (console or CLI outline)

Use your organization's standard OpenSearch baseline. Minimum fields:

| Setting | Staging starting point | Production notes |
| --- | --- | --- |
| Domain name | `notable-rag-staging` | Unique per environment |
| Engine | OpenSearch 2.x | Confirm k-NN support in selected version |
| Instance type | `t3.small.search` or org minimum | Scale with corpus + case volume |
| Instance count | 2 (multi-AZ) or 1 (dev only) | Multi-AZ for prod |
| Storage | 20–100 GiB gp3 | Monitor `_cat/indices` growth |
| VPC | Customer VPC | Same as Lambda subnets |
| Subnets | Private subnets (domain ENI) | Often 1 subnet per AZ used |
| Security group | OpenSearch SG (ingress from Lambda SG) | |
| Access policy | Phase A admin-only; Phase B after SAM | No public access |
| Encryption | CMK optional but recommended | Same key as `CustomerKmsKeyArn` when set |

CLI sketch (adjust for your VPC; requires approved deployment role):

```bash
export AWS_REGION=us-east-1
export DOMAIN_NAME=notable-rag-staging
export VPC_ID=vpc-xxxxxxxx
export SUBNET_IDS=subnet-aaa,subnet-bbb
export OPENSEARCH_SG=sg-xxxxxxxx
export KMS_KEY_ARN=arn:aws:kms:us-east-1:<account-id>:key/<key-id>

aws opensearch create-domain \
  --region "$AWS_REGION" \
  --domain-name "$DOMAIN_NAME" \
  --engine-version "OpenSearch_2.11" \
  --cluster-config InstanceType=t3.small.search,InstanceCount=2 \
  --ebs-options EBSEnabled=true,VolumeType=gp3,VolumeSize=50 \
  --vpc-options SubnetIds=$SUBNET_IDS,SecurityGroupIds=$OPENSEARCH_SG \
  --encryption-at-rest-options Enabled=true,KmsKeyId="$KMS_KEY_ARN" \
  --node-to-node-encryption-options Enabled=true \
  --enforce-https true \
  --domain-endpoint-options EnforceHTTPS=true,TLSSecurityPolicy=Policy-Min-TLS-1-2-2019-07
```

Wait until domain status is active, then record:

```bash
aws opensearch describe-domain \
  --region us-east-1 \
  --domain-name "$DOMAIN_NAME" \
  --query 'DomainStatus.{Endpoint:Endpoint,Arn:ARN}' \
  --output table
```

Map to preset env vars:

| Output | Env / SAM parameter |
| --- | --- |
| `Endpoint` | `OPENSEARCH_ENDPOINT` -> `https://vpc-...` |
| `ARN` | `OPENSEARCH_DOMAIN_ARN` |
| Stable tenant label | `RAG_TENANT_ID` (e.g. `customer-acme-prod`) |
| Lambda subnets | `CUSTOMER_VPC_SUBNET_IDS` |
| Lambda SG | `CUSTOMER_SECURITY_GROUP_IDS` |

## Tenant identifier

`RagTenantId` is applied to every OpenSearch document and query filter. Choose
one stable value per deployment boundary before first ingest. Changing it after
data exists requires re-ingestion or a controlled migration.

## Validation

Run in order:

1. **Domain health** — `aws opensearch describe-domain`; `Processing` is false,
   `Created` is true.
2. **Network** — from a host in the VPC (or post-deploy Lambda logs), HTTPS to
   the VPC endpoint succeeds.
3. **SAM deploy** — stack completes with OpenSearch parameters set; no
   `RequireOpenSearchForVectorCapabilities` assertion failures.
4. **Access policy Phase B** — after physical role ARNs are attached, no `403`
   on SigV4 requests from Lambdas.
5. **Index bootstrap** — publish one SOC manifest; confirm `soc_knowledge` (or
   your `OpenSearchSocIndex`) appears with k-NN mapping.
6. **Tenant isolation** — query with a wrong tenant returns zero hits (see
   [`../rag/KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md)
   validation section).
7. **Case path** — one notable through customer-default; CaseIndex
   `retrieval_status=ready` and `case_chunks` documents present.

Staging gate for customer-default:
[`../../testing/TESTING.md`](../../testing/TESTING.md) (OpenSearch preflight +
customer-default row).

## Next

- **Path B step 4 (after Phase A):** [`BEDROCK_ACCOUNT_ENABLEMENT.md`](BEDROCK_ACCOUNT_ENABLEMENT.md)
- **Path B step 8 complete:** [`KMS_CUSTOMER_KEY.md`](KMS_CUSTOMER_KEY.md) Phase B when using `CustomerKmsKeyArn`; then [`KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md)
- **Path C:** [`../../../README.md`](../../../README.md#path-c-custom-profiles) after Phase A or Phase B as applicable
