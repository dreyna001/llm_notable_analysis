# Host layout: git checkout vs installed runtime

Production on-prem hosts use **separate locations** for source control, running
code, runtime configuration, and optional RAG content. This is intentional:
`systemd` always runs from a fixed install tree; operators keep a git checkout
for templates, scripts, and upgrades.

## The four paths to remember

| Location | Typical path | Role |
| --- | --- | --- |
| **Git checkout** | Operator-chosen (see below) | `git pull`, `config.env.example`, deployment scripts, tests, docs |
| **Installed application** | `/opt/notable-analyzer` | Python venv, `src/`, portal `dist/`, copied RAG package; **what `systemd` executes** |
| **Runtime env files** | `/etc/notable-analyzer/config.env`, `portal.env` | Secrets, capability profiles, tuning; **not** overwritten on reinstall if files already exist |
| **Knowledge base content** | `/opt/llm-notable-analysis/knowledge_base/` | Customer source docs and ingest artifacts (data, not application code) |

Inference and proxy stacks use their own fixed trees: `/opt/vllm`, `/opt/litellm`,
`/opt/models/`, `/etc/litellm/config.yaml`. See
[`INSTALL.md`](INSTALL.md) and the package
[`README.md`](../../../README.md) prerequisites and Path A/B/C journeys.

## Intended behavior

1. **`scripts/install.sh` runs from the git checkout** (the directory that
   contains `scripts/install.sh`, i.e. `llm_notable_analysis_onprem_systemd/`).
   It copies application code into `/opt/notable-analyzer` and creates or
   upgrades the production venv there.

2. **`git pull` updates only the checkout.** It does **not** change
   `/opt/notable-analyzer` until you run `install.sh` again (or manually copy
   files). Services keep running the last installed copy.

3. **Configuration lives outside both trees.** Analyzer and portal units load
   `EnvironmentFile=/etc/notable-analyzer/config.env` and `portal.env`. Re-running
   `install.sh` skips replacing those files if they already exist.

4. **Profile and smoke scripts run from the checkout** but edit or read host
   paths (`/etc/notable-analyzer/`, vLLM drop-ins). Example:
   `scripts/apply_rtx_pro_6000_blackwell_5analysts_profile.sh` updates env files
   and the vLLM override; it does not redeploy Python packages.

5. **Config-only or profile-only changes** do not require `install.sh`. **Application
   code or dependency changes** on `main` require re-running `install.sh` and
   restarting affected services.

## Where to clone on the host

The installer does **not** require a fixed clone path. Common conventions:

| Convention | Monorepo root | Package dir (`install.sh` cwd) |
| --- | --- | --- |
| AWS EC2 lab bootstrap | `/opt/llm-notable-analysis-src` | `.../llm_notable_analysis_onprem_systemd` |
| Example customer layout | `/opt/src/llm_notable_analysis` | `.../llm_notable_analysis_onprem_systemd` |
| Ad hoc | Any path with `.git` at monorepo root | `.../llm_notable_analysis_onprem_systemd` |

Record the chosen **`MONOREPO_ROOT`** and **`ONPREM_DIR`** in runbooks so
operators and automation agree on where to pull and which directory to pass to
`install.sh`.

Full install expects sibling packages at monorepo root:
`onprem_rag_notable_analysis/`, `onprem-llm-sdk/` (override with
`RAG_PACKAGE_SRC_DIR` / `SDK_SOURCE_DIR` if needed).

## What `systemd` runs

From `deploy/systemd/notable-analyzer.service` and `notable-portal.service`:

```text
WorkingDirectory=/opt/notable-analyzer
ExecStart=/opt/notable-analyzer/venv/bin/python -m llm_notable_analysis_onprem_systemd.onprem_service.onprem_main
ExecStart=/opt/notable-analyzer/venv/bin/python -m llm_notable_analysis_onprem_systemd.onprem_service.portal_app
EnvironmentFile=/etc/notable-analyzer/config.env   # analyzer
EnvironmentFile=/etc/notable-analyzer/portal.env     # portal
```

Do not point units at the git checkout for production; use the install tree.

## Discover paths on an existing host

```bash
# Runtime (authoritative for services)
systemctl cat notable-analyzer notable-portal | grep -E 'WorkingDirectory|ExecStart|EnvironmentFile'
ls -la /opt/notable-analyzer/src/llm_notable_analysis_onprem_systemd/onprem_service/onprem_main.py

# Git checkout (search if unknown)
sudo find /opt /root /home -maxdepth 5 -name llm_notable_analysis_onprem_systemd -type d 2>/dev/null \
  | while read -r d; do
      root="$(dirname "$d")"
      [[ -d "$root/.git" ]] && echo "MONOREPO_ROOT=$root" && echo "ONPREM_DIR=$d"
    done

# Confirm drift between checkout and install (after setting ONPREM_DIR)
diff -qr "$ONPREM_DIR/src/llm_notable_analysis_onprem_systemd" \
        /opt/notable-analyzer/src/llm_notable_analysis_onprem_systemd | head
```

If `find` only shows `/opt/notable-analyzer/...`, the host may have been installed
from a tarball or the checkout was removed; restore a monorepo clone before the
next upgrade.

## Update workflow after `git pull`

Run from **`ONPREM_DIR`** (the checkout's `llm_notable_analysis_onprem_systemd/`):

```bash
cd "$ONPREM_DIR"
git -C "$MONOREPO_ROOT" pull

# When Python, frontend dist, or requirements changed:
sudo AUTO_START_SERVICES=false RUN_SMOKE_TEST=false bash scripts/install.sh
sudo systemctl restart notable-analyzer notable-portal

# When only env templates or deployment profile changed on main:
# Edit /etc/notable-analyzer/* or use profile scripts from the checkout; e.g.:
sudo bash scripts/apply_rtx_pro_6000_blackwell_5analysts_profile.sh        # dry-run
sudo bash scripts/apply_rtx_pro_6000_blackwell_5analysts_profile.sh --execute
sudo systemctl daemon-reload
sudo systemctl restart vllm litellm notable-analyzer notable-portal   # as needed
```

Compare live env to repo templates (secrets redact before sharing):

```bash
env_lines() { grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "$1" | sort; }
diff -u <(env_lines /etc/notable-analyzer/config.env) <(env_lines "$ONPREM_DIR/config.env.example")
diff -u <(env_lines /etc/notable-analyzer/portal.env) <(env_lines "$ONPREM_DIR/config.portal.env.example")
```

## Granite + image-ingest upgrade (existing Mixedbread hosts)

After `git pull` and `install.sh` when application code changed, run the upgrade
orchestrator from the checkout (not from `/opt/notable-analyzer`):

```bash
cd "$ONPREM_DIR"
export BUNDLE="$MONOREPO_ROOT/offline-bundles/image-ingest-YYYYMMDD"   # when bundle was built

sudo bash scripts/upgrade_granite_image_ingest.sh \
  --bundle-dir "$BUNDLE" \
  --config-env /etc/notable-analyzer/config.env \
  --portal-env /etc/notable-analyzer/portal.env \
  --analyzer-venv /opt/notable-analyzer/venv
```

That script runs, in order: optional prerequisite install from the offline
bundle, pgvector migration to 768 (clears chunk rows), Granite env defaults, and
verification. It does **not** rebuild indexes or restart services.

When prerequisites are already installed (as on auroraaihost after manual steps):

```bash
sudo bash scripts/upgrade_granite_image_ingest.sh \
  --skip-prereq-install \
  --config-env /etc/notable-analyzer/config.env \
  --portal-env /etc/notable-analyzer/portal.env
```

Then rebuild KB, case, and closed-ticket indexes and restart analyzer/portal.
See [`../rag/IMAGE_INGEST_PREREQUISITES.md`](../rag/IMAGE_INGEST_PREREQUISITES.md).

Customer default bundle and hardware profile baselines:
[`CUSTOMER_DEFAULT_DEPLOYMENT.md`](CUSTOMER_DEFAULT_DEPLOYMENT.md),
[`deployment_profiles/README.md`](deployment_profiles/README.md).

## Local development vs production host

| | Production host | Local dev (laptop / lab VM) |
| --- | --- | --- |
| Python env | `/opt/notable-analyzer/venv` | Monorepo `<repo-root>/.venv` |
| Run analyzer/portal | `systemd` + install tree | Preview scripts; see [`DEVELOPING.md`](../../../../DEVELOPING.md) |
| Config | `/etc/notable-analyzer/*.env` | Repo `config.portal-preview.env`, env vars |

See [`DEVELOPING.md`](../../../../DEVELOPING.md) for bootstrap; do not copy
`.venv` between Windows and Linux.

## Next

- Path A/B step 2: [`INSTALL.md`](INSTALL.md) — host install after you understand the layout
- Path B step 4: [`CUSTOMER_DEFAULT_DEPLOYMENT.md`](CUSTOMER_DEFAULT_DEPLOYMENT.md) — env mirror checklist
- Upgrades: re-run `install.sh` with `AUTO_START_SERVICES=false` per Update workflow above
- Path order: root [`README.md`](../../../README.md#2-deploy--pick-one-path) section 2

## Related docs

- [`INSTALL.md`](INSTALL.md) — First-time install and installer steps
- [`../../../README.md`](../../../README.md) — Filesystem map and package overview
- [`../analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md) — Portal unit paths and nginx static root under `/opt/notable-analyzer`
