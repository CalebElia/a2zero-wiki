# Integration Plans

This directory contains structured JSON integration plans produced by the **Comprehend** pass at the start of each source ingest. Each file is named `<source-uuid>.json` and reflects how the Comprehend LLM mapped that source onto the wiki's existing state.

## What's in a plan

Each plan has five fields:

- **strategies-touched** — which A2Zero strategies the source affects
- **extends** — existing entity pages the source contributes new data to
- **new-entities** — entities the source introduces that warrant new pages
- **retrieve-for-context** — existing entity bodies that get pre-loaded into the LDP chunk extraction prompts as integration context
- **theme-connections** — cross-strategy patterns the source surfaces

## Why they're committed

Plans are part of the audit trail. They document *why* the pipeline made specific integration decisions during each ingest, which helps when reviewing entity merges, debugging false splits, or auditing how a controversial claim was integrated.

## Lifecycle

Plans are overwritten on re-ingest of the same source. Use `git log <plan-path>` to see prior versions.

See `docs/architecture/comprehend-plan-write.md` for the full architecture.
