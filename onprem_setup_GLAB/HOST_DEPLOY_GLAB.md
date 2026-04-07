# GLAB host-only deployment (vLLM + LiteLLM + KB indexer)

This runbook is for a single Linux host with systemd. It uses the repository at:

- **Remote:** `https://github.com/dreyna001/llm_notable_analysis.git`
- **Default clone directory name:** `llm_notable_analysis`

No Docker. Three operational pieces:

1. **vLLM** — GPU inference, OpenAI-compatible API on `127.0.0.1:8000`
2. **LiteLLM** — proxy for callers, `POST /v1/chat/completions` on `127.0.0.1:4000`
3. **KB indexer** — rebuilds `kb.sqlite3` and `kb.faiss` under `/var/lib/notable-kb/index`

`vLLM` is installed from the repo root package `onprem_vllm_service/`. LiteLLM and KB assets live under `onprem_setup_GLAB/`.

---

## Prerequisites

- NVIDIA GPU driver and CUDA stack appropriate for vLLM
- Python 3.12 on the host (matches `onprem_vllm_service` defaults)
- `git`, `curl`, `sudo`, `systemd`
- Model weights for **gpt-oss-120b** staged on the host before starting vLLM (directory must contain `config.json`)

---

## Step 1 — Clone the repository

```bash
git clone https://github.com/dreyna001/llm_notable_analysis.git
cd llm_notable_analysis
```

All paths below assume your working tree root is `llm_notable_analysis` (the directory created by that clone).

---

## Step 2 — Stage the language model

Create the model directory and copy your **gpt-oss-120b** artifacts into it:

```bash
sudo mkdir -p /opt/models/gpt-oss-120b
```

Copy tokenizer, config, and weight shards so that at minimum this file exists:

```bash
test -f /opt/models/gpt-oss-120b/config.json && echo OK
```

Adjust ownership if your install script or operator account needs write access during staging; `install_vllm.sh` documents common patterns.

---

## Step 3 — Install and start vLLM

From the repository root (after Step 1 you are already in `llm_notable_analysis`):

```bash
cd onprem_vllm_service
sudo VLLM_MODEL_PATH=/opt/models/gpt-oss-120b \
     VLLM_SERVED_MODEL_NAME=gpt-oss-120b \
     bash install_vllm.sh
```

Verify:

```bash
sudo systemctl status vllm
curl -sf http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-oss-120b","messages":[{"role":"user","content":"Reply with OK"}],"max_tokens":16}'
```

Return to the repository root for Steps 4 and 5:

```bash
cd ..
```

---

## Step 4 — Install and start LiteLLM

### 4.1 Service user and directories

```bash
sudo groupadd --system litellm 2>/dev/null || true
sudo useradd --system --gid litellm --home-dir /opt/litellm --create-home --shell /sbin/nologin litellm 2>/dev/null || true
sudo mkdir -p /opt/litellm /etc/litellm
sudo chown -R litellm:litellm /opt/litellm
```

### 4.2 Python virtualenv and LiteLLM proxy package

```bash
sudo python3.12 -m venv /opt/litellm/venv
sudo /opt/litellm/venv/bin/pip install --upgrade pip
sudo /opt/litellm/venv/bin/pip install "litellm[proxy]"
```

### 4.3 Config and systemd unit from this repo

With your current working directory set to the repository root (the directory created by `git clone`, named `llm_notable_analysis`):

```bash
sudo cp onprem_setup_GLAB/onprem_litellm_service/config/config.yaml.example /etc/litellm/config.yaml
sudo cp onprem_setup_GLAB/onprem_litellm_service/systemd/litellm.service /etc/systemd/system/litellm.service
sudo chmod 600 /etc/litellm/config.yaml
```

### 4.4 Set the proxy master key

Edit `/etc/litellm/config.yaml` and set `general_settings.master_key` to a strong secret string that starts with `sk-`. Remove or replace the example value `sk-change-me-before-first-start` before the first production start.

### 4.5 Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now litellm
sudo systemctl status litellm
```

### 4.6 Smoke test through LiteLLM

Export the same key you set in `config.yaml` (the value after `master_key:`), then:

```bash
export LITELLM_KEY='sk-...'
curl -sS http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer ${LITELLM_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-oss-120b","messages":[{"role":"user","content":"Reply with OK"}],"max_tokens":16}'
```

Clients should use:

- **URL:** `http://127.0.0.1:4000/v1/chat/completions`
- **Model:** `gpt-oss-120b`
- **Authorization:** `Bearer <same master_key value>`

Per-user virtual keys are a separate LiteLLM feature and may require additional database configuration; this runbook uses the single master key pattern.

---

## Step 5 — KB indexer (SQLite + FAISS)

### 5.1 Service user and directories

```bash
sudo groupadd --system notable-kb 2>/dev/null || true
sudo useradd --system --gid notable-kb --home-dir /opt/notable-kb --create-home --shell /sbin/nologin notable-kb 2>/dev/null || true
sudo mkdir -p /opt/notable-kb/bin /etc/notable-kb /var/lib/notable-kb/source /var/lib/notable-kb/index
sudo chown -R notable-kb:notable-kb /opt/notable-kb /var/lib/notable-kb
```

### 5.2 Copy scripts, config, and systemd units

From repository root:

```bash
sudo cp onprem_setup_GLAB/onprem_kb_indexer/bin/run_kb_rebuild.sh /opt/notable-kb/bin/run_kb_rebuild.sh
sudo cp onprem_setup_GLAB/onprem_kb_indexer/config/config.env.example /etc/notable-kb/config.env
sudo cp onprem_setup_GLAB/onprem_kb_indexer/systemd/kb-rebuild.service /etc/systemd/system/kb-rebuild.service
sudo cp onprem_setup_GLAB/onprem_kb_indexer/systemd/kb-rebuild.timer /etc/systemd/system/kb-rebuild.timer
sudo chmod 750 /opt/notable-kb/bin/run_kb_rebuild.sh
```

### 5.3 Install `onprem_rag` and Python dependencies into `/opt/notable-kb/venv`

```bash
sudo rsync -a onprem_rag /opt/notable-kb/
sudo python3.12 -m venv /opt/notable-kb/venv
sudo /opt/notable-kb/venv/bin/pip install --upgrade pip
sudo /opt/notable-kb/venv/bin/pip install faiss-cpu sentence-transformers numpy python-docx docx2txt
sudo chown -R notable-kb:notable-kb /opt/notable-kb
```

### 5.4 Embedding model path

Either:

- Stage **sentence-transformers/all-MiniLM-L6-v2** under `/opt/models/embeddings/all-MiniLM-L6-v2` and point config there, or  
- If the host has Hugging Face access, set `KB_EMBEDDING_MODEL` to the Hugging Face id `sentence-transformers/all-MiniLM-L6-v2` in `/etc/notable-kb/config.env`.

Edit `/etc/notable-kb/config.env` and confirm:

- `KB_SOURCE_DIR=/var/lib/notable-kb/source`
- `KB_INDEX_DIR=/var/lib/notable-kb/index`
- `KB_EMBEDDING_MODEL` matches your staged path or HF id
- `KB_PYTHON=/opt/notable-kb/venv/bin/python`

Place `.txt` and `.docx` source documents under `/var/lib/notable-kb/source` (recursive discovery is supported).

### 5.5 Run rebuild and optional timer

```bash
sudo systemctl daemon-reload
sudo systemctl start kb-rebuild.service
sudo systemctl status kb-rebuild.service
sudo systemctl enable --now kb-rebuild.timer
```

Verify artifacts:

```bash
ls -l /var/lib/notable-kb/index/kb.sqlite3 /var/lib/notable-kb/index/kb.faiss
sudo journalctl -u kb-rebuild.service -n 100 --no-pager
```

---

## Step 6 — Point applications at LiteLLM

For **onprem-llm-sdk** and compatible clients, set:

- `LLM_API_URL=http://127.0.0.1:4000/v1/chat/completions`
- `LLM_MODEL_NAME=gpt-oss-120b`
- `LLM_API_TOKEN` to the LiteLLM master key value (Bearer token)

Do not send end-user traffic directly to vLLM port `8000` if LiteLLM is your intended control plane.

---

## Reference: files in this repo

| Component | Location in `llm_notable_analysis` |
|-----------|--------------------------------------|
| vLLM installer | `onprem_vllm_service/install_vllm.sh` |
| LiteLLM example config | `onprem_setup_GLAB/onprem_litellm_service/config/config.yaml.example` |
| LiteLLM systemd unit | `onprem_setup_GLAB/onprem_litellm_service/systemd/litellm.service` |
| KB rebuild script | `onprem_setup_GLAB/onprem_kb_indexer/bin/run_kb_rebuild.sh` |
| KB env example | `onprem_setup_GLAB/onprem_kb_indexer/config/config.env.example` |
| KB systemd units | `onprem_setup_GLAB/onprem_kb_indexer/systemd/kb-rebuild.service` and `kb-rebuild.timer` |
| Stack overview | `onprem_setup_GLAB/README.md` |

---

## Git reference

Clone URL:

```text
https://github.com/dreyna001/llm_notable_analysis.git
```

After updates, pull on the host:

```bash
cd llm_notable_analysis
git pull origin main
```

Re-copy any changed unit or config templates from `onprem_setup_GLAB/` if you maintain them from the repo, then `sudo systemctl daemon-reload` and restart affected services as needed.
