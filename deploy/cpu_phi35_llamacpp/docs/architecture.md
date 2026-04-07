# Architecture Diagram (CPU Phi-3.5 + llama.cpp)

This diagram shows the runtime architecture for the Docker bundle in this directory.

```mermaid
flowchart LR
    subgraph External["External systems"]
        SOC["SOC/SOAR platform"]
        SPL["Splunk ES REST API /services/notable_update"]
        SRC["Model artifact source (target/jump host staging)"]
    end

    subgraph Host["Runtime Host (Linux/WSL + Docker)"]
        subgraph Volumes["Host-mounted volumes"]
            IN["data/incoming"]
            PR["data/processed"]
            Q["data/quarantine"]
            REP["data/reports"]
            AR["data/archive"]
            KB["kb/index (optional)"]
            MOD["models/*.gguf (host-staged)"]
            CFG["config/config.env"]
        end

        subgraph Stack["Docker Compose stack"]
            A["analyzer container - notable-analyzer-service"]
            M["model-serving container - llama.cpp OpenAI API (port 8000)"]
        end
    end

    SOC -->|"exports notable payload; file-drop to host FS"| IN
    SRC -->|"stages GGUF model artifacts"| MOD
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

- GGUF model files are **not** baked into container images.
- GGUF model artifacts are staged on the host (`./models`) and mounted read-only into `model-serving`.
- SOC/SOAR drops inbound files on host filesystem `data/incoming` (then analyzer consumes them).
- Optional writeback calls Splunk ES REST API (`/services/notable_update`).
- Build hosts can build/push images without GPU; runtime hosts execute CPU inference for this stack.
