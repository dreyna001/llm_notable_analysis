# vLLM Operations Runbook

Standalone operations guide for `onprem_vllm_service`.

## Scope

- Service: `vllm` (`/etc/systemd/system/vllm.service`)
- Installer: `install_vllm.sh`
- Deployment model: single host, local endpoint (`127.0.0.1`)

## Install / re-install

```bash
cd /path/to/onprem_vllm_service
sudo bash install_vllm.sh
```

Useful install flags:

- `VLLM_PIP_SPEC` (pin or local wheel path for air-gapped installs)
- `VLLM_INSTALL_DIR`, `VLLM_VENV_DIR` (custom path)
- `VLLM_MODEL_PATH`, `VLLM_SERVED_MODEL_NAME`, `VLLM_PORT`
- `VLLM_GPU_MEMORY_UTILIZATION`
- `VLLM_RESET_OVERRIDES=true` (clear existing drop-ins)
- `AUTO_START_VLLM=false` (install only)

## Day-2 commands

```bash
sudo systemctl status vllm
sudo systemctl restart vllm
sudo journalctl -u vllm -f
curl -sf http://127.0.0.1:8000/health
```

## Post-install verification checklist

- `systemctl status vllm` shows `active (running)`.
- `/health` returns HTTP 200.
- Model path exists and has `config.json`.
- Unit `ExecStart` points to expected venv python and model path.
- `--served-model-name` matches client-side model string.

## Planned changes

### Change model path / model name

Re-run installer with desired values:

```bash
sudo VLLM_MODEL_PATH=/opt/models/<model-dir> \
     VLLM_SERVED_MODEL_NAME=<served-name> \
     bash install_vllm.sh
```

### Change port

```bash
sudo VLLM_PORT=8001 bash install_vllm.sh
curl -sf http://127.0.0.1:8001/health
```

### Change GPU utilization target

```bash
sudo VLLM_GPU_MEMORY_UTILIZATION=0.8 bash install_vllm.sh
```

## Upgrade process

1. Choose target artifact/version in `VLLM_PIP_SPEC`.
2. Re-run installer with same runtime flags used by current deployment.
3. Validate `systemctl status`, `journalctl`, and `/health`.
4. Validate at least one real completion request from a consumer service.

Example:

```bash
sudo VLLM_PIP_SPEC="vllm==0.14.1" bash install_vllm.sh
```

## Rollback process

1. Re-run installer with prior known-good `VLLM_PIP_SPEC`.
2. Verify health and logs.
3. Notify downstream clients if served model name or endpoint changed.

## Alerting signals (minimum)

- `vllm` service restart loops (`Restart=on-failure` repeatedly).
- `/health` failing for sustained interval.
- Frequent OOM/CUDA errors in journal.
- Unexpected changes in unit drop-ins under `/etc/systemd/system/vllm.service.d`.

