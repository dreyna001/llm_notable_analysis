# Azure Government upgrade and rollback

Use this process for every change to an existing Azure Government deployment.
An upgrade is the same Bicep deployment path as a first install, using a newly
qualified immutable image digest. Rollback uses the same path with the last
qualified digest and matching portal artifact.

## Before the change

1. Record the current deployment report, image digest, portal artifact version,
   capability profiles, model deployments, Search indexes, and Bicep revision.
2. Confirm the previous digest still exists in ACR and the prior portal artifact
   is available. Do not rely on a mutable tag.
3. Review the Bicep and configuration difference. Stop if it deletes or renames
   durable storage, Cosmos containers, Search indexes, or private-network
   resources unless a separate customer-approved migration and recovery plan
   covers that change.
4. Run the deployment helper against staging. Its source/image preflight and
   Resource Manager template validation must pass before deployment.

## Upgrade

Deploy the new digest through `scripts/setup-and-deploy.sh` or `.ps1`. Archive
the new JSON deployment report, then run the complete live-cloud release gate
in [`../testing/AZURE_GOVERNMENT_TESTING.md`](../testing/AZURE_GOVERNMENT_TESTING.md).
Production intake stays paused until the applicable checks pass.

This release supports in-place application and additive Bicep changes that keep
the existing data contracts compatible. Image rollback does not reverse data,
index, retention, backup-mode, or resource-deletion changes. Cosmos periodic to
continuous backup migration and non-zonal to zonal account migration are not
rollback operations; the deployment scripts require explicit handling for
those changes.

## Rollback

Rollback when the new release fails the live smoke, produces incorrect or
duplicate business results, cannot use managed identity/private networking, or
breaks required monitoring.

1. Pause or rate-limit intake without purging queues or deleting evidence.
2. Restore the last qualified `CONTAINER_IMAGE_URI` digest and the matching
   portal artifact/configuration. Keep the currently approved capability
   profile unless that profile is the cause; disabling a capability requires
   the recorded customer approval.
3. Run the same deployment helper so template validation, identity, host,
   private-origin, alert, and authenticated readiness checks run again.
4. Run the minimum smoke: one synthetic intake to one report, queue drain,
   authenticated Front Door `/ready`, direct-origin denial, and fresh synthetic
   monitoring. Check for a durable outcome before replaying any failed message.
5. Archive both deployment reports, operation IDs, failed and restored digests,
   validation results, approver, and any remaining risk.

Rollback must not enable public access, restore static Azure credentials, purge
queues, delete reports, or replace a customer-approved recovery decision.
