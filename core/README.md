# core/

The single source of truth of the framework: role definitions, the Punk Records schema, the inter-satellite protocol, and activation modes.

- **Canonical spec:** [`architecture.md`](architecture.md) — components, communication rule, activation modes, mission lifecycle, human-in-the-loop rules, flavor compliance checklist.
- [`punk-records.md`](punk-records.md) — Punk Records format, append-only rule, permissions, Markdown projection.
- [`schemas/`](schemas/) — `punk-records.schema.json`, `event.schema.json` and `examples/` (JSON Schema draft 2020-12).
- **Still to come:** canonical prompts in `prompts/` (Phase 1b).
- **Filled in:** Phase 1 — Core spec & prompts (1a: protocol and schemas).
- Flavors implement this folder; they never redefine roles or protocol. Changes land here first.
- **Must stay use-case agnostic:** nothing here may reference or assume anything from `examples/`.
