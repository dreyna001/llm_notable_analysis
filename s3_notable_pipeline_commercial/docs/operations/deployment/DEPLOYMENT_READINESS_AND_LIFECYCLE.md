# Path B readiness, acceptance, upgrades, and rollback

Use this checklist for every commercial AWS customer-default release.

## Local plan gate

```bash
export AWS_REGION=us-east-1
export COMMERCIAL_AWS_ACCOUNT_ID="<approved-12-digit-account>"

terraform fmt -check -recursive deploy/terraform
terraform -chdir=deploy/terraform/customer_default init
terraform -chdir=deploy/terraform/customer_default validate
bash scripts/setup-and-deploy.sh
terraform -chdir=deploy/terraform/customer_default show -json \
  customer-default.tfplan > customer-default.tfplan.json
```

Store the saved plan, JSON plan, immutable image digest, reviewer, approval, and
later `terraform output -json` with the change record. Do not commit them.

A release is blocked when the plan contains an unexplained replacement, mutable
image, public access, wrong account/region, missing JWT grant, missing queue/DLQ,
or IAM access beyond the documented runtime needs.

## Live-cloud acceptance

Record Pass, Fail, or Not applicable. Attach Terraform run ID or plan digest,
object keys, log-query links, alarm evidence, and approved screenshots. Never put
tokens, credentials, or raw JWTs in evidence.

| Check | Pass condition |
| --- | --- |
| Identity boundary | STS shows the approved account, `aws` partition, role, and `us-east-1` |
| Terraform convergence | A second full plan reports no unexpected changes |
| Private network | Lambdas reach Bedrock and VPC-only OpenSearch without a public application path |
| Encryption | S3, SQS, DynamoDB, logs, and OpenSearch use approved encryption and policies |
| IAM wiring | OpenSearch and optional KMS policies already include the deterministic application role ARNs after the one full apply |
| Core pipeline | A test notable produces versioned Markdown and JSON reports |
| RAG | Approved SOC and Splunk dictionary documents ingest and retrieve only for the deployment tenant |
| Portal auth | Approved analyst token succeeds; missing, expired, wrong-audience, and wrong-role/scope tokens fail |
| Queue recovery | A poison message reaches each applicable DLQ, alarms fire, and approved redrive processes it once |
| Operational outputs | Terraform outputs identify buckets, queues, DLQs, API endpoint, roles, and search endpoint without exposing secrets |
| Rollback rehearsal | Staging accepts the previous approved digest and inputs without data-store replacement |

Use [`../../testing/TESTING.md`](../../testing/TESTING.md) for commands and expected
outcomes. Production approval requires every applicable check to pass.

## Upgrade

1. Save current Terraform inputs, outputs, state version, image digest, plan, and acceptance report.
2. Back up OpenSearch and verify restore before mapping, retention, or engine changes.
3. Plan in staging and stop for unexplained replacement or IAM expansion.
4. Apply the immutable image digest in staging and run the full acceptance table.
5. Promote the same reviewed configuration and digest through the production approval path.

Application code must remain compatible with existing S3 objects, DynamoDB
items, queues, and OpenSearch documents unless a versioned migration is supplied,
tested, and approved.

## Rollback

Rollback restores the last approved Terraform input set and immutable image
digest. It does not delete infrastructure.

1. Stop new upstream file drops if the release could create bad side effects.
2. Restore the previous versioned `terraform.tfvars` values and digest.
3. Create and review a fresh saved plan; stop if it replaces a data store.
4. Apply after approval.
5. Re-run core, RAG, portal-auth, queue replay, and convergence checks.

Bucket, table, OpenSearch-domain, KMS-key, or state deletion is teardown and may
cause permanent data loss. It requires a separate approved teardown plan.

## Ownership at release time

The product team supplies versioned Terraform, the input and output contract,
tests, runbooks, and a digest-pinned image release. The customer owns AWS access,
remote state, networking, IdP, DNS/TLS/edge controls, keys, OpenSearch capacity
and backups, model access and quotas, integrations and secrets, alert routing,
change approval, evidence retention, and production rollback authority.
