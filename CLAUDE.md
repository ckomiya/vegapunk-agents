# CLAUDE.md

## Project purpose

`vegapunk-agents` is a **Multi-Agent Architecture Pattern (and Conceptual Framework)**, inspired by Dr. Vegapunk from One Piece.
It splits reasoning across six biased specialist satellites that share a central memory (Punk Records),
supervised by a human orchestrator (Stella). One spec (`core/`) is implemented by several runtimes (`flavors/`).

**Current phase: Phase 2 — Claude Code native flavor (`flavors/01-claude-code/`), not started.**

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

### HARD RULE — Attribution
Never remove or alter `LICENSE`, `NOTICE`, the authorship in `CITATION.cff`, or the README's final "Authorship, Citation & Inspiration Note" section. That section must always remain the LAST section of `README.md`.
New source files start with `SPDX-License-Identifier: Apache-2.0` and `Copyright 2026 Christian Gonzales Komiya`, in the appropriate comment syntax. Markdown files with YAML front matter carry the header as YAML comments inside the front matter, so the file starts with `---` on line 1. Other Markdown files use an HTML comment.

### HARD RULE — No official One Piece assets
No official One Piece artwork, logos, or copyrighted assets anywhere in the repo.

### Language
All code, comments, and docs are in English.

## Working rules

- Work in small, verifiable steps.
- Do not create files outside the current phase's scope.
- Do not add dependencies without stating them explicitly.
- Each flavor folder must be self-contained, with its own README and dependency file (added in its phase).
- Commits carry no AI co-author trailers; the author is the sole author.
- Run `python core/tools/validate_core.py` after any change in `core/`. Its dev/CI-only dependencies are listed in `core/tools/requirements.txt` (`jsonschema`, `pyyaml`, `rfc3339-validator`).
- Versioning: when bumping versions, update `version` in `CITATION.cff` and the README BibTeX block together. Each GitHub release gets a version DOI from Zenodo automatically; `CITATION.cff` and the README keep the concept DOI. Never mark releases as pre-release (Zenodo ignores them).
- Run all validations BEFORE committing; if any step fails, stop and report — never chain commit/push after an unverified step.
- Line endings: the repo uses LF (enforced by `.gitattributes`); the author works on Windows, so never commit CRLF.
