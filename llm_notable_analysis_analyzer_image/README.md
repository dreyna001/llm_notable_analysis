# Shared analyzer image build target

This directory defines the shared Docker build target for the
`notable-analyzer-service` image.

- Dockerfile: `Dockerfile.analyzer`
- Python dependencies: `requirements.analyzer-docker.txt`

Current source inputs:

- `llm_notable_analysis_analyzer_image/onprem_service`
- `llm_notable_analysis_analyzer_image/onprem_rag`
- `llm_notable_analysis_analyzer_image/tests/service_tests`

Both CPU and GPU Docker deployment bundles should build/publish the analyzer
image through this shared target to keep image contents consistent.

`llm_notable_analysis_onprem_systemd` remains the dedicated non-Docker
deployment path (systemd + host venv). It is intentionally separate from this
Docker-oriented analyzer build target.
