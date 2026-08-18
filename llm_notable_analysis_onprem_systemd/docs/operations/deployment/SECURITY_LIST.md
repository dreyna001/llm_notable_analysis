# On-Prem Build Security List

Implemented security controls for `llm_notable_analysis_onprem_systemd`. Single-host, air-gapped-capable, local LLM by default.

## Boundary

| Item | Default |
| --- | --- |
| Deployment | Single host (RHEL 8/9 or compatible) |
| LLM inference | Local LiteLLM → vLLM on loopback |
| Notable ingest | File drop (`*.json`, `*.txt`); commonly SFTP chroot |
| Internet | Not required at runtime |
| Analyst access | Optional portal via internal HTTPS + nginx |

## Service identities

| User | Role |
| --- | --- |
| `notable-analyzer` | Analyzer, portal, retention |
| `litellm` | LiteLLM proxy |
| `vllm` | vLLM inference |
| `soar-uploader` | SFTP ingest only (`/sbin/nologin`) |

## Network — listen / bind

| Service | Bind | Port | Analyst-reachable |
| --- | --- | --- | --- |
| vLLM | `127.0.0.1` | `8000` | No |
| LiteLLM | `127.0.0.1` | `4000` | No |
| Portal (FastAPI) | `127.0.0.1` (`PORTAL_BIND_HOST`) | `8080` | No (nginx proxy only) |
| nginx (portal) | host | `443` | Yes (internal subnets) |
| Postgres | `127.0.0.1` | `5432` | No |

## Network — internal portal edge

| Hop | Protocol | Auth |
| --- | --- | --- |
| Analyst browser → nginx | HTTPS (`443`) | TLS + nginx basic auth (v1) |
| nginx → FastAPI | HTTP loopback | `X-Notable-Portal-Proxy-Secret` + `X-Forwarded-User` |
| FastAPI → Postgres | TCP loopback | DB role in `portal.env` |

| Setting | Default |
| --- | --- |
| `PORTAL_BIND_HOST` | `127.0.0.1` |
| `PORTAL_ALLOW_NON_LOOPBACK_BIND` | `false` |
| `PORTAL_PROXY_SECRET` | Generated at install; shared with nginx |

## Network — firewall

| Allow | Do not expose |
| --- | --- |
| Analyst subnets → host `TCP 443` | Portal `TCP 8080` to analysts |
| SOAR → host `TCP 22` (SFTP) | vLLM `8000`, LiteLLM `4000` |
| Host → approved internal Splunk / ServiceNow / Elastic endpoints | Public internet (v1) |

Outbound integration targets: approved internal endpoints only.

## SFTP ingest

| Control | Value |
| --- | --- |
| User | `soar-uploader` |
| Chroot | `/var/sftp/soar` |
| Command | `internal-sftp` only |
| Password auth | Disabled |
| TCP/X11 forwarding | Disabled |
| Keys | `/var/sftp/soar/.ssh/authorized_keys` (`600`) |
| Drop | `/var/sftp/soar/incoming` (`775`, `soar-uploader:notable-analyzer`) |

## Process / credential separation

| Process | Config | Splunk / ServiceNow / Elastic secrets |
| --- | --- | --- |
| `notable-analyzer.service` | `/etc/notable-analyzer/config.env` | Yes |
| `notable-portal.service` | `/etc/notable-analyzer/portal.env` | No |
| `litellm.service` | `/etc/litellm/config.yaml` | Routing only |

## Protected files

| File | Mode | Owner |
| --- | --- | --- |
| `/etc/notable-analyzer/config.env` | `600` | `notable-analyzer` |
| `/etc/notable-analyzer/portal.env` | `600` | `notable-analyzer` |
| `/etc/litellm/config.yaml` | `600` | `litellm` |

## Outbound integrations

| Integration | Default | Enabled by |
| --- | --- | --- |
| Local LiteLLM | On (loopback) | Always |
| Splunk REST (writeback, search) | Off | `action_gated`, `spl_readonly`, or flags |
| Elasticsearch read-only | Off | `elastic_readonly` or flags |
| ServiceNow draft/create | Off | `ticket_draft`, `action_gated`, or flags |

Splunk / Elastic queries: allowlisted indexes, commands, fields, row limits, timeouts.

## External actions (analyzer only)

| Action | Default | Gate |
| --- | --- | --- |
| Splunk notable comment writeback | Off | `action_gated` + `SPLUNK_SINK_ENABLED` |
| ServiceNow draft | Off | `ticket_draft` |
| ServiceNow create | Off | `action_gated` + approval metadata in notable JSON |
| Side-effect idempotency markers | Off | `action_gated` |

Runs in analyzer process — not portal chat.

## Portal chat

| Capability | Portal chat |
| --- | --- |
| Text Q&A on pinned case | Yes |
| Tool / function calling | No |
| Subprocess / shell | No |
| Filesystem read/write from model output | No |
| Live Splunk / Elastic / ServiceNow / SOAR | No |
| Case archive writes | No |
| Draft SPL / queries for human review | Yes (text only) |

## Systemd hardening

| Unit | User | Sandbox |
| --- | --- | --- |
| `notable-analyzer.service` | `notable-analyzer` | Strict: `ProtectSystem=strict`, kernel protections, restricted address families |
| `notable-portal.service` | `notable-analyzer` | Same; read-only `/etc/notable-analyzer` |
| `notable-retention.service` | `notable-analyzer` | Strict oneshot |
| `litellm.service` | `litellm` | Loopback; `ProtectSystem=full` |
| `vllm.service` | `vllm` | Loopback; reduced restrictions (Gloo/NCCL) |

Common (analyzer + LiteLLM): `NoNewPrivileges=yes`, empty capabilities, `UMask=0077`, `PrivateTmp=yes`, journal logging.

## Input handling

| Control | Value |
| --- | --- |
| Accepted extensions | `*.json`, `*.txt` only |
| Recursion | None |
| Output filename IDs | Sanitized (no path traversal) |
| Oversized / invalid input | Quarantine |
| Size limit | `MAX_INPUT_FILE_BYTES` |

## Retention

| Setting | Controls |
| --- | --- |
| `INPUT_RETENTION_DAYS` | Incoming files |
| `REPORT_RETENTION_DAYS` | Reports |
| `ARCHIVE_RETENTION_DAYS` | Archive tree |
| Portal / Postgres settings | Case archive and chat history (separate) |

## TLS

| Path | Verification |
| --- | --- |
| Splunk outbound | On by default; optional `SPLUNK_CA_BUNDLE` |
| Elasticsearch outbound | HTTPS required when enabled |
| ServiceNow outbound | HTTPS expected |
| Portal inbound | nginx TLS (customer cert/policy) |
| Disable verification in production | Not supported |

## Model load

| Control | Default |
| --- | --- |
| vLLM `--trust-remote-code` | Disabled |
| vLLM rendezvous | `127.0.0.1` / `lo` only |

## Logging

| Item | Detail |
| --- | --- |
| Format | Structured JSON → journald |
| Correlation | Per-notable ID |
| Sensitive fields | Review inbound content + log forwarding policy |

## Supply chain

| Item | Reference |
| --- | --- |
| Declared dependency pins | [`DEPENDENCY_LIST.md`](DEPENDENCY_LIST.md) |
| Installed-environment evidence | `scripts/tools/generate_dependency_manifest.sh` |
| FIPS | OS / enclave requirement (RHEL FIPS mode, approved crypto modules) |

## Operator-owned

| Item |
| --- |
| Internal TLS certificates and cipher policy |
| nginx htpasswd users (v1) or OIDC / oauth2-proxy (future) |
| Internal DNS |
| Firewall rules and owning teams |
| Token rotation cadence |
| Model / wheelhouse checksum validation |
| Log redaction and retention policy |
