# Lean Production Build With Room for Two GPUs

## Status

| Item | Value |
| --- | --- |
| Status | Planning and procurement guidance only |
| Workload | Approximately 400 alerts/day and up to 5 portal analysts |
| Initial GPU count | 1 |
| Maximum planned GPU count | 2 |
| Model | `gemma-4-31B-it` |
| Server | Dell PowerEdge R770, 2U, dual-GPU-ready |

This build reduces initial GPU cost without removing the validated path to a
second RTX PRO 6000. Dell must quote the server with all dual-GPU enablement
components installed from the beginning.

## Initial Hardware

| Component | Specification |
| --- | --- |
| Chassis | Dell PowerEdge R770, 2U, dual-GPU-ready |
| CPU | 2x Intel Xeon 6517P, 16 cores each, 32 cores total |
| Initial GPU | 1x NVIDIA RTX PRO 6000 Blackwell Server Edition, 96 GB ECC |
| Future GPU | Space, power, cooling, PCIe lanes, riser, and cabling for a second identical GPU |
| GPU power | 450 W per GPU; Dell caps this GPU below its 600 W maximum |
| RAM | 256 GB DDR5-6400 ECC RDIMM (8x32 GB), balanced across both CPUs |
| Boot | 2x 480 GB enterprise M.2 NVMe on BOSS-N1, RAID 1 |
| Application/data | 2x 1.92 TB enterprise SSD, RAID 1 |
| Network | Dual-port 10 GbE OCP 3.0 + dedicated iDRAC management |
| Power | 2x 3200 W Titanium redundant PSUs, 200–240 V |
| Cooling | High Performance Platinum fan modules |
| Management | iDRAC10 Enterprise |
| Security | TPM 2.0, Secure Boot, and signed firmware |
| OS | Ubuntu 24.04.2 with kernel 6.11 or later |
| Support | 3-year ProSupport, next-business-day onsite |

The two CPUs are a platform topology requirement, not an application compute
requirement. Retaining two 16-core processors keeps both GPU PCIe paths active
and avoids a CPU replacement when the second GPU is installed.

## Required Dell Quote Language

Ask Dell to quote one R770 with one factory-installed RTX PRO 6000 Blackwell
Server Edition and the complete supported two-GPU configuration:

| Requirement | Dell configuration |
| --- | --- |
| GPU riser | Riser Configuration 6-2 with two double-width GPU slots |
| Initial GPU slot | Dell-recommended primary slot |
| GPU power cables | Install both slot-specific extended-solder cables |
| Slot 2 cable | Dell part `DCNHT` |
| Slot 7 cable | Dell part `K8FW0` |
| Fans | All fan modules must be HPR Platinum |
| Firmware | iDRAC `1.20.60.55` or newer |
| Power | Dual 3200 W supplies sized for two GPUs |
| Upgrade assurance | Written confirmation that a second RTX PRO 6000 is a supported field upgrade |
| Exclusions | No NVIDIA AI Enterprise license unless separately required |

Do not accept a quote that omits the second GPU's riser position, power cable,
cooling, or power capacity. Do not substitute the Workstation or Max-Q GPU;
the required part is the passively cooled Server Edition.

## Initial Serving Layout

```text
notable-analyzer.service ─┐
                          ├─> LiteLLM 127.0.0.1:4000
notable-portal.service ───┘       └─> vLLM 127.0.0.1:8000 -> GPU 0
```

The initial host runs one complete model copy on one GPU. Start with the
validated single-GPU service settings and benchmark representative alert
bursts plus five simultaneous portal sessions before raising concurrency.

## Second-GPU Expansion

The future expansion does not require replacing the CPUs, RAM, chassis,
network adapter, fans, riser, or power supplies when Dell supplies the
dual-GPU-ready configuration correctly.

| Step | Action |
| --- | --- |
| 1 | Install a Dell-qualified matching RTX PRO 6000 Server Edition in the reserved slot |
| 2 | Verify both GPUs, 450 W limits, temperatures, and PCIe link width |
| 3 | Add the second vLLM replica on GPU 1 and a distinct loopback port |
| 4 | Add the replica as an equal LiteLLM backend |
| 5 | Run concurrency, queue, thermal, restart, and single-GPU failure tests |

The target two-GPU serving architecture is documented in
[`rtx-pro-6000-blackwell-x2-server-plan.md`](rtx-pro-6000-blackwell-x2-server-plan.md).
The second GPU adds aggregate inference capacity and GPU/process failover; it
does not make the single server fully highly available.

## Capacity and Retention

| Item | Planning basis |
| --- | --- |
| Alert volume | Approximately 36,000 alerts retained over 90 days |
| Chat volume | Up to 5 analysts with 90 days of sessions |
| Data capacity | 1.92 TB usable after RAID 1 |
| Capacity guardrail | Keep 20–30% free and monitor actual retained bytes per alert |
| Retention | Enforce automated 90-day deletion for alerts, chats, logs, and backups as applicable |

RAID 1 protects service continuity after one drive failure. It is not a
backup; store required backups outside this server and test restoration.

## Budget Estimate

| Purchase stage | Current planning estimate before tax |
| --- | --- |
| Initial R770 with one GPU and full dual-GPU readiness | $83,000–$88,000 |
| Planning figure | Approximately $85,000 |
| Add a second Dell-qualified GPU later | Approximately $14,000–$17,000 |
| Eventual two-GPU total | Approximately $97,000–$105,000 |

These are August 2026 best-effort planning estimates, not Dell quotes. Confirm
the final bill of materials, GPU field-upgrade support, warranty treatment,
lead time, operating-system support, and sustained GPU power limit in writing.

## Acceptance Gates

| Gate | Requirement |
| --- | --- |
| Hardware identity | Server Edition GPU and expected 96 GB GPU memory |
| GPU power | Reported maximum is the Dell-supported 450 W |
| Memory | 256 GB visible with balanced DIMM population |
| Storage | Both RAID 1 volumes healthy and rebuild procedure documented |
| Network | Both 10 GbE ports and dedicated iDRAC path validated |
| Workload | Representative alert burst and five-session chat test meet the agreed latency and queue targets |
| Capacity | No GPU OOM, host-memory pressure, or sustained queue growth |
| Operations | Retention, backup, restore, monitoring, and failed-drive replacement tested |
