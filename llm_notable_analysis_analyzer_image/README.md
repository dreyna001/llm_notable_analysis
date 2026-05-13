# Shared analyzer image build target

Status: legacy/reference Docker build path, not production-equivalent to the
current systemd deployment. The default on-prem refactor path is
`llm_notable_analysis_onprem_systemd/` with host `systemd`, `LiteLLM`, `vLLM`,
PostgreSQL/pgvector RAG, and `gemma-4-31B-it`. Do not use this image path for
the new Postgres RAG/LiteLLM runtime contract until it is refreshed in a
separate Docker-specific change.

This directory defines the shared Docker build target for the
`notable-analyzer-service` image.

- Dockerfile: `Dockerfile.analyzer`
- Python dependencies: `requirements.analyzer-docker.txt`

Current source inputs:

- `llm_notable_analysis_analyzer_image/onprem_service`
- `llm_notable_analysis_analyzer_image/onprem_rag_notable_analysis`
- `llm_notable_analysis_analyzer_image/tests/service_tests`

Both CPU and GPU Docker deployment bundles should build/publish the analyzer
image through this shared target to keep image contents consistent.

`llm_notable_analysis_onprem_systemd` remains the dedicated non-Docker
deployment path (systemd + host venv). It is intentionally separate from this
Docker-oriented analyzer build target.
