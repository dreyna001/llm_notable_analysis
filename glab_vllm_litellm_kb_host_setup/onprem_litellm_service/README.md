# GLAB LiteLLM Service

Host-native LiteLLM proxy package for GLAB.

This service is the user-facing entrypoint for the three users and should proxy
requests to the local `vLLM` service on the same host.

## Intended Runtime Contract

- bind host: `127.0.0.1`
- bind port: `4000`
- client path: `POST /v1/chat/completions`
- upstream `vLLM` base URL: `http://127.0.0.1:8000/v1`
- user-facing model alias: `gpt-oss-120b`

## Expected Host Paths

- install dir: `/opt/litellm`
- config path: `/etc/litellm/config.yaml`
- service name: `litellm`

## Package Install

Verified LiteLLM proxy install command:

```bash
pip install 'litellm[proxy]'
```

## Files In This Package

- `config/config.yaml.example`
  - minimal proxy configuration pointing to local `vLLM`
- `systemd/litellm.service`
  - host-native `systemd` unit template

## Important Constraint

Current LiteLLM docs indicate that full virtual-key and per-user key-management
flows require a database backend. Until GLAB chooses and pins that backend
explicitly, do not claim that three distinct LiteLLM-issued user keys are fully
implemented. The safe default is one shared proxy master/admin key plus host or
network-level access controls.
