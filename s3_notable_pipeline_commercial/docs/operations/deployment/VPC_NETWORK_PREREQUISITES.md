# Commercial AWS VPC and network prerequisites

The customer supplies an existing VPC and private subnets. Path B Terraform
creates or accepts the Lambda security group and attaches the application
functions to the supplied network. It does not create the VPC, subnets, NAT
gateway, or route tables.

## Path B inputs

Record these in
`deploy/terraform/customer_default/terraform.tfvars`:

| Input | Requirement |
| --- | --- |
| `vpc_id` | Approved customer VPC in `us-east-1` |
| `private_subnet_ids` | Private subnets across at least two availability zones |
| Lambda security-group settings | Egress to OpenSearch and required AWS APIs |
| Optional endpoint settings | Customer-approved S3, SQS, DynamoDB, Logs, Bedrock Runtime, and Secrets Manager access |

Path B RAG, ingestion, case embedding, and portal retrieval require network
access to the VPC-only OpenSearch domain.

## Target layout

```text
customer VPC
  private subnets (2+ AZs) -> Lambda ENIs
  route tables             -> NAT and/or VPC endpoints
  Lambda security group    -> HTTPS egress to OpenSearch and approved APIs
  OpenSearch security group -> HTTPS ingress from Lambda security group only
```

Do not expose OpenSearch to `0.0.0.0/0`.

## Required outbound paths

- OpenSearch in the same VPC
- S3
- SQS
- DynamoDB
- CloudWatch Logs
- Bedrock Runtime
- Secrets Manager when an enabled integration uses a secret

Use NAT or approved VPC endpoints. Interface endpoints have ongoing cost and
security-group requirements; S3 and DynamoDB support gateway endpoints.

## Private customer integrations

For private Splunk, Elasticsearch, or ServiceNow endpoints, customer routing,
security groups, NACLs, peering, transit gateway, and DNS must permit HTTPS from
the Lambda subnets. URLs must use HTTPS and must not contain credentials.

## Plan checks

```bash
terraform -chdir=deploy/terraform/customer_default validate
bash scripts/setup-and-deploy.sh
```

Verify:

1. account and region are correct;
2. subnets are private and span the approved availability zones;
3. Lambda egress reaches only required destinations;
4. OpenSearch ingress allows the Lambda security group on 443 only;
5. no public application or search endpoint is introduced;
6. endpoint cost and ownership are approved.

After apply, confirm every Lambda has the expected VPC configuration and no
persistent timeout reaching OpenSearch or Bedrock.

## Paths A/C legacy SAM workflow

Paths A/C map the same IDs to `CustomerVpcSubnetIds` and
`CustomerSecurityGroupIds` in the legacy SAM deployment. Path B uses the native
Terraform inputs above.

## Next

- Path B: [`COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md)
- Path C with vector features: [`OPENSEARCH_PROVISIONING.md`](OPENSEARCH_PROVISIONING.md)
