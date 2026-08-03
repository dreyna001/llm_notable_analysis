# AWS GovCloud Readiness Plan

## Implementation Status

Local implementation is complete as of 2026-07-14 for the application and
infrastructure changes in this plan:

- GovCloud partition and `us-gov-east-1` deployment guards, immutable ECR digest inputs, customer model IDs/ARNs, VPC/KMS inputs, retention inputs, and scoped IAM
- S3 to SQS analyzer ingestion, analyzer/embed/RAG DLQs, partial-batch handling, bounded concurrency, retry-safe S3 identity, collision-safe outputs, and replay repair for pending embeds
- fenced side-effect leases, uncertain external-success handling, immutable case runs, and conditionally published latest-run pointers
- fail-closed portal authentication/authorization, strict cursor contracts, transactional chat idempotency, bounded readiness probes, private S3 SPA assets, and a regional HTTP API with a 29-second synchronous chat boundary
- application-managed S3 manifest to Bedrock embedding to VPC-only OpenSearch ingestion for SOC, Splunk dictionary, Elasticsearch dictionary, and case indexes with tenant/corpus/case filters and provenance
- index-first source replacement, superseded/deleted chunk tombstones, deterministic replay, customer-set retention documentation, explicit log groups, and queue/Lambda alarms
- backend, frontend, OpenAPI, LocalStack, template parser, shell syntax, Python compile, and container build/import validation

Remaining release gates require customer or live GovCloud state, not additional
product decisions:

- supply the GovCloud account/role, immutable ECR repository and digest, exact model IDs/ARNs, OpenSearch domain/capacity/ISM policy, VPC routes/security groups, KMS key, OIDC grants, CORS origins, retention values, quotas, secrets, alarm topic, and external endpoints
- run `sam validate --lint` where SAM CLI is installed, deploy a change set to a GovCloud staging account, and execute the end-to-end and fault-injection checks below
- validate live Bedrock, OpenSearch, Splunk, ServiceNow, API Gateway JWT, KMS, IAM, private DNS/routing, quotas, alarms, and rollback behavior

The regional HTTP API intentionally has no direct WAF association because AWS
WAF supports API Gateway REST APIs rather than HTTP APIs. If a customer makes
WAF mandatory, moving the portal edge to a regional REST API is a separately
scoped architecture change. Backup/restore and cross-region recovery remain the
approved internal gap in `docs/internal/AWS_GOVCLOUD_DEFERRED_GAPS.md`.

## Target

- [ ] Build and validate the AWS deployment for **AWS GovCloud (US-East), `us-gov-east-1`**.
- [ ] Treat GovCloud as the binding production target, not as an optional deployment variant.
- [ ] Confirm the associated GovCloud account, deployment role, ECR registry, Bedrock model access, and customer compliance requirements before implementation.
- [ ] Limit the initial deployment scope to `us-gov-east-1`; backup, restore, and cross-region recovery are deferred internal gaps.

## Locked Product Decisions

- [ ] Represent repeated deliveries of one `finding_id` as one logical case with immutable analysis runs, an atomic `latest_run` pointer, and preserved run history.
- [ ] Keep customer-specific values as deployment inputs: OIDC issuer/audience and analyst grants, deployment/tenant ID, KMS keys, VPC resources, private endpoints, CORS origins, quotas, retention, model IDs, OpenSearch capacity, ECR destination, and alarm targets.
- [ ] Use one VPC-only Amazon OpenSearch Service domain in `us-gov-east-1` for vector retrieval; use separate indexes and least-privilege access boundaries rather than separate retrieval services.
- [ ] Store source documents and versioned ingestion manifests in S3; store generated chunks, embeddings, and retrieval metadata in OpenSearch.
- [ ] Use separate OpenSearch indexes for case chunks, general SOC operational knowledge, Splunk/SIEM data dictionaries, and optional Elasticsearch data dictionaries.
- [ ] Treat SIEM dictionaries and SOC documents as true RAG corpora: validate, chunk, embed with a customer-approved GovCloud Bedrock embedding model, index, and retrieve with source attribution.
- [ ] Do not use DynamoDB as a vector store. Keep DynamoDB limited to transactional state, metadata, leases, chat history, and index/import status.
- [ ] Do not depend on Bedrock Knowledge Bases or S3 Vectors in the `us-gov-east-1` path; the application owns ingestion and retrieval because those managed retrieval capabilities are not available in the target region.
- [ ] Keep retrieved SOC and SIEM material advisory. Only the alert and bounded investigation results may supply case evidence.

## Definition Of Done

- [ ] `sam validate --lint`, unit tests, LocalStack tests, and GovCloud staging smoke tests pass.
- [ ] No commercial partition (`arn:aws`) or commercial-region-only resource remains in the GovCloud deployment path.
- [ ] Every asynchronous workflow has bounded concurrency, retry ownership, a DLQ or quarantine path, and observable alarms.
- [ ] S3 object identity and report outputs are collision-safe and replay-safe.
- [ ] Bedrock, Splunk, ServiceNow, private networking, and portal access are validated from the GovCloud account.
- [ ] Deployment artifacts are immutable, reproducible, and rollback-ready.
- [ ] Operations documentation, failure procedures, configuration examples, and architecture diagrams match the deployed design.

## Phase 0: GovCloud Foundation

- [ ] Update the technical specification and deployment documentation to make `us-gov-east-1` the default target.
- [ ] Replace hardcoded commercial ARNs, regions, endpoints, and ECR references with GovCloud-valid values or CloudFormation pseudo-parameters.
- [ ] Add explicit parameters for `AWS::Partition`, `AWS::Region`, account ID, ECR repository, image digest, Bedrock model/profile, and external service endpoints.
- [ ] Document Bedrock analysis and embedding model selection as customer deployment configuration; validate configured models against GovCloud regional availability at deployment and startup.
- [ ] Confirm GovCloud support and quotas for the selected Bedrock models, inference profiles, Lambda features, API Gateway, WAF, Secrets Manager, DynamoDB, SQS, and CloudFormation resources.
- [ ] Use a GovCloud-specific deployment role and credential workflow; do not reuse commercial AWS credentials.
- [ ] Define the deployment and data boundary as `us-gov-east-1`.
- [ ] Expose customer-set retention parameters for input objects, reports, case archives, DynamoDB records, logs, OpenSearch documents, queue messages, DLQ messages, and model diagnostics.
- [ ] Document retention defaults, allowed ranges, dependencies, and deletion behavior without prescribing one customer policy.

## Phase 1: Ingestion And Durable Processing

- [ ] Change direct S3 `ObjectCreated` -> analyzer Lambda invocation to S3 -> SQS -> analyzer Lambda.
- [ ] Add an analyzer DLQ, redrive policy, visibility timeout, maximum concurrency, and queue-depth/error alarms.
- [ ] Enable Lambda partial batch failure handling so successful messages are not retried with failed messages.
- [ ] Define retryable, terminal-validation, and quarantine outcomes for malformed or unsupported notable files.
- [ ] Add a durable embed queue and DLQ instead of relying on an asynchronous Lambda invocation after the archive write.
- [ ] Add reconciliation for cases left in pending or failed embedding states.

## Phase 2: S3 Identity, Idempotency, And Output Safety

- [ ] Decode S3 event keys before object access.
- [ ] Use bucket, full decoded key, version ID or ETag, and S3 sequencer as the processing identity.
- [ ] Enable S3 versioning where required for replay and audit behavior.
- [ ] Separate the business `finding_id` from the immutable processing/job ID.
- [ ] Preserve source prefixes in report and archive keys; prevent basename collisions across teams and folders.
- [ ] Add conditional writes and explicit overwrite/versioning policy for reports, manifests, and case records.
- [ ] Add duplicate, out-of-order, replay, overwrite, and partial-batch tests.
- [ ] Replace side-effect stale-lock deletion with atomic lease takeover and a unique fencing token.
- [ ] Condition side-effect completion and release on the active fencing token.
- [ ] Record external-success/marker-failure as an uncertain reconciliation state; do not automatically replay a potentially completed Splunk or ServiceNow action.
- [ ] Claim case/run state before writing immutable envelopes and finalize pointers conditionally so concurrent workers cannot make DynamoDB metadata reference another worker's S3 content.

## Phase 3: Analyzer Failure Semantics

- [ ] Distinguish successful analysis, degraded analysis, retryable inference failure, terminal input failure, and external-integration failure.
- [ ] Ensure retryable Bedrock and downstream failures cause the queue message to be retried or quarantined instead of being reported as successful.
- [ ] Prevent duplicate external writes and duplicate expensive Bedrock work during retries.
- [ ] Publish degraded reports for non-critical enrichment failures and expose the degraded state in DynamoDB, reports, logs, and portal responses.
- [ ] Retry and then quarantine core Bedrock analysis failures; do not publish them as successful analysis.
- [ ] Add correlation IDs and processing IDs to every stage and external call.

## Phase 4: GovCloud IAM And Network Validation

- [ ] Add the portal role's scoped `s3:ListBucket` permission for case-chunk prefixes.
- [ ] Generate Bedrock IAM permissions from the selected model/profile instead of granting only a fixed commercial profile.
- [ ] Include all required foundation-model and destination-region permissions for the selected GovCloud inference profile.
- [ ] Review every role for least privilege, partition correctness, and resource scoping.
- [ ] Connect Splunk and ServiceNow through private VPC connectivity.
- [ ] Add VPC subnets, security groups, routing, VPN or Direct Connect integration, private DNS, and connectivity tests.
- [ ] Use customer-managed KMS keys for S3, DynamoDB, SQS, CloudWatch Logs, Secrets Manager, and OpenSearch where supported.
- [ ] Parameterize KMS key ARNs and key-administration roles for each customer deployment.
- [ ] Add TLS-only S3 bucket policies and audit logging requirements.

## Phase 5: Analyst Portal And Retrieval

- [ ] Replace Lambda Function URLs with a regional API Gateway endpoint because Function URLs are unavailable in GovCloud.
- [ ] Use GovCloud regional HTTP API Gateway, JWT authentication, CORS allowlists, throttling, and restricted backend invocation as the portal front door; do not claim direct WAF association because WAF supports API Gateway REST APIs, not HTTP APIs.
- [ ] Keep CloudFront out of the default architecture because it operates outside the GovCloud boundary.
- [ ] Add API throttling, Lambda reserved concurrency, and per-user or per-tenant quotas; do not rely on an in-process semaphore as the global limit.
- [ ] Serve `/api/*` and bounded static SPA reads through the portal Lambda behind API Gateway; keep the SPA bucket private and separate from case data.
- [ ] Scope the portal role to read only deployed SPA objects; do not permit bucket listing, writes, or case-data access.
- [ ] Use a JWT Lambda authorizer for API routes and retain application-layer issuer, audience, tenant, and authorization validation as defense in depth.
- [ ] Require a customer-configured analyst application role or delegated scope; a valid issuer/audience token without an approved grant must receive `403`.
- [ ] Condition all portal resources and protected routes on `PortalEnabled`; disabling the portal must prevent case and chat access, not only fail readiness.
- [ ] Replace per-query S3 chunk listing and in-Lambda ranking with a VPC-only Amazon OpenSearch Service domain in `us-gov-east-1`.
- [ ] Store case chunks in an OpenSearch k-NN index and execute hybrid lexical/vector retrieval in OpenSearch.
- [ ] Use Amazon Titan Text Embeddings V2 as the documented default embedding model while allowing customers to configure another GovCloud-supported embedding model.
- [ ] Keep S3 as the durable source/archive and DynamoDB as the case/status index; do not duplicate those responsibilities in OpenSearch.
- [ ] Filter every OpenSearch write and query by tenant and case identifiers and return stored S3 provenance with each result.
- [ ] Size the OpenSearch domain for the expected workload and expose only essential capacity, retention, snapshot, and scaling parameters.
- [ ] Validate retrieval behavior, provenance, tenant isolation, and authorization using GovCloud staging data.
- [ ] Validate and honor the shared case-list filters and two-part cursor contract; reject partial or malformed cursors instead of silently ignoring them.
- [ ] Use `client_request_id` as the chat idempotency key and persist each user/assistant turn with an atomic DynamoDB capacity reservation and transaction.
- [ ] Add bounded, non-mutating DynamoDB, archive, and OpenSearch dependency probes to `/ready`.

## Phase 6: GovCloud RAG And SIEM Dictionary Ingestion

- [ ] Add a versioned ingestion manifest contract for each corpus with deployment/tenant ID, corpus lane, source object version, content checksum, schema version, and requested embedding model.
- [ ] Add a durable ingestion queue and DLQ for source-document create, update, deletion, and full-rebuild jobs.
- [ ] Validate supported file types, document size, metadata, tenant ownership, and checksums before parsing or embedding.
- [ ] Chunk and embed approved documents with the configured GovCloud Bedrock embedding model; write vectors and source provenance to the matching OpenSearch index.
- [ ] Make ingestion idempotent by source version and checksum; index the replacement first, then tombstone only superseded IDs so a failed replacement leaves the last good source retrievable.
- [ ] Remove or tombstone chunks for deleted and superseded source versions so stale dictionary guidance cannot remain retrievable.
- [ ] Provide a reconciliation job that compares the approved S3 manifest with OpenSearch and repairs missing, stale, or orphaned chunks.
- [ ] Define the Splunk/SIEM dictionary schema and onboarding template for indexes, sourcetypes, fields and types, CIM data models, macros, lookup names/schemas, approved SPL examples, aliases, ownership, and effective version.
- [ ] Retrieve general SOC context before the main alert-analysis call so it may inform hypotheses, evidence gaps, pivots, and recommended actions without becoming alert evidence.
- [ ] Retrieve the Splunk/SIEM dictionary only for bounded SPL generation; use it to ground indexes, sourcetypes, fields, CIM models, macros, and lookups.
- [ ] Retrieve case chunks plus optional general SOC context for chatbot answers while preserving separate `current_case` and `knowledge_base` source lanes.
- [ ] Record corpus version, retrieved chunk IDs, source object versions, scores, and embedding model in analysis metadata for auditability.
- [ ] Add ingestion, deletion, resync, tenant-filtering, provenance, stale-content, and retrieval-quality tests using representative customer dictionary fixtures.

## Phase 7: Optional Capabilities And Infrastructure Conditions

- [ ] Make optional ServiceNow, disposition, RAG, and portal resources conditional on capability profiles.
- [ ] Separate capability enablement from table-name or empty-string parameters.
- [ ] Validate capability dependencies at deployment and startup.
- [ ] Ensure disabled capabilities do not create unused tables, functions, schedules, permissions, or secrets access.

## Phase 8: Release And Observability

- [ ] Replace `latest` image deployment with immutable ECR tags and image digests.
- [ ] Build and scan the image in CI using a GovCloud-compatible base image and GovCloud ECR destination.
- [ ] Add CloudFormation change-set review, staging smoke tests, deployment health checks, and rollback procedures.
- [ ] Add explicit CloudWatch log groups with retention, structured logs, metrics, alarms, dashboards, and tracing where supported.
- [ ] Monitor queue depth, age of oldest message, DLQ count, Lambda errors/throttles, Bedrock throttles, failed embeddings, portal errors, and external integration failures.
- [ ] Apply customer-configured retention values consistently across infrastructure, runtime validation, examples, and operator documentation.

## Phase 9: API And Behavioral Compatibility

- [ ] Keep the AWS OpenAPI export and vendored frontend contract synchronized with the shared Azure/on-prem contract except documented platform metadata.
- [ ] Add runtime contract tests for authorization failures, case-list filters/cursors, chat idempotency, disabled capabilities, readiness, and error responses.
- [ ] Preserve shared business outputs and evidence semantics while keeping AWS-native queueing, identity, storage, networking, and retrieval implementations.

## Validation Commands And Gates

- [ ] Run backend unit tests without AWS credentials.
- [ ] Run LocalStack integration tests for request shape and local event flow.
- [ ] Run `sam validate --lint` against the final template.
- [ ] Deploy to a GovCloud staging account using the GovCloud deployment role.
- [ ] Run an end-to-end staged notable through S3, SQS, analyzer, archive, embedding, portal retrieval, and configured integrations.
- [ ] Exercise duplicate delivery, delayed delivery, malformed input, Bedrock throttling, Lambda timeout, DLQ redrive, and external-service outage scenarios.
- [ ] Capture the deployed template, image digest, model/profile IDs, region, account, alarms, and rollback version in the release record.
