# AI Notable Analysis Pipeline — Azure End-to-End Diagrams

Pre-rendered exports of each figure (same folder):

- **PNG (open anywhere):** `END_TO_END_DIAGRAMS.fig01-full-story.png` through `END_TO_END_DIAGRAMS.fig04-deployment-sequence.png`
- **SVG (vector):** matching `.svg` files
- **Mermaid source:** matching `.mmd` files

Regenerate PNG/SVG from `azure_notable_pipeline`:

```powershell
$dir = "docs/delivery_package/end_to_end_diagrams"
foreach ($f in @("fig01-full-story","fig02-swimlane","fig03-azure-runtime","fig04-deployment-sequence")) {
  npx -y @mermaid-js/mermaid-cli -i "$dir/END_TO_END_DIAGRAMS.$f.mmd" -o "$dir/END_TO_END_DIAGRAMS.$f.png" -b white -s 2 -w 2400
  npx -y @mermaid-js/mermaid-cli -i "$dir/END_TO_END_DIAGRAMS.$f.mmd" -o "$dir/END_TO_END_DIAGRAMS.$f.svg" -b white
}
```

Optional 16:9 slide crops for fig01: `node ../s3_notable_pipeline/scripts/tools/export_svg_to_ppt_pngs.mjs docs/delivery_package/end_to_end_diagrams/END_TO_END_DIAGRAMS.fig01-full-story.mmd` (requires `npm install` in `s3_notable_pipeline`).

These Mermaid diagrams summarize how work flows from **how customers build and fire notables** through **customer-side deployment** to **analyst-ready reports** on **Azure US Government**.

**Assumptions (planning, not a guarantee):**

- **Volume:** **~250 alerts per day** handed to analysis **as one notable object each** (typical SOAR/upload pattern). That scale assumes **well-tuned detections**, not an unbounded noisy firehose.
- **Illustrative Azure-only run cost** (order of magnitude; excludes labor, SIEM/SOAR, and other tools; varies with model choice, prompt size, tokens per notable, retries, and regional pricing): **Azure OpenAI inference is usually the dominant line item** at this volume; private storage and Functions consumption are comparatively small.

---

## 1. Full story: from detections to the report

Customers typically **alert on thresholds per user or host**; when a threshold trips, an **alert fires**, **correlation searches** pull the surrounding context, and the SIEM (for example **Splunk**) ends up with **one consolidated evidence object per notable**. This pipeline **does not replace** that stack; it **takes that one object at a time** (often via SOAR) and drops it into private Blob Storage for analysis.

```mermaid
flowchart TB
  subgraph Authoring["A. What detection engineers shape"]
    DE[Thresholds & baselines<br/>on users / hosts]
    NR[Searches, correlation logic,<br/>notable workflow]
  end

  subgraph Live["B. When a threshold trips"]
    POP[Alert fires]
    CORR[Correlation searches run<br/>enrich / roll up into one bundle]
    NOT[One notable + one bundled<br/>payload for processing]
    ANA[Analyst triage in SIEM<br/>e.g. Splunk]
  end

  subgraph Package["C. Integration handoff (typical)"]
    SOAR[SOAR / playbook<br/>one JSON file per notable]
    PUT["Private PUT to<br/>input/incoming/{finding_id}.json or .json.gz"]
  end

  subgraph Azure["D. Deployed Azure Government pipeline"]
    TRG["Blob trigger (polling)<br/>prefix: input/incoming/"]
    PUB["Strict v1 job publish<br/>queue: notable-analysis-jobs"]
    ANZ[Analyzer Function<br/>container from ACR]
    READ[Read + normalize JSON or plaintext]
    PRM[Prompt stack + output contract:<br/>doctrine, evidence-gate,<br/>stateless / unknown discipline,<br/>6-way competing hypotheses,<br/>analyze_notable tool JSON schema]
    SRCH[Optional Azure AI Search retrieve:<br/>SOC RAG, SPL grounding,<br/>Elastic grounding]
    OAI[Azure OpenAI<br/>base analysis + optional<br/>query generation / interpretation]
    VAL["Hallucination controls:<br/>required keys, parse + repair,<br/>content rules, ATT&CK v17.1 allowlist<br/>raw fallback for human review"]
    QRY[Optional read-only investigation:<br/>Splunk REST/MCP or Elasticsearch _search<br/>policy validated and bounded]
    MD[Report assembly:<br/>markdown + JSON + optional HTML]
    OUT[("Output storage<br/>reports/{stem}.*")]
    ARCH{{Optional case archive:<br/>Blob envelope + CaseIndex<br/>analyst_portal profile}}
    EMB{{Optional embed Function:<br/>case-embed-invocations queue<br/>1024-d vectors to Search}}
    PAPI{{Optional analyst portal:<br/>Front Door + portal Function<br/>+ static SPA}}
    SPLK{{Splunk REST<br/>notable comment?}}
    SN{{ServiceNow<br/>incident create?}}
    COSM[(Cosmos DB<br/>state, CaseIndex, idempotency)]
  end

  subgraph Consume["E. Who consumes the output"]
    REV[Analyst review:<br/>Blob reports, optional portal,<br/>and/or SIEM comment]
  end

  DE --> NR
  NR --> POP
  POP --> CORR
  CORR --> NOT
  NOT --> ANA
  NOT --> SOAR
  SOAR --> PUT
  PUT --> TRG
  TRG --> PUB
  PUB --> ANZ
  ANZ --> READ
  READ --> PRM
  PRM -. optional advisory context .-> SRCH
  SRCH -. snippets .-> OAI
  PRM --> OAI
  OAI --> VAL
  VAL -. optional generated queries .-> QRY
  QRY -. normalized results .-> OAI
  QRY --> MD
  VAL --> MD
  MD --> OUT
  MD -. analyst_portal .-> ARCH
  ARCH -. async embed job .-> EMB
  ARCH -. CaseIndex upsert .-> COSM
  EMB -. browse + pinned-case Q&A .-> PAPI
  MD -. optional: ReportSinkMode notable_rest .-> SPLK
  MD -. optional: ServiceNow approval .-> SN
  SPLK -. idempotency .-> COSM
  SN -. idempotency .-> COSM
  OUT --> REV
  ARCH --> REV
  PAPI --> REV
  SPLK --> REV
  SN --> REV
  ANA -. human parallel path .-> REV
```

**Prompting and hallucination resistance (Azure path):** The model only sees **what is in the notable** plus explicit instructions to separate **evidence from inference**, use **unknown** when facts are missing, and pass an **evidence-gate** before labeling a TTP. **`analyze_notable` tool / JSON schema** tightens the answer shape. Optional Azure AI Search and query-grounding snippets are advisory context, not observed case facts. After Azure OpenAI returns, **deterministic code** validates, **repairs once** on failure, **allowlists** technique IDs, validates generated SPL or Elastic queries before execution, applies **content policies**, and if structure still fails, **surfaces raw output for review** instead of pretending the run was clean.

**Contract reminders:**

- One upload under `input/incoming/` triggers one strict v1 queue job and one analyzer run, producing one report set under `reports/` (markdown + JSON, plus HTML when `html_reports` is enabled), unless the object is skipped as empty, folder marker, or placeholder filename.
- With `analyst_portal`, the analyzer also archives a bounded case envelope to output storage and upserts CaseIndex metadata in Cosmos DB for the read-only portal API; portal chat Q&A uses Azure OpenAI over retrieved case evidence only.
- For **Splunk `notable_rest` writeback**, `finding_id` comes from the **filename stem**: e.g. `input/incoming/abc-123.json` implies `finding_id=abc-123`.
- Optional `spl_readonly` and `elastic_readonly` profiles are mutually exclusive; one read-only investigation backend is active per deployment.

**Out of scope today (non-goals):** The pipeline **does not** drive **remediation, suppression, or case closure**. ServiceNow support is limited to incident drafting and approval-gated creation; it does not make autonomous ticketing decisions.

**RAG (advisory context):** Retrieval over **customer SOPs**, **Splunk-facing knowledge packs**, and **Elasticsearch data dictionaries** can tighten **pivot ideas, query framing, and procedure fit**. Retrieved material stays **advisory**; **observed case facts** remain **only what is in the notable** the pipeline ingests.

**Operations note:** Blob triggers and Storage Queues can **retry**; customers should expect **at-least-once** delivery semantics and treat **blob ETag + finding identity** as the natural idempotency boundary for a single analysis run. External side effects such as Splunk writeback and ServiceNow create use Cosmos DB reservations when action-gated idempotency is enabled. Poison queues (`webjobs-blobtrigger-poison`, `notable-analysis-jobs-poison`, `case-embed-invocations-poison`) require manual reconciliation; see [`../../operations/AZURE_MONITORING_AND_RECOVERY.md`](../../operations/AZURE_MONITORING_AND_RECOVERY.md).

**Network:** Functions call **Azure OpenAI** and optional **Azure AI Search** via private endpoints and managed identity. Read-only investigation and writeback features use **HTTPS** to customer-configured Splunk, MCP, Elasticsearch, or ServiceNow endpoints from the analyzer execution environment. With `analyst_portal`, analysts reach the portal API through **Azure Front Door Premium** private origin links to the portal Function and static `$web` SPA.

---

## 2. Inputs, processing steps, and outputs (single swimlane)

```mermaid
flowchart LR
  subgraph Inputs["Inputs the customer must have or configure"]
    I1[(Per-notable bundle:<br/>threshold alert + correlation context)]
    I2[("Private input storage<br/>prefix: input/incoming/")]
    I3[Deploy-time params:<br/>storage accounts, ContainerImageUri,<br/>CapabilityProfiles, ReportSinkMode,<br/>Azure OpenAI deployments, Search indexes]
    I4[Runtime: Azure OpenAI access<br/>in Azure Government]
    I5[Container image in ACR<br/>before Bicep deploy]
  end

  subgraph Middle["What happens in the middle"]
    M1[Blob trigger observes upload]
    M2[Publish strict v1 job to notable-analysis-jobs]
    M3[Analyzer reads object body]
    M4[Assemble bounded prompt + tool schema - Azure OpenAI]
    M5[Validate, allowlist TTPs, repair, policies]
    M6[Report generator + optional case archive]
  end

  subgraph Outputs["Outputs"]
    O1[("Markdown + JSON reports under output/reports/;<br/>optional HTML when html_reports")]
    O2[("Splunk notable comment, notable_rest + action_gated")]
    O3[Application Insights + Log Analytics - traceability]
    O4{{Optional analyst portal:<br/>CaseIndex browse + pinned-case Q&A<br/>analyst_portal profile}}
  end

  I1 --> I2
  I2 --> M1
  M1 --> M2
  M2 --> M3
  M3 --> M4
  M4 --> M5
  M5 --> M6
  M6 --> O1
  M6 -. notable_rest .-> O2
  M6 --> O3
  M6 -. analyst_portal archive .-> O4
```

---

## 3. Azure runtime architecture (what the stack provisions)

Aligned with [`../../../deploy/azure/main.bicep`](../../../deploy/azure/main.bicep): private input and output storage accounts, containerized Azure Functions (analyzer, embed, disposition, optional portal), Storage Queues (`notable-analysis-jobs`, `case-embed-invocations`), customer-owned Azure OpenAI, Cosmos DB, optional Azure AI Search, Key Vault, Application Insights, and optional Front Door portal origins when `analyst_portal` is enabled. **Pick the Azure Government region** that fits policy and model access; default qualified region is **`usgovvirginia`**.

```mermaid
flowchart TB
  subgraph Subscription["Customer Azure Government subscription"]
    subgraph Storage["Private storage accounts"]
      BIN[("Input storage<br/>Blob input/incoming/<br/>Queue: blob trigger receipts")]
      BOUT[("Output storage<br/>Blob reports/, cases/, chunks/<br/>Queues: analyzer + embed")]
      BWEB[("Portal UI storage<br/>static $web SPA")]
    end

    subgraph Compute["Azure Functions (container)"]
      ACR[(Azure Container Registry<br/>linux/amd64 image @sha256)]
      INTAKE[Analyzer app: intake_blob<br/>Blob trigger]
      ANZ[Analyzer app: analyzer_queue<br/>notable-analysis-jobs]
      EMB[Embed app: case_embed_queue<br/>case-embed-invocations]
      PLAM[Portal app: portal_http<br/>analyst_portal profile]
    end

    subgraph AI["Model + retrieval"]
      OAI[Azure OpenAI<br/>analysis, chat, 1024-d embeddings<br/>customer deployments in usgovvirginia]
      SEARCH[Azure AI Search<br/>knowledge + case indexes]
    end

    subgraph State["Transactional state"]
      COSM[(Cosmos DB<br/>CaseIndex, idempotency,<br/>chat quota/sessions)]
    end

    subgraph Secret["Optional integrations"]
      KV[Key Vault<br/>Splunk, MCP, Elastic,<br/>ServiceNow tokens]
    end

    subgraph PortalEdge["Optional analyst_portal"]
      FD[Azure Front Door Premium<br/>private origin links]
    end

    subgraph Ops["Operations"]
      AIOPS[Application Insights<br/>+ Log Analytics]
      BICEP[Bicep main.bicep stack]
    end

    BIN -->|polling Blob trigger input/incoming/*| INTAKE
    INTAKE -->|enqueue strict v1 job| BOUT
    BOUT -->|dequeue notable-analysis-jobs| ANZ
    ANZ -->|read input blob| BIN
    ANZ -->|write reports/* cases/*| BOUT
    ANZ -->|structured chat completion| OAI
    ANZ -. optional hybrid retrieve .-> SEARCH
    ANZ -. optional GetSecret .-> KV
    ANZ -. conditional writes .-> COSM
    ANZ -. optional HTTPS .-> SPL[Splunk REST / MCP]
    ANZ -. optional HTTPS .-> ES[Elasticsearch _search]
    ANZ -. optional HTTPS .-> SN[ServiceNow REST]
    ANZ -. async embed invoke .-> EMB
    EMB -->|embedding request| OAI
    EMB -->|case vector upsert| SEARCH
    EMB -->|retrieval-ready marker| COSM
    PLAM -->|read CaseIndex + archive| COSM
    PLAM -->|read case chunks| BOUT
    PLAM -. pinned-case Q&A .-> SEARCH
    PLAM -. bounded chat .-> OAI
    FD --> BWEB
    FD -->|/api/*| PLAM
    INTAKE -. telemetry .-> AIOPS
    ANZ -. telemetry .-> AIOPS
    EMB -. telemetry .-> AIOPS
    PLAM -. telemetry .-> AIOPS
    BICEP -. provisions .-> BIN
    BICEP -. provisions .-> BOUT
    BICEP -. provisions .-> ANZ
    ACR -. ContainerImageUri at deploy .-> ANZ
    ACR -. same digest .-> EMB
    ACR -. same digest .-> PLAM
  end
```

---

## 4. Deployment handoff: delivery to customer team

The development organization **delivers the source** at an agreed milestone (for example a repository or release package). After handoff, the **customer owns and maintains** the deployment, fork, merge cadence, and production operations. There is **no separate software license fee**; cost is mainly **customer integration labor** (often **hours to a few days** for a straightforward deploy: image, parameters, storage, Azure OpenAI access). **New releases** can be **merged into the customer codebase** on the **customer's** schedule.

This is the **operational path** in the **customer's Azure Government subscription**: who builds the image, who runs deploy, and what proves it works.

```mermaid
sequenceDiagram
  participant Dev as Development org<br/>ships code at milestone
  participant Eng as Customer engineer / platform team<br/>owns integration
  participant Entra as Entra ID + RBAC
  participant ACR as Azure Container Registry
  participant Build as Docker build scripts
  participant Bicep as az deployment / setup-and-deploy
  participant Storage as Private storage accounts
  participant Func as Azure Functions apps

  Dev->>Eng: Hand off source (README, main.bicep, Dockerfile, optional upstream for merges)
  Eng->>Entra: Confirm subscription, managed identities, Azure OpenAI RBAC, Key Vault access
  Eng->>ACR: Create or choose Government registry
  Eng->>Build: docker build + push linux/amd64 image, capture @sha256 digest
  Eng->>Bicep: deploy main.bicep with ContainerImageUri, CapabilityProfiles, OpenAI + Search params
  Bicep->>Storage: Create input/output/portal storage, queues, lifecycle, private endpoints
  Bicep->>Func: Create analyzer, embed, disposition, optional portal Function apps
  Eng->>Storage: Upload test notable to input/incoming via private path
  Storage-->>Eng: Verify report under output/reports/ + Application Insights traces
```

**Important:** Bicep **references** a pre-published `ContainerImageUri` digest; it does not build or push the image for the customer. See [`../../operations/deployment/DEPLOYMENT_IMAGE_STEPS.md`](../../operations/deployment/DEPLOYMENT_IMAGE_STEPS.md).

**Documentation** shipped with the solution includes, among others: [`../../../README.md`](../../../README.md) (deploy, sinks, test path), [`../EXECUTIVE_WORKFLOW_READINESS.md`](../EXECUTIVE_WORKFLOW_READINESS.md) (end-to-end narrative), [`../../operations/deployment/DEPLOYMENT_IMAGE_STEPS.md`](../../operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) (ACR and Function image order), [`../../operations/platform/CAPABILITY_PROFILES.md`](../../operations/platform/CAPABILITY_PROFILES.md) (feature bundles including `analyst_portal`), [`../../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md) (portal stack and day-two ops), [`../../operations/integrations/SIEM_SOAR_PRIVATE_INTAKE_OPERATIONS.md`](../../operations/integrations/SIEM_SOAR_PRIVATE_INTAKE_OPERATIONS.md) (SOAR to private Blob pattern), [`../../security/ATTACK_LLM_ANALYSIS.md`](../../security/ATTACK_LLM_ANALYSIS.md) (ATT&CK grounding and validation posture), and [`../../../deploy/azure/main.bicep`](../../../deploy/azure/main.bicep) (infrastructure contract).

---

## Related docs in this package

- [`../../../README.md`](../../../README.md) — quick deploy and sink modes
- [`../EXECUTIVE_WORKFLOW_READINESS.md`](../EXECUTIVE_WORKFLOW_READINESS.md) — narrative executive overview
- [`../../architecture/AZURE_GOVERNMENT_ARCHITECTURE.md`](../../architecture/AZURE_GOVERNMENT_ARCHITECTURE.md) — logical architecture and boundary rules
- [`../../architecture/AZURE_GOVERNMENT_END_TO_END.md`](../../architecture/AZURE_GOVERNMENT_END_TO_END.md) — intake sequence and failure/recovery path
- [`../../operations/deployment/DEPLOYMENT_IMAGE_STEPS.md`](../../operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) — ACR and Function image order of operations
- [`../../operations/platform/CAPABILITY_PROFILES.md`](../../operations/platform/CAPABILITY_PROFILES.md) — supported feature bundles (`core`, `analyst_portal`, and others)
- [`../../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md) — optional portal stack, archive, and Case Q&A
- [`../../operations/integrations/SIEM_SOAR_PRIVATE_INTAKE_OPERATIONS.md`](../../operations/integrations/SIEM_SOAR_PRIVATE_INTAKE_OPERATIONS.md) — SOAR to private Blob payload pattern
- [`../../security/ATTACK_LLM_ANALYSIS.md`](../../security/ATTACK_LLM_ANALYSIS.md) — ATT&CK grounding, validation, and LLM trust boundaries
