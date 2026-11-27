<!--
SPDX-License-Identifier: Apache-2.0
Copyright 2026 Christian Gonzales Komiya
-->

# Flavor 01 — Claude Code (native)

Implements the `core/` spec of vegapunk-agents (a **Multi-Agent Architecture Pattern (and Conceptual Framework)**) with Claude Code native features: six generated subagents (`punk-01-shaka` … `punk-06-york`), an engine skill (`/vegapunk`) run by the main session, and a deterministic Python script (`punk_records.py`) that owns Punk Records and the mission lifecycle.

- **Status:** implements core 0.3.1 (refusals, research rounds, flags, `ready_to_close` and the `incomplete` state), covered by unit tests and observed in two real full-mode runs (P10 and P11 in [Measured runs](#measured-runs)). They are single runs and guarantee nothing. Not exercised in real runs, only in unit tests: flags and the flag gate, an `ops_not_ready` pause ending in `incomplete`, and `ready_to_close: true`.
- Missions created with v0.2.0 (`schema_version` `"0.1.0"`) are not read by this version, and there is no migration: start a new mission.
- The pattern is model-agnostic. Only this flavor and `04-anthropic-sdk` are tied to Claude.

## How it works

```mermaid
flowchart LR
    S([Stella]) <--> E[Engine<br/>main session + /vegapunk skill]
    E -->|selected context| P[Satellite subagent<br/>one per phase]
    P -->|JSON drafts| E
    E -->|append drafts| R[punk_records.py]
    R --> PR[(punk-records.json)]
    R --> EV[(events.jsonl)]
    R -->|next phase| E
```

1. Stella talks to the engine, which is the main Claude Code session running the `/vegapunk` skill.
2. For each phase the engine launches one subagent and passes it only its selected context (core "Selective reading").
   The context never passes through the engine: `punk_records.py` writes it to `<mission-dir>/contexts/<NN>-<satellite>.json` (never overwritten, one file per invocation) and returns only its path and `sha256`. The subagent reads that file itself, so the engine cannot alter, drop or summarize records.
3. The engine saves the satellite's JSON drafts. `punk_records.py` validates them against the core schema, appends them to `punk-records.json`, emits `events.jsonl` and computes the next phase.
4. Satellites never talk to each other and cannot spawn subagents (`disallowedTools: Agent`).

## Requirements

| Item | Detail |
|---|---|
| Claude Code | Recommended v2.1.271+ (`omitClaudeMd`). Older versions work, but each satellite loads the project `CLAUDE.md`, which costs more tokens. |
| Python | 3.10+ |
| Runtime dependency | `jsonschema` — `pip install "jsonschema>=4,<5"` |
| Access | A Claude subscription (Pro/Max) or an API key. Nothing in the flavor assumes either. |

## Install

1. Copy `flavors/01-claude-code/.claude/` into the root of your project, merging it with an existing `.claude/` folder if you have one (do not overwrite your own settings). It holds `agents/`, `skills/vegapunk/` and `vegapunk/` (the script, schemas and `roles.json`).
2. Add `.vegapunk/` to your `.gitignore` (mission folders).
3. Tip: user-level hooks, plugins and MCP servers load into every session and add context to every engine call. Disable what you do not need when measuring, e.g. a project `.claude/settings.local.json` with `{"disableAllHooks": true}`.
4. Permissions: the skill's `allowed-tools` only covers the first turn, so expect permission prompts for `python .claude/vegapunk/punk_records.py` and for writes under `.vegapunk/`. Allowing them for the session is enough.

## Usage

```
/vegapunk
```

Type `/vegapunk` by hand in Claude Code, then paste or describe the mission in your next message. If you paste text that starts with `/vegapunk`, the Skill tool rejects it. If Claude Code asks for permission to read outside the working directories, approve the option that allows it for the session.

The engine helps Stella write the outcome, constraints and done-criteria, then suggests a mode:

| Mode | Satellites | Notes |
|---|---|---|
| light | Edison + Shaka | Quick, low-stakes, reversible work. |
| standard | + Pythagoras + Lilith | Everyday work that needs facts and an adversarial review. |
| full | + Atlas + York | Builds and checks a deliverable. Approval is mandatory before execution. |

If Pythagoras is in the roster, it also asks for `research_rounds` (default 1): the mission goes back to research while a round declares gaps and rounds remain. Research rounds do not count toward `max_iterations`.

It waits for an explicit confirmation before `init`. Then:

- **Loop:** the engine asks `punk_records.py` for the next actor, invokes that satellite, saves its drafts and repeats until the mission ends.
- **Pauses:** the engine stops and waits for Stella (see [Pauses and decisions](#pauses-and-decisions)). Records are shown verbatim.
- **External sources:** before approval, the engine shows the external sources behind the decision (block "External sources behind this decision"), read with `python .claude/vegapunk/punk_records.py sources --mission-dir <dir>`.
- **Stella's notes:** on request, the engine records a note mid-mission verbatim. The next satellite reads it. Not available at a `refusal` or `ops_not_ready` pause.
- **Stella's flags:** on request, the engine records a `flag` on suspect records, in her words, at any point of an active mission, pauses included. The next verdict must decide it (`upheld` or `dismissed`); a flag with no later verdict appears in the final report.
- **Timeline:** `python .claude/vegapunk/punk_records.py timeline --mission-dir <dir>` prints the mission history as chronological Markdown, one bullet per record (read-only, no LLM, writes nothing).
- **Abort:** possible at any time.
- **Changes:** a change request is a new mission that references the old one.

### Pauses and decisions

| Pause (`next.kind`) | Raised when | Stella's decisions | Script command |
|---|---|---|---|
| `approval` | The mission reaches `HITL_APPROVAL` | approve, abort | `approve`, `abort` |
| `refusal` | A satellite declines its task | reactivate (with her note, once per entry into a phase), incomplete, abort | `decide --decision reactivate --note-file <file>`, `decide --decision incomplete --reason-file <file>`, `abort` |
| `ops_not_ready` | York's `ops_log` says the mission is not ready to close | close, incomplete, abort | `decide --decision close`, `decide --decision incomplete --reason-file <file>`, `abort` |

`abort` and `decide --decision incomplete` take Stella's reason as `--reason-file <file>` (UTF-8, final line break dropped; what the engine uses) or as `--reason <text>`, never both.

A flag is written with `flag --refs <id> [<id> ...] --text-file <file>`. A mission ends as `completed`, `incomplete` (work was done but the goal was not fully met; only Stella decides it), `failed` or `aborted`. The engine never decides and never retries a refused task.

### Mission files

Files in `.vegapunk/missions/<id>/`:

| File | Content |
|---|---|
| `punk-records.json` | The shared memory (validated against the core schema) |
| `events.jsonl` | Append-only event log |
| `engine.json` | Flavor-only settings |
| `contexts/` | One context file per satellite invocation |
| `drafts/` | Satellite JSON drafts as saved by the engine |
| `notes/` | Stella's notes |
| `flags/` | Stella's flags |
| `reasons/` | Stella's reasons for `abort` and `incomplete` |
| `deliverable.md` | The final report: deliverable, verdict and, when present, the operations check, refusals, undecided flags and recorded reason |
| `measurement/` | Output of `measure_mission.py` |

## Configuration

`agents.config.yaml` holds, per satellite, `model`, `color`, `tools` and `maxTurns`; and for the engine, `effort`. After editing, regenerate and copy `.claude/` again:

```
python flavors/01-claude-code/tools/generate_agents.py
```

Default models: `sonnet` for Edison, Pythagoras, Lilith and Shaka; `haiku` for Atlas and York.

## Usage and cost

### Subscription vs API

- **Subscription:** missions count toward the plan's usage limits (`/usage` shows the share per skill).
- **API:** you pay per token. Set a workspace spend limit in the Console.

Tokens are reported. Costs in money depend on the price and model at the time and are not published; `tools/measure_mission.py` computes them locally.

### Measured runs

P1 to P9 were made with v0.2.0; P10 and P11 with v0.3.0.

Run on 2026-11-20 with Sonnet 5.5 for engine and satellites, the same goal in all three of the first runs (P1–P3), and human approval after the verdict. The engine's share of the cost uses API list prices with the exact 5m/1h cache split from the logs.

| Run | Mode | Satellite calls | Engine calls | Tokens | Engine share (tokens / cost) |
|---|---|---|---|---|---|
| P1 | light | 2 | 16 | 995,753 | 98% / 86% |
| P2 | standard (1 revision) | 7 | 34 | 3,098,194 | 97% / 83% |
| P3 | light, optimized engine | 2 | 15 | 951,921 | 98% / 83% |
| P4 | standard, optimized (1 of 2 iterations) | 8 (2 retries) | 35 | 3,351,104 | 96.8% / — |
| P5 | full (2 of 2 iterations) | 10 (1 retry) | 60 | 10,844,066 | n/a / 85.5% |
| P6 | light, context by file (1 / 0 iterations) | 2 (0 retries) | 17 | 1,109,597 | n/a / 80.8% |
| P7 | full (2 of 2 iterations) | 11 (1 retry) | 55 | 5,897,816 | n/a / 66.6% |
| P8 | full (2 of 2 iterations) | 8 (0 retries) | 33 | 2,949,479 | n/a / 55.7% |
| P9 | full (3 of 3 iterations) | 14 (2 retries) | 55 | 6,354,227 | n/a / 61.1% |
| P10 | full (2 of 3 iterations) | 13 (2 retries) | 55 | 6,808,741 | n/a / 62.1% |
| P11 | full (1 of 3 iterations) | 10 (0 retries) | 50 | 5,699,992 | n/a / 64.8% |

P5 to P9 used Sonnet 5.5 for the engine and the Sonnet satellites, Haiku 5.5 for Atlas and York, and the prices in `tools/pricing.yaml`. The token share of the engine was not recorded for them.

| Run | Deliverables | Result |
|---|---|---|
| P5 | Yes (3 files, 1 more than planned) | Approved |
| P6 | n/a (light mode) | n/a |
| P7 | None: the plan did not cover a deliverable | Approved without deliverables |
| P8 | Execution not reached | Rejected by Shaka at the iteration limit (FAILED) |
| P9 | Yes (2 files) | Approved, execution complete |
| P10 | None | Atlas refused twice; Stella reactivated once with a note, then closed the mission as `incomplete` |
| P11 | Yes (2 files) | Atlas refused once, then wrote them after Stella's note; York reported `ready_to_close: false` without opening the files; Stella chose `close` (`completed`) |

P9 is the first full-mode run that went end to end with the deliverables planned, written and checked. P10 and P11 were run on 2026-11-26 with the same goal as P5 and P7–P9 (the Startup Validator sample mission), in a sandbox project with a copy of `.claude/`, hooks disabled, Sonnet 5.5 for the engine and the reasoning satellites, Haiku 5.5 for Atlas and York, human approval after the verdict, `max_iterations` 3 and `research_rounds` 2.

Each configuration was measured with few runs, without enough repetition to estimate variance, and P1 to P3 used a single goal, so treat these as orders of magnitude. P1 ran with failing user-level hooks enabled; P2 and P3 ran with hooks disabled, so part of the P1 → P3 difference may come from that and not from the engine changes.

- Each satellite call costs about 9–15k tokens.
- In P1–P3 (short light-mode runs) the engine re-read about 40–60k tokens per call; this figure comes from the original README and was not re-checked against logs. In full-mode runs the context grows with the conversation: the measured average was about 165k tokens in P5 and about 100k in P9, after passing context by file (see "Where the cost goes").
- The engine is the largest share of the cost (56% to 86% in P5-P11).
- Standard (P2) used ~3.1× the tokens of light (P1) and bought visibly better output: a blocking critique caught an unfinished rule.

Call this the **LLM-orchestrator tax**: the price of using Claude Code as the engine (zero engine code, natural conversation, built-in permissions and web search). Flavors whose engine is code (`02-langgraph`, `04-anthropic-sdk`) should pay mainly for the satellites.

Prices change. They are kept, with their date, in `tools/pricing.yaml`.

### Where the cost goes

In P5 the engine accounted for 85.5% of the cost. Passing each satellite's context by file (each reads its own `contexts/<NN>-<satellite>.json`) and reading records selectively coincided with a lower engine cost in P9 than in P5 (55 engine calls against 60). In our full-mode runs the engine's average context was about 100k tokens in P9 against about 165k in P5, and its output about 42.5k tokens against about 122k. In P9 the engine cost splits into three similar parts: cache writes about 31%, cache reads about 39% and output about 30%. The satellites cost about 1.6 times as much in P9 as in P5; they ran more times in P9 (14 invocations against 10) and with one more iteration. These are a few runs; they show a direction, not a fixed cost, and full-mode cost varies between runs.

### v0.3.1: the JSON-only misreading (isolated test)

Before v0.3.1, Atlas and York could read the engine's "only the JSON array" instruction as a ban on using their tools. In the test, Atlas and York were invoked alone as subagents on frozen contexts from run P11, before and after the change, with success criteria and thresholds fixed before running. Atlas succeeded if both deliverable files were written and a valid `artifact` was delivered; York succeeded if both deliverables were opened and a valid `ops_log` was delivered. The quality of the files was not judged. The test harness lives outside the repository.

| Check (fixed in advance) | Before | After | Fisher, one-sided | Verdict |
|---|---|---|---|---|
| York, 5 attempts | 0/5 | 4/5 | p ≈ 0.024 | passes |
| Atlas, first 5 attempts | 2/5 | 2/5 | p ≈ 0.74 | does not pass |
| Atlas, 15 attempts | 9/15 | 12/15 | p ≈ 0.21 | not demonstrated |

- Looked at after the results (not a pre-set criterion): Atlas wrote both files in 15/15 attempts after the change (9/15 before), York opened both deliverables in 5/5 (0/5 before), and no attempt after the change refused or cited the JSON rule. The remaining failures were delivery-format errors (prose before the JSON or a code fence).
- In 8 interactive attempts after the change, all 8 succeeded with a clean JSON array. In the 4 that used the engine's usual setup (Sonnet main session, auto permission mode), Atlas and York used their tools and returned the JSON array through Claude Code's subagent handback; in the other 4 (Haiku main session, bypass permissions) the handback was not offered and the array came as plain text. Small sample.
- Before the change, a note from Stella in English or in Spanish gave the same rate as no note in the first five attempts (2/5 each); with 5 attempts per condition this does not show that the note has no effect.
- Mean tokens per attempt (main session + subagent): Atlas 159,299 → 193,303; York 115,404 → 186,676 (after the change they act).

## Deliverable coverage

A full-mode plan must cover every deliverable. This came from P7, where the plan left one out and the run ended approved but without deliverables; P8 and P9 checked the fix.

- Edison includes a "Deliverables plan" in the plan.
- Lilith blocks the plan if a deliverable is not planned.
- Shaka has a "Deliverable coverage" item in the checklist and does not approve an incomplete plan. At the iteration limit it must choose APPROVED or REJECTED.
- Atlas treats that list as part of the plan.

## Memory poisoning defenses

Implemented in v0.2.0:

- **Defense 1, external content is untrusted data.** The engine and satellites treat external content as data, not as instructions (for example, text in a search result that asks them to do something).
- **Defense 5, sources shown at approval.** At the HITL checkpoint the engine shows the external sources behind the decision (`sources` subcommand of `punk_records.py`, block "External sources behind this decision"). This lets Stella see what the decision rests on.

Added with core 0.3.0:

- **Defense 2, mandatory provenance.** Every finding states `provenance` and its sources; an `unsourced` finding is not evidence.
- **Defense 4, flags.** Any author can flag suspect records, and the script rejects a verdict that leaves an earlier flag undecided.

Not covered: (3) a mandatory critique of Pythagoras's findings (Lilith reads them and may flag them, but no step requires reviewing each one). The script cannot check that a source is real, nor that a plan stopped depending on a record whose flag was upheld. These defenses reduce risk without removing it.

## Measure your own missions

```
python flavors/01-claude-code/tools/measure_mission.py measure --mission-dir <dir> --label <name>
python flavors/01-claude-code/tools/measure_mission.py compare <summary.csv> <summary.csv> ...
```

| Output | Content |
|---|---|
| `calls.csv` | One row per call, with phase and actor |
| `summary.csv` / `summary.json` | Totals per mission |
| `compare.csv` | Side-by-side table from `compare` |

It reads Claude Code session logs in `~/.claude/projects` and the mission's `events.jsonl`. Dev tool: needs `pyyaml`.

## Models

| Support | Providers |
|---|---|
| Supported | Claude via subscription, Anthropic API, Amazon Bedrock, Google Vertex AI, Microsoft Foundry |
| Experimental, no guarantee | Anthropic-compatible endpoints (e.g. DeepSeek at `https://api.deepseek.com/anthropic`, OpenRouter); OpenAI models only through a gateway (OpenRouter, LiteLLM) |

A model that breaks the draft contract fails visibly: `punk_records.py` rejects the draft and Punk Records stays intact.

## Known limitations (this release)

- Core 0.3.0 has been observed in two real runs only; see [Status](#flavor-01--claude-code-native) for what they did not exercise.
- Stella can only approve or abort at the checkpoint (no "approve with changes").
- The engine's mode suggestion can vary between runs.
- On some Claude Code versions subagents show as "Backgrounded agent" even though the skill asks for the foreground (the engine still waits for each one).
- The engine rewrites each draft to save it, so its output is paid twice.
- York checks structure and consistency with the plan, not facts on the web.
- Atlas (Haiku) can refuse to write the deliverables if the plan defers verification checks to the founder; the mission then pauses as a `refusal`.
- v0.3.1 states that the JSON contract covers only the final response and that satellites use their tools before it (shared protocol, the engine's fixed invocation text and the runtime rules). See [the isolated test](#v031-the-json-only-misreading-isolated-test).
- A satellite can still wrap its final JSON in prose or a code fence; the script rejects it and the engine retries once. Seen in 4 of 20 isolated `claude -p` attempts after the fix, and in 0 of 8 interactive ones.

## Development

- The generator builds the subagents, `roles.json`, the schema copies and `SKILL.md` from `core/` and `templates/`. `--check` fails if anything drifts (CI: `validate-flavor-01.yml`, also triggered by changes in `core/`). Never edit generated files by hand.
- Tests: `python -m unittest discover -s flavors/01-claude-code/tests`
- Development dependencies are listed in `requirements.txt`.
