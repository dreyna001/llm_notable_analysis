# On-Prem Analyzer — Release + Customer Delivery (GitLab / Bitbucket)

This document describes the **operator workflow** to obtain a vetted release bundle from **GitLab or Bitbucket**, transfer it to a target server (including air-gapped workflows), unpack it, and **start the install** by running `install.sh`.

Scope:
- Starts at the Git hosting portal (GitLab/Bitbucket)
- Ends at: `sudo bash install.sh`
- Does **not** document what `install.sh` does internally (see `INSTALL.md`)

## What is delivered

Deliver artifacts:
- `notable-analyzer-onprem-<version>.tar.gz` (preferred for Linux/RHEL targets)
- `SHA256SUMS` (and optionally `SHA256SUMS.sig` if you sign artifacts)
- Optional (if required by customer governance): SBOM/evidence bundle produced by your internal pipeline

## Choose a release version

Use a version/tag that maps to a specific commit (example pattern: `onprem-vX.Y.Z`).

## Download from GitLab

1. Open the GitLab portal and navigate to the project repo.
2. Go to **Deployments → Releases** (or **Repository → Tags** if you don’t use Releases).
3. Select the desired version/tag.
4. Download:
   - `notable-analyzer-onprem-<version>.tar.gz`
   - `SHA256SUMS` (and signature file if present)

## Download from Bitbucket

1. Open the Bitbucket portal and navigate to the repo.
2. Locate the desired version/tag:
   - **Tags** page (preferred), or
   - A release bundle published under **Downloads** (common pattern), or
   - A CI artifact link surfaced in the build summary (org-dependent).
3. Download:
   - `notable-analyzer-onprem-<version>.tar.gz`
   - `SHA256SUMS` (and signature file if present)

## Verify integrity (recommended before transfer)

On the machine you downloaded the artifacts to:

```bash
sha256sum -c SHA256SUMS
```

If your org signs artifacts, verify the signature using your standard tooling/policy.

## Transfer to the target server

### Connected target (SCP/SFTP allowed)

```bash
scp notable-analyzer-onprem-<version>.tar.gz SHA256SUMS <user>@<target-host>:/tmp/
```

### Air-gapped target (approved media)

1. Copy `notable-analyzer-onprem-<version>.tar.gz` and `SHA256SUMS` to approved media.
2. Transfer media to the enclave per customer policy.
3. Copy artifacts onto the target host (example: `/tmp/`).

## Verify integrity on the target

On the target host:

```bash
cd /tmp
sha256sum -c SHA256SUMS
```

## Unpack and start install

On the target host:

```bash
mkdir -p /opt/notable-analyzer-release
tar -xzf /tmp/notable-analyzer-onprem-<version>.tar.gz -C /opt/notable-analyzer-release
cd /opt/notable-analyzer-release/llm_notable_analysis_onprem
sudo bash install.sh
```

Next: follow `INSTALL.md` (configuration + service start/verification).

