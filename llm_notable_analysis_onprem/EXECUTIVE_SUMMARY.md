# On-Prem / Air-Gapped Notable Analyzer Service Executive Summary

## What this is
An **on-prem, air-gapped** service that turns security alerts (“notables”) into **clear, consistent investigation analysis notes** that analysts can act on immediately.

## Why it matters
- **Faster triage**: Reduces time spent analyzing alerts, mapping TTPs, and investigating blast radius.
- **More consistent outcomes**: Standardizes the quality and format of analysis across shifts/teams.
- **Works in restricted environments**: Designed for customers who **cannot send data to the cloud**.

## What it produces
- A **human-readable report** per notable (for analyst review and case tracking).
- An optional **update back to Splunk** (attach the report to the original notable as a comment), if enabled.

## How it fits operationally
- **Recommended workflow**: Your SOAR platform selects/pulls notables and securely delivers them to the service.
- The service runs **on a single host** inside the customer enclave and keeps data local.

## Security & governance posture (high level)
- **No internet dependency** during runtime (air-gapped operation).
- Supports standard enterprise controls: least-privilege access, internal certificate authorities, and auditable logs.

## What you provision (at a glance)
- One host (VM or physical) sized for the expected alert volume and the chosen local inference stack
- Storage for short-term inputs, outputs, and retention/archiving


