# On-Prem Test Guide

**Validation terminus:** all deploy paths end here. You are done when path-specific
smoke and staging checks pass on the deployed host. Path order:
root [`README.md`](../../README.md#3-validate-all-paths-end-here) section 3.

Run commands from the **monorepo root**. Use the shared dev virtualenv at
`.venv/` (see [`DEVELOPING.md`](../../../DEVELOPING.md) for bootstrap, daily
workflow, and portal E2E).

## Test layout

| Path under `llm_notable_analysis_onprem_systemd/tests/` | Focus |
| --- | --- |
| `onprem_service/` | Analyzer service, portal API, case archive, deployment contracts, integrations (mocked) |
| `onprem_rag_notable_analysis/` | Postgres RAG SQL, ingest, retrieval, config |
| `soar_playbook/` | Phantom notable-index playbook helpers |
| `scripts/` | Preview portal and synthetic pipeline operator scripts |
| `test_benchmark_inference_server.py` | Inference benchmark helper (top-level module) |

Pytest `pythonpath` is set in [`pyproject.toml`](../../pyproject.toml)
(`tests`, `src`). `test_portal_chat_history_http.py` imports sibling helpers as
`test_case_chat_history`; add `tests/onprem_service` to `PYTHONPATH` when
running pytest (see commands below).

## Unit tests (pytest)

Activate the venv, then from the monorepo root:

```bash
source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1

export PYTHONPATH="llm_notable_analysis_onprem_systemd/tests/onprem_service:llm_notable_analysis_onprem_systemd/src:onprem-llm-sdk/src"
# Windows PowerShell:
# $env:PYTHONPATH = "llm_notable_analysis_onprem_systemd/tests/onprem_service;llm_notable_analysis_onprem_systemd/src;onprem-llm-sdk/src"
```

Primary service suite:

```bash
pytest llm_notable_analysis_onprem_systemd/tests/onprem_service -q
```

Focused suites:

```bash
pytest llm_notable_analysis_onprem_systemd/tests/onprem_rag_notable_analysis -q
pytest llm_notable_analysis_onprem_systemd/tests/soar_playbook -q
pytest llm_notable_analysis_onprem_systemd/tests/scripts -q
pytest llm_notable_analysis_onprem_systemd/tests/test_benchmark_inference_server.py -q
```

Full on-prem package:

```bash
pytest llm_notable_analysis_onprem_systemd/tests -q
```

`tests/scripts/` imports preview helpers that optionally use Bedrock; install
preview chat support before that suite:

```bash
pip install boto3==1.37.38
```

Expected pytest collection (Linux validation host, current tree):

| Suite | Collected |
| --- | --- |
| `tests/onprem_service` | 436 |
| `tests/onprem_rag_notable_analysis` | 36 |
| `tests/soar_playbook` | 4 |
| `tests/scripts` | 8 (with `boto3`) |
| `tests/test_benchmark_inference_server.py` | 5 |
| **Full `tests/`** | **489** |

Pass/fail on a healthy Linux dev host or CI: all collected tests pass. Noisy
warnings during negative-path tests are expected; trust the final pytest result.

### Offline test contract

The unit and contract test bootstrap forces Hugging Face, Transformers, and
dataset clients into offline mode, disables cloud-instance metadata lookup, and
rejects TCP/IP resolution or connections, including loopback services. Tests
must inject fakes for embedding models, LLMs, and remote integrations. Missing
cached content must fail a test rather than trigger a download.

Model/package downloads belong only in explicit install, prestage, or download
scripts. The normal pytest and unittest commands in this guide do not require
`HF_TOKEN` and must not contact Hugging Face or any other external service.

Contract tests to run when changing runtime env, profiles, or deployment assets:

- `tests/onprem_service/test_config_runtime_contract.py`
- `tests/onprem_service/test_deployment_contract.py`
- `tests/onprem_service/test_local_llm_client_contract.py`

## Golden eval (disposition baseline)

First-slice corpus and rubric for easy true-positive / false-positive / unknown
alerts. Offline tests run in CI; live LLM eval is opt-in.

```bash
python -m unittest discover \
  -s llm_notable_analysis_onprem_systemd/tests/onprem_service \
  -p "test_golden_eval.py" -q
```

See [`GOLDEN_EVAL.md`](GOLDEN_EVAL.md) for corpus layout and live run steps.

## Legacy unittest entrypoints

CI (`.github/workflows/pylint.yml`) runs the service suite with unittest:

```bash
export PYTHONPATH=".:llm_notable_analysis_onprem_systemd/src:onprem-llm-sdk/src"
python -m unittest discover \
  -s llm_notable_analysis_onprem_systemd/tests/onprem_service \
  -p "test_*.py"
```

Full-tree unittest (used in install and air-gap docs):

```bash
export PYTHONPATH="llm_notable_analysis_onprem_systemd/src:onprem-llm-sdk/src"
python -m unittest discover \
  -s llm_notable_analysis_onprem_systemd/tests \
  -p "test*.py" -v
```

Unittest and pytest counts can differ slightly (subtests); prefer pytest
collection above for current totals.

## Portal E2E (Playwright)

Browser tests for the analyst portal React UI are not part of the pytest tree.
After bootstrap, run from the repo root:

```bash
bash scripts/dev_portal_e2e.sh
```

See [`DEVELOPING.md`](../../../DEVELOPING.md) and
[`frontend/analyst-portal/README.md`](../../frontend/analyst-portal/README.md).

## Shell checks

Syntax-check shell scripts in the on-prem package and LLM SDK:

```bash
find llm_notable_analysis_onprem_systemd/scripts onprem-llm-sdk/scripts \
  -type f -name "*.sh" -print |
  sort |
  while IFS= read -r script; do bash -n "$script" || exit 1; done
```

## Docker-backed pgvector smoke

Run when Docker is available on a validation workstation or release host:

```bash
bash llm_notable_analysis_onprem_systemd/scripts/smoke_postgres_rag.sh
```

The smoke starts a disposable `pgvector/pgvector:pg16` container, runs the real
Postgres schema/ingest/retrieval path twice (general KB snippets into the default
`kb_chunks`-style smoke table **and** separate SPL grounding snippets into
`spl_query_chunks`), validates both `SOC_OPERATIONAL_CONTEXT` and
`SPL_QUERY_GROUNDING_CONTEXT` retrieval with deterministic smoke embeddings, and
removes the container afterward. Override table names via `SMOKE_TABLE` /
`SMOKE_SPL_TABLE` if needed.

Options: `--python PATH`, `--port PORT`, `--keep-container` (see script `--help`).

Docker is only the test harness; production uses the configured host
PostgreSQL/pgvector service.

This proves the database, pgvector extension, schema/table DDL, insert/upsert,
and both retrieval-context code paths used by analyzers. It does not prove
Mixedbread model loading or reranking.

## Full service chain

After vLLM, LiteLLM, and `notable-analyzer` are running on a host:

```bash
sudo bash llm_notable_analysis_onprem_systemd/scripts/smoke_service_chain.sh \
  --config-env /etc/notable-analyzer/config.env
```

The smoke script uses `LLM_API_TOKEN` from the config file for both the LiteLLM
models and chat-completion checks without placing the token in process arguments.
`--skip-file-drop` checks only vLLM and LiteLLM HTTP paths. See script
`--help` for `CONFIG_ENV`, timeout, and `ALLOW_NON_LOOPBACK_HTTP` overrides.

## Customer-like acceptance and rollback

Run this release gate on a staging host that matches the customer OS, GPU,
network controls, offline/connected mode, and enabled capability profiles. Unit
tests alone do not satisfy this gate.

| Check | Evidence to retain | Pass condition |
| --- | --- | --- |
| Preflight | `preflight_customer_deployment.sh --report-file ...` | No `FAIL`; all offline inputs staged when applicable |
| Install and services | Approved change log plus `systemctl` status | Required services are enabled and active |
| Database and RAG | `smoke_postgres_rag.sh` output and host audit | Schemas exist, vector sizes match, required corpora contain rows |
| End-to-end notable | `smoke_service_chain.sh` output and resulting case ID | One synthetic notable reaches processed output and the portal |
| Portal access | Browser/TLS evidence from the customer network | HTTPS, customer DNS, authentication, case view, and chat work |
| Real integrations | Customer-controlled SOAR and ServiceNow evidence | One approved test input and one read-only sync complete without excess access |
| Failure recovery | Quarantine/retry evidence from a malformed test input | Bad input is visible, does not stop later work, and follows documented recovery |
| Rollback | Previous-release audit report | Prior release is restored and the same smoke checks pass |

Save the final read-only host result after the tests:

```bash
sudo bash llm_notable_analysis_onprem_systemd/scripts/audit_customer_target_host.sh \
  --repo-root /path/to/llm_notable_analysis \
  --report-file /path/to/change-record/onprem-deployment-result.txt
```

Add `--run-smoke` only after approval for its synthetic file and report writes.
Treat `FAIL` as a go-live blocker. Resolve or explicitly sign off each `UNKNOWN`;
the audit intentionally cannot claim evidence from customer-controlled external
systems. Perform the rollback steps in
[`operations/deployment/HOST_LAYOUT_AND_UPDATES.md`](../operations/deployment/HOST_LAYOUT_AND_UPDATES.md)
on the same staging host before approving the release.

## Next

- Path complete: return to root [`README.md`](../../README.md#3-validate-all-paths-end-here) section 3
- Host install context: [`operations/deployment/INSTALL.md`](../operations/deployment/INSTALL.md) (Verification)
- Path B KB validation: [`operations/rag/KNOWLEDGE_BASE_OPERATIONS.md`](../operations/rag/KNOWLEDGE_BASE_OPERATIONS.md) (Validation Checklist)

## Related docs

| Topic | Doc |
| --- | --- |
| Dev venv and portal preview | [`DEVELOPING.md`](../../../DEVELOPING.md) |
| Maintainer validation commands | [`internal/DEVELOPER_MAINTAINER_GUIDE.md`](../internal/DEVELOPER_MAINTAINER_GUIDE.md) |
| Operations index | [`operations/README.md`](../operations/README.md) |
| Host install and post-install checks | [`operations/deployment/INSTALL.md`](../operations/deployment/INSTALL.md) |
| Air-gap acceptance | [`operations/deployment/AIRGAPPED_DEPLOYMENT.md`](../operations/deployment/AIRGAPPED_DEPLOYMENT.md) |
| LLM inference ops | [`operations/llm/LLM_INFERENCE_OPERATIONS.md`](../operations/llm/LLM_INFERENCE_OPERATIONS.md) |
| RAG tuning | [`operations/rag/RAG_OPERATIONS.md`](../operations/rag/RAG_OPERATIONS.md) |
| Analyst portal ops | [`operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md) |
| Phantom SOAR playbook tests | [`integrations/SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md`](../integrations/SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md) |
