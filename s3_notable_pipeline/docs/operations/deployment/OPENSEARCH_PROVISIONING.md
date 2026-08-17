# GovCloud OpenSearch provisioning

Run **before** the main SAM stack when `rag`, `RagIngestionEnabled`,
`SplQueryRagEnabled`, or `analyst_portal` case Q&A is enabled. The product stack
does **not** create an OpenSearch domain — provision a customer-managed VPC-only
Amazon OpenSearch Service domain in `us-gov-east-1` (partition `aws-us-gov`),
wire network access, attach IAM permissions, then pass endpoint and ARN values
into SAM (`OpenSearchEndpoint`, `OpenSearchDomainArn`, `CustomerVpcSubnetIds`,
`CustomerSecurityGroupIds`, `RagTenantId`).

**Path B steps 3 (Phase A) and 8 (Phase B):**
[`../../../README.md`](../../../README.md#path-b-customer-default).
Customer-default preset: [`GOVCLOUD_CUSTOMER_DEFAULT_DEPLOYMENT.md`](GOVCLOUD_CUSTOMER_DEFAULT_DEPLOYMENT.md).

On-prem equivalent: Postgres + pgvector (see on-prem RAG ops). GovCloud production
uses application-managed OpenSearch retrieval per
[`../../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md`](../../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md).

VPC and subnet design:
[`VPC_NETWORK_PREREQUISITES.md`](VPC_NETWORK_PREREQUISITES.md).

## Domain requirements

| Requirement | Notes |
| --- | --- |
| Region | `us-gov-east-1` only for this product |
| Partition | `aws-us-gov` |
| Network | VPC-only; disable public access |
| Endpoint | HTTPS URL for `OpenSearchEndpoint` (no credentials in URL) |
| ARN | `OpenSearchDomainArn` matching `arn:aws-us-gov:es:us-gov-east-1:...` |
| k-NN | Required; indexes use `knn_vector` at 1024 dimensions (Titan V2) |
| Encryption | At rest with customer CMK recommended; align with `CustomerKmsKeyArn` |
| Fine-grained access control | **Off** for v1 unless your security team validates IAM role mapping separately |

The application creates indexes and k-NN mappings on first write via
`ensure_vector_index()` in `src/s3_notable_pipeline/opensearch_client.py`. Do
**not** hand-create index mappings unless you are debugging; use the product
ingestion and case-embed paths instead.

## Indexes (typical RAG + portal bundle)

| SAM parameter | Default | Created when |
| --- | --- | --- |
| `OpenSearchSocIndex` | `soc_knowledge` | First SOC manifest ingestion |
| `OpenSearchSplunkIndex` | `splunk_dictionary` | First Splunk dictionary ingestion |
| `OpenSearchCaseIndex` | `case_chunks` | First case embed job |

Optional `OpenSearchElasticIndex` (`elastic_dictionary`) applies only when
`ElasticsearchGroundingEnabled=true`.

## Network layout

Lambdas that touch OpenSearch run inside the customer VPC when
`CustomerVpcSubnetIds` and `CustomerSecurityGroupIds` are set (required for
enabled vector capabilities).

```text
                    +---------------------------+
                    |  Private subnets (2+ AZ)  |
                    |                           |
  S3 / SQS / DDB /  |  Lambda SG  ----443---->  |  OpenSearch domain SG
  Bedrock / Logs    |       |                   |  (VPC endpoint only)
  via NAT or        |       v                   |
  VPC endpoints     |  Analyzer, Portal,        |
                    |  Case embed, RAG ingest   |
                    +---------------------------+
```

### Lambda security group (egress)

- TCP **443** to the OpenSearch domain security group only (not `0.0.0.0/0` for
  the OpenSearch path).
- Egress to AWS APIs required for non-VPC services: use **NAT gateway** in the
  VPC route table **or** interface VPC endpoints for:
  - `com.amazonaws.us-gov-east-1.s3`
  - `com.amazonaws.us-gov-east-1.sqs`
  - `com.amazonaws.us-gov-east-1.dynamodb`
  - `com.amazonaws.us-gov-east-1.logs`
  - `com.amazonaws.us-gov-east-1.bedrock-runtime`
  - `com.amazonaws.us-gov-east-1.secretsmanager` (when integrations use Secrets Manager)

Record the Lambda security group ID as `CustomerSecurityGroupIds` and private
subnet IDs as `CustomerVpcSubnetIds` (comma-separated, no spaces).

### OpenSearch domain security group (ingress)

- TCP **443** from the Lambda security group only.

Place the domain in the **same VPC** as the Lambda subnets. Cross-VPC peering
is out of scope for the default runbook; treat as a custom network design.

## IAM: product Lambda roles and OpenSearch actions

The SAM template grants these **IAM role** permissions (SigV4 to the domain):

| Lambda (default name) | OpenSearch IAM actions |
| --- | --- |
| `notable-analyzer-s3` | `es:ESHttpGet`, `es:ESHttpPost` |
| `notable-portal-api` | `es:ESHttpGet`, `es:ESHttpPost` |
| `notable-case-embed` | `es:ESHttpGet`, `es:ESHttpPost`, `es:ESHttpPut`, `es:ESHttpDelete` |
| `notable-rag-ingestion` | `es:ESHttpGet`, `es:ESHttpPost`, `es:ESHttpPut`, `es:ESHttpDelete` |

You must also allow those **role ARNs** in the OpenSearch **domain access
policy** (resource-based policy on the domain). IAM on the Lambda side alone is
not sufficient.

### Two-phase access policy (recommended)

**Phase A — create domain:** use your deployment role or a break-glass admin
principal to create the domain and validate cluster health.

**Phase B — after `sam deploy`:** collect Lambda execution role ARNs from the
CloudFormation stack (Resources tab or CLI), then update the domain access
policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": [
          "arn:aws-us-gov:iam::<account-id>:role/<stack-name>-AnalyzerFunctionRole-<suffix>",
          "arn:aws-us-gov:iam::<account-id>:role/<stack-name>-PortalApiFunctionRole-<suffix>",
          "arn:aws-us-gov:iam::<account-id>:role/<stack-name>-CaseEmbedFunctionRole-<suffix>",
          "arn:aws-us-gov:iam::<account-id>:role/<stack-name>-RagIngestionFunctionRole-<suffix>"
        ]
      },
      "Action": [
        "es:ESHttpGet",
        "es:ESHttpPost",
        "es:ESHttpPut",
        "es:ESHttpDelete"
      ],
      "Resource": "arn:aws-us-gov:es:us-gov-east-1:<account-id>:domain/<domain-name>/*"
    }
  ]
}
```

Use read-only actions only for analyzer and portal roles if your policy engine
requires least privilege per principal. The template currently grants write
actions only to case-embed and rag-ingestion roles.

Example role lookup after deploy:

```bash
aws cloudformation describe-stack-resources \
  --stack-name notable-analyzer-stack \
  --region us-gov-east-1 \
  --query "StackResources[?ResourceType=='AWS::IAM::Role'].[LogicalResourceId,PhysicalResourceId]" \
  --output table
```

## Create domain (console or CLI outline)

Use your organization's GovCloud OpenSearch baseline. Minimum fields:

| Setting | Staging starting point | Production notes |
| --- | --- | --- |
| Domain name | `notable-rag-staging` | Unique per environment |
| Engine | OpenSearch 2.x | Confirm k-NN support in selected version |
| Instance type | Org-approved minimum search instance | Scale with corpus + case volume |
| Instance count | 2 (multi-AZ) or 1 (dev only) | Multi-AZ for prod |
| Storage | 20–100 GiB gp3 | Monitor `_cat/indices` growth |
| VPC | Customer GovCloud VPC | Same as Lambda subnets |
| Subnets | Private subnets (domain ENI) | Often 1 subnet per AZ used |
| Security group | OpenSearch SG (ingress from Lambda SG) | |
| Access policy | Phase B policy above | No public access |
| Encryption | CMK optional but recommended | Same key as `CustomerKmsKeyArn` when set |

CLI sketch (adjust for your VPC; requires approved GovCloud deployment role):

```bash
export AWS_REGION=us-gov-east-1
export DOMAIN_NAME=notable-rag-staging
export SUBNET_IDS=subnet-aaa,subnet-bbb
export OPENSEARCH_SG=sg-xxxxxxxx
export KMS_KEY_ARN=arn:aws-us-gov:kms:us-gov-east-1:<account-id>:key/<key-id>

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
  --region us-gov-east-1 \
  --domain-name "$DOMAIN_NAME" \
  --query 'DomainStatus.{Endpoint:Endpoint,Arn:ARN}' \
  --output table
```

Map to SAM parameters:

| Output | SAM parameter |
| --- | --- |
| `Endpoint` | `OpenSearchEndpoint` -> `https://vpc-...` |
| `ARN` | `OpenSearchDomainArn` |
| Stable tenant label | `RagTenantId` (e.g. `customer-acme-prod`) |
| Lambda subnets | `CustomerVpcSubnetIds` |
| Lambda SG | `CustomerSecurityGroupIds` |
| Region | `OpenSearchRegion=us-gov-east-1` (template default) |

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
4. **Access policy** — after role ARNs are attached, no `403` on SigV4 requests
   from Lambdas.
5. **Index bootstrap** — publish one SOC manifest; confirm `soc_knowledge` (or
   your `OpenSearchSocIndex`) appears with k-NN mapping.
6. **Tenant isolation** — query with a wrong tenant returns zero hits (see
   [`../rag/KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md)
   validation section).
7. **Case path** — when portal is enabled, one notable through the stack;
   CaseIndex `retrieval_status=ready` and `case_chunks` documents present.

Staging gate:
[`../../testing/TESTING.md`](../../testing/TESTING.md) (OpenSearch preflight +
Wave 1/2 checklists).

## Sizing and cost (orientation only)

OpenSearch cost is separate from Bedrock embedding and Lambda. Start small in
staging; scale data nodes and storage from observed corpus size, case chunk
count, and query latency. Snapshot and ISM retention policies are customer-owned.

## Next

- **Path B step 4 (after Phase A):** [`BEDROCK_ACCOUNT_ENABLEMENT.md`](BEDROCK_ACCOUNT_ENABLEMENT.md)
- **Path B step 8 complete:** [`KMS_CUSTOMER_KEY.md`](KMS_CUSTOMER_KEY.md) Phase B when using `CustomerKmsKeyArn`; then [`KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md)
- **Path C:** [`../../../README.md`](../../../README.md#path-c-custom-profiles) after Phase A or Phase B as applicable
