# Azure resilience profile

The default Bicep values preserve existing development and staging deployments.
Production deployments fail preflight unless Blob data protection and Cosmos
continuous backup are explicitly enabled. Zone redundancy and isolated Functions
host storage remain opt-in because they require regional-capacity, naming, cost,
and migration decisions that cannot be made safely by the template.

## Production baseline

Set these values for every new production deployment:

```bash
BLOB_DATA_PROTECTION_ENABLED=true
BLOB_SOFT_DELETE_RETENTION_DAYS=30
CONTAINER_SOFT_DELETE_RETENTION_DAYS=30
PREVIOUS_VERSION_RETENTION_DAYS=30
COSMOS_CONTINUOUS_BACKUP_ENABLED=true
```

This enables Blob and container soft delete, Blob versioning, bounded cleanup of
previous versions, and Cosmos continuous seven-day backup. Lifecycle deletion of
current input, report, and case blobs remains governed by the existing retention
settings; soft delete adds a recovery window after lifecycle deletion.

For a region that supports availability zones, evaluate and then enable:

```bash
STORAGE_SKU_NAME=Standard_ZRS
FUNCTION_PLAN_ZONE_REDUNDANT=true
COSMOS_ZONE_REDUNDANT=true
```

Zone-redundant Functions Premium starts with two workers instead of one. Confirm
the region's Functions, Storage, and Cosmos zone support and quota before changing
these settings. Apply and validate them in staging first.

## Functions host-storage isolation

New environments can isolate Functions runtime state and trigger receipts per app:

```bash
ISOLATE_FUNCTIONS_HOST_STORAGE=true
ANALYZER_HOST_STORAGE_ACCOUNT_NAME=<globally-unique-name>
EMBED_HOST_STORAGE_ACCOUNT_NAME=<globally-unique-name>
DISPOSITION_HOST_STORAGE_ACCOUNT_NAME=<globally-unique-name>
PORTAL_HOST_STORAGE_ACCOUNT_NAME=<globally-unique-name>
```

Isolation creates private Blob, Queue, and Table endpoints and grants each app's
managed identity access only to its own host account. Do not turn this on directly
against a running production deployment. Functions host state includes trigger
receipts and leases; changing accounts can cause replay. Deploy the isolated
accounts in staging, stop ingestion for the cutover, drain queues, deploy, validate
the exact enabled Functions and host status, and retain the old account through the
rollback window.

The four account names are intentionally not derived in Bicep: Storage names are
global and a collision-free customer naming convention is required. The portal
name is required even when the portal profile is currently disabled so enabling it
later does not silently change the host-storage topology.

## Cosmos multi-region boundary

The current Cosmos account is serverless, Strong-consistency, and single-region.
This change adds same-region zone redundancy and continuous backup only. It does
not pretend that a second region is a parameter-only change. A multi-region design
requires an RTO/RPO, read/write-region choice, consistency review, provisioned
throughput and cost decision, private DNS/networking in every region, application
failover behavior, and a rehearsed data migration.

The recommended mature target is a new provisioned-throughput Cosmos account with
zone-redundant regions and continuous backup, migrated and cut over through a
separate change plan. Do not mutate the existing production serverless account in
place as part of ordinary application deployment.
