# LLM Inference Operations

This guide helps customers tune the local LLM call path without changing code.
It covers the LiteLLM endpoint, model identifier, structured output mode, token
limits, and timeout behavior.

## What This Controls

The analyzer calls an OpenAI-compatible chat completion endpoint. The default
deployment routes through LiteLLM on loopback, with vLLM behind it. The analyzer
does not own model serving internals; it owns the client contract and prompt
parsing behavior.

## Recommended Starting Posture

- Keep `LLM_API_URL=http://127.0.0.1:4000/v1/chat/completions`.
- Keep `LLM_MODEL_NAME=gemma-4-31B-it` unless the serving stack advertises a
  different model id.
- Use `LLM_STRUCTURED_OUTPUT_MODE=prompt_json` first.
- Increase `LLM_TIMEOUT` only after measuring model startup and inference
  latency. Default is `240` to cover spl_readonly plus query interpretation.
  Core-only deployments may use `120`.
- Keep LiteLLM/vLLM bound to loopback unless a documented authenticated edge
  listener is approved.

## Customer Decisions

### Which endpoint should the analyzer call?

**Settings:** `LLM_API_URL`, `LLM_API_TOKEN`

- Default to loopback LiteLLM for the production systemd chain.
- Use a token only when the local gateway requires one.
- Do not put long-lived tokens in committed files.
- If using a different OpenAI-compatible gateway, verify `/v1/models` and chat
  completion response shape before changing production config.

### How do I use the LiteLLM Admin UI?

The packaged `litellm[proxy]` install includes LiteLLM's web Admin UI at
`/ui`. The analyzer does **not** require it; use it only when operators want a
browser-based view of the proxy (Swagger link, optional key/spend features).

**Default install posture:** loopback-only proxy with **no committed master key**.
The API works without auth on `127.0.0.1:4000`, but Admin UI login fails until
you set a master key on the host. Do not commit the key to git.

#### Access from a headless server (SSH tunnel)

LiteLLM binds to `127.0.0.1:4000`, so open the UI from your **local desktop
browser** through SSH port forwarding:

```powershell
# From your desktop (PowerShell or Windows Terminal), not inside the remote shell
ssh -L 4000:127.0.0.1:4000 YOUR_SSH_USER@YOUR_SERVER
```

Keep that session open, then browse to `http://127.0.0.1:4000/ui` on your
desktop. If local port `4000` is taken, use `-L 14000:127.0.0.1:4000` and open
`http://127.0.0.1:14000/ui` instead.

Confirm LiteLLM is up on the server first:

```bash
# Before a master key is set (default install)
curl -sS http://127.0.0.1:4000/v1/models

# After LITELLM_MASTER_KEY is set (401 without the header)
curl -sS http://127.0.0.1:4000/v1/models \
  -H "Authorization: Bearer sk-your-chosen-secret-here"
```

#### Set a master key (required for Admin UI login)

Choose a secret that starts with `sk-`. Example placeholder only — replace with
your own value:

```bash
sudo mkdir -p /etc/systemd/system/litellm.service.d

sudo tee /etc/systemd/system/litellm.service.d/master-key.conf <<'EOF'
[Service]
Environment="LITELLM_MASTER_KEY=sk-your-chosen-secret-here"
EOF

sudo systemctl daemon-reload
sudo systemctl restart litellm
sudo systemctl status litellm --no-pager
```

Alternative: add `general_settings.master_key` to `/etc/litellm/config.yaml`
(see [LiteLLM virtual keys](https://docs.litellm.ai/docs/proxy/virtual_keys)).
Use one method, not two different keys.

#### Log in

| Field | Value |
|-------|-------|
| Username | `admin` |
| Password | The exact `LITELLM_MASTER_KEY` value (`sk-...`) |

If you see `Master Key not set for Proxy`, the master key is still missing or
LiteLLM was not restarted after setting it.

#### After a master key is enabled

Setting `LITELLM_MASTER_KEY` protects the LiteLLM API, not just the UI.

1. **Analyzer:** set the same value in `/etc/notable-analyzer/config.env` as
   `LLM_API_TOKEN` and restart `notable-analyzer`. Without this, analysis calls
   return `401 Authentication Error, No api key passed in.`
2. **Operator curl checks:** pass `Authorization: Bearer <master-key>` on
   `/v1/models` and chat completion requests (see example above).
3. **Smoke test:** `scripts/smoke_service_chain.sh` reads `LLM_API_TOKEN` from
   config when present.

#### Optional: require the same key for analyzer API calls

Once a master key exists, treat `LLM_API_TOKEN` as **required** for the
production analyzer path (not optional). Set the same value in
`/etc/notable-analyzer/config.env`:

```bash
LLM_API_TOKEN=sk-your-chosen-secret-here
```

Then restart the analyzer:

```bash
sudo systemctl restart notable-analyzer
```

#### Full Admin UI login requires PostgreSQL

Admin UI **login** (not just loading `/ui`) requires LiteLLM to connect to
**PostgreSQL** via `DATABASE_URL`. SQLite is not supported for proxy user
management.

If login shows `Authentication Error, Not connected to DB!`, the master key is
set but LiteLLM has no database. The default notable analysis install does not
configure a LiteLLM database. Postgres in this stack (when RAG is enabled) is
for RAG, not for LiteLLM.

**Operator choices:**

| Goal | Action |
|------|--------|
| Run analysis only (no Admin UI) | Do not set a master key; leave loopback API open and skip `/ui` |
| Run analysis with master-key auth | Keep `LITELLM_MASTER_KEY`; set matching `LLM_API_TOKEN`; skip `/ui` or use Swagger at `/` with Bearer auth |
| Use Admin UI | Add `DATABASE_URL=postgresql://...` for a dedicated LiteLLM database, restart `litellm`, then log in as `admin` with the master key |

Example local Postgres setup (replace the generated password with your local
secret-management process if required):

First confirm the host has a local PostgreSQL service:

```bash
getent passwd postgres
psql --version
```

If `getent passwd postgres` returns nothing, install and initialize PostgreSQL
for the host before creating the LiteLLM database. On RHEL-family hosts:

```bash
sudo dnf install -y postgresql-server postgresql-contrib
sudo postgresql-setup --initdb
sudo systemctl enable --now postgresql
```

On Debian/Ubuntu hosts:

```bash
sudo apt-get update
sudo apt-get install -y postgresql postgresql-contrib
sudo systemctl enable --now postgresql
```

If the host already uses Postgres for RAG, do **not** reinitialize Postgres.
Reuse the running Postgres service and create only the separate LiteLLM role and
database below. This does not reuse or modify the RAG defaults
(`notable_analyzer`, `notable_rag`, or the `notable_rag` schema/tables).

Then create the LiteLLM role and database:

```bash
LITELLM_DB_PASSWORD="$(openssl rand -hex 32)"
printf 'LiteLLM DB password: %s\n' "$LITELLM_DB_PASSWORD"

sudo -u postgres psql -v ON_ERROR_STOP=1 \
  -v litellm_password="$LITELLM_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE litellm LOGIN PASSWORD %L', :'litellm_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'litellm')\gexec

SELECT format('ALTER ROLE litellm WITH PASSWORD %L', :'litellm_password')
WHERE EXISTS (SELECT FROM pg_roles WHERE rolname = 'litellm')\gexec

SELECT 'CREATE DATABASE litellm OWNER litellm'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'litellm')\gexec
SQL
```

Then add the database URL to the LiteLLM systemd drop-in:

```bash
sudo tee /etc/systemd/system/litellm.service.d/database.conf <<'EOF'
[Service]
Environment="DATABASE_URL=postgresql://litellm:REPLACE_WITH_DB_PASSWORD@127.0.0.1:5432/litellm"
EOF

sudo sed -i "s|REPLACE_WITH_DB_PASSWORD|$LITELLM_DB_PASSWORD|g" \
  /etc/systemd/system/litellm.service.d/database.conf
sudo chmod 600 /etc/systemd/system/litellm.service.d/database.conf
sudo systemctl daemon-reload
sudo systemctl restart litellm
```

When `DATABASE_URL` is set, LiteLLM uses Prisma for proxy database access. If
startup fails with `ModuleNotFoundError: No module named 'prisma'`, install and
generate the Prisma client in the LiteLLM venv. On Debian/Ubuntu, install Node
tooling first if Prisma cannot bootstrap its CLI:

```bash
sudo apt-get install -y nodejs npm
sudo /opt/litellm/venv/bin/pip install prisma

SCHEMA_PATH="$(
  /opt/litellm/venv/bin/python - <<'PY'
from pathlib import Path
import litellm

print(Path(litellm.__file__).resolve().parent / "proxy" / "schema.prisma")
PY
)"

sudo install -d -o litellm -g litellm -m 0750 /opt/litellm/.cache /opt/litellm/.npm
sudo chown -R litellm:litellm /opt/litellm/venv /opt/litellm/.cache /opt/litellm/.npm

sudo -u litellm env \
  HOME=/opt/litellm \
  XDG_CACHE_HOME=/opt/litellm/.cache \
  npm_config_cache=/opt/litellm/.npm \
  PATH="/opt/litellm/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  SCHEMA_PATH="$SCHEMA_PATH" \
  bash -lc 'cd /opt/litellm && /opt/litellm/venv/bin/python -m prisma generate --schema "$SCHEMA_PATH"'

sudo -u litellm env \
  HOME=/opt/litellm \
  XDG_CACHE_HOME=/opt/litellm/.cache \
  npm_config_cache=/opt/litellm/.npm \
  PATH="/opt/litellm/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  DATABASE_URL="postgresql://litellm:REPLACE_WITH_DB_PASSWORD@127.0.0.1:5432/litellm" \
  SCHEMA_PATH="$SCHEMA_PATH" \
  bash -lc 'cd /opt/litellm && /opt/litellm/venv/bin/python -m prisma db push --schema "$SCHEMA_PATH"'

sudo systemctl restart litellm
```

Replace `REPLACE_WITH_DB_PASSWORD` with the same LiteLLM database password used
in `/etc/systemd/system/litellm.service.d/database.conf`. If UI login fails with
`The table public.LiteLLM_UserTable does not exist`, rerun the `prisma db push`
command above and restart `litellm`.

If Prisma generate fails with `AssertionError: Target \`bin\` directory does not
exist`, clear any partial Prisma Python cache and rerun the generate command
above:

```bash
sudo -u litellm env \
  HOME=/opt/litellm \
  XDG_CACHE_HOME=/opt/litellm/.cache \
  bash -lc 'cd /opt/litellm && /opt/litellm/venv/bin/python -m prisma_cleanup'
```

LiteLLM runs schema migration on startup when `DATABASE_URL` is set. Check
startup and login failures with:

```bash
sudo journalctl -u litellm -n 200 --no-pager
```

Key management, spend tracking, and user administration also depend on this
database. Without it, use loopback API checks instead of the UI:

```bash
curl -sS http://127.0.0.1:4000/v1/models \
  -H "Authorization: Bearer sk-your-chosen-secret-here"
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/metrics
```

#### Roll back master-key auth (restore open loopback API)

If you enabled a master key only to try the UI and want the default open
loopback posture back:

```bash
sudo rm -f /etc/systemd/system/litellm.service.d/master-key.conf
sudo systemctl daemon-reload
sudo systemctl restart litellm
```

Clear `LLM_API_TOKEN` in `/etc/notable-analyzer/config.env` if you set it, then
restart `notable-analyzer`.

### Which model name should be sent?

**Setting:** `LLM_MODEL_NAME`

- The value must match the model id advertised by the gateway.
- Keep docs, service units, LiteLLM config, and `config.env` aligned when
  changing model names.
- Treat model swaps as validation events: run representative notables and check
  parse/repair rates.

### Prompt JSON or tool-call output?

**Setting:** `LLM_STRUCTURED_OUTPUT_MODE`

- `prompt_json` is the conservative default: prompt, parse, validate, repair.
- `tool_call` asks the OpenAI-compatible server for function/tool-call shaped
  output and falls back to prompt-json behavior if parsing fails.
- Use `tool_call` only when vLLM/model parser/template settings are confirmed
  for the selected model.

### How large and slow may responses be?

**Settings:** `LLM_MAX_TOKENS`, `LLM_TIMEOUT`

- Keep token limits large enough for the structured report but low enough to
  avoid runaway outputs.
- Increase timeout only when the model needs it under normal load.
- Revisit timeout when enabling RAG, SPL generation, or concurrent processing.

### What local inference telemetry is available?

vLLM exposes a local Prometheus-format metrics endpoint on the loopback vLLM
listener:

```bash
curl -sS http://127.0.0.1:8000/metrics
```

This endpoint is useful for checking model-server behavior such as request
latency, token throughput, cache behavior, and queueing. The packaged
deployment does not scrape, persist, or export these metrics by default;
operators should wire an approved Prometheus/OpenTelemetry path if they need
long-term metrics retention.

### Which vLLM endpoints are operator-facing?

The analyzer should call LiteLLM, not vLLM directly. Keep application traffic on:

```bash
http://127.0.0.1:4000/v1/chat/completions
```

Operators may use these loopback vLLM endpoints for validation and debugging:

```bash
# Readiness
curl -sS http://127.0.0.1:8000/health

# Prometheus-format model-server metrics
curl -sS http://127.0.0.1:8000/metrics

# Direct vLLM model advertisement
curl -sS http://127.0.0.1:8000/v1/models

# Prompt sizing/debugging
curl -sS http://127.0.0.1:8000/tokenize \
  -H 'Content-Type: application/json' \
  -d '{"model":"gemma-4-31B-it","prompt":"test prompt"}'
```

The vLLM OpenAI-compatible server may also expose direct completion endpoints
such as `/v1/chat/completions` and `/v1/completions`, plus model-dependent
surfaces such as `/v1/embeddings`. Those are not the supported analyzer
integration path in this deployment; use them only for isolated operator tests
unless the LiteLLM routing contract is intentionally changed.

### Should freeform mode be used?

The default analyzer is the structured report path. A separate freeform service
entrypoint exists for lab or fallback use when operators want paragraph output
instead of the structured schema.

- Unit: `notable-analyzer-freeform.service`
- Entrypoint: `python -m llm_notable_analysis_onprem_systemd.onprem_service.freeform_main`
- Output suffix: `*_freeform.md`

Do not run the structured analyzer and freeform analyzer against the same
`INCOMING_DIR` at the same time. Treat freeform as an alternate operating mode,
not a per-file toggle.

## Config Quick Reference

| Area | Primary variables |
|------|-------------------|
| Endpoint | `LLM_API_URL`, `LLM_API_TOKEN` |
| Model | `LLM_MODEL_NAME` |
| Output contract | `LLM_STRUCTURED_OUTPUT_MODE` |
| Bounds | `LLM_MAX_TOKENS`, `LLM_TIMEOUT` |
| LiteLLM Admin UI (optional) | `LITELLM_MASTER_KEY` in `/etc/systemd/system/litellm.service.d/` or `general_settings.master_key` in `/etc/litellm/config.yaml`; browse via SSH tunnel to `http://127.0.0.1:4000/ui` |
| vLLM operator checks | `/health`, `/metrics`, `/v1/models`, `/tokenize` on `127.0.0.1:8000` |
| Alternate report mode | `notable-analyzer-freeform.service` systemd unit |

## Validation And Rollout

1. Confirm the endpoint responds locally:
   `curl -sS http://127.0.0.1:4000/v1/models`.
2. Confirm vLLM is healthy:
   `curl -sS http://127.0.0.1:8000/health`.
3. Optionally confirm local vLLM metrics are exposed:
   `curl -sS http://127.0.0.1:8000/metrics`.
4. Run the service-chain smoke test after services are started:
   `sudo bash scripts/smoke_service_chain.sh --config-env /etc/notable-analyzer/config.env`.
5. Before raising analyzer concurrency or vLLM batch limits, run an inference
   serving benchmark:
   [`LLM_INFERENCE_BENCHMARKING.md`](LLM_INFERENCE_BENCHMARKING.md).
6. Process representative JSON and text notables.
7. Review parse/repair metadata, report completeness, and latency.
8. Change one inference setting at a time between validation runs.

## Related Docs

- [`LLM_INFERENCE_BENCHMARKING.md`](LLM_INFERENCE_BENCHMARKING.md)
- [`INSTALL.md`](INSTALL.md)
- [`OFFLINE_PRESTAGE_GUIDE.md`](OFFLINE_PRESTAGE_GUIDE.md)
- [`RAG_OPERATIONS.md`](RAG_OPERATIONS.md)

