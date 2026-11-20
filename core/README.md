# core/

The single source of truth of the framework: role definitions, the Punk Records schema, the inter-satellite protocol, and activation modes.

- **Canonical spec:** [`architecture.md`](architecture.md) — components, communication rule, activation modes, mission lifecycle, human-in-the-loop rules, flavor compliance checklist.
- [`punk-records.md`](punk-records.md) — Punk Records format, append-only rule, permissions, Markdown projection.
- [`schemas/`](schemas/) — `punk-records.schema.json`, `event.schema.json` and `examples/` (JSON Schema draft 2020-12).
- [`prompts/`](prompts/) — canonical system prompts for `stella` and the six satellites.
- [`tools/`](tools/) — `validate_core.py`, the cross-consistency validator (dev/CI only).
- **Filled in:** Phase 1 — Core spec & prompts (1a: protocol and schemas, 1b: prompts, 1c: validator).

## Validating the core

```
pip install -r core/tools/requirements.txt && python core/tools/validate_core.py
```

The validator needs `jsonschema`, `pyyaml` and `rfc3339-validator`. They are dev/CI dependencies only; the specification itself has none. CI runs the validator on every change to `core/`.
- Flavors implement this folder; they never redefine roles or protocol. Changes land here first.
- **Must stay use-case agnostic:** nothing here may reference or assume anything from `examples/`.
