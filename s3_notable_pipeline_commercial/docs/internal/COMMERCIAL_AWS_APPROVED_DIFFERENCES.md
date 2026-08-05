# Commercial AWS Approved Differences

Internal engineering register for intentional differences between the copied
baseline and the commercial `aws` / `us-east-1` product. Customer-specific
values remain deployment inputs; they are not product differences.

| ID | Area | Commercial decision | Rationale and impact | Validation/status |
| --- | --- | --- | --- | --- |
| CAWS-001 | Deployment boundary | Accept only partition `aws` and region `us-east-1`. | Prevents cross-partition or cross-region deployment; customer account and resource identifiers remain required inputs. | Template and deployment-script negative tests pass. |
| CAWS-002 | Portal front door | Retain regional API Gateway HTTP API; do not create Lambda Function URLs in v1. | Preserves the copied 29-second synchronous API contract and one authenticated regional entry point. Longer synchronous chat would require a separately approved API contract change. | Templates and tests assert that Function URL resources and outputs are absent. |
| CAWS-003 | Portal static edge | Do not create CloudFront in v1; serve bounded private SPA reads through the portal Lambda and API Gateway. | Preserves the private S3 bucket and current security/topology contract. CDN adoption would change cost, caching, TLS/DNS, WAF, and customer responsibilities. | Template resource review and portal contract tests. |
| CAWS-004 | Production retrieval | Retain application-managed S3 ingestion and VPC-only OpenSearch retrieval. | Preserves tenant/corpus/case filters, four index lanes, provenance, replay, and private-networking responsibilities. | Capability rules and OpenSearch tests pass. |
| CAWS-005 | Bedrock Knowledge Bases | Keep the existing backend only for explicit compatibility testing; do not make it the commercial production default. | Availability alone does not justify changing provenance, IAM, cost, or operating contracts. | Unit-tested compatibility path; production templates select OpenSearch. |
| CAWS-006 | S3 Vectors | Treat as a v1 non-goal. | No implementation or evidence shows parity with existing index, provenance, isolation, or private-networking contracts. | No template or runtime dependency. |
| CAWS-007 | Product identity | Use commercial names in runtime and operator material while retaining internal Python package `s3_notable_pipeline`. | Avoids a high-churn package rename while giving the independent product an accurate operator identity. | Documentation/link scan and existing import tests. |

Any proposed change to this register must identify effects on external
contracts, security, evidence semantics, cost, customer responsibilities, tests,
and rollback before approval.
