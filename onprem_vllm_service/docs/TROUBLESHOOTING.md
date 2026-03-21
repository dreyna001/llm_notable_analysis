# vLLM Service Troubleshooting

This guide is for the standalone `onprem_vllm_service` package (`install_vllm.sh` + `systemd/vllm.service`).

## Fast triage commands

```bash
sudo systemctl status vllm
sudo journalctl -u vllm -n 200 --no-pager
curl -sf http://127.0.0.1:8000/health
```

## Common symptoms

| Symptom | Likely cause | What to check | Fix |
| --- | --- | --- | --- |
| Service fails immediately on start | Wrong venv/python path in unit | `sudo systemctl cat vllm` and `ExecStart` path | Re-run installer with correct `VLLM_INSTALL_DIR` / `VLLM_VENV_DIR`, then `sudo systemctl daemon-reload && sudo systemctl restart vllm` |
| Health endpoint timeout after install | Model still loading or bad model path | `sudo journalctl -u vllm -f` and model path existence | Ensure `VLLM_MODEL_PATH/config.json` exists; increase `VLLM_HEALTH_TIMEOUT_SECONDS` and restart |
| `install_vllm.sh` warns model not found and skips auto-start | Model artifacts not present yet | `ls -la /opt/models/...` | Copy model files, then run `sudo systemctl enable --now vllm` |
| `pip install` fails for vLLM | Python/version mismatch or unavailable artifacts in air-gap | Installer output around step `[3/5]` | Pin `VLLM_PYTHON_BIN=python3.12`; in air-gap use `VLLM_PIP_SPEC` pointing at local wheel |
| Service starts then OOM / CUDA memory errors | GPU memory pressure too high | `journalctl` error logs | Lower `VLLM_GPU_MEMORY_UTILIZATION` (for example `0.8`) and restart service |
| Port conflict on `8000` | Another process bound to port | `sudo ss -lntp \| grep :8000` | Set `VLLM_PORT` at install time or stop conflicting process |
| Unexpected runtime flags after install | Existing systemd drop-ins overriding repo unit | `sudo ls /etc/systemd/system/vllm.service.d` | Re-run install with `VLLM_RESET_OVERRIDES=true` |
| `/health` fails but service active | Bind mismatch (`host`/`port`) or startup partial failure | `systemctl cat vllm`, `journalctl -u vllm` | Verify `--host` and `--port` in unit and query correct URL |
| `/health` is OK but inference fails | Request shape/model mismatch | test `POST /v1/chat/completions` with expected `model` name | Verify `--served-model-name` and request payload fields |

## Focused checks

### Verify installed unit content

```bash
sudo systemctl cat vllm
```

Confirm:

- `ExecStart` points to the expected venv Python.
- `--model` matches deployed model path.
- `--served-model-name` matches what clients call.
- `--host 127.0.0.1` and expected `--port`.

### Verify venv and vLLM import

```bash
sudo -u vllm /opt/vllm/venv/bin/python -c "import vllm; print(vllm.__version__)"
```

If you installed to a custom path, replace `/opt/vllm/venv`.

### Verify model path permissions

```bash
ls -la /opt/models
ls -la /opt/models/gpt-oss-20b
```

The `vllm` service user must be able to read model files.

### Verify chat inference endpoint

```bash
curl -sS http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-oss-20b","messages":[{"role":"user","content":"Reply with exactly OK."}],"temperature":0,"max_tokens":16}'
```

## Recovery actions

### Clean restart flow

```bash
sudo systemctl daemon-reload
sudo systemctl restart vllm
sudo journalctl -u vllm -n 100 --no-pager
```

### Re-apply canonical unit from repo

```bash
cd /path/to/onprem_vllm_service
sudo VLLM_RESET_OVERRIDES=true bash install_vllm.sh
```

### Safe rollback concept

Use a previously known-good `VLLM_PIP_SPEC` and rerun installer:

```bash
sudo VLLM_PIP_SPEC="vllm==<known-good-version>" bash install_vllm.sh
```

