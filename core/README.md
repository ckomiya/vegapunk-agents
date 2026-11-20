# core/

The single source of truth of the framework: role definitions, the Punk Records schema, the inter-satellite protocol, and activation modes.

- **Will contain:** the specification (Stella, Punk Records, 6 satellites, Light/Standard/Full modes) and canonical prompts in `prompts/`.
- **Filled in:** Phase 1 — Core spec & prompts.
- Flavors implement this folder; they never redefine roles or protocol. Changes land here first.
- **Must stay use-case agnostic:** nothing here may reference or assume anything from `examples/`.
