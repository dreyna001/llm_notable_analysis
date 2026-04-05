# GHCR: log in and push images

**This project’s Git repo and GHCR package names:** [canonical-repos.md](canonical-repos.md).

You’re logging Docker into **GitHub Container Registry** at `ghcr.io`. The registry does **not** use your GitHub account password.

**When Docker asks for a password, paste the Personal Access Token (PAT) you created** — that token *is* the password for `docker login`.

## Before you run `docker login`

1. In GitHub, create a **classic** PAT (or a fine‑grained PAT with package permissions).
2. Enable at least **`read:packages`** and **`write:packages`** (classic), or the equivalent **Packages → Read and write** (fine‑grained).
3. Copy the token once; GitHub won’t show it again.

## Log in (PowerShell-friendly)

Log out first so old bad creds don’t stick:

```powershell
docker logout ghcr.io
```

Log in. **Username** = your **GitHub username** (below uses **`dreyna001`** for this repo; use yours if different). **Password** = **paste your PAT** when prompted:

```powershell
docker login ghcr.io -u dreyna001
```

Or pipe the PAT so it isn’t echoed (still treat the PAT like a password — don’t commit it):

```powershell
$env:GHCR_PAT = "paste-your-pat-here"
$env:GHCR_PAT | docker login ghcr.io -u dreyna001 --password-stdin
Remove-Item Env:GHCR_PAT
```

You want to see **Login Succeeded**.

## Put **both** stack images in GHCR

For **`dreyna001`** (this repo’s maintainer), the published names for **this** bundle are `ghcr.io/dreyna001/notable-analyzer-service` (Python analyzer worker, CPU/GPU-agnostic) and `ghcr.io/dreyna001/llama-cpp-server-cpu-phi35-llamacpp` (mirrored **llama.cpp** server for this reference stack) — see [canonical-repos.md](canonical-repos.md). Below, replace `dreyna001` with **your** GitHub username if you fork or use a different account. Tags (`1.0.0`, `server`) should match what you intend to publish.

1. **Go to the compose directory** (so `docker compose` finds `compose.yaml`):

   ```bash
   cd llm_notable_analysis_onprem_docker_cpu_phi35_llamacpp
   ```

2. **Log in to GHCR** (password = PAT):

   ```bash
   docker login ghcr.io -u dreyna001
   ```

3. **Analyzer** (your app image — build, tag under your user, push):

   ```bash
   docker compose build analyzer
   docker tag notable-analyzer-service-analyzer:latest ghcr.io/dreyna001/notable-analyzer-service:1.0.0
   docker push ghcr.io/dreyna001/notable-analyzer-service:1.0.0
   ```

4. **llama.cpp server** (mirror upstream into your namespace — re-tag local copy or pull first, then push):

   ```bash
   docker pull ghcr.io/ggml-org/llama.cpp:server
   docker tag ghcr.io/ggml-org/llama.cpp:server ghcr.io/dreyna001/llama-cpp-server-cpu-phi35-llamacpp:server
   docker push ghcr.io/dreyna001/llama-cpp-server-cpu-phi35-llamacpp:server
   ```

5. **On an air-gapped / pull-only host**, set these in `.env` when using `compose.airgap.yaml`:

   ```env
   ANALYZER_IMAGE=ghcr.io/dreyna001/notable-analyzer-service:1.0.0
   MODEL_SERVING_IMAGE=ghcr.io/dreyna001/llama-cpp-server-cpu-phi35-llamacpp:server
   ```

Then: `docker compose -f compose.airgap.yaml pull` and `docker compose -f compose.airgap.yaml up -d`.

The **GGUF** still lives on the host under `models/`; it is not inside either image. More context: `airgap-deployment.md`.

## If you get `denied: denied`

- Confirm you used the **PAT** as the password, not your GitHub login password.
- Confirm **username** matches your GitHub handle.
- Run `docker logout ghcr.io` and remove stale **Windows Credential Manager** entries for `ghcr.io`, then log in again.
- If your packages live under an **org** with **SAML SSO**, authorize the PAT for that org in GitHub (PAT settings → **Configure SSO**).
