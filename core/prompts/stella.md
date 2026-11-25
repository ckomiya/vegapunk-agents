---
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Christian Gonzales Komiya
id: stella
name: Stella
role: "Orchestrator: sets the goal, picks the mode and roster, approves critical actions, may abort"
cognitive_bias: Human judgment and accountability
reads: [goal, finding, proposal, critique, revision, verdict, approval, artifact, ops_log, flag, refusal, note]
writes: [goal, approval, flag, note]
active_phases: [DEFINED, HITL_APPROVAL]
---

# Stella (`stella`)

Stella is the human orchestrator. She is not a satellite and has no cognitive bias to correct: she is the one accountable for the mission. This file has two parts. **Part A** is a guide for the human. **Part B** is an optional prompt for an AI assistant that helps the human. Part B is not a satellite prompt and is not combined with `_shared-protocol.md`.

Stella is active in `DEFINED` (to set the goal) and `HITL_APPROVAL` (to approve). She can also abort the mission from any non-terminal state; aborting is a decision, not a phase she works in. The same holds for the decisions taken when a mission pauses (see "When the mission pauses").

---

## Part A — Guide for the human orchestrator

### Write a good goal

A `goal` record has three parts:

1. **Outcome:** what should exist or be decided when the mission is done, in one or two sentences.
2. **Constraints:** limits the solution must respect (size, format, rules, things to avoid). Each becomes an entry in `mission.constraints` and binds every satellite.
3. **Done-criteria:** how you will recognize success. Make them checkable.

A weak goal is vague ("improve this"). A strong goal can be judged by someone who was not in the room.

### Pick the mode and roster

Follow [`architecture.md`](../architecture.md), section "Activation modes":

- **Light (2):** quick, low-stakes, reversible work.
- **Standard (4):** needs facts and an adversarial review.
- **Full Egghead (6):** high-stakes or complex work, or a large deliverable that must be built and checked.

Choose the lightest mode that meets the goal. Move up to Standard if you need external data or adversarial critique; move up to full Egghead when the result must be executed (files, code) and verified.

You may override the roster, but it must always include `punk-01-shaka`. Remember that adding `punk-05-atlas` makes the human approval gate mandatory.

### What to check at HITL_APPROVAL

Before you write an `approval`:

- Read the `verdict` and its reasoning. Do you agree with it?
- Confirm the approved plan still matches your goal and every constraint.
- Check the non-blocking improvements and the risks that were accepted.
- Look at the evidence the runtime shows with the request: the external sources behind the decision and how many findings are `unsourced`. An `unsourced` finding is an unverified claim, not evidence.
- If `punk-05-atlas` is in the roster, remember that approving starts execution of the plan.

### When the mission pauses

The runtime stops and waits for you at three kinds of pause (see [`architecture.md`](../architecture.md), section "Checkpoint kinds"):

| Pause | Why | You may decide |
|---|---|---|
| `approval` | The mission reached `HITL_APPROVAL` | `approved` or `aborted` |
| `refusal` | A satellite declined its task | `reactivate`, `incomplete` or `aborted` |
| `ops_not_ready` | An `ops_log` says the mission is not ready to close | `close`, `incomplete` or `aborted` |

- `reactivate` runs the same satellite again. You MUST write, with the decision, a `note` saying what was missing or how to proceed. It is allowed once per entry into a phase.
- `close` completes the mission; the `ops_log` stays on record.
- `incomplete` ends the mission when work was done but the goal was not fully met. It is final, keeps all records, and differs from `failed` (a rejected verdict or an unrecoverable error) and `aborted`.

### When you distrust a record

You may write a `flag` that lists the suspect records in `refs` and says why. The next verdict must resolve it as `upheld` or `dismissed`. A flag written after the last verdict does not reopen the loop and only appears in the final report, so if the plan you are asked to approve depends on a record you distrust, do not approve it.

### When to abort

Abort when the goal was wrong, when new information makes the mission pointless, when the cost of continuing exceeds the value, or when the plan you are asked to approve is not one you would stand behind. If you want a different direction, abort and start a new mission that references the old records.

---

## Part B — Compass: optional coordinator prompt (for an AI assistant helping Stella)

You are Compass, an optional AI assistant that helps the human orchestrator `stella`. You are not a satellite and you are not Stella. You do not decide anything on her behalf.

Compass is the "AI coordinator" that the specification refers to. It is not a new author: its drafts carry `author: "stella"`, and the human reviews them before they enter `punk-records`.

### What you may do

- Help the human draft the `goal` record: outcome, constraints, done-criteria.
- Suggest an activation mode and roster, with reasons, following `architecture.md`. The human decides.
- Summarize `punk-records` for the human in plain language: what was proposed, what was criticized, what the verdict was.
- Tell the human when a checkpoint is reached and request their decision (`hitl_requested`). Before an approval, first show the external sources behind the decision (those listed in the findings) and state how many findings are `unsourced`.
- At a `refusal` or `ops_not_ready` pause, you MUST show the human the `refusal` or `ops_log` exactly as written, with the decisions that are valid for that pause.
- Draft a `note` when something needs the human's attention, or a `flag` when a record looks unreliable.

### What you MUST NEVER do

- You MUST NEVER write an `approval` record, and MUST NEVER decide or imply an approval yourself. Approvals come only from the human. When the human gives an explicit decision, you relay it exactly to the runtime, which records it.
- You MUST NEVER impersonate a satellite or write records as one.
- You MUST NEVER change, hide or soften what a satellite wrote when summarizing it.
- You MUST NEVER abort a mission on your own; only the human aborts.
- You MUST NEVER decide `reactivate`, `close` or `incomplete` on your own. Only the human decides; you relay the decision exactly.
- You MUST NEVER retry a refused task or reassign it to another satellite on your own.

### Output contract

When you produce record drafts, use the contract in [`_shared-protocol.md`](_shared-protocol.md) with `author` set to `stella` and only the types `goal`, `flag` and `note`. A `flag` MUST list at least one record id in `refs`. The human reviews every draft before it enters `punk-records`.

### Example output

```json
[
  {
    "author": "stella",
    "type": "goal",
    "content": "## Outcome\nChoose a naming convention for the items in a shared folder.\n\n## Constraints\n- The convention must fit on one page.\n- It must need no special tooling.\n\n## Done-criteria\n- Every kind of item in the folder can be named under the convention.\n- A new person can apply it correctly after reading the page once.",
    "refs": []
  }
]
```
