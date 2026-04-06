# Architecture Diagram (GPU vLLM + gpt-oss-120b)

This diagram shows the runtime architecture for the Docker bundle in this directory.

```mermaid
flowchart LR
    subgraph External["External systems"]
        SOC["SOC/SOAR platform"]
        SPL["Splunk ES REST API /services/notable_update"]
        SRC["Model artifact source (target/jump host staging)"]
    end

    subgraph Host["Runtime Host (Linux + Docker + NVIDIA runtime)"]
        subgraph Volumes["Host-mounted volumes"]
            IN["data/incoming"]
            PR["data/processed"]
            Q["data/quarantine"]
            REP["data/reports"]
            AR["data/archive"]
            KB["kb/index (optional)"]
            MOD["models/gpt-oss-120b (host-staged)"]
            CFG["config/config.env"]
        end

        subgraph Stack["Docker Compose stack"]
            A["analyzer container - notable-analyzer-service"]
            M["model-serving container - vLLM OpenAI API (port 8000)"]
        end
    end

    SOC -->|"exports notable payload; file-drop to host FS"| IN
    SRC -->|"stages model artifacts"| MOD
    IN --> A
    A --> PR
    A --> Q
    A --> REP
    A --> AR
    KB -. optional RAG .-> A
    CFG --> A
    A <-->|"HTTP /v1/chat/completions request + response"| M
    MOD -->|"read-only bind mount; container reads /models"| M
    A -. optional REST writeback .-> SPL
    SPL <-->|"optional notable/case lifecycle"| SOC
```

## Notes

- Model artifacts are **not** baked into container images.
- Model artifacts are staged on the host (`./models`) and mounted read-only into `model-serving`.
- SOC/SOAR drops inbound files on host filesystem `data/incoming` (then analyzer consumes them).
- Optional writeback calls Splunk ES REST API (`/services/notable_update`).
- Build hosts can produce/push images without a GPU; GPU is required on runtime hosts.
