# vLLM Security Posture

Security baseline for the standalone `onprem_vllm_service` package.

## Default security boundaries

- Service listens on loopback by default (`127.0.0.1`).
- Runtime uses a dedicated non-login account (`vllm`).
- Baseline systemd hardening is enabled (`NoNewPrivileges`, `ProtectHome`, `PrivateTmp`, `UMask=0077`).
- Logs are written to systemd journal.

## `--trust-remote-code` policy

Default is disabled and should remain disabled unless both are true:

1. The selected model requires custom architecture code.
2. Model artifacts were imported through a trusted, verified process.

## Package artifact controls

- Prefer pinned installs via `VLLM_PIP_SPEC`.
- In air-gapped deployments, install from approved local wheel artifacts.
- Record package version, artifact source, and checksum/provenance evidence.

## If you expose beyond loopback

Loopback-only is preferred. If remote access is required, add compensating controls:

- network ACL/firewall restrictions
- authentication policy (for example API key usage if allowed by your deployment policy)
- TLS and certificate lifecycle controls

## Security drift checks

```bash
sudo systemctl cat vllm
sudo ls /etc/systemd/system/vllm.service.d
sudo journalctl -u vllm -n 200 --no-pager
```

If drift is found, re-apply the canonical unit:

```bash
cd /path/to/onprem_vllm_service
sudo VLLM_RESET_OVERRIDES=true bash install_vllm.sh
```

