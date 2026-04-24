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

## One-Line Summary

Standardize delivery around a reusable document stack that locks the shared core before deployment-specific implementation and keeps customer onboarding separate from core product definition.
