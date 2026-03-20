# Air-Gapped Distribution (Build Side)

This guide covers how to produce a transportable SDK bundle outside the enclave.

## Inputs

- Clean build host with Python 3.12.
- Source checkout of `onprem-llm-sdk`.
- Approval to transfer release artifacts into enclave.

## Build command

```bash
bash scripts/build_offline_bundle.sh
```

## Output artifact

`bundle/onprem_llm_sdk_bundle_<version>.tar.gz` containing:

- `wheels/` (SDK + dependencies)
- `requirements-lock.txt`
- `SHA256SUMS`
- `VERSION`
- `INSTALL.md`

## Required controls before transfer

1. Verify checksum manifest exists.
2. Archive build logs with package versions.
3. Attach release notes (`CHANGELOG.md`).
4. Transfer via approved offline process.

## Transfer guidance

- Keep artifact immutable between export and import.
- Record who exported/imported and timestamps.
- Re-validate `SHA256SUMS` after import on enclave side.

