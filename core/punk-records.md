<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright 2026 Christian Gonzales Komiya -->

# Punk Records

`punk-records` is the shared memory of one mission: the single place where `stella` and the six satellites exchange everything. This document explains the data format. The protocol that uses it is in [`architecture.md`](architecture.md); the normative format is [`schemas/punk-records.schema.json`](schemas/punk-records.schema.json).

## Structure

A Punk Records document has four top-level fields:

| Field | Content |
|---|---|
| `schema_version` | Version of the document format. It is `"0.1.0"` in specification 0.2.0 too, because the format has not changed since 0.1.0 |
| `mission` | `id`, `goal`, `mode` (`light`/`standard`/`full`), `roster` (satellite ids), `constraints`, `max_iterations` (default 2), `created_at` |
| `state` | `phase` (lifecycle state), `iteration`, `status` (`active`/`completed`/`failed`/`aborted`), `updated_at` |
| `records` | Ordered array of records |

A record has: `id`, `author`, `type`, `phase`, `iteration`, `content` (Markdown allowed), `refs` (ids of earlier records), optional `confidence` (0–1), `verdict` (only for `type: verdict`), `blocking` (only for `type: critique`), and `created_at`.

`blocking` is a boolean that is **required on every `critique` and forbidden on every other type**. It is the machine-readable signal that drives the critique/revision loop: `true` means the critique raises issues that must be addressed before a verdict. Flavors never infer it from the critique text.

## Append-only rule

- Records are only ever **appended**. They are never edited or deleted.
- To correct a record, append a new one whose `refs` includes the id of the record being corrected.
- `refs` MUST point to records that appear earlier in `records`.
- Only `state` (and the file as a whole) changes in place, because it is derived from the lifecycle.

## Author → record-type permissions

| Author | May write |
|---|---|
| `stella` | `goal`, `approval`, `note` |
| `punk-01-shaka` | `verdict`, `note` |
| `punk-02-lilith` | `critique`, `note` |
| `punk-03-edison` | `proposal`, `revision`, `note` |
| `punk-04-pythagoras` | `finding`, `note` |
| `punk-05-atlas` | `artifact`, `note` |
| `punk-06-york` | `ops_log`, `note` |

The schema rejects a record whose author may not write its type, requires `verdict` exactly when `type` is `verdict`, and requires `blocking` exactly when `type` is `critique`.

## Markdown projection

Flavors that keep Punk Records as files (for example a Claude Code flavor) can use a Markdown projection. It carries the same information as the JSON form and MUST round-trip to it.

- A YAML front matter block holds `schema_version`, `mission` and `state`.
- Each record is one block: a heading `### [record-id] author · type · phase · iteration`, then a short metadata list (`refs`, `confidence`, `verdict`, `created_at`, omitting what is absent; critiques also carry a `blocking: true|false` line), then the content.
- Blocks appear in record order. New blocks are appended at the end of the file.

Example:

````markdown
---
schema_version: "0.1.0"
mission:
  id: mission-example
  goal: Pick a naming scheme for internal tags.
  mode: light
  roster: [punk-03-edison, punk-01-shaka]
  constraints: []
  max_iterations: 2
  created_at: "2026-01-01T09:00:00Z"
state:
  phase: VERDICT
  iteration: 0
  status: active
  updated_at: "2026-01-01T09:10:00Z"
---

### [r-001] stella · goal · DEFINED · 0

- refs: none
- created_at: 2026-01-01T09:00:00Z

Pick a naming scheme for internal tags.

### [r-002] punk-03-edison · proposal · IDEATION · 0

- refs: r-001
- created_at: 2026-01-01T09:05:00Z

Use `area-topic` lowercase tags, for example `billing-invoices`.
````

## Events

Alongside the records, a flavor emits an event stream (`events.jsonl`, one JSON object per line) conforming to [`schemas/event.schema.json`](schemas/event.schema.json). Events describe what happened and when; the records hold the content. Both are use-case agnostic.

## Examples

- [`schemas/examples/punk-records.example.json`](schemas/examples/punk-records.example.json) — a complete mission in Standard mode, with one critique/revision loop and an `APPROVED` verdict.
- [`schemas/examples/events.example.jsonl`](schemas/examples/events.example.jsonl) — the matching event stream.
