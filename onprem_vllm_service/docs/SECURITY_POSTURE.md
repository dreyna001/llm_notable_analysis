# vLLM Security Posture

Security posture for the standalone `onprem_vllm_service` package.

## Baseline model

- Local-only service by default (`--host 127.0.0.1`).
- Dedicated non-login service account (`vllm` user/group).
- Systemd hardening flags enabled in baseline unit.

## Runtime hardening in `vllm.service`

- `NoNewPrivileges=yes`
- `CapabilityBoundingSet=` and `AmbientCapabilities=`
- `ProtectHome=yes`
- `PrivateTmp=yes`
- `UMask=0077`
- Restart policy: `Restart=on-failure`
- Log output to systemd journal only

Note: Some stricter systemd network sandbox flags are intentionally not enforced due to known distributed runtime bootstrap issues for torch/Gloo/NCCL in certain environments.

## `--trust-remote-code` stance

- Disabled by default.
- Should only be enabled when:
  - model requires custom architecture code, and
  - model artifacts are verified from a trusted, controlled import process.

## Artifact and supply-chain expectations

- Prefer pinned `VLLM_PIP_SPEC` values.
- In air-gapped mode, install from approved local wheel artifacts.
- Keep auditable records for:
  - vLLM artifact source
  - installed version
  - checksum/provenance evidence

## Network exposure guidance

- Keep endpoint bound to loopback unless an explicit architecture requires remote access.
- If remote binding is required, add compensating controls:
  - network ACL/firewall restrictions
  - authentication (`--api-key` if your deployment policy supports it)
  - transport encryption and certificate policy

## Operational security checks

- Review `journalctl -u vllm` for repeated startup failures.
- Verify no unexpected unit overrides exist in `/etc/systemd/system/vllm.service.d`.
- Reapply canonical unit using installer when drift is detected.

