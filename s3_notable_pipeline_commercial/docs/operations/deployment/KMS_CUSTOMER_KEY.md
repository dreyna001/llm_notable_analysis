# Customer-managed KMS key

## Path B

Path B can create an optional KMS key in
[`deploy/terraform/customer_default/`](../../../deploy/terraform/customer_default/)
or use an existing approved key ARN.

For an existing key, Terraform does not replace its key policy. Before setting
`existing_kms_policy_ready = true`, the customer key owner must permit the four
deterministic Path B Lambda roles, regional CloudWatch Logs encryption,
OpenSearch use when applicable, and `s3.amazonaws.com`
`kms:Decrypt`/`kms:GenerateDataKey` for encrypted queue notifications from the
input bucket. Scope service grants to the commercial account and exact resource
ARNs. The full deploy fails closed until this confirmation is set.

For a Terraform-created key, the full plan knows the deterministic application
role ARNs and writes their least-privilege grants into the key policy in the same
apply. Path B does not require a later role lookup or second apply.

Review these controls:

- approved customer administrator principals retain key administration;
- OpenSearch may use the key when the managed domain is encrypted with it;
- application roles receive only the operations required by their data paths;
- no wildcard principal, cross-account grant, or public access is introduced;
- key rotation and deletion-window values match customer policy;
- deletion remains a separate, explicitly approved teardown action.

```bash
terraform -chdir=deploy/terraform/customer_default validate
bash scripts/setup-and-deploy.sh
# Review key policy and grants in the saved plan.
bash scripts/setup-and-deploy.sh --apply
```

Validate encrypted S3, SQS, DynamoDB, logs, and OpenSearch operations through the
live acceptance checklist in
[`DEPLOYMENT_READINESS_AND_LIFECYCLE.md`](DEPLOYMENT_READINESS_AND_LIFECYCLE.md).

## Paths A/C legacy SAM workflow

Paths A/C may use the standalone [`deploy/terraform/kms/`](../../../deploy/terraform/kms/)
module with their legacy SAM application deployment. In that split-state layout,
follow its README for the explicit application-role policy handoff. Do not use
that handoff for Path B.
