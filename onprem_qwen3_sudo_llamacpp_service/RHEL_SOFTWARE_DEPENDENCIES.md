# RHEL-class host software (`onprem_qwen3_sudo_llamacpp_service`)

Use this checklist for a fresh minimal RHEL/Rocky/Alma host before running `install_llamacpp.sh`.

This package is root-oriented (service account + `/etc` + systemd). All install examples use `sudo`.

## 1) Packages implied by the installer script

The script checks for these commands regardless of skip flags:

- `git`
- `cmake`
- `make`
- `curl`
- `sed`
- `sha256sum` (from `coreutils`)

It also uses root/account/service commands:

- `groupadd`, `useradd`, `getent` (from `shadow-utils`)
- `systemctl` when systemd path is enabled

Typical package set on RHEL:

| Role | Typical RPM packages |
|------|----------------------|
| Shell + core utilities | `bash`, `coreutils` |
| Source sync | `git` |
| Build system | `cmake`, `make` |
| C/C++ toolchain | `gcc`, `gcc-c++` |
| Model/health HTTP calls | `curl`, `ca-certificates` |
| Text processing | `sed` |
| Account management (`useradd`/`groupadd`) | `shadow-utils` |
| systemd management | `systemd` |

Typical one-liner:

```bash
sudo dnf install -y bash coreutils git cmake make gcc gcc-c++ curl ca-certificates sed shadow-utils systemd
```

## 2) Online vs offline dependency behavior

- default installer path: `LLAMA_INSTALL_DEPS=true` (uses `dnf`/`apt-get`)
- offline/airgapped path: set `LLAMA_INSTALL_DEPS=false` and pre-stage RPMs in local media/repo

If running offline, install mirrored RPMs first, then run installer with offline flags.

## 3) CMake and compiler expectations

Pinned `llama.cpp` baseline in this package is `b8457` / commit `149b249`. A current RHEL 8/9 AppStream `cmake` is usually sufficient. If your SOE pins older tooling, provide a compatible toolchain via approved internal channels.

## 4) Runtime libraries

`llama-server` is dynamically linked. If the binary is built elsewhere and copied in, validate on target:

```bash
ldd /usr/local/bin/llama-server
```

Install RPMs for any unresolved `.so` dependencies (`libstdc++`, `libgcc`, `glibc`, `libgomp`, etc., depending on build options).

## 5) Skip-flag caveat

Even with:

- `LLAMA_SKIP_RUNTIME_BUILD=true`
- `LLAMA_SKIP_MODEL_DOWNLOAD=true`

the script still runs command checks for `git`, `cmake`, `make`, `curl`, `sed`, and `sha256sum`. Keep these installed unless you also modify the installer logic.

## 6) Capacity planning (non-RPM requirements)

- Disk:
  - model file is ~2.5 GB (`2497280256` bytes)
  - add headroom for logs and any local build artifacts
- RAM:
  - sufficient for model load + KV cache + concurrent requests
  - tune `LLAMA_CTX_SIZE`, `LLAMA_PARALLEL`, and token limits based on host size

## 7) What this package does not require

- no GPU/CUDA stack in default CPU path
- no Python/Node/container runtime for `install_llamacpp.sh` itself
