# vLLM Run and Fix Guide

If you only read one operations page, read this one.

## Daily commands

```bash
# Status + health
sudo systemctl status vllm
curl -sf http://127.0.0.1:8000/health

# Logs
sudo journalctl -u vllm -n 200 --no-pager
sudo journalctl -u vllm -f

# Restart
sudo systemctl restart vllm
```

## Standard verify checklist

Run after install, upgrade, rollback, or config changes:

1. `sudo systemctl status vllm` is `active (running)`.
2. `curl -sf http://127.0.0.1:<port>/health` returns `200`.
3. A `POST /v1/chat/completions` smoke request returns `2xx`.
4. Model directory includes `config.json`.
5. Installed unit has expected values for `--model`, `--served-model-name`, and `--port`.

## Common failures and fixes

| Symptom | Fast check | Fix |
| --- | --- | --- |
| Service exits right after start | `sudo systemctl cat vllm` and inspect `ExecStart` paths | Re-run installer to rebuild unit with correct paths |
| Health endpoint times out | `sudo journalctl -u vllm -f` during startup | Confirm model path exists and includes `config.json` |
| Installer skips start because model missing | `ls -la <model-path>` | Copy model artifacts, then `sudo systemctl enable --now vllm` |
| CUDA/OOM errors in logs | inspect journal for memory failures | Lower `VLLM_GPU_MEMORY_UTILIZATION` and re-run installer |
| Port conflict on `8000` | `sudo ss -lntp | rg ":8000"` | Set `VLLM_PORT` to a free port and re-run installer |
| Runtime flags do not match expected | `sudo ls /etc/systemd/system/vllm.service.d` | Re-run installer with `VLLM_RESET_OVERRIDES=true` |

## Common change commands

```bash
# Change model path + served model name
sudo VLLM_MODEL_PATH=/opt/models/<model-dir> \
     VLLM_SERVED_MODEL_NAME=<served-name> \
     bash install_vllm.sh

# Change port
sudo VLLM_PORT=8001 bash install_vllm.sh

# Tune GPU memory target
sudo VLLM_GPU_MEMORY_UTILIZATION=0.8 bash install_vllm.sh
```

## Upgrade or rollback

```bash
# Upgrade/pin version
sudo VLLM_PIP_SPEC="vllm==0.14.1" bash install_vllm.sh

# Roll back to known-good version
sudo VLLM_PIP_SPEC="vllm==<known-good-version>" bash install_vllm.sh
```

After either command, run the standard verify checklist.

## Reset to known-good baseline

```bash
cd /path/to/onprem_vllm_service
sudo VLLM_RESET_OVERRIDES=true bash install_vllm.sh
```

## Minimum alerts to monitor

- service restart loops
- `/health` repeatedly failing
- repeated CUDA/OOM failures in journal
- unexpected overrides in `/etc/systemd/system/vllm.service.d`

