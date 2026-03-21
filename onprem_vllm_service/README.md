# On-Prem vLLM Service Package

Standalone runtime package for deploying a shared local `vLLM` service on an on-prem server.

This package is intentionally standalone so multiple services can consume the same local LLM endpoint. This assumes all services exist on the same server/VM/etc. (Not running a service that consumes the LLM endpoint/GPU resources from a different server/VM)

## What is included

- `install_vllm.sh` — vLLM-only installer (user, venv, pip install, systemd unit, optional auto-start).
- `systemd/vllm.service` — baseline service unit installed to `/etc/systemd/system/vllm.service`.

## Quick start

```bash
cd /path/to/onprem_vllm_service
sudo bash install_vllm.sh
```

## Common options

```bash
# Air-gapped local wheel artifact
sudo VLLM_PIP_SPEC="/mnt/media/wheels/vllm-0.14.1-*.whl" bash install_vllm.sh

# Custom install paths
sudo VLLM_INSTALL_DIR=/opt/vllm312 VLLM_VENV_DIR=/opt/vllm312/venv bash install_vllm.sh

# Skip auto-start
sudo AUTO_START_VLLM=false bash install_vllm.sh
```

## Runtime defaults

- Host/port: `127.0.0.1:8000`
- Model path: `/opt/models/gpt-oss-20b`
- Served model name: `gpt-oss-20b`
- GPU utilization target: `0.9`

## Operations documentation

- `docs/TROUBLESHOOTING.md`
- `docs/OPERATIONS_RUNBOOK.md`
- `docs/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`
- `docs/SECURITY_POSTURE.md`

## Quick health checks

```bash
sudo systemctl status vllm
curl -sf http://127.0.0.1:8000/health
sudo journalctl -u vllm -n 100 --no-pager
```

