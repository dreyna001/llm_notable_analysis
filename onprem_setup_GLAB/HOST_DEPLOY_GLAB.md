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

## Choose your path

| Situation | What to do |
|-----------|------------|
| **Target server has internet** | Install [prerequisites on the target](#prerequisites-on-the-target-server) on the target, then start at [Step 1 — Internet-connected target](#internet-connected-target). |
| **Target server has no internet** | On a **staging** machine with internet, complete [Phase A](#phase-a--gather-everything-on-the-staging-server-internet-connected), then [Phase B](#phase-b--copy-the-bundle-to-the-target-server), then install [prerequisites on the target](#prerequisites-on-the-target-server) from media or bundled OS packages, then [Phase C](#phase-c--unpack-on-the-target-and-set-paths) and follow [Step 1 — Offline target](#offline-target-after-phase-c). |

---

## Prerequisites on the staging server (internet-connected)

Use a staging Linux host (for example WSL2 or a jump box) that can reach `https://github.com` and PyPI. **Match the target as closely as you can:** same CPU architecture (for example `x86_64`) and same major OS family as the GPU server, so Python wheels you download are likely to install on the target.

On the staging server, install tooling used below.

Debian/Ubuntu-style:

```bash
sudo apt update
sudo apt install -y git curl python3.12 python3.12-venv python3-pip
```

RHEL 8/9 or compatible:

```bash
sudo dnf install -y git curl python3.12 python3.12-pip
```

Confirm:

```bash
python3.12 --version
git --version
curl --version
```

---

## Phase A — Gather everything on the staging server (internet-connected)

Create one directory that will become your transfer bundle:

```bash
mkdir -p ~/glab_transfer/wheelhouse
mkdir -p ~/glab_transfer/models/gpt-oss-120b
mkdir -p ~/glab_transfer/models/embeddings/all-MiniLM-L6-v2
cd ~/glab_transfer
```

### A.1 Clone this repository

```bash
git clone https://github.com/dreyna001/llm_notable_analysis.git
```

You should have `~/glab_transfer/llm_notable_analysis/` with `onprem_vllm_service/` and `onprem_setup_GLAB/` inside it.

### A.2 Download Python wheels for offline install on the target

From the staging server, download wheels into `~/glab_transfer/wheelhouse`. This pulls `vLLM` and its dependencies (large download).

```bash
cd ~/glab_transfer
python3.12 -m pip download -d wheelhouse pip setuptools wheel
python3.12 -m pip download -d wheelhouse "vllm==0.14.1"
python3.12 -m pip download -d wheelhouse "litellm[proxy]"
python3.12 -m pip download -d wheelhouse faiss-cpu sentence-transformers numpy python-docx docx2txt
```

`pip download` does not support `--upgrade` on many pip versions (you may see “no such option --upgrade”); omit it. To upgrade staging `pip` itself, run `python3.12 -m pip install --user -U pip` separately, then re-run the download block if needed.

If `pip download` fails for `vllm` on the staging OS, run the same `pip download` commands on another Linux system that matches the **target** OS and CUDA/Python stack, then merge the resulting `wheelhouse` directories.

### A.3 Stage **gpt-oss-120b** model files

You must end up with a **complete Hugging Face–style model directory** under `~/glab_transfer/models/gpt-oss-120b/`. That tree includes `config.json`, tokenizer files, and all weight shards — it is **not** in this Git repo (too large). The canonical public Hub repo id is **`openai/gpt-oss-120b`** ([model card](https://huggingface.co/openai/gpt-oss-120b)).

**Before downloading:** ensure enough disk space on the staging machine (this checkpoint is **very large**; plan **hundreds of gigabytes** free depending on precision/shards — confirm on the model card). If Hugging Face requires **accepting a license** or **gated access**, log in at [huggingface.co/openai/gpt-oss-120b](https://huggingface.co/openai/gpt-oss-120b) and create a token with read access; then export it:

```bash
export HF_TOKEN='hf_...'
# or
export HUGGINGFACE_TOKEN='hf_...'
```

**Option A — Hugging Face CLI** (from `~/glab_transfer`, directory already exists from Phase A setup):

```bash
python3.12 -m pip install --user "huggingface_hub>=0.23.0"
huggingface-cli download openai/gpt-oss-120b \
  --local-dir ~/glab_transfer/models/gpt-oss-120b \
  --local-dir-use-symlinks False
```

**Option B — Python `snapshot_download`** (same result; good for scripting and resume):

```bash
python3.12 -m pip install --user "huggingface_hub>=0.23.0"
python3.12 - <<'PY'
import os
from huggingface_hub import snapshot_download

repo_id = "openai/gpt-oss-120b"
local_dir = os.path.expanduser("~/glab_transfer/models/gpt-oss-120b")
token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
snapshot_download(
    repo_id=repo_id,
    local_dir=local_dir,
    local_dir_use_symlinks=False,
    token=token,
    resume_download=True,
)
print("Downloaded to", local_dir)
PY
```

**Verify** (after either option finishes):

```bash
test -f ~/glab_transfer/models/gpt-oss-120b/config.json && echo OK
```

**Option C — Copy from internal storage or removable media** (no Hub access on staging):

```bash
# Example: adjust SOURCE to your NAS mount or USB path
sudo rsync -a --info=progress2 SOURCE/gpt-oss-120b/ ~/glab_transfer/models/gpt-oss-120b/
test -f ~/glab_transfer/models/gpt-oss-120b/config.json && echo OK
```

If TLS interception breaks Hub downloads, fix CA trust (preferred) or use the same `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` approach as for `pip`; avoid disabling TLS unless your security team approves.

### A.4 Stage the sentence-transformers embedding model (recommended for offline KB)

Install the Hub client on staging, then snapshot the embedding model into the bundle:

```bash
python3.12 -m pip install --user "huggingface_hub>=0.23.0"
python3.12 - <<'PY'
import os
from huggingface_hub import snapshot_download

repo_id = "sentence-transformers/all-MiniLM-L6-v2"
local_dir = os.path.expanduser("~/glab_transfer/models/embeddings/all-MiniLM-L6-v2")
token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
snapshot_download(
    repo_id=repo_id,
    local_dir=local_dir,
    local_dir_use_symlinks=False,
    token=token,
)
print("Downloaded to", local_dir)
PY
```

If your environment uses a Hugging Face token for gated assets, export `HF_TOKEN` (or `HUGGINGFACE_TOKEN`) before running the snippet.

### A.5 Optional — download OS packages for the target (same distro as target)

On a host that has the **same** distro/repositories as the target, you can prefetch RPMs or DEBs for Python 3.12, venv, headers, and common tools so the target can install without internet. Example for `dnf`:

```bash
mkdir -p ~/glab_transfer/os_packages
sudo dnf install --downloadonly --downloaddir="$HOME/glab_transfer/os_packages" \
  python3.12 python3.12-pip git curl
```

Package names vary by release; align with what your target image provides.

### A.6 Create one archive for SCP

```bash
cd ~
tar -czvf glab_offline_bundle.tgz -C glab_transfer .
ls -lh ~/glab_offline_bundle.tgz
```

---

## Phase B — Copy the bundle to the target server

From the staging machine (replace `deploy` and `TARGET_HOST` with your SSH user and hostname or IP):

```bash
scp ~/glab_offline_bundle.tgz deploy@TARGET_HOST:/tmp/glab_offline_bundle.tgz
```

For large bundles, `rsync` over SSH may be easier to resume:

```bash
rsync -avP --progress ~/glab_offline_bundle.tgz deploy@TARGET_HOST:/tmp/glab_offline_bundle.tgz
```

---

## Prerequisites on the target server

Whether the target is internet-connected or air-gapped, it needs:

- **NVIDIA GPU driver** and a **CUDA** stack compatible with the `vllm==0.14.1` wheel you staged
- **Python 3.12** and `python3.12 -m venv` (package names differ by distro)
- **`systemd`**, **`sudo`**, **`curl`** (for health checks in this runbook)
- **`git`** only if you will `git pull` on the target; not required if you deploy only from the tarball

If the target has **no internet**, install those OS packages from your standard image, from vendor ISO, or from the `os_packages/` directory you added in Phase A.5.

---

## Phase C — Unpack on the target and set paths

On the **target** server:

```bash
sudo mkdir -p /opt/glab_transfer
sudo tar -xzf /tmp/glab_offline_bundle.tgz -C /opt/glab_transfer
```

After this, these paths exist:

- Repository: `/opt/glab_transfer/llm_notable_analysis`
- Wheels: `/opt/glab_transfer/wheelhouse`
- Staged LLM weights: `/opt/glab_transfer/models/gpt-oss-120b`
- Staged embedding model: `/opt/glab_transfer/models/embeddings/all-MiniLM-L6-v2`

Install the language model into the runtime location vLLM expects:

```bash
sudo mkdir -p /opt/models/gpt-oss-120b
sudo rsync -a /opt/glab_transfer/models/gpt-oss-120b/ /opt/models/gpt-oss-120b/
test -f /opt/models/gpt-oss-120b/config.json && echo OK
```

Optional: copy the embedding tree for KB offline use:

```bash
sudo mkdir -p /opt/models/embeddings/all-MiniLM-L6-v2
sudo rsync -a /opt/glab_transfer/models/embeddings/all-MiniLM-L6-v2/ /opt/models/embeddings/all-MiniLM-L6-v2/
```

For all **offline** `pip install` commands in Steps 3–5, use environment variables so `pip` does not reach the network:

```bash
export PIP_NO_INDEX=1
export PIP_FIND_LINKS=/opt/glab_transfer/wheelhouse
```

Pass `-E` to `sudo` when you need those variables to apply to `pip` inside `sudo` (examples appear in Step 3.B).

---

## Step 1 — Repository on the target

### Internet-connected target

```bash
git clone https://github.com/dreyna001/llm_notable_analysis.git
cd llm_notable_analysis
```

All paths below assume your working tree root is `llm_notable_analysis` (the directory created by that clone).

### Offline target (after Phase C)

Skip `git clone` on the target. Use the tree unpacked from the bundle:

```bash
cd /opt/glab_transfer/llm_notable_analysis
```

Treat this directory as the repository root for Steps 2–6 (same layout as a fresh clone).

---

## Step 2 — Stage the language model (internet-connected target only)

If you completed [Phase C](#phase-c--unpack-on-the-target-and-set-paths), you already populated `/opt/models/gpt-oss-120b` from the bundle. Skip this step.

Otherwise, on the target:

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

From the repository root (`llm_notable_analysis` for an internet-connected clone, or `/opt/glab_transfer/llm_notable_analysis` after Phase C):

### 3.A — Internet-connected target (default)

```bash
cd onprem_vllm_service
sudo VLLM_MODEL_PATH=/opt/models/gpt-oss-120b \
     VLLM_SERVED_MODEL_NAME=gpt-oss-120b \
     bash install_vllm.sh
```

### 3.B — Offline target (wheelhouse from Phase A)

```bash
cd onprem_vllm_service
export PIP_NO_INDEX=1
export PIP_FIND_LINKS=/opt/glab_transfer/wheelhouse
sudo -E env PIP_NO_INDEX=1 PIP_FIND_LINKS=/opt/glab_transfer/wheelhouse \
  VLLM_MODEL_PATH=/opt/models/gpt-oss-120b \
  VLLM_SERVED_MODEL_NAME=gpt-oss-120b \
  VLLM_PIP_SPEC="/opt/glab_transfer/wheelhouse/vllm-0.14.1-*.whl" \
  bash install_vllm.sh
```

If the glob does not expand on your shell, replace `VLLM_PIP_SPEC` with the exact wheel filename under `/opt/glab_transfer/wheelhouse/`.

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

**Internet-connected target:**

```bash
sudo python3.12 -m venv /opt/litellm/venv
sudo /opt/litellm/venv/bin/pip install --upgrade pip
sudo /opt/litellm/venv/bin/pip install "litellm[proxy]"
```

**Offline target** (after Phase C, wheelhouse at `/opt/glab_transfer/wheelhouse`):

```bash
sudo python3.12 -m venv /opt/litellm/venv
sudo PIP_NO_INDEX=1 PIP_FIND_LINKS=/opt/glab_transfer/wheelhouse \
  /opt/litellm/venv/bin/pip install --upgrade pip
sudo PIP_NO_INDEX=1 PIP_FIND_LINKS=/opt/glab_transfer/wheelhouse \
  /opt/litellm/venv/bin/pip install "litellm[proxy]"
```

### 4.3 Config and systemd unit from this repo

With your current working directory set to the repository root (`llm_notable_analysis` after `git clone`, or `/opt/glab_transfer/llm_notable_analysis` after Phase C):

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

**Internet-connected target** (repository root is the current directory):

```bash
sudo rsync -a onprem_rag /opt/notable-kb/
sudo python3.12 -m venv /opt/notable-kb/venv
sudo /opt/notable-kb/venv/bin/pip install --upgrade pip
sudo /opt/notable-kb/venv/bin/pip install faiss-cpu sentence-transformers numpy python-docx docx2txt
sudo chown -R notable-kb:notable-kb /opt/notable-kb
```

**Offline target:**

```bash
sudo rsync -a /opt/glab_transfer/llm_notable_analysis/onprem_rag /opt/notable-kb/
sudo python3.12 -m venv /opt/notable-kb/venv
sudo PIP_NO_INDEX=1 PIP_FIND_LINKS=/opt/glab_transfer/wheelhouse \
  /opt/notable-kb/venv/bin/pip install --upgrade pip
sudo PIP_NO_INDEX=1 PIP_FIND_LINKS=/opt/glab_transfer/wheelhouse \
  /opt/notable-kb/venv/bin/pip install faiss-cpu sentence-transformers numpy python-docx docx2txt
sudo chown -R notable-kb:notable-kb /opt/notable-kb
```

### 5.4 Embedding model path

Either:

- Stage **sentence-transformers/all-MiniLM-L6-v2** under `/opt/models/embeddings/all-MiniLM-L6-v2` and point config there (this matches the tree produced in Phase A.4 after you copy it in Phase C), or  
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

After updates, on an **internet-connected** target:

```bash
cd llm_notable_analysis
git pull origin main
```

On an **air-gapped** target, refresh by repeating Phase A on staging, transferring a new `glab_offline_bundle.tgz`, unpacking over `/opt/glab_transfer`, and re-running any changed install steps.

Re-copy any changed unit or config templates from `onprem_setup_GLAB/` if you maintain them from the repo, then `sudo systemctl daemon-reload` and restart affected services as needed.
