# CLAUDE.md

## Project purpose

`vegapunk-agents` is a cognitive meta-framework for multi-agent reasoning, inspired by Dr. Vegapunk from One Piece.
It splits reasoning across six biased specialist satellites that share a central memory (Punk Records),
supervised by a human orchestrator (Stella). One spec (`core/`) is implemented by several runtimes (`flavors/`).

**Current phase: Phase 0 — Repo initialization.**

## Hard constraints

### Decoupling rule
The framework (`core/`, `flavors/`, `visualizer/`) must NEVER import, reference, or assume anything from `examples/`.
Examples consume the framework; the framework never depends on examples.

### `core/` is the single source of truth
Flavors implement `core/`; they never redefine roles or protocol. If a flavor needs a behavior change, update `core/` first, then the flavor.

### Canonical naming
Use these exact names everywhere (kebab-case for files):
- Orchestrator: `stella`
- Shared memory: `punk-records`
- Satellites: `punk-01-shaka`, `punk-02-lilith`, `punk-03-edison`, `punk-04-pythagoras`, `punk-05-atlas`, `punk-06-york`

### Language
All code, comments, and docs are in English.

## Working rules

- Work in small, verifiable steps.
- Do not create files outside the current phase's scope.
- Do not add dependencies without stating them explicitly.
- Each flavor folder must be self-contained, with its own README and dependency file (added in its phase).
