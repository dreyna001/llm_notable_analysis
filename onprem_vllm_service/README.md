# On-Prem vLLM Service

Minimal package to run a shared local `vLLM` endpoint on one host.

Use this when multiple local services on the same machine need one GPU-backed OpenAI-compatible endpoint.

## 5-minute quick start

1. Move into this directory.
2. Run the installer:

```bash
cd /path/to/onprem_vllm_service
sudo bash install_vllm.sh
```

3. Verify service health:

```bash
sudo systemctl status vllm
curl -sf http://127.0.0.1:8000/health
```

4. Run a smoke test:

```bash
curl -sS http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model":"gpt-oss-120b",
    "messages":[{"role":"user","content":"Reply with exactly OK."}],
    "temperature":0,
    "max_tokens":16
  }'
```

## Defaults (if you set nothing)

- Endpoint: `127.0.0.1:8000`
- Model path: `/opt/models/gpt-oss-120b`
- Served model name: `gpt-oss-120b`
- GPU memory target: `0.9`
- Service name: `vllm`

## Common install variants

```bash
# Air-gapped wheel
sudo VLLM_PIP_SPEC="/mnt/media/wheels/vllm-0.14.1-*.whl" bash install_vllm.sh

# Custom model path + served model name
sudo VLLM_MODEL_PATH=/opt/models/<model-dir> \
     VLLM_SERVED_MODEL_NAME=<served-name> \
     bash install_vllm.sh

# Different port
sudo VLLM_PORT=8001 bash install_vllm.sh

# Install without starting service
sudo AUTO_START_VLLM=false bash install_vllm.sh
```

## What is in this package

- `install_vllm.sh` - installer (user, venv, package install, systemd unit, optional start)
- `systemd/vllm.service` - baseline unit template
- `docs/OPERATIONS_RUNBOOK.md` - run, verify, and troubleshoot in one page
- `docs/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md` - failure/restart expectations
- `docs/SECURITY_POSTURE.md` - security boundaries and operator checks

