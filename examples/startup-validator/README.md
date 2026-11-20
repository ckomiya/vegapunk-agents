<!--
SPDX-License-Identifier: Apache-2.0
Copyright 2026 Christian Gonzales Komiya
-->
# Startup Validator

A demo that applies the Vegapunk pattern, a **Multi-Agent Architecture Pattern (and Conceptual Framework)**, to validating a startup idea: six biased specialists share one memory and a human decides.

**Status:** Defined (Phase 2); first run with flavor 01 pending.

## The sample idea

A mobile app where neighbors rent each other household tools they rarely use, with pickup on foot, launching in one district of Lima, Peru.
The idea is fictional, chosen so that public evidence exists and the satellites have real trade-offs to argue about.

## Files

| File | Purpose |
|---|---|
| [mission-template.md](mission-template.md) | Template with `{{IDEA}}` and `{{FOUNDER_CONSTRAINTS}}` slots, for any flavor |
| [sample-mission.md](sample-mission.md) | The template filled in with the sample idea: goal block to paste, plus engine settings |
| [deliverables.md](deliverables.md) | What each satellite produces; exact sections of both output files; York's checklist |

## How to run it

| Flavor | How |
|---|---|
| `01-claude-code` | Copy `.claude/` as described in the [flavor README](../../flavors/01-claude-code/README.md), run `/vegapunk`, paste the goal block of `sample-mission.md` as written, say "search limit 6, draft limit 500", and choose full mode. |
| `02-langgraph` | Coming in later phases. |
| `03-crewai` | Coming in later phases. |
| `04-anthropic-sdk` | Coming in later phases. |

Search differs per flavor: flavor 01 uses Claude Code's built-in web search; flavor 02 will use `duckduckgo-search` (no API key). Results and costs can differ between flavors.

## What success looks like

- `./startup-validator-output/validation-report.md` has the 8 required sections, and every factual claim has a source or is marked as an estimate.
- `./startup-validator-output/experiment-plan.md` has 3 experiments with hypothesis, method, cost, duration and success threshold, all within the founder's budget.
- York's operations record (type ops_log, in Punk Records, not a file) confirms that validation-report.md and experiment-plan.md exist and have every required section, and lists any other file left in ./startup-validator-output/ as extra.
- The verdict's reasoning cites findings and addresses every blocking critique.

## Running it on your own idea

Fill in the goal block of `mission-template.md`, paste it into the engine as written, and give the settings listed there.
Mission folders (`.vegapunk/`) and `./startup-validator-output/` stay local if you add them to `.gitignore`; nothing is published unless you share it.

## Cost

To be measured on the first run.

## Relationship to the framework

This demo consumes the framework; the framework does not depend on it.
