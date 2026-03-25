# `llamacpp` PoC Troubleshooting

This guide is for the standalone `onprem_qwen3_sudo_llamacpp_service` package (`install_llamacpp.sh` + `systemd/llamacpp.service`).

## Fast triage commands

```bash
sudo systemctl status llamacpp
sudo journalctl -u llamacpp -n 200 --no-pager
curl -sf http://127.0.0.1:8000/health
curl -sf http://127.0.0.1:8000/metrics
```

## Common symptoms

| Symptom | Likely cause | What to check | Fix |
| --- | --- | --- | --- |
| Service fails on startup | Missing/invalid model path | `sudo systemctl cat llamacpp`, `/etc/llamacpp/llamacpp.env` | Set `LLAMA_MODEL_PATH` correctly and re-run installer |
| Health endpoint times out | Model still loading | `sudo journalctl -u llamacpp -f` | Wait for load, or increase `LLAMA_HEALTH_TIMEOUT_SECONDS` and restart |
| Model download fails | Network/connectivity issue | Installer output around model download step | Re-run install, verify outbound access to Hugging Face |
| SHA256 mismatch | Corrupted/incomplete model file | `sha256sum /opt/llamacpp/models/Qwen3-4B-Q4_K_M.gguf` | Delete file and rerun installer |
| Port conflict on 8000 | Another process bound to port | `sudo ss -lntp | rg :8000` | Set `LLAMA_PORT` and rerun installer or stop conflicting process |
| `/metrics` unreachable | Service not fully started or mis-bound | Unit and env host/port values | Verify `LLAMA_HOST`/`LLAMA_PORT`, restart and re-check |

## Focused checks

### Verify installed unit

```bash
sudo systemctl cat llamacpp
```

Confirm:

- `ExecStart` points to `/usr/local/bin/llama-server`.
- `EnvironmentFile` points to `/etc/llamacpp/llamacpp.env`.
- host and port values match expected endpoint.

### Verify model artifact

```bash
ls -lah /opt/llamacpp/models
sha256sum /opt/llamacpp/models/Qwen3-4B-Q4_K_M.gguf
```

Expected SHA256:

`7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`

## Recovery actions

### Clean restart flow

```bash
sudo systemctl daemon-reload
sudo systemctl restart llamacpp
sudo journalctl -u llamacpp -n 100 --no-pager
```

### Re-apply canonical package configuration

```bash
cd /path/to/onprem_qwen3_sudo_llamacpp_service
sudo bash install_llamacpp.sh
```
