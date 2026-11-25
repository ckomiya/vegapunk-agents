<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright 2026 Christian Gonzales Komiya -->

# Punk Records

`punk-records` is the shared memory of one mission: the single place where `stella` and the six satellites exchange everything. This document explains the data format. The protocol that uses it is in [`architecture.md`](architecture.md); the normative format is [`schemas/punk-records.schema.json`](schemas/punk-records.schema.json).

## Structure

A Punk Records document has four top-level fields:

| Field | Content |
|---|---|
| `schema_version` | Version of the document format: `"0.3.0"`. The format changed in specification 0.3.0: a document of format `"0.1.0"` is not valid, the 0.3 tools do not read it, and there is no migration |
| `mission` | `id`, `goal`, `mode` (`light`/`standard`/`full`), `roster` (satellite ids), `constraints`, `max_iterations` (default 2), `research_rounds` (default 1), `created_at` |
| `state` | `phase` (lifecycle state), `iteration`, `research_round`, `status` (`active`/`completed`/`incomplete`/`failed`/`aborted`), `updated_at` |
| `records` | Ordered array of records |

A record has: `id`, `author`, `type`, `phase`, `iteration`, `content` (Markdown allowed), `refs` (ids of earlier records), optional `confidence` (0–1), `verdict` (only for `type: verdict`), `blocking` (only for `type: critique`), and `created_at`.

`blocking` is a boolean that is **required on every `critique` and forbidden on every other type**. It is the machine-readable signal that drives the critique/revision loop: `true` means the critique raises issues that must be addressed before a verdict. Flavors never infer it from the critique text.

Other fields belong to a single record type and are forbidden on the rest:

| Record type | Fields | Purpose |
|---|---|---|
| `finding` | `provenance`, `sources` (required); `gaps` (optional) | See [Finding provenance](#finding-provenance) |
| `refusal` | `reason` (required) | Why the satellite declines the task |
| `verdict` | `flag_resolutions` (required while a flag is unresolved) | `upheld` or `dismissed` for each flag |
| `ops_log` | `ready_to_close` (required) | Whether the mission can be closed |

A `flag` has no field of its own; it MUST have at least one entry in `refs`. The rules that act on these fields are in [`architecture.md`](architecture.md#rules).

## Append-only rule

- Records are only ever **appended**. They are never edited or deleted.
- To correct a record, append a new one whose `refs` includes the id of the record being corrected.
- `refs` MUST point to records that appear earlier in `records`.
- Only `state` (and the file as a whole) changes in place, because it is derived from the lifecycle.

## Author → record-type permissions

| Author | May write |
|---|---|
| `stella` | `goal`, `approval`, `flag`, `note` |
| `punk-01-shaka` | `verdict`, `flag`, `refusal`, `note` |
| `punk-02-lilith` | `critique`, `flag`, `refusal`, `note` |
| `punk-03-edison` | `proposal`, `revision`, `flag`, `refusal`, `note` |
| `punk-04-pythagoras` | `finding`, `flag`, `refusal`, `note` |
| `punk-05-atlas` | `artifact`, `flag`, `refusal`, `note` |
| `punk-06-york` | `ops_log`, `flag`, `refusal`, `note` |

The schema rejects a record whose author may not write its type, requires `verdict` exactly when `type` is `verdict`, and requires `blocking` exactly when `type` is `critique`.

## Finding provenance

Every `finding` states where its claims come from:

| `provenance` | Meaning | Requires |
|---|---|---|
| `external` | Backed by sources outside the mission | at least one entry in `sources` |
| `internal` | Derived from earlier records of the mission | the records it derives from, in `refs` |
| `unsourced` | The satellite's own knowledge, with no citable source | `sources: []` |

- `internal` is only for claims derived from earlier records, and the finding MUST cite those records in `refs`.
- What the satellite knows but cannot cite is `unsourced`, never `internal`.
- A finding that mixes sourced and unsourced claims uses `external`, and its content MUST mark as "Unverified" whatever the listed sources do not support.
- Each source states its `access`: `opened` if the source itself was read, `snippet` if only an excerpt was seen (for example in a search result). A source MUST NOT be marked `opened` unless it was read.
- `gaps` lists the open questions that further research should answer, each with `question` and `why_needed`. Omit the field when there are none. A declared gap can start another research round.

## Markdown projection

Flavors that keep Punk Records as files (for example a Claude Code flavor) can use a Markdown projection. It carries the same information as the JSON form and MUST round-trip to it.

- A YAML front matter block holds `schema_version`, `mission` and `state`.
- Each record is one block: a heading `### [record-id] author · type · phase · iteration`, then a short metadata list, then the content.
- The metadata list has one line per field, omitting what is absent: `refs`, `confidence`, `verdict`, `blocking`, `provenance`, `sources`, `gaps`, `reason`, `flag_resolutions`, `ready_to_close`, `created_at`.
- `sources`, `gaps` and `flag_resolutions` are written as JSON on their single line, for example `- sources: [{"locator": "https://example.org/guide", "access": "opened"}]`. An empty list is written `[]`.
- Blocks appear in record order. New blocks are appended at the end of the file.

Example:

````markdown
---
schema_version: "0.3.0"
mission:
  id: mission-example
  goal: Pick a naming scheme for internal tags.
  mode: light
  roster: [punk-03-edison, punk-01-shaka]
  constraints: []
  max_iterations: 2
  research_rounds: 1
  created_at: "2026-01-01T09:00:00Z"
state:
  phase: VERDICT
  iteration: 0
  research_round: 0
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

- [`schemas/examples/punk-records.example.json`](schemas/examples/punk-records.example.json) — a complete mission in Standard mode, with two research rounds, a flag, one critique/revision loop and an `APPROVED` verdict.
- [`schemas/examples/events.example.jsonl`](schemas/examples/events.example.jsonl) — the matching event stream.
