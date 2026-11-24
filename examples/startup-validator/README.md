<!--
SPDX-License-Identifier: Apache-2.0
Copyright 2026 Christian Gonzales Komiya
-->
# Startup Validator

A demo that applies the Vegapunk pattern, a **Multi-Agent Architecture Pattern (and Conceptual Framework)**, to validating a startup idea: six biased specialists share one memory and a human decides.

**Status:** Tested with flavor 01 (Claude Code) in full mode; see [What to expect](#what-to-expect).

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

## What to expect

- **Why 3 iterations:** in full mode Lilith often blocks the first revisions. In one of our three runs with 2 iterations, Shaka rejected the plan at the iteration limit because a blocking critique was still open; in a fourth run with 3 iterations the third critique was resolved and the run reached execution. Three iterations gives more headroom, at a small extra cost.
- **Atlas may stop and ask for a decision:** if the approved plan defers verification checks (prices, legal rules) to the founder, Atlas can refuse to write the files, because it has no web tools. The engine will pause and ask you. A note like "The checks in the plan are founder steps, not preconditions for writing. Write both files now and mark every unverified figure as an estimate, saying what it rests on." unblocks it.
- **York's verdict:** York verifies structure and consistency against the approved plan (sections present, exactly two files, additions not in the plan). It does not verify facts on the web.
- **Empty output folder:** before each run, `./startup-validator-output/` must be empty. The engine will stop and ask if old files are there.
- **Deliverables:** in our runs the result was a low-confidence pivot recommendation and a 3-experiment plan. The facts the satellites could not verify are labelled "Unverified" or "Estimate" in the report.

## Running it on your own idea

Fill in the goal block of `mission-template.md`, paste it into the engine as written, and give the settings listed there.
Mission folders (`.vegapunk/`) and `./startup-validator-output/` stay local if you add them to `.gitignore`; nothing is published unless you share it.

## Cost

A complete run with the flavor 01 engine cost about US$2.3 at API prices in our last run; it varies between runs, and Light and Standard modes cost less. The measurement method and the Light and Standard figures are in the [flavor 01 README](../../flavors/01-claude-code/README.md#usage-and-cost); the full-mode figure is not published there yet and will be added with the flavor.

## Relationship to the framework

This demo consumes the framework; the framework does not depend on it.
