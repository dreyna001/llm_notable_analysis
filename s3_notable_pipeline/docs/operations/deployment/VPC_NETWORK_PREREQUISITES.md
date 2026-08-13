# GovCloud AWS VPC and network prerequisites

Provision customer VPC networking **before** OpenSearch, private integration
endpoints, or any SAM deploy that sets `CustomerVpcSubnetIds` and
`CustomerSecurityGroupIds`.

The product stack does **not** create a VPC, subnets, NAT gateway, route tables,
or VPC endpoints. It attaches Lambdas to subnets and security groups you supply.

Partition `aws-us-gov`, region `us-gov-east-1` only.

## When this runbook is required

| Deploy shape | VPC required? |
| --- | --- |
| `CapabilityProfiles=core` only, no private integrations | **Optional** — Lambdas can run without `VpcConfig` |
| `rag`, `RagIngestionEnabled`, `SplQueryRagEnabled`, portal case Q&A | **Required** — OpenSearch is VPC-only |
| `spl_readonly` / `elastic_readonly` to **private** SIEM URLs | **Required** — set `AllowPrivateOutboundEndpoints=true` |
| `analyst_portal` with OpenSearch case retrieval | **Required** |

OpenSearch domain setup continues in
[`OPENSEARCH_PROVISIONING.md`](OPENSEARCH_PROVISIONING.md) after this runbook.

## Target layout

```text
VPC (customer)
  private subnets (2+ AZ)  ---> Lambda ENIs (product functions)
  optional public subnets  ---> NAT gateway (if not using VPC endpoints)
  route tables             ---> NAT and/or gateway endpoints
  Lambda security group    ---> egress 443 to OpenSearch SG + AWS APIs
  OpenSearch security group ---> ingress 443 from Lambda SG only
```

## Minimum customer deliverables

Record these for SAM:

| Value | SAM parameter |
| --- | --- |
| Private subnet IDs (comma-separated, no spaces) | `CustomerVpcSubnetIds` |
| Lambda security group ID(s) | `CustomerSecurityGroupIds` |

Subnets must have routes to:

1. **OpenSearch** (same VPC) — via security group rules on port 443
2. **AWS service APIs** — via **NAT gateway** or **interface VPC endpoints**

## Lambda security group (egress)

Recommended rules:

| Direction | Protocol | Destination | Purpose |
| --- | --- | --- | --- |
| Egress | TCP 443 | OpenSearch domain security group | Vector retrieval and ingestion |
| Egress | TCP 443 | Prefix list or endpoint SG for VPC endpoints | S3, DynamoDB, SQS, Bedrock, Logs, Secrets Manager |
| Egress | TCP 443 | `0.0.0.0/0` via NAT | Only if **not** using VPC endpoints for those services |
| Egress | TCP 443 | Customer Splunk/Elastic/ServiceNow private IPs | When integrations enabled and `AllowPrivateOutboundEndpoints=true` |

Do not expose the OpenSearch domain to `0.0.0.0/0`.

## NAT gateway vs VPC endpoints

| Approach | Pros | Cons |
| --- | --- | --- |
| **NAT gateway** | Simple; works for all HTTPS egress | Ongoing cost; traffic leaves VPC to reach AWS APIs |
| **Interface VPC endpoints** | Private AWS API access; no NAT for those services | Per-endpoint cost; more setup |

Minimum interface endpoints when avoiding NAT for Lambda in private subnets:

- `com.amazonaws.us-gov-east-1.s3` (gateway endpoint — no charge, route table association)
- `com.amazonaws.us-gov-east-1.sqs`
- `com.amazonaws.us-gov-east-1.dynamodb` (gateway optional; interface also works)
- `com.amazonaws.us-gov-east-1.logs`
- `com.amazonaws.us-gov-east-1.bedrock-runtime`
- `com.amazonaws.us-gov-east-1.secretsmanager` (when integration secrets are used)

Bedrock and OpenSearch still require correct IAM and security groups regardless of path.

## Private integration endpoints

When Splunk, Elasticsearch, or ServiceNow URLs resolve to **private** RFC1918
addresses, set SAM `AllowPrivateOutboundEndpoints=true`. Without it, outbound
HTTPS validation fails closed for private targets.

Ensure:

- Lambda subnets route to those networks (same VPC, peering, or TGW — customer design)
- Security groups and NACLs allow egress from Lambda SG to integration targets on 443
- Secrets and URLs use HTTPS without embedded credentials

## Deploy order relative to other runbooks

```text
1. VPC + subnets + routing (this runbook)
2. OpenSearch domain (OPENSEARCH_PROVISIONING.md)
3. Optional KMS key (KMS_CUSTOMER_KEY.md)
4. Bedrock model access (BEDROCK_ACCOUNT_ENABLEMENT.md)
5. SAM stack
6. Optional portal JWT (PORTAL_JWT_IDENTITY.md) before portal cutover
```

## Validation

Before SAM deploy with VPC parameters:

1. Subnets are **private** (no direct Internet ingress on Lambda subnets unless your design requires it)
2. Route tables send `0.0.0.0/0` to NAT **or** required gateway endpoints exist
3. Lambda SG can reach a test HTTPS endpoint in the VPC (OpenSearch or a bastion probe)
4. `CustomerVpcSubnetIds` and `CustomerSecurityGroupIds` are comma-separated with no spaces

After SAM deploy:

1. Lambda functions show `VpcConfig` with your subnets and SG
2. CloudWatch logs show no persistent `Timeout` connecting to OpenSearch or Bedrock
3. `/ready` on the portal reports OpenSearch reachable when case Q&A is enabled

## Related docs

- [`OPENSEARCH_PROVISIONING.md`](OPENSEARCH_PROVISIONING.md)
- [`KMS_CUSTOMER_KEY.md`](KMS_CUSTOMER_KEY.md)
- [`GOVCLOUD_CUSTOMER_CONFIGURATION.md`](GOVCLOUD_CUSTOMER_CONFIGURATION.md)
- [`../security/SECURITY_OPERATIONS.md`](../security/SECURITY_OPERATIONS.md)
