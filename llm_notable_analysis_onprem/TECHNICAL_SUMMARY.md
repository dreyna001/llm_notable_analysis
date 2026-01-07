# On-Prem/Air-Gapped Notable Analysis Service

**What it is**: A **single-host**, **air-gapped** service that converts security “notables” into **analyst-ready markdown reports** using a **local LLM (vLLM + gpt-oss-20b or comparable model)** plus **MITRE ATT&CK technique (TTP) validation**.

**How it works (high level)**:
- **Input**: Operations drop JSON or text files of the desired information from each notable that alerts in the customer's SIEM, into an **incoming directory**.
- **Processing**: The **notable-analyzer** service normalizes the notable, runs local LLM analysis, validates MITRE TTP IDs, and generates a markdown report of TTP subtechniques, attack chain, and actionable hypotheses for the notable.
- **Output**: Reports land in a **reports directory**; inputs are moved to processed; optional archiving/deletion controls disk usage.

**Integration model**:
- **Recommended**: **SOAR-driven workflow** — SOAR pulls notables from Splunk ES and **delivers files** to the analyzer.
- **Transport**: **SFTP (recommended)** with chrooted, no-shell user and atomic rename to avoid partial reads; **NFS** supported as an alternative.
- **Optional**: **Splunk REST writeback** to attach the markdown report to Splunk ES notables (**placeholder endpoint/payload — must be confirmed per environment**).

**Operations & lifecycle**:
- **Systemd-managed** services for the analyzer and vLLM; journal-based logs.
- **Retention**: Two-stage policy (**archive then delete**) with either in-service scheduling or an optional **systemd timer**.

**Performance controls**:
- Default is **sequential processing**; optional **bounded concurrency** (small thread pool + backpressure) for bursty ingestion.

**Requirements (order-of-magnitude)**:
- CPU: **8–16 cores**, RAM: **64–128 GB**, GPU: **24–96 GB VRAM**, Storage: **500 GB–1 TB NVMe**.

**Security posture**:
- Air-gapped by design; vLLM `--trust-remote-code` is **disabled by default**; supports Splunk internal CA trust configuration.

