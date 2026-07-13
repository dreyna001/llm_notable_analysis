# Azure monitoring and recovery

Production intake is not enabled until an `AlertActionGroupResourceId`, an
authenticated portal synthetic monitor, tested poison recovery, and named
on-call/escalation owners are recorded. The stack routes alerts to the supplied
action group; it does not create customer notification destinations.
For portal production deployment, the named external monitor must already emit
a successful `AppAvailabilityResults` row into this deployment's Application
Insights workspace within the last 15 minutes; the deployment scripts verify
that evidence without reading or storing its bearer token.

## Required alert set

| Signal | Initial threshold | Owner response |
| --- | --- | --- |
| `webjobs-blobtrigger-poison` nonempty (input) | any message | determine whether analyzer job was already published |
| `notable-analysis-jobs-poison` nonempty (output) | any message | inspect analyzer failure and durable report/side effects |
| `case-embed-invocations-poison` nonempty (output) | any message | inspect envelope, chunks, and embed status |
| analyzer/embed backlog | customer count threshold sustained 15 min | compare burst, scale cap, quota, throttling |
| Function failure/timeout | customer consecutive/rate threshold | correlate invocation, dependency, and queue message |
| Foundry/OpenAI throttle/service error | sustained customer threshold | preserve queue, reduce intake/cap or obtain quota |
| Cosmos 429 | sustained customer threshold | inspect RU/query/partition telemetry; do not add retry amplification |
| Front Door 5xx | customer rate threshold | inspect private origins and Function/APIM health |
| authenticated `/ready` | customer consecutive failures | identity/token, edge, and dependency triage |
| disposition sync | no successful completion in 26 hours | ServiceNow auth/network/map/Cosmos and cursor triage |

The defaults above are conservative starting points, not universal SLOs.
Record exact count/rate thresholds, evaluation windows, action group, runbook
link, and escalation in each customer deployment record. Test every rule in
staging.

## Three independent poison paths

1. `webjobs-blobtrigger-poison` means discovery/publication did not complete.
   Check Application Insights and whether the strict analyzer job already exists
   before re-uploading the original object.
2. `notable-analysis-jobs-poison` means publication succeeded but analyzer
   processing failed after five dequeues. Check report blobs, case envelope,
   idempotency state, and external-side-effect records before replay.
3. `case-embed-invocations-poison` means case embedding failed independently.
   Check the envelope, current chunks, dimensions, OpenAI quota, and Cosmos
   status before replaying the embed job.

None is automatically replayed. Snapshot message text/metadata and invocation
correlation without secrets or full sensitive payloads; correct the cause;
confirm no completed durable outcome; send one validated message to the normal
queue/path; observe completion; then remove/quarantine the poison copy under the
customer evidence policy. Replays preserve schema version and stable identity.

## Incident sequence

1. Stop or rate-limit the producer if backlog or duplicate side effects could
   grow; do not purge queues.
2. Identify the failing boundary from queue, Function, dependency, and edge
   telemetry. Separate direct case evidence from operational inference.
3. Disable only the affected capability when possible. Consequential Splunk and
   ServiceNow create remain fail-closed.
4. Restore identity/RBAC, DNS/private connectivity, quota, model/index, or
   configuration through Bicep/config deployment.
5. Replay one synthetic item, then one approved failed item; expand gradually.
6. Reconcile reports, cases, chunks, disposition state, and side-effect locks.
7. Record timeline, operation IDs, image digest, thresholds, replayed IDs,
   rollback, and residual risk.

Portal recovery uses the customer synthetic identity documented in
[`analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](analyst_portal/ANALYST_PORTAL_OPERATIONS.md).
Image rollback uses the last qualified digest and never restores public access.
