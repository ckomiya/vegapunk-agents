# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Christian Gonzales Komiya
"""Deterministic Punk Records engine for the Claude Code flavor.

Validates satellite drafts, assigns ids, writes punk-records.json and
events.jsonl atomically, and computes the next phase of the mission.

All stdout output is JSON. Errors are JSON with an "errors" list and a
non-zero exit code. Schemas and roles.json are loaded from this script's own
folder, never from core/.

Runtime dependency: jsonschema.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

HERE = Path(__file__).resolve().parent
RECORDS_FILE = "punk-records.json"
EVENTS_FILE = "events.jsonl"
ENGINE_FILE = "engine.json"

SCHEMA_VERSION = "0.1.0"
SATELLITES = [
    "punk-01-shaka",
    "punk-02-lilith",
    "punk-03-edison",
    "punk-04-pythagoras",
    "punk-05-atlas",
    "punk-06-york",
]
DEFAULT_ROSTERS = {
    "light": ["punk-03-edison", "punk-01-shaka"],
    "standard": ["punk-04-pythagoras", "punk-03-edison", "punk-02-lilith", "punk-01-shaka"],
    "full": list(SATELLITES),
}
# Linear lifecycle (REVISION is never reached in linear order).
LINEAR = [
    "DEFINED",
    "RESEARCH",
    "IDEATION",
    "CRITIQUE",
    "VERDICT",
    "HITL_APPROVAL",
    "EXECUTION",
    "OPERATIONS",
    "COMPLETED",
]
# Record type each satellite phase produces.
PHASE_PRODUCES = {
    "RESEARCH": "finding",
    "IDEATION": "proposal",
    "CRITIQUE": "critique",
    "REVISION": "revision",
    "VERDICT": "verdict",
    "EXECUTION": "artifact",
    "OPERATIONS": "ops_log",
}
TERMINAL = {"COMPLETED", "FAILED", "ABORTED"}
DRAFT_FIELDS = {"author", "type", "content", "refs", "confidence", "blocking", "verdict"}
DRAFT_REQUIRED = {"author", "type", "content", "refs"}
RUNTIME_FIELDS = {"id", "phase", "iteration", "created_at"}


class EngineError(Exception):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = [errors] if isinstance(errors, str) else list(errors)


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj: dict, code: int = 0) -> int:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    return code


def fail(errors) -> int:
    return emit({"ok": False, "errors": [errors] if isinstance(errors, str) else list(errors)}, 1)


def dump_json(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def load_runtime_files() -> tuple[dict, dict, dict]:
    try:
        records_schema = json.loads((HERE / "punk-records.schema.json").read_text(encoding="utf-8"))
        event_schema = json.loads((HERE / "event.schema.json").read_text(encoding="utf-8"))
        roles = json.loads((HERE / "roles.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EngineError(
            f"cannot load schemas/roles.json from {HERE} (run generate_agents.py): {exc}"
        ) from None
    return records_schema, event_schema, roles


def schema_errors(schema: dict, instance, label: str) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    out = []
    for err in sorted(validator.iter_errors(instance), key=lambda e: list(map(str, e.absolute_path))):
        where = "/".join(str(p) for p in err.absolute_path) or "<root>"
        out.append(f"{label} schema violation at {where}: {err.message}")
    return out


def atomic_write_all(files: dict[Path, bytes]) -> None:
    """Write several files so that a failure leaves every one as it was."""
    tmp_paths: dict[Path, Path] = {}
    originals: dict[Path, bytes | None] = {}
    replaced: list[Path] = []
    try:
        for path, data in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
            tmp_paths[path] = Path(tmp)
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            originals[path] = path.read_bytes() if path.exists() else None
        for path, tmp in tmp_paths.items():
            os.replace(tmp, path)
            replaced.append(path)
    except BaseException:
        for path in replaced:  # roll back files already replaced
            try:
                if originals[path] is None:
                    path.unlink()
                else:
                    path.write_bytes(originals[path])
            except OSError:
                pass
        raise
    finally:
        for tmp in tmp_paths.values():
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass


# --------------------------------------------------------------------------
# Mission state
# --------------------------------------------------------------------------

class Mission:
    """In-memory mission: document + events + engine config, with a pending event list."""

    def __init__(self, directory: Path, doc: dict, events: list[dict], engine: dict, roles: dict):
        self.dir = directory
        self.doc = doc
        self.events = events
        self.engine = engine
        self.roles = roles
        self.ts = now()

    # -- accessors -------------------------------------------------------
    @property
    def roster(self) -> list[str]:
        return self.doc["mission"]["roster"]

    @property
    def phase(self) -> str:
        return self.doc["state"]["phase"]

    @property
    def iteration(self) -> int:
        return self.doc["state"]["iteration"]

    @property
    def max_iterations(self) -> int:
        return self.doc["mission"]["max_iterations"]

    @property
    def hitl_after_verdict(self) -> bool:
        return bool(self.engine.get("hitl_after_verdict", False))

    def actor_for(self, phase: str) -> str | None:
        """The satellite active in a phase (None for stella/system/terminal phases)."""
        for sid in SATELLITES:
            if phase in self.roles.get(sid, {}).get("active_phases", []):
                return sid
        return None

    def active(self, phase: str) -> bool:
        if phase in ("DEFINED", "VERDICT", "COMPLETED"):
            return True
        if phase == "HITL_APPROVAL":
            return "punk-05-atlas" in self.roster or self.hitl_after_verdict
        actor = self.actor_for(phase)
        return actor in self.roster

    def next_linear(self, phase: str) -> str:
        for cand in LINEAR[LINEAR.index(phase) + 1:]:
            if self.active(cand):
                return cand
        return "COMPLETED"

    # -- mutation (in memory) -------------------------------------------
    def add_event(self, etype: str, actor: str, payload: dict) -> None:
        self.events.append(
            {
                "ts": self.ts,
                "mission_id": self.doc["mission"]["id"],
                "seq": len(self.events) + 1,
                "type": etype,
                "actor": actor,
                "payload": payload,
            }
        )

    def add_record(self, author: str, rtype: str, content: str, refs: list[str], extra: dict) -> dict:
        rec = {
            "id": f"r-{len(self.doc['records']) + 1:03d}",
            "author": author,
            "type": rtype,
            "phase": self.phase,
            "iteration": self.iteration,
            "content": content,
            "refs": refs,
        }
        for key in ("confidence", "verdict", "blocking"):
            if key in extra:
                rec[key] = extra[key]
        rec["created_at"] = self.ts
        self.doc["records"].append(rec)
        self.add_event("record_written", author, {"record_id": rec["id"], "record_type": rtype})
        return rec

    def go(self, to: str) -> None:
        """Change phase and apply the entry effects."""
        frm = self.phase
        state = self.doc["state"]
        state["phase"] = to
        state["updated_at"] = self.ts
        if to == "REVISION":
            state["iteration"] += 1
        self.add_event("phase_changed", "system", {"from": frm, "to": to})
        satellite = self.actor_for(to)
        if satellite:
            self.add_event("satellite_activated", satellite, {"phase": to})
        if to == "HITL_APPROVAL":
            verdict = self.last_record("verdict")
            payload = {
                "reason": (
                    "Approve the verdict before punk-05-atlas starts execution."
                    if "punk-05-atlas" in self.roster
                    else "Approve the verdict before the mission continues."
                )
            }
            if verdict:
                payload["record_id"] = verdict["id"]
            self.add_event("hitl_requested", "system", payload)
        elif to == "COMPLETED":
            state["status"] = "completed"
            self.add_event("mission_completed", "system", {})

    def terminate(self, to: str, event: str, reason: str, extra: dict | None = None) -> None:
        self.doc["state"]["status"] = {"FAILED": "failed", "ABORTED": "aborted"}[to]
        self.go(to)
        self.add_event(event, "system", {"reason": reason, **(extra or {})})

    def last_record(self, rtype: str) -> dict | None:
        for rec in reversed(self.doc["records"]):
            if rec["type"] == rtype:
                return rec
        return None

    # -- next-step report ------------------------------------------------
    def next_info(self, with_context: bool = False) -> dict:
        info = self._next_info()
        if with_context and info["action"] == "invoke_satellite":
            info["context"] = build_context(self, info["actor"], False, [])
        return info

    def _next_info(self) -> dict:
        phase = self.phase
        status = self.doc["state"]["status"]
        if status == "completed":
            return {"phase": phase, "actor": None, "action": "completed"}
        if status == "failed":
            return {"phase": phase, "actor": None, "action": "failed"}
        if status == "aborted":
            return {"phase": phase, "actor": None, "action": "aborted"}
        if phase == "HITL_APPROVAL":
            return {"phase": phase, "actor": "stella", "action": "await_hitl"}
        return {"phase": phase, "actor": self.actor_for(phase), "action": "invoke_satellite"}

    # -- persistence -----------------------------------------------------
    def validate(self, records_schema: dict, event_schema: dict) -> list[str]:
        errors = schema_errors(records_schema, self.doc, "punk-records")
        for ev in self.events:
            errors += schema_errors(event_schema, ev, f"event seq {ev.get('seq')}")
        seqs = [e["seq"] for e in self.events]
        if seqs != list(range(1, len(seqs) + 1)):
            errors.append("events seq is not consecutive from 1")
        terminal = [e for e in self.events if e["type"] in ("mission_completed", "mission_failed", "mission_aborted")]
        if len(terminal) > 1:
            errors.append("more than one terminal event")
        return errors

    def save(self, extra: dict[Path, bytes] | None = None) -> None:
        events_bytes = b"".join(
            (json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            for e in self.events
        )
        atomic_write_all(
            {
                self.dir / RECORDS_FILE: dump_json(self.doc),
                self.dir / EVENTS_FILE: events_bytes,
                **(extra or {}),
            }
        )


def load_mission(directory: Path) -> tuple[Mission, dict, dict]:
    records_schema, event_schema, roles = load_runtime_files()
    try:
        doc = json.loads((directory / RECORDS_FILE).read_text(encoding="utf-8"))
        events = [
            json.loads(line)
            for line in (directory / EVENTS_FILE).read_text(encoding="utf-8").split("\n")
            if line.strip()
        ]
        engine = json.loads((directory / ENGINE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EngineError(f"cannot load mission from {directory}: {exc}") from None
    return Mission(directory, doc, events, engine, roles), records_schema, event_schema


def commit(mission: Mission, records_schema: dict, event_schema: dict, extra=None) -> None:
    errors = mission.validate(records_schema, event_schema)
    if errors:
        raise EngineError(errors)
    try:
        mission.save(extra)
    except OSError as exc:
        raise EngineError(f"write failed, nothing was changed: {exc}") from None


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def resolve_dir(args) -> Path:
    if args.mission_dir:
        return Path(args.mission_dir)
    if args.mission_id:
        return Path(".vegapunk") / "missions" / args.mission_id
    raise EngineError("pass --mission-dir or --mission-id")


def cmd_init(args) -> dict:
    records_schema, event_schema, roles = load_runtime_files()
    errors = []
    if not args.goal.strip():
        errors.append("--goal must not be empty")
    if args.max_iterations < 0:
        errors.append("--max-iterations must be >= 0")
    roster = list(args.roster) if args.roster else list(DEFAULT_ROSTERS[args.mode])
    bad = [r for r in roster if r not in SATELLITES]
    if bad:
        errors.append(f"roster has non-canonical ids: {bad}")
    if len(set(roster)) != len(roster):
        errors.append("roster has duplicate ids")
    if "punk-01-shaka" not in roster:
        errors.append("roster must include punk-01-shaka (only Shaka issues verdicts)")
    mission_id = args.mission_id or datetime.now(timezone.utc).strftime("mission-%Y%m%d-%H%M%S")
    directory = Path(args.mission_dir) if args.mission_dir else Path(".vegapunk") / "missions" / mission_id
    if (directory / RECORDS_FILE).exists():
        errors.append(f"a mission already exists in {directory}")
    if errors:
        raise EngineError(errors)

    ts = now()
    doc = {
        "schema_version": SCHEMA_VERSION,
        "mission": {
            "id": mission_id,
            "goal": args.goal,
            "mode": args.mode,
            "roster": roster,
            "constraints": list(args.constraint or []),
            "max_iterations": args.max_iterations,
            "created_at": ts,
        },
        "state": {"phase": "DEFINED", "iteration": 0, "status": "active", "updated_at": ts},
        "records": [],
    }
    engine = {
        "$comment": "Flavor-only settings, not part of the core specification.",
        "hitl_after_verdict": bool(args.hitl_after_verdict),
    }
    m = Mission(directory, doc, [], engine, roles)
    m.ts = ts
    m.add_event("mission_started", "stella", {"mode": args.mode, "roster": roster})
    constraints = "\n".join(f"- {c}" for c in doc["mission"]["constraints"]) or "None."
    criteria = "\n".join(f"- {c}" for c in (args.done_criterion or [])) or "None."
    m.add_record(
        "stella",
        "goal",
        f"## Outcome\n{args.goal}\n\n## Constraints\n{constraints}\n\n## Done-criteria\n{criteria}",
        [],
        {},
    )
    m.go(m.next_linear("DEFINED"))
    commit(m, records_schema, event_schema, {directory / ENGINE_FILE: dump_json(engine)})
    return {
        "ok": True,
        "mission_id": mission_id,
        "mission_dir": str(directory),
        "next": m.next_info(with_context=True),
    }


def read_draft_text(source: str) -> str:
    try:
        if source == "-":
            return sys.stdin.buffer.read().decode("utf-8-sig")
        return Path(source).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise EngineError(f"cannot read drafts from {source}: {exc}") from None


def validate_drafts(m: Mission, text: str) -> list[dict]:
    if m.doc["state"]["status"] != "active":
        raise EngineError(f"mission is {m.doc['state']['status']}; nothing can be appended")
    phase = m.phase
    actor = m.actor_for(phase)
    if actor is None:
        raise EngineError(f"phase {phase} takes no satellite drafts")
    try:
        drafts = json.loads(text)
    except ValueError as exc:
        raise EngineError(f"drafts are not valid JSON: {exc}") from None
    if not isinstance(drafts, list) or not drafts:
        raise EngineError("drafts must be a non-empty JSON array")

    errors = []
    produced = PHASE_PRODUCES[phase]
    ids = {r["id"] for r in m.doc["records"]}
    counts: dict[str, int] = {}
    for i, d in enumerate(drafts):
        tag = f"draft[{i}]"
        if not isinstance(d, dict):
            errors.append(f"{tag}: must be an object")
            continue
        for key in sorted(RUNTIME_FIELDS & set(d)):
            errors.append(f"{tag}: '{key}' is assigned by the runtime and must not be present")
        for key in sorted(set(d) - DRAFT_FIELDS - RUNTIME_FIELDS):
            errors.append(f"{tag}: unknown field '{key}'")
        for key in sorted(DRAFT_REQUIRED - set(d)):
            errors.append(f"{tag}: missing required field '{key}'")
        author, rtype = d.get("author"), d.get("type")
        if "author" in d and author != actor:
            errors.append(f"{tag}: author {author!r} is not the active satellite {actor!r} for {phase}")
        if "type" in d:
            if rtype not in (produced, "note"):
                errors.append(f"{tag}: type {rtype!r} is not allowed in {phase} (expected {produced!r} or 'note')")
            elif rtype not in m.roles[actor]["writes"]:
                errors.append(f"{tag}: {actor} may not write {rtype!r}")
            counts[rtype] = counts.get(rtype, 0) + 1
        if "content" in d and not isinstance(d["content"], str):
            errors.append(f"{tag}: content must be a string")
        refs = d.get("refs")
        if "refs" in d:
            if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
                errors.append(f"{tag}: refs must be an array of record ids")
            else:
                for r in refs:
                    if r not in ids:
                        errors.append(f"{tag}: ref {r!r} does not exist")
        if rtype == "critique" and not isinstance(d.get("blocking"), bool):
            errors.append(f"{tag}: a critique requires boolean 'blocking'")
        if rtype != "critique" and "blocking" in d:
            errors.append(f"{tag}: 'blocking' is only allowed on a critique")
        if rtype == "verdict":
            if d.get("verdict") not in ("APPROVED", "NEEDS_REVISION", "REJECTED"):
                errors.append(f"{tag}: a verdict requires 'verdict' APPROVED, NEEDS_REVISION or REJECTED")
            if d.get("verdict") == "NEEDS_REVISION":
                if m.iteration >= m.max_iterations:
                    errors.append(
                        f"{tag}: NEEDS_REVISION is invalid at iteration {m.iteration} "
                        f"(max_iterations {m.max_iterations}); choose APPROVED or REJECTED"
                    )
                if "punk-03-edison" not in m.roster:
                    errors.append(f"{tag}: NEEDS_REVISION is invalid because punk-03-edison is not in the roster")
        elif "verdict" in d:
            errors.append(f"{tag}: 'verdict' is only allowed on a verdict record")

    if counts.get(produced, 0) == 0:
        errors.append(f"{phase} must produce at least one {produced!r} record")
    if produced in ("critique", "verdict") and counts.get(produced, 0) > 1:
        errors.append(f"{phase} must contain exactly one {produced!r} record")
    if errors:
        raise EngineError(errors)
    return drafts


def cmd_append(args) -> dict:
    directory = resolve_dir(args)
    m, records_schema, event_schema = load_mission(directory)
    drafts = validate_drafts(m, read_draft_text(args.draft_file))

    phase, actor = m.phase, m.actor_for(m.phase)
    written = []
    for d in drafts:
        extra = {k: d[k] for k in ("confidence", "blocking", "verdict") if k in d}
        written.append(m.add_record(d["author"], d["type"], d["content"], d["refs"], extra))
    m.add_event("satellite_idle", actor, {"phase": phase})

    main_rec = next(r for r in written if r["type"] == PHASE_PRODUCES[phase])
    if phase == "CRITIQUE":
        revise = (
            main_rec["blocking"]
            and m.iteration < m.max_iterations
            and "punk-03-edison" in m.roster  # REVISION is skipped without its satellite
        )
        m.go("REVISION" if revise else "VERDICT")
    elif phase == "REVISION":
        m.go("CRITIQUE" if "punk-02-lilith" in m.roster else "VERDICT")
    elif phase == "VERDICT":
        value = main_rec["verdict"]
        if value == "REJECTED":
            m.terminate("FAILED", "mission_failed", f"Verdict REJECTED ({main_rec['id']})",
                        {"record_id": main_rec["id"]})
        elif value == "NEEDS_REVISION":
            m.go("REVISION")
        else:
            m.go(m.next_linear("VERDICT"))
    else:
        m.go(m.next_linear(phase))

    commit(m, records_schema, event_schema)
    return {"ok": True, "records": [r["id"] for r in written], "next": m.next_info(with_context=True)}


def cmd_note(args) -> dict:
    m, records_schema, event_schema = load_mission(resolve_dir(args))
    status = m.doc["state"]["status"]
    if status != "active":
        raise EngineError(f"mission is {status}; notes can no longer be recorded")
    if args.text is not None:
        text = args.text
    else:
        try:
            text = Path(args.text_file).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise EngineError(f"cannot read note from {args.text_file}: {exc}") from None
        if text.endswith("\r\n"):  # drop only the final line break of the file
            text = text[:-2]
        elif text.endswith("\n"):
            text = text[:-1]
    if not text.strip():
        raise EngineError("note text must not be empty")
    refs = list(args.refs or [])
    ids = {r["id"] for r in m.doc["records"]}
    missing = [rid for rid in refs if rid not in ids]
    if missing:
        raise EngineError([f"ref {rid!r} does not exist" for rid in missing])
    m.add_record("stella", "note", text, refs, {})
    commit(m, records_schema, event_schema)
    return {"ok": True, "record_id": m.doc["records"][-1]["id"], "next": m.next_info(with_context=True)}


def cmd_approve(args) -> dict:
    m, records_schema, event_schema = load_mission(resolve_dir(args))
    if m.doc["state"]["status"] != "active" or m.phase != "HITL_APPROVAL":
        raise EngineError(f"approve is only valid in HITL_APPROVAL (current phase: {m.phase})")
    m.add_event("hitl_resolved", "stella", {"decision": "approved"})
    verdict = m.last_record("verdict")
    content = "Approved." + (f"\n\n{args.note}" if args.note else "")
    m.add_record("stella", "approval", content, [verdict["id"]] if verdict else [], {})
    m.go(m.next_linear("HITL_APPROVAL"))
    commit(m, records_schema, event_schema)
    return {"ok": True, "next": m.next_info(with_context=True)}


def cmd_abort(args) -> dict:
    m, records_schema, event_schema = load_mission(resolve_dir(args))
    if m.doc["state"]["status"] != "active":
        raise EngineError(f"mission is already {m.doc['state']['status']}")
    if m.phase == "HITL_APPROVAL":
        m.add_event("hitl_resolved", "stella", {"decision": "aborted"})
    m.terminate("ABORTED", "mission_aborted", args.reason)
    commit(m, records_schema, event_schema)
    return {"ok": True, "next": m.next_info()}


def cmd_fail(args) -> dict:
    m, records_schema, event_schema = load_mission(resolve_dir(args))
    if m.doc["state"]["status"] != "active":
        raise EngineError(f"mission is already {m.doc['state']['status']}")
    m.terminate("FAILED", "mission_failed", args.reason)
    commit(m, records_schema, event_schema)
    return {"ok": True, "next": m.next_info()}


def cmd_status(args) -> dict:
    m, _, _ = load_mission(resolve_dir(args))
    listing = []
    for r in m.doc["records"]:
        item = {k: r[k] for k in ("id", "author", "type", "phase", "iteration")}
        for key in ("blocking", "verdict"):
            if key in r:
                item[key] = r[key]
        listing.append(item)
    return {
        "ok": True,
        "mission_id": m.doc["mission"]["id"],
        "phase": m.phase,
        "iteration": m.iteration,
        "max_iterations": m.max_iterations,
        "status": m.doc["state"]["status"],
        "roster": m.roster,
        "next": m.next_info(),
        "records": listing,
    }


def cmd_show(args) -> dict:
    m, _, _ = load_mission(resolve_dir(args))
    by_id = {r["id"]: r for r in m.doc["records"]}
    missing = [rid for rid in args.ids if rid not in by_id]
    if missing:
        raise EngineError([f"record {rid!r} does not exist" for rid in missing])
    return {"ok": True, "records": [by_id[rid] for rid in args.ids]}


DELIVERABLE_FILE = "deliverable.md"


def cmd_report(args) -> dict:
    directory = resolve_dir(args)
    m, _, _ = load_mission(directory)
    status = m.doc["state"]["status"]
    if status == "active":
        raise EngineError("report is only valid on a finished mission (status: active)")
    records = m.doc["records"]
    verdict = m.last_record("verdict")
    chosen: list[dict] = []
    if status == "completed":
        chosen = [r for r in records if r["type"] == "artifact"]
        if not chosen:
            before = records[: records.index(verdict)] if verdict else records
            for r in reversed(before):
                if r["type"] in ("proposal", "revision"):
                    chosen = [r]
                    break
    if verdict:
        chosen.append(verdict)

    parts = [
        f"# Mission {m.doc['mission']['id']}\n\n"
        f"- Status: {status}\n- Iteration: {m.iteration}\n"
    ]
    for r in chosen:
        parts.append(f"## {r['id']} — {r['author']} ({r['type']})\n\n{r['content']}\n")
    if status != "completed":
        reasons = [
            e["payload"].get("reason")
            for e in m.events
            if e["type"] in ("mission_failed", "mission_aborted")
        ]
        if reasons and reasons[-1]:
            parts.append(f"## Recorded reason\n\n{reasons[-1]}\n")
    path = directory / DELIVERABLE_FILE
    try:
        atomic_write_all({path: "\n".join(parts).encode("utf-8")})
    except OSError as exc:
        raise EngineError(f"cannot write {path}: {exc}") from None
    return {
        "ok": True,
        "path": str(path),
        "status": status,
        "iteration": m.iteration,
        "record_ids": [r["id"] for r in chosen],
        "passed_hitl": any(
            e["type"] == "phase_changed" and e["payload"]["to"] == "HITL_APPROVAL" for e in m.events
        ),
    }


def select_context(m: Mission, satellite: str, full: bool, include: list[str]) -> tuple[list[dict], int]:
    """Pick the records to pass to the active satellite (read-only).

    Returns (records in original order, number of readable records).
    """
    records = m.doc["records"]
    by_id = {r["id"]: r for r in records}
    reads = set(m.roles[satellite]["reads"])
    readable = {r["id"] for r in records if r["type"] in reads}

    errors = []
    for rid in include:
        if rid not in by_id:
            errors.append(f"--include {rid!r} does not exist")
        elif rid not in readable:
            errors.append(f"--include {rid!r} has type {by_id[rid]['type']!r}, which {satellite} may not read")
    if errors:
        raise EngineError(errors)

    if full:
        chosen = set(readable)
    else:
        floor = m.iteration - 1  # current and previous iteration
        chosen = set(include)
        for r in records:
            if r["id"] not in readable:
                continue
            if (
                r["type"] in ("goal", "finding")
                or r["iteration"] >= floor
                or (satellite == "punk-01-shaka" and r["type"] == "critique" and r.get("blocking") is True)
            ):
                chosen.add(r["id"])
        for rid in list(chosen):  # one level of refs, from the records chosen above
            chosen.update(ref for ref in by_id[rid]["refs"] if ref in readable)
    return [r for r in records if r["id"] in chosen], len(readable)


def cmd_context(args) -> dict:
    m, _, _ = load_mission(resolve_dir(args))
    satellite = m.actor_for(m.phase)
    if m.doc["state"]["status"] != "active" or satellite is None:
        raise EngineError(
            f"context is only valid while a satellite is active (current phase: {m.phase}, "
            f"status: {m.doc['state']['status']})"
        )
    return build_context(m, satellite, args.full, args.include or [])


def build_context(m: Mission, satellite: str, full: bool, include: list[str]) -> dict:
    """The exact output of the `context` command for the given satellite."""
    passed, readable = select_context(m, satellite, full, include)
    mission = m.doc["mission"]
    return {
        "ok": True,
        "satellite": satellite,
        "mission": {k: mission[k] for k in ("goal", "mode", "roster", "constraints", "max_iterations")},
        "state": {"phase": m.phase, "iteration": m.iteration},
        "records": passed,
        "selection": {
            "mode": "full" if full else "selective",
            "records_passed": len(passed),
            "records_readable": readable,
            "content_chars": sum(len(r["content"]) for r in passed),
        },
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--mission-dir", help="mission folder (default: .vegapunk/missions/<mission-id>/)")
    common.add_argument("--mission-id", help="mission id; used to locate the default mission folder")

    ap = argparse.ArgumentParser(description="Deterministic Punk Records engine (JSON in, JSON out).")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", parents=[common], help="create a mission")
    p.add_argument("--goal", required=True)
    p.add_argument("--constraint", action="append")
    p.add_argument("--done-criterion", action="append", metavar="TEXT")
    p.add_argument("--mode", required=True, choices=["light", "standard", "full"])
    p.add_argument("--roster", nargs="+", metavar="ID")
    p.add_argument("--max-iterations", type=int, default=2)
    p.add_argument("--hitl-after-verdict", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("append", parents=[common], help="append satellite record drafts")
    p.add_argument("--draft-file", required=True, help="JSON array file, or '-' for stdin")
    p.set_defaults(func=cmd_append)

    p = sub.add_parser("note", parents=[common], help="record Stella's own words as a note")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", help="note text, recorded as given")
    src.add_argument("--text-file", help="file holding the note text (final line break dropped)")
    p.add_argument("--refs", nargs="+", action="extend", metavar="ID", help="records the note refers to")
    p.set_defaults(func=cmd_note)

    p = sub.add_parser("approve", parents=[common], help="Stella approves at HITL_APPROVAL")
    p.add_argument("--note")
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("abort", parents=[common], help="Stella aborts the mission")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_abort)

    p = sub.add_parser("fail", parents=[common], help="mark an unrecoverable failure")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_fail)

    p = sub.add_parser("status", parents=[common], help="show phase, roster, next actor and records")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("context", parents=[common], help="print the context for the active satellite (read-only)")
    p.add_argument("--full", action="store_true", help="pass every record the satellite may read")
    p.add_argument("--include", nargs="+", action="extend", metavar="ID",
                   help="also pass these records (e.g. to answer a note asking for context)")
    p.set_defaults(func=cmd_context)

    p = sub.add_parser("show", parents=[common], help="print full records by id, in the order requested (read-only)")
    p.add_argument("ids", nargs="+", metavar="ID")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("report", parents=[common], help="write deliverable.md for a finished mission")
    p.set_defaults(func=cmd_report)
    return ap


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", newline="\n")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help or argparse usage errors
        if exc.code in (0, None):
            return 0
        return fail("invalid arguments (see --help)")
    try:
        return emit(args.func(args))
    except EngineError as exc:
        return fail(exc.errors)
    except Exception as exc:  # never leave a traceback on stdout consumers
        return fail(f"unexpected error: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
