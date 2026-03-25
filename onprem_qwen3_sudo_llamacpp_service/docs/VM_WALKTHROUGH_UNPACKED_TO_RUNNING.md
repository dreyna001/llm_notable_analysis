# VM walkthrough: unpacked code → `llama-server` + notable analyzer

This document is a **single end-to-end path** from “the code is already on the Linux VM” (archive unpacked or repo copied) through a **working** stack:

1. **`onprem_qwen3_sudo_llamacpp_service`** — local `llama.cpp` (`llama-server`) on loopback  
2. **`llm_notable_analysis_onprem`** — notable analysis **client** that calls that endpoint  
3. **`onprem-llm-sdk`** — Python dependency of the client (install from the **same** tree)

For deeper reference, see:

- `onprem_qwen3_sudo_llamacpp_service/README.md` — installer flags, `/no_think`, health checks  
- `onprem_qwen3_sudo_llamacpp_service/docs/TROUBLESHOOTING.md` — `llama-server` triage  
- `llm_notable_analysis_onprem/README.md` — architecture, Splunk, systemd-oriented install  
- `llm_notable_analysis_onprem/INSTALL.md` — full `install.sh` (RHEL + vLLM) when you are **not** using this mini stack  

---

## Assumptions

- You are on a **Linux** VM (e.g. Ubuntu/Debian; RHEL family also works with equivalent package names).
- You have **sudo** where indicated.
- The VM can **reach Hugging Face** for the first model download (or you already have the pinned GGUF at the expected path).
- You have **~3+ GB free** on the filesystem that holds `/opt/llamacpp/models` (model is ~2.3 GiB plus build artifacts if compiling from source).
- This walkthrough targets **no systemd** for `llama-server` (containers / Runpod-style). The analyzer is run **manually** in the foreground for clarity; you can wrap it in systemd later using `systemd/notable-analyzer.service` as a template.

---

## 1) Confirm unpack layout

Pick a single parent directory for sources (this doc uses **`/opt/notable-analyzer-src`**). After unpack you should have **all three** of:

```text
/opt/notable-analyzer-src/onprem_qwen3_sudo_llamacpp_service/
/opt/notable-analyzer-src/llm_notable_analysis_onprem/
/opt/notable-analyzer-src/onprem-llm-sdk/
```

Quick check:

```bash
ls -la /opt/notable-analyzer-src/onprem_qwen3_sudo_llamacpp_service/install_llamacpp.sh
ls -la /opt/notable-analyzer-src/llm_notable_analysis_onprem/onprem_service/onprem_main.py
ls -la /opt/notable-analyzer-src/onprem-llm-sdk/pyproject.toml
```

If `onprem-llm-sdk` is missing, the client **cannot** run as shipped (`llm_notable_analysis_onprem/requirements.txt` depends on it).

---

## 2) Optional: fix Windows CRLF on shell scripts

If scripts were copied from Windows without LF normalization, bash may error (`set: pipefail` / `invalid option`).

```bash
find /opt/notable-analyzer-src/onprem_qwen3_sudo_llamacpp_service -name "*.sh" -print0 \
  | xargs -0 sed -i 's/\r$//' 2>/dev/null || true

bash -n /opt/notable-analyzer-src/onprem_qwen3_sudo_llamacpp_service/install_llamacpp.sh && echo "install_llamacpp.sh: OK"
```

The repo root **`.gitattributes`** helps keep LF in git; use `git archive` for transfers when possible.

---

## 3) Install the mini `llama-server` stack

From the mini package:

```bash
cd /opt/notable-analyzer-src/onprem_qwen3_sudo_llamacpp_service
sudo LLAMA_SKIP_SYSTEMD=true bash install_llamacpp.sh
```

Common variants:

- **`LLAMA_SKIP_RUNTIME_BUILD=true`** — if `/usr/local/bin/llama-server` already exists from a previous install.  
- **`LLAMA_SKIP_MODEL_DOWNLOAD=true`** — if the pinned GGUF is already at `LLAMA_MODEL_PATH`.  
- **`LLAMA_INSTALL_DEPS=false`** — if build dependencies are already installed.

Installer writes **`/etc/llamacpp/llamacpp.env`** and expects loopback **`127.0.0.1:8000`** (see `config/llamacpp.env.example`).

---

## 4) Start `llama-server` (no systemd)

Use the **foreground** command first so you see load errors; when stable, use **background** + log file.

**Foreground** (blocks the terminal):

```bash
sudo bash -lc 'source /etc/llamacpp/llamacpp.env; /usr/local/bin/llama-server --model "$LLAMA_MODEL_PATH" --host "$LLAMA_HOST" --port "$LLAMA_PORT" --threads "$LLAMA_THREADS" --threads-batch "$LLAMA_THREADS_BATCH" --parallel "$LLAMA_PARALLEL" --ctx-size "$LLAMA_CTX_SIZE" --n-predict "$LLAMA_DEFAULT_MAX_TOKENS" --cache-type-k "$LLAMA_CACHE_TYPE_K" --cache-type-v "$LLAMA_CACHE_TYPE_V" ${LLAMA_CONT_BATCHING_FLAG:-} ${LLAMA_MMAP_FLAG:-} ${LLAMA_MLOCK_FLAG:-} --metrics --no-webui ${LLAMA_EXTRA_ARGS:-}'
```

**Background** (same as `onprem_qwen3_sudo_llamacpp_service/README.md`):

```bash
sudo bash -lc 'source /etc/llamacpp/llamacpp.env; nohup /usr/local/bin/llama-server --model "$LLAMA_MODEL_PATH" --host "$LLAMA_HOST" --port "$LLAMA_PORT" --threads "$LLAMA_THREADS" --threads-batch "$LLAMA_THREADS_BATCH" --parallel "$LLAMA_PARALLEL" --ctx-size "$LLAMA_CTX_SIZE" --n-predict "$LLAMA_DEFAULT_MAX_TOKENS" --cache-type-k "$LLAMA_CACHE_TYPE_K" --cache-type-v "$LLAMA_CACHE_TYPE_V" ${LLAMA_CONT_BATCHING_FLAG:-} ${LLAMA_MMAP_FLAG:-} ${LLAMA_MLOCK_FLAG:-} --metrics --no-webui ${LLAMA_EXTRA_ARGS:-} >/tmp/llama-server.log 2>&1 &'
tail -f /tmp/llama-server.log
```

**Stop** manual process:

```bash
pkill -f "/usr/local/bin/llama-server"
```

---

## 5) Verify the inference endpoint

Defaults: **`http://127.0.0.1:8000`**, OpenAI-compatible **`POST /v1/chat/completions`**.

```bash
curl -sf http://127.0.0.1:8000/health
curl -sf http://127.0.0.1:8000/metrics | head
```

Minimal chat smoke (JSON only + Qwen3 `/no_think` hint):

```bash
curl -sS http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model":"Qwen3-4B-Q4_K_M.gguf",
    "temperature":0,
    "messages":[
      {"role":"system","content":"Return JSON only. /no_think"},
      {"role":"user","content":"Return {\"ok\":true}"}
    ]
  }'
```

If these fail, fix **`llama-server`** before continuing (port, model path, disk, logs in `/tmp/llama-server.log` or foreground output).

---

## 6) Notable analyzer: data directories

The client expects **file-drop** dirs (defaults match `config.env.example`):

```bash
sudo mkdir -p /var/notables/{incoming,processed,quarantine,reports,archive}
sudo chmod 755 /var/notables
# PoC: run as your user — own the tree so the process can move files
sudo chown -R "$USER:$USER" /var/notables
```

Production hardening (dedicated `notable-analyzer` user, SFTP chroot) is described in `llm_notable_analysis_onprem/INSTALL.md` / `README.md`; not required for a single-user PoC.

---

## 6b) Fast path: one script for client setup

If you unpacked both `llm_notable_analysis_onprem` and `onprem-llm-sdk` as sibling folders, you can skip sections 7-8 and run:

```bash
cd /opt/notable-analyzer-src/llm_notable_analysis_onprem
sudo bash install_mini_qwen_cpu_client.sh
```

This handles venv creation, SDK install, `/etc/notable-analyzer/config.env` mini defaults, launcher creation, and data directories.

Then jump to section 9 and run:

```bash
sudo -u notable-analyzer /usr/local/bin/notable-analyzer-mini-run
```

If your SDK path is not the default sibling location, run:

```bash
sudo SDK_SOURCE_DIR=/opt/notable-analyzer-src/onprem-llm-sdk bash install_mini_qwen_cpu_client.sh
```

---

## 7) Python venv and dependencies

Use one venv for the analyzer (path is arbitrary; here **`/opt/notable-analyzer-venv`**):

```bash
sudo mkdir -p /opt/notable-analyzer-venv
sudo chown "$USER:$USER" /opt/notable-analyzer-venv

python3 -m venv /opt/notable-analyzer-venv
source /opt/notable-analyzer-venv/bin/activate
python -m pip install -U pip wheel
```

Install the **SDK from the unpacked tree** (editable install is fine):

```bash
pip install -e /opt/notable-analyzer-src/onprem-llm-sdk
```

Install the analyzer’s **`requests`** pin. The requirements file also lists `onprem-llm-sdk==0.1.0` for PyPI installs; **after** `pip install -e`, install the rest without re-pulling the SDK:

```bash
pip install requests==2.32.5
```

If you prefer a single file-driven install and your environment can resolve **`onprem-llm-sdk==0.1.0`** from an internal index, use `pip install -r /opt/notable-analyzer-src/llm_notable_analysis_onprem/requirements.txt` **instead** (no editable SDK). For **this** walkthrough, the **editable SDK + `requests`** pattern matches “everything from the unpacked directory.”

---

## 8) Configuration: `/etc/notable-analyzer/config.env`

Create the config directory and seed from the example:

```bash
sudo mkdir -p /etc/notable-analyzer
sudo cp /opt/notable-analyzer-src/llm_notable_analysis_onprem/config.env.example /etc/notable-analyzer/config.env
sudo chmod 600 /etc/notable-analyzer/config.env
sudo chown root:root /etc/notable-analyzer/config.env
```

Edit **`/etc/notable-analyzer/config.env`** (e.g. `sudo nano`):

**LLM (must match mini service):**

- `LLM_API_URL=http://127.0.0.1:8000/v1/chat/completions`
- `LLM_MODEL_NAME=Qwen3-4B-Q4_K_M.gguf` (must match what `llama-server` serves / request `model` field)
- `LLM_MAX_TOKENS` — start conservative (e.g. `1024`) on CPU; increase after stability testing
- `LLM_TIMEOUT` — raise if generations are slow (e.g. `120` or higher)

**`MITRE_IDS_PATH` (important for “unpack only” layouts):**

`config.env.example` points at **`/opt/notable-analyzer/onprem_service/...`**, which exists only after a full **`install.sh`** layout. If you have **not** copied code to `/opt/notable-analyzer`, either:

- **Set** `MITRE_IDS_PATH` to the real file under your unpack tree, e.g.  
  `/opt/notable-analyzer-src/llm_notable_analysis_onprem/onprem_service/enterprise_attack_v17.1_ids.json`  
  **or**
- **Remove** the `MITRE_IDS_PATH=` line entirely from `config.env` so the process uses the default next to `onprem_service` **when that package is imported from the unpacked tree** (see step 9).

**Splunk:** leave `SPLUNK_SINK_ENABLED=false` unless you are intentionally testing writeback.

---

## 9) Run the notable analyzer (foreground)

The service reads **environment variables** (`os.getenv`). When not using systemd’s `EnvironmentFile=`, **source** the file into your shell before starting Python.

**Working directory** must be the **`llm_notable_analysis_onprem`** folder (parent of the `onprem_service` package):

```bash
source /opt/notable-analyzer-venv/bin/activate
set -a
source /etc/notable-analyzer/config.env
set +a
cd /opt/notable-analyzer-src/llm_notable_analysis_onprem
python -m onprem_service.onprem_main
```

Leave this running; it polls `INCOMING_DIR` every `POLL_INTERVAL` seconds.

**Optional — freeform mode** (paragraph reports, different entrypoint):

```bash
# same env sourcing as above
cd /opt/notable-analyzer-src/llm_notable_analysis_onprem
python -m onprem_service.freeform_main
```

Do **not** run structured and freeform against the same `INCOMING_DIR` concurrently (`README.md`).

---

## 10) Functional test (end-to-end)

In **another** shell, with the analyzer still running:

```bash
echo '{"summary":"Test notable","ip_address":"203.0.113.45","user":"svc_test"}' \
  > /var/notables/incoming/notable_poc_001.json
```

Within a few poll intervals, check:

```bash
ls -la /var/notables/processed/
ls -la /var/notables/reports/
ls -la /var/notables/quarantine/
```

A successful run produces a markdown report under **`REPORT_DIR`**. If files land in **`quarantine`**, read analyzer logs in the terminal running `onprem_main` for LLM/schema errors.

---

## 11) Shutdown / cleanup

```bash
# Stop analyzer: Ctrl+C in its terminal, or from another shell:
pkill -f "onprem_service.onprem_main"

# Stop llama-server:
pkill -f "/usr/local/bin/llama-server"
```

---

## Related commands summary

| Goal | Command / location |
|------|---------------------|
| Mini installer | `sudo LLAMA_SKIP_SYSTEMD=true bash install_llamacpp.sh` in `onprem_qwen3_sudo_llamacpp_service/` |
| Mini env file | `/etc/llamacpp/llamacpp.env` |
| Analyzer config | `/etc/notable-analyzer/config.env` |
| Analyzer entry (structured) | `python -m onprem_service.onprem_main` from `llm_notable_analysis_onprem/` |
| Health | `curl -sf http://127.0.0.1:8000/health` |
| Chat API | `POST http://127.0.0.1:8000/v1/chat/completions` |

---

## Operational notes

- **Port:** Inference is standardized on **`127.0.0.1:8000`** in-tree; the analyzer does **not** bind that port—it **calls** it.  
- **Qwen3 reasoning:** For JSON-heavy prompts, use **`/no_think`** in the system message (see `onprem_qwen3_sudo_llamacpp_service/README.md`).  
- **Full production install** (users, vLLM, SELinux, systemd units): follow `llm_notable_analysis_onprem/install.sh` + `INSTALL.md`—different from this PoC path.
