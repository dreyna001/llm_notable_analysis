#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

test -f .env || cp .env.example .env
test -f config/config.env || cp config/config.env.example config/config.env

UIDX="$(id -u)"
GIDX="$(id -g)"
sed -i "s/^CONTAINER_UID=.*/CONTAINER_UID=$UIDX/" .env
sed -i "s/^CONTAINER_GID=.*/CONTAINER_GID=$GIDX/" .env

# Keep analyzer model id aligned with the GGUF filename Compose mounts for llama-server
MODEL="$(
  grep '^LLM_MODEL_FILENAME=' .env | head -1 | sed 's/^LLM_MODEL_FILENAME=//' | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
)"
if [[ -z "$MODEL" ]]; then
  MODEL="Phi-3.5-mini-instruct-Q4_K_M.gguf"
  sed -i "s/^LLM_MODEL_FILENAME=.*/LLM_MODEL_FILENAME=$MODEL/" .env
fi
if grep -q '^LLM_MODEL_NAME=' config/config.env; then
  sed -i "s/^LLM_MODEL_NAME=.*/LLM_MODEL_NAME=$MODEL/" config/config.env
fi

mkdir -p data/incoming data/processed data/quarantine data/reports data/archive

download_gguf() {
  local name="$1"
  local url=""
  case "$name" in
    Phi-3.5-mini-instruct-Q4_K_M.gguf)
      echo "Downloading Phi-3.5-mini-instruct Q4_K_M (~2.2 GiB) to models/$name ..."
      url="https://huggingface.co/bartowski/Phi-3.5-mini-instruct-GGUF/resolve/main/Phi-3.5-mini-instruct-Q4_K_M.gguf"
      ;;
    *)
      echo "No bundled download URL for models/$name"
      echo "Place that file under models/ (or set LLM_MODEL_FILENAME=Phi-3.5-mini-instruct-Q4_K_M.gguf in .env) and re-run."
      return 1
      ;;
  esac
  curl -fSL -L -C - --progress-bar -o "models/$name" "$url"
}

if [[ ! -f "models/$MODEL" ]]; then
  download_gguf "$MODEL"
fi

docker compose pull model-serving
docker compose build analyzer
docker compose up -d --force-recreate

echo "Waiting for healthchecks (up to 180s)..."
for _ in $(seq 1 36); do
  ms="$(docker compose ps model-serving --format '{{.Health}}' 2>/dev/null || true)"
  an="$(docker compose ps analyzer --format '{{.Health}}' 2>/dev/null || true)"
  if [[ "$ms" == "healthy" ]] && [[ "$an" == "healthy" ]]; then
    break
  fi
  sleep 5
done

docker compose ps
echo "--- model-serving (last 40 lines) ---"
docker compose logs model-serving --tail 40
echo "--- analyzer (last 40 lines) ---"
docker compose logs analyzer --tail 40
