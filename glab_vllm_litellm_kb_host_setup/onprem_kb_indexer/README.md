# GLAB KB Indexer

Host-native rebuild job for local retrieval artifacts.

This package rebuilds:

- `kb.sqlite3`
- `kb.faiss`
- `chunks.jsonl`
- `ingest_report.json`

It uses `onprem_rag_notable_analysis.future.corpus_ingest` and should run as a `systemd`
`oneshot` service plus an optional `timer`.

## Important Boundary

Do not create `sqlite.service` or `faiss.service`.

`SQLite` and `FAISS` are artifacts on disk. The running unit here is only the
rebuild job that refreshes those artifacts.

## Intended Host Paths

- install dir: `/opt/notable-kb`
- config path: `/etc/notable-kb/config.env`
- source docs: `/var/lib/notable-kb/source`
- live index dir: `/var/lib/notable-kb/index`
- local embedding model: `/opt/models/embeddings/all-MiniLM-L6-v2`

## Files In This Package

- `config/config.env.example`
  - source/index/model path contract
- `bin/run_kb_rebuild.sh`
  - validated wrapper around `python -m onprem_rag_notable_analysis.future.corpus_ingest`
- `systemd/kb-rebuild.service`
  - `oneshot` rebuild job
- `systemd/kb-rebuild.timer`
  - optional scheduled rebuild trigger
