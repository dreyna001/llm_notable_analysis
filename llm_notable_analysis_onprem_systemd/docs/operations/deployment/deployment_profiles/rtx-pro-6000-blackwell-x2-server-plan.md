# Planned Deployment Profile: `rtx-pro-6000-blackwell-x2-server`

## Status

| Item | Value |
| --- | --- |
| Status | Planning only — not implemented |
| Workload | ~400 large notables/day + up to 5 concurrent portal analysts |
| Model | `gemma-4-31B-it` |
| Serving design | Two independent vLLM replicas behind one LiteLLM proxy |
| Baseline | [`a6000-96gb-ultra9-285k.md`](a6000-96gb-ultra9-285k.md) |

Do not apply this document directly to a host. The files and installer behavior
listed below must be implemented and tested first.

## Hardware

| Component | Planned specification |
| --- | --- |
| Server | Supermicro `SYS-212GB-FNR`, 2U, qualified for RTX PRO 6000 Blackwell Server Edition |
| CPU | 1x Intel Xeon 6731P, 32 cores |
| GPU | 2x NVIDIA RTX PRO 6000 Blackwell Server Edition, 96 GB ECC each |
| GPU power | 600 W each; test 450 W only as an optional power-capped profile |
| RAM | 256 GB DDR5-6400 ECC RDIMM (8x32 GB) |
| Boot | 2x 960 GB enterprise M.2 NVMe, RAID 1 |
| Application/data | 2x 3.84 TB enterprise E1.S NVMe, RAID 1 |
| Network | Dual 10 GbE + dedicated BMC |
| Power | 2x 2700 W Titanium redundant PSUs; 200–240 V A/B feeds |
| OS | RHEL 9.x approved against the NVIDIA driver/CUDA matrix |
| Support | 3-year next-business-day support |

## Power and Cooling

| Item | Planning value |
| --- | --- |
| GPU draw | Up to 1,200 W total |
| Estimated server draw at load | 1.5–1.8 kW |
| Estimated heat output | 5,100–6,100 BTU/hour |
| Cooling | Datacenter rack airflow; passive server GPUs require chassis airflow |
| Rack | 2U; verify rack depth for the approximately 900 mm chassis |

## Serving Architecture

```text
notable-analyzer.service ─┐
                          ├─> LiteLLM 127.0.0.1:4000
notable-portal.service ───┘       ├─> vLLM replica 0 127.0.0.1:8000 -> GPU 0
                                 └─> vLLM replica 1 127.0.0.1:8001 -> GPU 1
```

| Decision | Value |
| --- | --- |
| Replica count | 2 |
| Models per GPU | 1 complete model copy |
| Tensor parallelism | `1` per replica |
| NVLink | Not required |
| Routing | LiteLLM `least-busy` across equal model aliases |
| Redis | Not required for one LiteLLM proxy |
| Failure behavior | LiteLLM retries the surviving replica; validate during acceptance |

Two replicas increase aggregate throughput and provide process/GPU failover.
They do not make the single server, LiteLLM process, storage, or network highly
available.

## Planned File Changes

| File | Action |
| --- | --- |
| `deploy/systemd/vllm@.service` | Add templated vLLM replica unit |
| `deploy/vllm/replica-0.env.example` | Add GPU 0 / port 8000 values |
| `deploy/vllm/replica-1.env.example` | Add GPU 1 / port 8001 values |
| `deploy/systemd/litellm.rtx-pro-6000-blackwell-x2-server.drop-in.example` | Replace the default dependency with both replica units |
| `deploy/litellm/config.rtx-pro-6000-blackwell-x2-server.yaml.example` | Add two equal local deployments and routing |
| `config.env.rtx-pro-6000-blackwell-x2-server.example` | Add analyzer target values |
| `config.portal.env.rtx-pro-6000-blackwell-x2-server.example` | Add portal target values |
| `scripts/apply_rtx_pro_6000_blackwell_x2_server_profile.sh` | Add guarded profile installer |
| `scripts/install.sh` | Add explicit dual-replica profile handling |
| `scripts/smoke_service_chain.sh` | Check both vLLM replicas |
| `scripts/verify_image_ingest_prerequisites.sh` | Check both vLLM replica units |
| `scripts/tools/generate_dependency_manifest.sh` | Capture both units and replica environment files |
| `tests/onprem_service/test_deployment_contract.py` | Add two-replica deployment contract tests |
| Deployment/security/LLM docs | Add port 8001, two units, routing, monitoring, and rollback |

The existing single-GPU files remain the default and must continue to work.

## Proposed `deploy/systemd/vllm@.service`

```ini
[Unit]
Description=vLLM Inference Server Replica %i (gemma-4-31B-it)
Documentation=https://docs.vllm.ai/
After=network.target

[Service]
Type=simple
User=vllm
Group=vllm
WorkingDirectory=/opt/vllm
EnvironmentFile=/etc/vllm/replica-%i.env

ExecStart=/opt/vllm/venv/bin/python -m vllm.entrypoints.openai.api_server \
    --model ${MODEL_PATH} \
    --served-model-name ${SERVED_MODEL_NAME} \
    --host 127.0.0.1 \
    --port ${VLLM_PORT} \
    --gpu-memory-utilization ${GPU_MEMORY_UTILIZATION} \
    --max-model-len ${MAX_MODEL_LEN} \
    --max-num-seqs ${MAX_NUM_SEQS} \
    --dtype bfloat16 \
    --distributed-executor-backend mp \
    --enforce-eager

TimeoutStopSec=60
KillMode=mixed
KillSignal=SIGTERM
Restart=on-failure
RestartSec=30

Environment="PATH=/usr/local/cuda-13.3/bin:/opt/vllm/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="VLLM_HOST_IP=127.0.0.1"
Environment="MASTER_ADDR=127.0.0.1"
Environment="NCCL_SOCKET_IFNAME=lo"
Environment="GLOO_SOCKET_IFNAME=lo"
Environment="NCCL_IB_DISABLE=1"

NoNewPrivileges=yes
CapabilityBoundingSet=
AmbientCapabilities=
ProtectKernelTunables=no
ProtectKernelModules=no
ProtectControlGroups=no
ProtectKernelLogs=no
RestrictNamespaces=no
SystemCallArchitectures=native
LockPersonality=yes
UMask=0077
ProtectHome=yes
PrivateTmp=yes
LimitNOFILE=65535
LimitMEMLOCK=infinity

StandardOutput=journal
StandardError=journal
SyslogIdentifier=vllm-%i

[Install]
WantedBy=multi-user.target
```

Keep `--trust-remote-code` disabled.

## Proposed Replica Environment Files

Install as `root:root` mode `0644`; these files contain no credentials.

### `/etc/vllm/replica-0.env`

```bash
CUDA_VISIBLE_DEVICES=0
VLLM_PORT=8000
MASTER_PORT=29500
MODEL_PATH=/opt/models/gemma-4-31B-it
SERVED_MODEL_NAME=gemma-4-31B-it
GPU_MEMORY_UTILIZATION=0.85
MAX_MODEL_LEN=32768
MAX_NUM_SEQS=4
CUDA_HOME=/usr/local/cuda-13.3
```

### `/etc/vllm/replica-1.env`

```bash
CUDA_VISIBLE_DEVICES=1
VLLM_PORT=8001
MASTER_PORT=29501
MODEL_PATH=/opt/models/gemma-4-31B-it
SERVED_MODEL_NAME=gemma-4-31B-it
GPU_MEMORY_UTILIZATION=0.85
MAX_MODEL_LEN=32768
MAX_NUM_SEQS=4
CUDA_HOME=/usr/local/cuda-13.3
```

`MASTER_PORT` must differ so the two local torch/vLLM processes cannot collide.
Confirm the production CUDA path instead of assuming `13.3`.

## Proposed LiteLLM Configuration

Install as `/etc/litellm/config.yaml`.

```yaml
model_list:
  - model_name: gemma-4-31B-it
    litellm_params:
      model: hosted_vllm/gemma-4-31B-it
      api_base: http://127.0.0.1:8000/v1

  - model_name: gemma-4-31B-it
    litellm_params:
      model: hosted_vllm/gemma-4-31B-it
      api_base: http://127.0.0.1:8001/v1

router_settings:
  routing_strategy: least-busy
  num_retries: 1
```

| Setting | Value |
| --- | --- |
| Public model alias | `gemma-4-31B-it` |
| Replica 0 | `http://127.0.0.1:8000/v1` |
| Replica 1 | `http://127.0.0.1:8001/v1` |
| Router | `least-busy` |
| Retry | One retry to the other deployment |
| LiteLLM listener | `127.0.0.1:4000` |

Before implementation, pin a LiteLLM contract test for this configuration
against the repo version (`litellm[proxy]==1.83.14`).

## Proposed LiteLLM Systemd Drop-In

Future repo file:
`deploy/systemd/litellm.rtx-pro-6000-blackwell-x2-server.drop-in.example`.

Install as:
`/etc/systemd/system/litellm.service.d/override.conf`.

```ini
[Unit]
After=
After=network.target vllm@0.service vllm@1.service
Wants=
Wants=vllm@0.service vllm@1.service
```

The empty assignments remove the inherited dependency on `vllm.service`. Keep
`Wants`, not `Requires`, so LiteLLM and the surviving replica can remain
available when one vLLM process fails. Do not change the packaged
`deploy/systemd/litellm.service`; it remains the single-GPU default.

## Proposed Analyzer Configuration

Future template:
`config.env.rtx-pro-6000-blackwell-x2-server.example`.

### LLM contract

```bash
LLM_API_URL=http://127.0.0.1:4000/v1/chat/completions
LLM_MODEL_NAME=gemma-4-31B-it
LLM_STRUCTURED_OUTPUT_MODE=prompt_json
LLM_MAX_TOKENS=4096
LLM_TIMEOUT=240
CASE_QA_MODEL_CONTEXT_TOKENS=32768
```

### Initial acceptance

```bash
CONCURRENCY_ENABLED=false
MAX_WORKERS=1
MAX_QUEUE_DEPTH=8
```

### Planned production target after load test

```bash
CONCURRENCY_ENABLED=true
MAX_WORKERS=2
MAX_QUEUE_DEPTH=16
```

All remaining capability, RAG, Splunk, retention, path, and secret values stay
aligned with
`config.env.rtx-pro-6000-blackwell-5analysts.example`.

## Proposed Portal Configuration

Future template:
`config.portal.env.rtx-pro-6000-blackwell-x2-server.example`.

```bash
LLM_API_URL=http://127.0.0.1:4000/v1/chat/completions
LLM_API_TOKEN=<host-managed-value>
LLM_MODEL_NAME=gemma-4-31B-it
LLM_TIMEOUT=240
CASE_QA_MODEL_CONTEXT_TOKENS=32768
PORTAL_CHAT_MAX_CONCURRENCY=4
PORTAL_BIND_HOST=127.0.0.1
PORTAL_PORT=8080
PORTAL_ALLOW_NON_LOOPBACK_BIND=false
```

Keep portal concurrency at `4` initially. Two analyzer workers plus four portal
requests produce a maximum application-side target of six concurrent requests
against eight aggregate vLLM sequence slots. Raise portal concurrency only after
representative mixed-load testing.

All Postgres, chat history, retrieval, retention, proxy-secret, and image limits
stay aligned with
`config.portal.env.rtx-pro-6000-blackwell-5analysts.example`.

## Proposed Installer/Profile Behavior

| Item | Planned value |
| --- | --- |
| Profile selector | `VLLM_PROFILE=rtx-pro-6000-blackwell-x2-server` |
| Installed unit | `/etc/systemd/system/vllm@.service` |
| Replica configs | `/etc/vllm/replica-0.env`, `/etc/vllm/replica-1.env` |
| Enabled units | `vllm@0.service`, `vllm@1.service`, `litellm.service` |
| Disabled unit | `vllm.service` |
| LiteLLM unit drop-in | `/etc/systemd/system/litellm.service.d/override.conf` |
| LiteLLM config | Dual local deployment config above |
| Backups | Timestamped copies before replacing any live file |
| Secrets | Preserve all existing values; never copy from examples |

The profile applicator must:

1. Verify exactly two RTX PRO 6000 GPUs are visible.
2. Verify GPU indexes `0` and `1` or require explicit index overrides.
3. Back up analyzer, portal, LiteLLM, replica, and systemd files.
4. Install both replica environments and the template unit.
5. Install the dual-deployment LiteLLM configuration and unit drop-in.
6. Upsert only profile-owned analyzer and portal keys.
7. Disable `vllm.service`.
8. Run `systemctl daemon-reload`.
9. Leave service restart to an explicit operator step.

## Proposed Smoke-Test Changes

```bash
VLLM_HEALTH_URLS="http://127.0.0.1:8000/health http://127.0.0.1:8001/health"
VLLM_UNITS="vllm@0.service vllm@1.service"
LITELLM_MODELS_URL=http://127.0.0.1:4000/v1/models
```

The smoke test must:

1. Require both vLLM health endpoints during normal acceptance.
2. Verify both `/v1/models` endpoints advertise `gemma-4-31B-it`.
3. Verify LiteLLM advertises the common alias.
4. Send repeated LiteLLM requests and confirm both deployments receive traffic.
5. Stop replica 1 and confirm LiteLLM succeeds through replica 0.
6. Restart replica 1, stop replica 0, and confirm LiteLLM succeeds through replica 1.
7. Restore both replicas before file-drop testing.

## Monitoring

| Check | Command / endpoint |
| --- | --- |
| GPU inventory | `nvidia-smi -L` |
| GPU utilization/power | `nvidia-smi dmon` |
| Replica 0 | `http://127.0.0.1:8000/health`, `/metrics`, `/v1/models` |
| Replica 1 | `http://127.0.0.1:8001/health`, `/metrics`, `/v1/models` |
| LiteLLM | `http://127.0.0.1:4000/v1/models` |
| Replica 0 logs | `journalctl -u vllm@0.service` |
| Replica 1 logs | `journalctl -u vllm@1.service` |
| LiteLLM logs | `journalctl -u litellm.service` |

Ports `4000`, `8000`, and `8001` remain loopback-only. Do not open them in the
host or network firewall.

Both replicas use the same weight tree at
`/opt/models/gemma-4-31B-it`; do not create a second model copy.

## Validation Matrix

| Test | Starting value | Pass condition |
| --- | --- | --- |
| Direct replica baseline | Concurrency `1`, then `4` per replica | Zero failures; no OOM/restart |
| Combined direct load | Concurrency `8` total | Both GPUs active and stable |
| LiteLLM load balance | Concurrency `1,2,4,8` | Requests reach both replicas |
| Representative analyzer | `MAX_WORKERS=1` | Existing single-GPU quality/latency baseline met |
| Mixed load | 2 analyzer workers + 4 portal chats | No OOM; acceptable p95 latency |
| Replica 0 failure | Stop `vllm@0` | Requests continue through replica 1 |
| Replica 1 failure | Stop `vllm@1` | Requests continue through replica 0 |
| Reboot | Both units enabled | Both replicas and LiteLLM recover automatically |
| Thermal soak | Sustained mixed load | No GPU throttling or thermal alarms |

Capture:

- request success/failure count
- p50/p95/p99 latency and time to first token
- output and total token throughput
- utilization, memory, power, and temperature per GPU
- CPU and host RAM utilization
- LiteLLM routing and retry behavior
- analyzer queue depth and portal chat readiness

## Go-Live Values

| Area | Value |
| --- | --- |
| vLLM replicas | 2 |
| GPU assignment | Replica 0 → GPU 0; replica 1 → GPU 1 |
| vLLM ports | `8000`, `8001` |
| Context | `32768` |
| Memory utilization | `0.85` per GPU |
| Sequences | `4` per GPU |
| Precision | `bfloat16` |
| LiteLLM | `127.0.0.1:4000`, `least-busy`, one retry |
| Analyzer | `MAX_WORKERS=2`, `MAX_QUEUE_DEPTH=16` after acceptance |
| Portal | `PORTAL_CHAT_MAX_CONCURRENCY=4` |
| External exposure | nginx `443` only; inference ports stay loopback |

## Rollback

1. Stop and disable `vllm@0.service` and `vllm@1.service`.
2. Restore `/etc/litellm/config.yaml` and prior analyzer/portal env backups.
3. Restore and enable the packaged `vllm.service`.
4. Run `systemctl daemon-reload`.
5. Start `vllm.service`, then `litellm.service`.
6. Run `scripts/smoke_service_chain.sh`.

## Implementation Exit Criteria

- New dual-replica assets are committed and covered by deployment contract tests.
- The default single-GPU install remains unchanged and passes existing tests.
- Both replicas survive reboot and remain bound to their assigned GPUs.
- LiteLLM routing and one-replica failure tests pass.
- Representative mixed-load and thermal soak tests pass.
- The measured report is committed beside this plan before production approval.
