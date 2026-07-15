# AWS GovCloud Deferred Gaps

Internal engineering record. Do not include this document in customer delivery packages.

## Backup And Recovery

Status: deferred from the initial `us-gov-east-1` delivery.

- No formal backup architecture is included.
- No tested restore procedure is included.
- No cross-region replication or `us-gov-west-1` recovery environment is included.
- No committed RPO or RTO is included.
- Customer-configured retention is not a substitute for backup or disaster recovery.

Before claiming backup or recovery capability:

- Define customer and compliance requirements for RPO, RTO, retention, and regional data movement.
- Select backup and replication controls for S3, DynamoDB, OpenSearch, configuration, KMS, and deployment artifacts.
- Define key recovery and cross-region KMS strategy.
- Implement restore automation and `us-gov-west-1` recovery infrastructure where required.
- Exercise restore, replay, failover, and failback procedures in GovCloud staging.
- Record recovery evidence and operational ownership.
