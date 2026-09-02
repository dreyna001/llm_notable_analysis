# Deployment readiness, acceptance, upgrades, and rollback

Use this checklist for every GovCloud customer-default release. It separates
local proof from checks that require the customer's real AWS account.

## One local preflight and report

After filling `customer-default.env`, run:

```bash
python scripts/deployment_readiness.py \
  --env-file customer-default.env \
  --report-out deployment-readiness-report.json
```

The command rejects missing values, example placeholders, invalid account IDs,
mutable image references, and non-HTTPS JWT issuers. It also runs
`sam validate --lint`. The JSON report contains no secret values and can be attached to change
records. A `blocked` report must not be promoted.

The deployment script runs the same SAM validation gate before `sam build`:

```bash
bash scripts/setup-and-deploy.sh
```

## Live-cloud acceptance checklist

Record Pass, Fail, or Not applicable and attach CloudFormation event IDs, object
keys, log query links, and approved screenshots. Do not put tokens in evidence.

| Check | Pass condition |
| --- | --- |
| Identity boundary | STS shows the approved account, `aws-us-gov` partition, role, and `us-gov-east-1` |
| Stack | CloudFormation reaches `CREATE_COMPLETE` or `UPDATE_COMPLETE` with no unexpected replacement |
| Private network | Lambdas reach Bedrock and the VPC-only OpenSearch domain; public paths are not required |
| Encryption | S3, SQS, DynamoDB, logs, and OpenSearch use the approved keys and policies |
| Core pipeline | A test notable produces versioned Markdown and JSON reports |
| RAG | Approved SOC and Splunk dictionary documents ingest and can be retrieved only for the deployment tenant |
| Portal | An approved analyst token works; missing, expired, wrong-audience, and wrong-role tokens fail |
| Failure recovery | A poison message reaches the DLQ, alarms fire, and approved redrive processes it once |
| Rollback | The previous image digest and parameter set redeploy successfully in staging |

Use [`../../testing/TESTING.md`](../../testing/TESTING.md) for commands and expected
outputs. Production approval requires all applicable checks to pass.

## Upgrade

1. Save the current stack parameters, template, image digest, and readiness and
   acceptance reports.
2. Review the CloudFormation change set. Stop for replacements of buckets,
   tables, queues, the API, or IAM changes outside the approved release.
3. Deploy to staging with an immutable image digest and run the full acceptance
   checklist.
4. Back up customer-owned OpenSearch data and verify its restore path before a
   mapping or retention change.
5. Promote the same template, parameters, and digest to production.

Application code must remain compatible with existing S3 objects, DynamoDB
items, queues, and OpenSearch documents unless a release-specific migration is
documented and approved.

## Rollback

Rollback means redeploying the last approved template, parameter set, and image
digest. It does not mean deleting the stack or Terraform-managed resources.

1. Stop new upstream file drops if the failing release could produce bad side effects.
2. Redeploy the last approved artifacts through the normal change-set path.
3. Re-run core, RAG, portal-auth, and replay checks.
4. Redrive only after confirming idempotency and receiving the customer's approval.

Bucket, table, OpenSearch-domain, KMS-key, or stack deletion is teardown and may
cause permanent data loss. It requires a separate approved teardown plan.

## Ownership at release time

The product team supplies the versioned template, immutable image reference,
parameter contract, tests, and runbooks. The customer owns AWS account access,
networking, IdP, DNS/TLS/edge controls, keys, OpenSearch capacity and backups,
model access and quotas, integration endpoints and secrets, alerts/on-call,
change approval, evidence retention, and production rollback authorization.
