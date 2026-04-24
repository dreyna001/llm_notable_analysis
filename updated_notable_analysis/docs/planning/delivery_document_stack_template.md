# Delivery Document Stack Template

## Purpose

Use this template to define the standard document stack for a product that is delivered in layers:

- shared core behavior first
- environment-specific deployment paths later
- customer onboarding as a separate delivery concern

This file is intentionally generic.

It should be usable as:

- a naming standard
- a document-generation template
- an LLM input for producing a full document set with consistent quality

## Intended Use

Use this file when you want an LLM or engineer to generate a complete document stack for a product or capability family.

The output should be:

- planning documents that clarify boundaries before implementation
- technical specs that act as build contracts
- execution prompts that drive bounded implementation
- onboarding documents that capture customer-specific facts without polluting the core product docs
- tracker documents that keep delivery state explicit

## Standard Document Types

This stack uses these document types:

- workflow discovery document
- capability and roadmap document
- architecture document
- technical spec document
- workflow prompt document
- customer onboarding template

## Standard Generation Sequence

Generate documents in this order unless there is a justified exception:

1. `manual_workflow.md`
2. `domain_capability_map.md`
3. `executive_staged_overview.md`
4. `implementation_tracker.md`
5. `shared_core_architecture.md`
6. `shared_core_technical_spec.md`
7. `customer_onboarding_template.md`
8. `shared_core_workflow_prompt.md`
9. `<cloud_state_name>_deployment_architecture.md`
10. `<cloud_state_name>_deployment_technical_spec.md`
11. `<cloud_state_name>_workflow_prompt.md`
12. `<onprem_state_name>_deployment_architecture.md`
13. `<onprem_state_name>_deployment_technical_spec.md`
14. `<onprem_state_name>_workflow_prompt.md`

## Practical Rule

For future projects:

- do not start with deployment-specific implementation
- do not use customer onboarding to define the product
- do not write prompts before the matching technical spec exists
- do not write technical specs before the matching architecture decisions are locked

## One-Line Summary

Standardize delivery around a reusable document stack: discover the workflow, define the capability model, lock the shared core, generate build-ready specs and prompts from that core, and keep customer onboarding as a separate template that captures customer facts without redefining the product.
