<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright 2026 Christian Gonzales Komiya -->

# core/prompts/

Canonical system prompts for `stella` and the six satellites. They implement the protocol in [`../architecture.md`](../architecture.md) and the formats in [`../punk-records.md`](../punk-records.md) and [`../schemas/`](../schemas/). If a prompt and the architecture disagree, the architecture wins and the prompt is a bug.

## Composition order

A flavor builds the prompt for a satellite by concatenating, in this order:

1. [`_shared-protocol.md`](_shared-protocol.md): the pattern, the communication rule and the output contract.
2. The satellite file, for example `punk-02-lilith.md`: identity, bias, counterweight, responsibilities, reads, writes, rules.
3. The runtime context: mission (goal, mode, roster, constraints, max_iterations, research_rounds), state (phase, iteration, research_round) and the records relevant to the satellite.

The seven role files (`stella` and the six satellites) start with `---` on line 1: a YAML front matter block (`id`, `name`, `role`, `cognitive_bias`, `reads`, `writes`, `active_phases`) whose first lines are the SPDX/copyright header as YAML comments. The front matter values match the components table in `architecture.md` exactly. Markdown files without front matter (this README and `_shared-protocol.md`) carry the header as an HTML comment instead.

## Canonical, not negotiable

These prompts are canonical. Flavors may adapt the **format** (for example splitting front matter into agent metadata, or stripping the header comment), but never the **semantics**: roles, permissions, templates, rules and the output contract stay as written. A behavior change is made here first.

## Structured output

The canonical output contract in `_shared-protocol.md` is a JSON array of record drafts. Flavors MAY enforce the record-draft contract through native structured output or tool calling instead of raw JSON text, as long as the resulting drafts are identical in shape and rules.

## Files

| File | Purpose |
|---|---|
| `_shared-protocol.md` | Shared preamble and output contract for all satellites |
| `stella.md` | Part A: guide for the human orchestrator. Part B: optional AI coordinator prompt |
| `punk-01-shaka.md` | Logic & architecture; issues the verdict |
| `punk-02-lilith.md` | Critique / red teaming |
| `punk-03-edison.md` | Ideation & strategy; proposals and revisions |
| `punk-04-pythagoras.md` | Research & data; findings |
| `punk-05-atlas.md` | Execution / brute force; artifacts |
| `punk-06-york.md` | Operations & maintenance; ops logs |

**Must stay use-case agnostic:** no prompt may reference `examples/`, any specific domain, tool or framework.
