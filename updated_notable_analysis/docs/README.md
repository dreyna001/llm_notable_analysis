# Docs Layout

## Purpose

This `docs/` tree is organized by document purpose so the structure stays self-documenting and easier to maintain as `updated_notable_analysis` grows from planning into implementation.

## Folders

### `delivery_package/`

Customer-facing handoff material for a customer that has already said yes and is preparing to deploy into AWS or on-prem.

This folder exists in the standard stack, even if this project path does not use it immediately.

### `planning/`

Internal planning, sequencing, and execution-tracking docs.

Includes:

- `domain_capability_map.md`
- `implementation_tracker.md`
- `executive_staged_overview.md`
- `delivery_document_stack_template.md`

### `architecture/`

Planning and runtime-shape documents for each application state.

Includes:

- `core_deployment_architecture.md`
- `aws_deployment_architecture.md`
- `onprem_deployment_architecture.md`

### `technical_specs/`

Build-ready implementation contracts.

Includes:

- `core_technical_spec.md`
- later `current_product_technical_spec.md`
- `aws_deployment_technical_spec.md`
- `onprem_deployment_technical_spec.md`

### `prompts/`

Implementation kickoff prompts tied to specific technical-spec slices.

This folder exists in the standard stack, even if prompt files begin as placeholders.

### `internal/`

Internal-only working templates and reminders.

This folder holds reusable templates and lightweight working notes that should not redefine product contracts.

## Navigation Rule

If you are looking for:

- product capability shape and sequencing: start in `planning/`
- shared-core and deployment boundary design: start in `architecture/`
- exact implementation contracts for the active coding slice: start in `technical_specs/`

## Current State

At this stage, the `updated_notable_analysis/docs/` stack is still planning-first, but it now also documents additive implemented slices in `core/`, `aws/`, and `onprem/`.

The current active documents are:

- `planning/domain_capability_map.md`
- `planning/implementation_tracker.md`
- `architecture/core_deployment_architecture.md`
- `architecture/aws_deployment_architecture.md`
- `architecture/onprem_deployment_architecture.md`
- `technical_specs/core_technical_spec.md`
- `technical_specs/aws_deployment_technical_spec.md`
- `technical_specs/onprem_deployment_technical_spec.md`

Additional folders and placeholder files exist so the new path matches the standard document-stack layout used across projects.

## One-Line Summary

This `docs/` tree is organized by purpose: customer delivery, planning, architecture, technical specs, prompts, and internal working material for the new `updated_notable_analysis` path.
