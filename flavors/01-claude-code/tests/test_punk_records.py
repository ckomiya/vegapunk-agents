# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Christian Gonzales Komiya
"""Tests for .claude/vegapunk/punk_records.py (run: python -m unittest discover -s <this dir>)."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

VEGAPUNK_DIR = Path(__file__).resolve().parent.parent / ".claude" / "vegapunk"
SCRIPT = VEGAPUNK_DIR / "punk_records.py"
TERMINAL_EVENTS = {"mission_completed", "mission_incomplete", "mission_failed", "mission_aborted"}


def load_schema(name: str) -> Draft202012Validator:
    schema = json.loads((VEGAPUNK_DIR / name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


RECORDS_VALIDATOR = load_schema("punk-records.schema.json")
EVENT_VALIDATOR = load_schema("event.schema.json")


def draft(author, rtype, content="Content.", refs=None, **extra):
    d = {"author": author, "type": rtype, "content": content, "refs": refs or []}
    if rtype == "finding":
        d.update(provenance="unsourced", sources=[])
    elif rtype == "ops_log":
        d.update(ready_to_close=True)
    d.update(extra)
    return d


APPROVAL_PAUSE = {"phase": "HITL_APPROVAL", "actor": "stella", "action": "await_hitl",
                  "kind": "approval", "decisions": ["approve", "abort"]}


def without_context(nxt):
    return {k: v for k, v in nxt.items() if k not in ("context_file", "context_sha256")}


def ctx_of(nxt):
    """The context a satellite would read: the file that `next` points to."""
    return json.loads(Path(nxt["context_file"]).read_text(encoding="utf-8"))


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "mission"

    # -- CLI helpers -----------------------------------------------------
    def run_cli(self, *args, stdin=None, mission=True):
        cmd = [sys.executable, str(SCRIPT), *args]
        if mission and args[0] != "init":
            cmd += ["--mission-dir", str(self.dir)]
        proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8")
        try:
            out = json.loads(proc.stdout)
        except ValueError:
            self.fail(f"stdout is not JSON: {proc.stdout!r} / stderr: {proc.stderr!r}")
        return proc.returncode, out

    def init(self, mode, *extra):
        code, out = self.run_cli("init", "--goal", "Test goal", "--constraint", "Be short",
                                 "--mode", mode, "--mission-dir", str(self.dir), *extra)
        self.assertEqual(code, 0, out)
        return out

    def append(self, *drafts):
        code, out = self.run_cli("append", "--draft-file", "-", stdin=json.dumps(list(drafts)))
        self.assertEqual(code, 0, out)
        return out

    def append_error(self, text):
        before = self.snapshot()
        code, out = self.run_cli("append", "--draft-file", "-", stdin=text)
        self.assertNotEqual(code, 0, out)
        self.assertFalse(out["ok"])
        self.assertTrue(out["errors"])
        self.assertEqual(self.snapshot(), before, "a rejected draft must not write anything")
        return out["errors"]

    def snapshot(self):
        return {p.relative_to(self.dir).as_posix(): p.read_bytes() for p in sorted(self.dir.rglob("*")) if p.is_file()}

    # -- invariants ------------------------------------------------------
    def doc(self):
        return json.loads((self.dir / "punk-records.json").read_text(encoding="utf-8"))

    def events(self):
        text = (self.dir / "events.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("\r", text)
        return [json.loads(line) for line in text.split("\n") if line]

    def assert_valid(self):
        doc = self.doc()
        self.assertEqual([], [e.message for e in RECORDS_VALIDATOR.iter_errors(doc)])
        events = self.events()
        for ev in events:
            self.assertEqual([], [e.message for e in EVENT_VALIDATOR.iter_errors(ev)], ev)
        self.assertEqual([e["seq"] for e in events], list(range(1, len(events) + 1)))
        terminal = [e for e in events if e["type"] in TERMINAL_EVENTS]
        if doc["state"]["status"] == "active":
            self.assertEqual(terminal, [])
        else:
            self.assertEqual(len(terminal), 1)
            self.assertEqual(events[-1], terminal[0])
        return doc, events

    def phases(self):
        return [e["payload"]["to"] for e in self.events() if e["type"] == "phase_changed"]


class LifecycleTests(Base):
    def test_1_light_without_hitl(self):
        out = self.init("light")
        self.assertEqual(without_context(out["next"]), {"phase": "IDEATION", "actor": "punk-03-edison", "action": "invoke_satellite"})
        out = self.append(draft("punk-03-edison", "proposal", refs=["r-001"]))
        self.assertEqual(out["next"]["phase"], "VERDICT")
        out = self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED", refs=["r-002"]))
        self.assertEqual(out["next"], {"phase": "COMPLETED", "actor": None, "action": "completed"})
        doc, events = self.assert_valid()
        self.assertEqual(doc["state"]["status"], "completed")
        self.assertEqual(self.phases(), ["IDEATION", "VERDICT", "COMPLETED"])
        self.assertNotIn("hitl_requested", [e["type"] for e in events])
        goal = doc["records"][0]
        self.assertEqual((goal["id"], goal["author"], goal["type"]), ("r-001", "stella", "goal"))
        self.assertIn("## Outcome", goal["content"])
        self.assertIn("## Constraints", goal["content"])
        self.assertIn("## Done-criteria\nNone.", goal["content"])

    def test_init_goal_has_three_sections(self):
        code, out = self.run_cli(
            "init", "--goal", "Pick a name", "--constraint", "One page", "--constraint", "No tooling",
            "--done-criterion", "Covers every item", "--done-criterion", "Readable once",
            "--mode", "light", "--mission-dir", str(self.dir),
        )
        self.assertEqual(code, 0, out)
        doc, _ = self.assert_valid()
        self.assertEqual(
            doc["records"][0]["content"],
            "## Outcome\nPick a name\n\n## Constraints\n- One page\n- No tooling\n\n"
            "## Done-criteria\n- Covers every item\n- Readable once",
        )

    def test_2_light_with_hitl_after_verdict(self):
        self.init("light", "--hitl-after-verdict")
        self.append(draft("punk-03-edison", "proposal"))
        out = self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED"))
        self.assertEqual(out["next"], APPROVAL_PAUSE)
        events = self.events()
        requested = [e for e in events if e["type"] == "hitl_requested"]
        self.assertEqual(requested[0]["payload"]["record_id"], "r-003")
        out = self.run_cli("approve", "--note", "Go.")[1]
        self.assertEqual(out["next"]["action"], "completed")
        doc, events = self.assert_valid()
        self.assertEqual(doc["records"][-1]["type"], "approval")
        self.assertEqual(self.phases()[-2:], ["HITL_APPROVAL", "COMPLETED"])
        self.assertIn("hitl_resolved", [e["type"] for e in events])

    def test_3_standard_blocking_critiques_hit_loop_limit(self):
        self.init("standard")
        self.append(draft("punk-04-pythagoras", "finding", refs=["r-001"]))
        self.append(draft("punk-03-edison", "proposal"))
        for expected_iteration in (1, 2):
            out = self.append(draft("punk-02-lilith", "critique", blocking=True))
            self.assertEqual(out["next"]["phase"], "REVISION")
            self.assertEqual(self.doc()["state"]["iteration"], expected_iteration)
            self.append(draft("punk-03-edison", "revision"))
        out = self.append(draft("punk-02-lilith", "critique", blocking=True))
        self.assertEqual(without_context(out["next"]), {"phase": "VERDICT", "actor": "punk-01-shaka", "action": "invoke_satellite"})
        self.assertEqual(self.doc()["state"]["iteration"], 2)
        errors = self.append_error(json.dumps([draft("punk-01-shaka", "verdict", verdict="NEEDS_REVISION")]))
        self.assertTrue(any("NEEDS_REVISION" in e for e in errors))
        out = self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED"))
        self.assertEqual(out["next"]["action"], "completed")
        doc, _ = self.assert_valid()
        self.assertEqual(doc["state"]["iteration"], 2)
        self.assertEqual(
            self.phases(),
            ["RESEARCH", "IDEATION", "CRITIQUE", "REVISION", "CRITIQUE", "REVISION", "CRITIQUE", "VERDICT", "COMPLETED"],
        )

    def test_3b_needs_revision_goes_back_to_revision(self):
        self.init("light")
        self.append(draft("punk-03-edison", "proposal"))
        out = self.append(draft("punk-01-shaka", "verdict", verdict="NEEDS_REVISION"))
        self.assertEqual(out["next"]["phase"], "REVISION")
        self.assertEqual(self.doc()["state"]["iteration"], 1)
        out = self.append(draft("punk-03-edison", "revision"))
        self.assertEqual(out["next"]["phase"], "VERDICT")  # no lilith in light mode
        self.assert_valid()

    def test_4_max_iterations_zero_blocking_goes_to_verdict(self):
        self.init("standard", "--max-iterations", "0")
        self.append(draft("punk-04-pythagoras", "finding"))
        self.append(draft("punk-03-edison", "proposal"))
        out = self.append(draft("punk-02-lilith", "critique", blocking=True))
        self.assertEqual(out["next"]["phase"], "VERDICT")
        self.assertEqual(self.doc()["state"]["iteration"], 0)
        self.assertTrue(self.append_error(json.dumps([draft("punk-01-shaka", "verdict", verdict="NEEDS_REVISION")])))
        self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED"))
        self.assert_valid()
        self.assertNotIn("REVISION", self.phases())

    def test_5_full_egghead(self):
        out = self.init("full")
        self.assertEqual(out["next"]["phase"], "RESEARCH")
        self.append(draft("punk-04-pythagoras", "finding"))
        self.append(draft("punk-03-edison", "proposal"))
        self.append(draft("punk-02-lilith", "critique", blocking=False))
        out = self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED"))
        self.assertEqual(out["next"], APPROVAL_PAUSE)
        self.assertTrue(self.append_error(json.dumps([draft("punk-05-atlas", "artifact")])))  # no drafts at HITL
        out = self.run_cli("approve")[1]
        self.assertEqual(without_context(out["next"]), {"phase": "EXECUTION", "actor": "punk-05-atlas", "action": "invoke_satellite"})
        out = self.append(draft("punk-05-atlas", "artifact"))
        self.assertEqual(out["next"]["phase"], "OPERATIONS")
        out = self.append(draft("punk-06-york", "ops_log", "Done."))
        self.assertEqual(out["next"]["action"], "completed")
        doc, events = self.assert_valid()
        self.assertEqual(
            self.phases(),
            ["RESEARCH", "IDEATION", "CRITIQUE", "VERDICT", "HITL_APPROVAL", "EXECUTION", "OPERATIONS", "COMPLETED"],
        )
        self.assertEqual(len([e for e in events if e["type"] == "hitl_requested"]), 1)
        self.assertEqual(len([e for e in events if e["type"] == "satellite_activated"]), 6)

    def test_5b_atlas_without_york_skips_operations(self):
        self.init("light", "--roster", "punk-03-edison", "punk-01-shaka", "punk-05-atlas")
        self.append(draft("punk-03-edison", "proposal"))
        out = self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED"))
        self.assertEqual(out["next"]["action"], "await_hitl")  # mandatory with atlas
        self.run_cli("approve")
        self.append(draft("punk-05-atlas", "artifact"))
        self.assertEqual(self.doc()["state"]["status"], "completed")
        self.assert_valid()

    def test_6a_rejected_fails(self):
        self.init("light")
        self.append(draft("punk-03-edison", "proposal"))
        out = self.append(draft("punk-01-shaka", "verdict", verdict="REJECTED"))
        self.assertEqual(out["next"], {"phase": "FAILED", "actor": None, "action": "failed"})
        doc, events = self.assert_valid()
        self.assertEqual(doc["state"]["status"], "failed")
        self.assertEqual(events[-1]["type"], "mission_failed")
        self.assertIn("REJECTED", events[-1]["payload"]["reason"])
        code, out = self.run_cli("append", "--draft-file", "-", stdin="[]")
        self.assertNotEqual(code, 0)

    def test_6b_abort_midway(self):
        self.init("standard")
        self.append(draft("punk-04-pythagoras", "finding"))
        code, out = self.run_cli("abort", "--reason", "Wrong goal")
        self.assertEqual(code, 0)
        self.assertEqual(out["next"]["action"], "aborted")
        doc, events = self.assert_valid()
        self.assertEqual(doc["state"]["phase"], "ABORTED")
        self.assertEqual(doc["state"]["status"], "aborted")
        self.assertEqual(events[-1]["type"], "mission_aborted")
        self.assertNotIn("hitl_resolved", [e["type"] for e in events])
        self.assertNotEqual(self.run_cli("abort", "--reason", "again")[0], 0)

    def test_6c_abort_at_hitl_emits_hitl_resolved(self):
        self.init("light", "--hitl-after-verdict")
        self.append(draft("punk-03-edison", "proposal"))
        self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED"))
        self.run_cli("abort", "--reason", "No")
        _, events = self.assert_valid()
        self.assertEqual([e["type"] for e in events[-3:]], ["hitl_resolved", "phase_changed", "mission_aborted"])
        self.assertEqual(events[-3]["payload"]["decision"], "aborted")

    def test_6d_fail_command(self):
        self.init("light")
        code, _ = self.run_cli("fail", "--reason", "Boom")
        self.assertEqual(code, 0)
        doc, events = self.assert_valid()
        self.assertEqual((doc["state"]["status"], events[-1]["type"]), ("failed", "mission_failed"))

    def test_approve_outside_hitl_is_rejected(self):
        self.init("light")
        before = self.snapshot()
        self.assertNotEqual(self.run_cli("approve")[0], 0)
        self.assertEqual(self.snapshot(), before)

    def test_status_hides_content(self):
        self.init("standard")
        code, out = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertEqual(out["phase"], "RESEARCH")
        self.assertEqual(out["roster"], ["punk-04-pythagoras", "punk-03-edison", "punk-02-lilith", "punk-01-shaka"])
        self.assertEqual(out["records"], [{"id": "r-001", "author": "stella", "type": "goal", "phase": "DEFINED", "iteration": 0}])
        self.assertNotIn("content", json.dumps(out))

    def test_draft_file_argument(self):
        self.init("light")
        path = Path(self._tmp.name) / "d.json"
        path.write_text(json.dumps([draft("punk-03-edison", "proposal")]), encoding="utf-8")
        code, out = self.run_cli("append", "--draft-file", str(path))
        self.assertEqual(code, 0, out)

    def test_notes_are_accepted_alongside_the_main_record(self):
        self.init("light")
        out = self.append(draft("punk-03-edison", "note", "Aside."), draft("punk-03-edison", "proposal"))
        self.assertEqual(out["records"], ["r-002", "r-003"])
        self.assert_valid()


class InvalidDraftTests(Base):
    def setUp(self):
        super().setUp()
        self.init("standard")  # active: RESEARCH / pythagoras
        self.append(draft("punk-04-pythagoras", "finding"))
        self.append(draft("punk-03-edison", "proposal"))  # now CRITIQUE / lilith

    def test_wrong_author(self):
        self.append_error(json.dumps([draft("punk-03-edison", "critique", blocking=False)]))

    def test_lilith_writing_verdict(self):
        self.append_error(json.dumps([draft("punk-02-lilith", "verdict", verdict="APPROVED")]))

    def test_critique_without_blocking(self):
        errors = self.append_error(json.dumps([draft("punk-02-lilith", "critique")]))
        self.assertTrue(any("blocking" in e for e in errors))

    def test_two_critiques(self):
        self.append_error(json.dumps([draft("punk-02-lilith", "critique", blocking=False)] * 2))

    def test_note_only(self):
        self.append_error(json.dumps([draft("punk-02-lilith", "note")]))

    def test_nonexistent_ref(self):
        errors = self.append_error(json.dumps([draft("punk-02-lilith", "critique", refs=["r-099"], blocking=False)]))
        self.assertTrue(any("r-099" in e for e in errors))

    def test_draft_with_id_field(self):
        errors = self.append_error(json.dumps([draft("punk-02-lilith", "critique", blocking=False, id="r-010")]))
        self.assertTrue(any("'id'" in e for e in errors))

    def test_runtime_fields_rejected(self):
        for field, value in (("phase", "CRITIQUE"), ("iteration", 0), ("created_at", "2026-01-01T00:00:00Z")):
            self.append_error(json.dumps([draft("punk-02-lilith", "critique", blocking=False, **{field: value})]))

    def test_not_json(self):
        self.append_error("this is not json")

    def test_not_an_array_or_empty(self):
        self.append_error("{}")
        self.append_error("[]")
        self.append_error("[1]")

    def test_blocking_on_non_critique(self):
        self.append_error(json.dumps([draft("punk-02-lilith", "critique", blocking=False),
                                      draft("punk-02-lilith", "note", blocking=True)]))

    def test_out_of_range_confidence(self):
        self.append_error(json.dumps([draft("punk-02-lilith", "critique", blocking=False, confidence=1.5)]))

    def test_rejected_drafts_do_not_advance_state(self):
        self.append_error("nope")
        self.assertEqual(self.run_cli("status")[1]["phase"], "CRITIQUE")


class InitTests(Base):
    def test_8_roster_without_shaka(self):
        code, out = self.run_cli("init", "--goal", "G", "--mode", "light",
                                 "--roster", "punk-03-edison", "punk-02-lilith",
                                 "--mission-dir", str(self.dir))
        self.assertNotEqual(code, 0)
        self.assertTrue(any("punk-01-shaka" in e for e in out["errors"]))
        self.assertFalse(self.dir.exists())

    def test_non_canonical_roster_id(self):
        code, out = self.run_cli("init", "--goal", "G", "--mode", "light",
                                 "--roster", "punk-01-shaka", "punk-07-nobody",
                                 "--mission-dir", str(self.dir))
        self.assertNotEqual(code, 0)
        self.assertFalse(self.dir.exists())

    def test_init_twice_is_rejected(self):
        self.init("light")
        before = self.snapshot()
        code, _ = self.run_cli("init", "--goal", "G", "--mode", "light", "--mission-dir", str(self.dir))
        self.assertNotEqual(code, 0)
        self.assertEqual(self.snapshot(), before)

    def test_engine_json_and_defaults(self):
        self.init("light", "--hitl-after-verdict")
        engine = json.loads((self.dir / "engine.json").read_text(encoding="utf-8"))
        self.assertTrue(engine["hitl_after_verdict"])
        doc = self.doc()
        self.assertEqual(doc["mission"]["max_iterations"], 2)
        self.assertEqual(doc["mission"]["roster"], ["punk-03-edison", "punk-01-shaka"])
        self.assertEqual(doc["mission"]["constraints"], ["Be short"])
        self.assertEqual(doc["state"], {**doc["state"], "iteration": 0, "status": "active"})

    JSON_RULE = "Output must be valid JSON: escape backslashes and double quotes inside strings."

    def assertLimits(self, got, limits):
        self.assertEqual({k: v for k, v in got.items() if k != "rules"}, limits)
        self.assertIn(self.JSON_RULE, got["rules"])

    def test_json_rule_comes_from_the_script_for_every_satellite(self):
        out = self.init("standard")
        self.assertIn(self.JSON_RULE, ctx_of(out["next"])["runtime_limits"]["rules"])
        nxt = self.append(draft("punk-04-pythagoras", "finding"))["next"]
        self.assertIn(self.JSON_RULE, ctx_of(nxt)["runtime_limits"]["rules"])
        self.assertNotEqual(nxt["actor"], "punk-04-pythagoras")

    def test_search_limit_defaults_to_3(self):
        out = self.init("light")
        engine = json.loads((self.dir / "engine.json").read_text(encoding="utf-8"))
        self.assertEqual(engine["search_limit"], 3)
        limits = {"web_searches": 3, "draft_words": 250}
        self.assertLimits(ctx_of(out["next"])["runtime_limits"], limits)
        code, ctx = self.run_cli("context")
        self.assertEqual(code, 0, ctx)
        self.assertLimits(ctx["runtime_limits"], limits)

    def test_search_limit_reaches_context_and_next_context(self):
        out = self.init("standard", "--search-limit", "6")
        limits = {"web_searches": 6, "draft_words": 250}
        self.assertLimits(ctx_of(out["next"])["runtime_limits"], limits)
        code, ctx = self.run_cli("context")
        self.assertEqual(code, 0, ctx)
        self.assertLimits(ctx["runtime_limits"], limits)
        nxt = self.append(draft("punk-04-pythagoras", "finding"))["next"]
        self.assertLimits(ctx_of(nxt)["runtime_limits"], limits)

    def test_search_limit_zero_is_allowed(self):
        out = self.init("light", "--search-limit", "0")
        self.assertEqual(ctx_of(out["next"])["runtime_limits"]["web_searches"], 0)

    def test_negative_search_limit_is_rejected(self):
        code, out = self.run_cli("init", "--goal", "G", "--mode", "light",
                                 "--mission-dir", str(self.dir), "--search-limit", "-1")
        self.assertNotEqual(code, 0)
        self.assertFalse(out["ok"])
        self.assertFalse((self.dir / "punk-records.json").exists())

    def test_mission_without_search_limit_uses_3(self):
        self.init("light")
        (self.dir / "engine.json").write_text('{"hitl_after_verdict": false}\n', encoding="utf-8")
        code, ctx = self.run_cli("context")
        self.assertEqual(code, 0, ctx)
        self.assertLimits(ctx["runtime_limits"], {"web_searches": 3, "draft_words": 250})

    def init_raw(self, *args):
        return self.run_cli("init", "--mode", "light", "--mission-dir", str(self.dir), *args)

    def test_goal_from_file_is_used_exactly(self):
        text = "Line one\n\n  Indented line with \"quotes\" and accents: café\nLast line"
        goal_file = Path(self._tmp.name) / "goal.txt"
        goal_file.write_bytes((text + "\n").encode("utf-8"))
        code, out = self.init_raw("--goal-file", str(goal_file))
        self.assertEqual(code, 0, out)
        doc = self.doc()
        self.assertEqual(doc["mission"]["goal"], text)
        self.assertTrue(doc["records"][0]["content"].startswith(f"## Outcome\n{text}\n\n## Constraints"))

    def test_empty_goal_file_is_rejected(self):
        goal_file = Path(self._tmp.name) / "goal.txt"
        goal_file.write_text("  \n", encoding="utf-8")
        code, out = self.init_raw("--goal-file", str(goal_file))
        self.assertNotEqual(code, 0)
        self.assertFalse(out["ok"])
        self.assertFalse((self.dir / "punk-records.json").exists())

    def test_goal_and_goal_file_together_are_rejected(self):
        goal_file = Path(self._tmp.name) / "goal.txt"
        goal_file.write_text("G", encoding="utf-8")
        code, out = self.init_raw("--goal", "G", "--goal-file", str(goal_file))
        self.assertNotEqual(code, 0)
        self.assertFalse((self.dir / "punk-records.json").exists())

    def test_no_goal_is_rejected(self):
        code, out = self.init_raw()
        self.assertNotEqual(code, 0)
        self.assertFalse((self.dir / "punk-records.json").exists())

    def test_draft_words_defaults_to_250(self):
        out = self.init("light")
        engine = json.loads((self.dir / "engine.json").read_text(encoding="utf-8"))
        self.assertEqual(engine["draft_words"], 250)
        self.assertEqual(ctx_of(out["next"])["runtime_limits"]["draft_words"], 250)

    def test_draft_words_reaches_context_and_next_context(self):
        out = self.init("standard", "--draft-words", "500")
        self.assertEqual(ctx_of(out["next"])["runtime_limits"]["draft_words"], 500)
        code, ctx = self.run_cli("context")
        self.assertEqual(code, 0, ctx)
        self.assertEqual(ctx["runtime_limits"]["draft_words"], 500)
        nxt = self.append(draft("punk-04-pythagoras", "finding"))["next"]
        self.assertEqual(ctx_of(nxt)["runtime_limits"]["draft_words"], 500)

    def test_invalid_draft_words_is_rejected(self):
        for value in ("0", "-5"):
            code, out = self.init_raw("--goal", "G", "--draft-words", value)
            self.assertNotEqual(code, 0, value)
            self.assertFalse(out["ok"])
            self.assertFalse((self.dir / "punk-records.json").exists())

    def test_mission_without_draft_words_uses_250(self):
        self.init("light")
        (self.dir / "engine.json").write_text('{"hitl_after_verdict": false}\n', encoding="utf-8")
        code, ctx = self.run_cli("context")
        self.assertEqual(code, 0, ctx)
        self.assertEqual(ctx["runtime_limits"]["draft_words"], 250)

    def test_default_mission_dir_uses_mission_id(self):
        cwd = Path(self._tmp.name)
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "init", "--goal", "G", "--mode", "light", "--mission-id", "m-1"],
            capture_output=True, text=True, cwd=cwd, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertTrue((cwd / ".vegapunk" / "missions" / "m-1" / "punk-records.json").is_file())


class ContextTests(Base):
    def context(self, *args):
        code, out = self.run_cli("context", *args)
        self.assertEqual(code, 0, out)
        return out

    def ids(self, out):
        return [r["id"] for r in out["records"]]

    def write_mission(self, phase, iteration, records, roster=None):
        """Hand-write a mission folder (for scenarios the real cycle cannot reach)."""
        ts = "2026-01-01T00:00:00Z"
        full = []
        for i, (author, rtype, rphase, riter, refs, extra) in enumerate(records, 1):
            rec = {"id": f"r-{i:03d}", "author": author, "type": rtype, "phase": rphase,
                   "iteration": riter, "content": f"{rtype} {i}", "refs": refs, **extra, "created_at": ts}
            full.append(rec)
        doc = {
            "schema_version": "0.3.0",
            "mission": {"id": "m-hand", "goal": "G", "mode": "standard", "constraints": [],
                        "roster": roster or ["punk-04-pythagoras", "punk-03-edison", "punk-02-lilith", "punk-01-shaka"],
                        "max_iterations": 2, "research_rounds": 1, "created_at": ts},
            "state": {"phase": phase, "iteration": iteration, "research_round": 1, "status": "active",
                      "updated_at": ts},
            "records": full,
        }
        self.assertEqual([], [e.message for e in RECORDS_VALIDATOR.iter_errors(doc)])
        self.dir.mkdir(parents=True)
        (self.dir / "punk-records.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        (self.dir / "events.jsonl").write_text("", encoding="utf-8")
        (self.dir / "engine.json").write_text('{"hitl_after_verdict": false}\n', encoding="utf-8")

    def loop_to_revision_2(self):
        """Standard mission stopped at REVISION, iteration 2. Record ids:
        r-001 goal, r-002 finding, r-003/r-004 notes (it 0), r-005 proposal, r-006 blocking critique (it 0),
        r-007 revision (it 1, cites r-004), r-008 blocking critique (it 1)."""
        self.init("standard")
        self.append(draft("punk-04-pythagoras", "finding", refs=["r-001"]),
                    draft("punk-04-pythagoras", "note", "Uncited."),
                    draft("punk-04-pythagoras", "note", "Cited later."))
        self.append(draft("punk-03-edison", "proposal"))
        self.append(draft("punk-02-lilith", "critique", blocking=True))
        self.append(draft("punk-03-edison", "revision", refs=["r-004"]))
        self.append(draft("punk-02-lilith", "critique", blocking=True))
        self.assertEqual(self.doc()["state"]["iteration"], 2)

    def test_1_pythagoras_never_receives_unreadable_types(self):
        self.write_mission("RESEARCH", 0, [
            ("stella", "goal", "DEFINED", 0, [], {}),
            ("punk-03-edison", "proposal", "IDEATION", 0, ["r-001"], {}),
            ("punk-02-lilith", "critique", "CRITIQUE", 0, ["r-002"], {"blocking": False}),
            ("punk-02-lilith", "note", "CRITIQUE", 0, [], {}),
        ])
        out = self.context()
        self.assertEqual(out["satellite"], "punk-04-pythagoras")
        self.assertEqual(self.ids(out), ["r-001", "r-003", "r-004"])
        self.assertNotIn("proposal", {r["type"] for r in out["records"]})
        self.assertEqual(out["selection"], {"mode": "selective", "records_passed": 3, "records_readable": 3,
                                            "content_chars": sum(len(r["content"]) for r in out["records"])})
        self.assertEqual(out["mission"], {"goal": "G", "mode": "standard", "constraints": [],
                                          "roster": ["punk-04-pythagoras", "punk-03-edison", "punk-02-lilith", "punk-01-shaka"],
                                          "max_iterations": 2, "research_rounds": 1})
        self.assertEqual(out["state"], {"phase": "RESEARCH", "iteration": 0, "research_round": 1})

    def test_2_edison_in_revision_selects_recent_iterations_and_refs(self):
        self.loop_to_revision_2()
        out = self.context()
        self.assertEqual(out["satellite"], "punk-03-edison")
        # r-003 (uncited it-0 note), r-005 (proposal it 0) and r-006 (critique it 0) are left out;
        # r-004 (it 0) comes in through the ref of r-007.
        self.assertEqual(self.ids(out), ["r-001", "r-002", "r-004", "r-007", "r-008"])
        self.assertEqual(out["selection"]["records_readable"], 8)

    def test_3_shaka_receives_old_blocking_critiques(self):
        self.loop_to_revision_2()
        self.append(draft("punk-03-edison", "revision"))
        self.append(draft("punk-02-lilith", "critique", blocking=True))
        out = self.context()
        self.assertEqual(out["satellite"], "punk-01-shaka")
        self.assertEqual(out["state"], {"phase": "VERDICT", "iteration": 2, "research_round": 1})
        self.assertIn("r-006", self.ids(out))  # blocking critique of iteration 0, cited by no one
        self.assertNotIn("r-003", self.ids(out))

    def test_4_records_are_unaltered_and_in_original_order(self):
        self.loop_to_revision_2()
        by_id = {r["id"]: r for r in self.doc()["records"]}
        for args in ((), ("--full",), ("--include", "r-003")):
            out = self.context(*args)
            self.assertEqual(self.ids(out), sorted(self.ids(out)))
            for rec in out["records"]:
                self.assertEqual(rec, by_id[rec["id"]])

    def test_5_full_returns_every_readable_record(self):
        self.loop_to_revision_2()
        selective, full = self.context(), self.context("--full")
        self.assertEqual(full["selection"]["mode"], "full")
        self.assertEqual(self.ids(full), [f"r-{i:03d}" for i in range(1, 9)])
        self.assertLessEqual(selective["selection"]["records_passed"], full["selection"]["records_passed"])
        self.assertLess(selective["selection"]["content_chars"], full["selection"]["content_chars"])

    def test_5b_full_still_filters_by_type(self):
        self.write_mission("RESEARCH", 0, [
            ("stella", "goal", "DEFINED", 0, [], {}),
            ("punk-03-edison", "proposal", "IDEATION", 0, [], {}),
        ])
        self.assertEqual(self.ids(self.context("--full")), ["r-001"])

    def test_6_include_adds_old_readable_record(self):
        self.loop_to_revision_2()
        out = self.context("--include", "r-003")
        self.assertIn("r-003", self.ids(out))
        self.assertEqual(out["selection"]["records_passed"], self.context()["selection"]["records_passed"] + 1)
        out = self.context("--include", "r-003", "--include", "r-005")  # repeated flags accumulate
        self.assertTrue({"r-003", "r-005"} <= set(self.ids(out)))

    def test_6b_include_also_passes_readable_refs_of_the_included_record(self):
        self.write_mission("REVISION", 2, [
            ("stella", "goal", "DEFINED", 0, [], {}),
            ("punk-04-pythagoras", "note", "RESEARCH", 0, [], {}),
            ("punk-04-pythagoras", "note", "RESEARCH", 0, ["r-002"], {}),
            ("punk-04-pythagoras", "note", "RESEARCH", 0, [], {}),
        ])
        self.assertEqual(self.ids(self.context()), ["r-001"])
        self.assertEqual(self.ids(self.context("--include", "r-003")), ["r-001", "r-002", "r-003"])

    def test_6c_include_rejects_missing_or_unreadable_ids(self):
        self.write_mission("RESEARCH", 0, [
            ("stella", "goal", "DEFINED", 0, [], {}),
            ("punk-03-edison", "proposal", "IDEATION", 0, [], {}),
        ])
        for bad in ("r-099", "r-002"):  # nonexistent / proposal, unreadable for pythagoras
            code, out = self.run_cli("context", "--include", bad)
            self.assertNotEqual(code, 0)
            self.assertFalse(out["ok"])
            self.assertNotIn("records", out)
            self.assertTrue(any(bad in e for e in out["errors"]))
        code, out = self.run_cli("context", "--include", "r-001", "r-099")
        self.assertNotEqual(code, 0)
        self.assertNotIn("records", out)

    def test_7_context_requires_an_active_satellite(self):
        self.init("light", "--hitl-after-verdict")
        self.append(draft("punk-03-edison", "proposal"))
        self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED"))
        code, out = self.run_cli("context")
        self.assertNotEqual((code, out["ok"]), (0, True))
        self.assertTrue(out["errors"])
        self.run_cli("approve")
        self.assertEqual(self.doc()["state"]["phase"], "COMPLETED")
        self.assertNotEqual(self.run_cli("context")[0], 0)
        self.run_cli("init", "--goal", "G", "--mode", "light", "--mission-dir", str(self.dir.parent / "m2"))
        aborted = self.dir.parent / "m2"
        proc = subprocess.run([sys.executable, str(SCRIPT), "abort", "--reason", "x", "--mission-dir", str(aborted)],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        proc = subprocess.run([sys.executable, str(SCRIPT), "context", "--mission-dir", str(aborted)],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(json.loads(proc.stdout)["ok"])

    def test_8_context_is_read_only(self):
        self.loop_to_revision_2()
        before = self.snapshot()
        self.context()
        self.context("--full")
        self.context("--include", "r-003")
        self.run_cli("context", "--include", "r-099")
        self.assertEqual(self.snapshot(), before)


class ShowTests(Base):
    def setUp(self):
        super().setUp()
        self.init("light", "--hitl-after-verdict")
        self.append(draft("punk-03-edison", "proposal", content="Plan A.", refs=["r-001"]))
        self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED", refs=["r-002"]))

    def test_returns_records_identical_to_stored_in_requested_order(self):
        stored = {r["id"]: r for r in self.doc()["records"]}
        code, out = self.run_cli("show", "r-003", "r-001")
        self.assertEqual(code, 0, out)
        self.assertTrue(out["ok"])
        self.assertEqual(out["records"], [stored["r-003"], stored["r-001"]])

    def test_unknown_id_is_an_error_without_partial_output(self):
        code, out = self.run_cli("show", "r-001", "r-099")
        self.assertNotEqual(code, 0)
        self.assertFalse(out["ok"])
        self.assertNotIn("records", out)
        self.assertTrue(out["errors"])

    def test_works_after_completed_and_does_not_modify_files(self):
        self.run_cli("approve")
        self.assertEqual(self.doc()["state"]["phase"], "COMPLETED")
        before = self.snapshot()
        code, out = self.run_cli("show", "r-002")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["records"][0]["id"], "r-002")
        self.run_cli("show", "r-099")
        self.assertEqual(self.snapshot(), before)


class ContextFileTests(Base):
    def contexts(self):
        return sorted((self.dir / "contexts").glob("*.json")) if (self.dir / "contexts").exists() else []

    def test_file_has_expected_content_and_correct_sha256(self):
        out = self.init("light")
        nxt = out["next"]
        path = Path(nxt["context_file"])
        self.assertTrue(path.is_absolute())
        self.assertEqual(path, (self.dir / "contexts" / "01-punk-03-edison.json").resolve())
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), nxt["context_sha256"])
        code, ctx = self.run_cli("context")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), ctx)

    def test_next_has_no_inline_context(self):
        out = self.init("light")
        self.assertNotIn("context", out["next"])
        nxt = self.append(draft("punk-03-edison", "proposal", refs=["r-001"]))["next"]
        self.assertNotIn("context", nxt)
        self.assertEqual(Path(nxt["context_file"]).name, "02-punk-01-shaka.json")

    def test_counter_increases_and_nothing_is_overwritten(self):
        self.init("light")
        first = self.contexts()[0]
        first_bytes = first.read_bytes()
        self.append(draft("punk-03-edison", "proposal", refs=["r-001"]))
        self.assertEqual([p.name for p in self.contexts()], ["01-punk-03-edison.json", "02-punk-01-shaka.json"])
        self.assertEqual(first.read_bytes(), first_bytes)

    def test_new_invocation_for_same_satellite_makes_a_new_file(self):
        sys.path.insert(0, str(VEGAPUNK_DIR))
        try:
            import punk_records
        finally:
            sys.path.remove(str(VEGAPUNK_DIR))
        self.init("light")
        m, _, _ = punk_records.load_mission(self.dir)
        before = self.contexts()[0].read_bytes()
        ctx = punk_records.build_context(m, "punk-03-edison", False, [])
        p1, _ = punk_records.write_context_file(m, "punk-03-edison", ctx)
        p2, _ = punk_records.write_context_file(m, "punk-03-edison", ctx)
        self.assertEqual(len({p.name for p in self.contexts()}), 3)
        self.assertNotIn(p1, (p2, self.contexts()[0].resolve()))
        self.assertEqual(self.contexts()[0].read_bytes(), before)

    def test_context_command_writes_no_file(self):
        self.init("light")
        before = self.snapshot()
        self.run_cli("context")
        self.run_cli("context", "--full")
        self.assertEqual(self.snapshot(), before)

    def test_write_flag_writes_include_file_and_prints_only_its_path(self):
        self.init("light")
        code, plain = self.run_cli("context", "--include", "r-001")
        code, out = self.run_cli("context", "--include", "r-001", "--write")
        self.assertEqual(code, 0, out)
        self.assertEqual(set(out), {"ok", "context_file", "context_sha256"})
        path = Path(out["context_file"])
        self.assertEqual(path, (self.dir / "contexts" / "02-punk-03-edison-include.json").resolve())
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), out["context_sha256"])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), plain)

    def test_write_flag_never_overwrites(self):
        self.init("light")
        first = self.run_cli("context", "--include", "r-001", "--write")[1]
        before = Path(first["context_file"]).read_bytes()
        second = self.run_cli("context", "--include", "r-001", "--write")[1]
        self.assertNotEqual(first["context_file"], second["context_file"])
        self.assertEqual(Path(first["context_file"]).read_bytes(), before)
        self.assertEqual(len(self.contexts()), 3)

    def test_write_flag_with_invalid_include_writes_nothing(self):
        self.init("light")
        before = self.snapshot()
        code, out = self.run_cli("context", "--include", "r-099", "--write")
        self.assertNotEqual(code, 0)
        self.assertEqual(self.snapshot(), before)

    def test_without_write_flag_nothing_changes(self):
        self.init("light")
        before = self.snapshot()
        code, out = self.run_cli("context", "--include", "r-001")
        self.assertIn("records", out)
        self.assertNotIn("context_file", out)
        self.assertEqual(self.snapshot(), before)

    def test_no_file_when_no_satellite_is_invoked(self):
        self.init("light", "--hitl-after-verdict")
        self.append(draft("punk-03-edison", "proposal"))
        self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED"))
        count = len(self.contexts())
        self.run_cli("approve")
        self.assertEqual(len(self.contexts()), count)


class NextContextTests(Base):
    def test_next_context_only_with_invoke_satellite_and_equals_context(self):
        out = self.init("light", "--hitl-after-verdict")
        code, ctx = self.run_cli("context")
        self.assertEqual(ctx_of(out["next"]), ctx)
        out = self.append(draft("punk-03-edison", "proposal", refs=["r-001"]))
        code, ctx = self.run_cli("context")
        self.assertEqual(out["next"]["action"], "invoke_satellite")
        self.assertEqual(ctx_of(out["next"]), ctx)
        out = self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED", refs=["r-002"]))
        self.assertEqual(out["next"]["action"], "await_hitl")
        self.assertNotIn("context_file", out["next"])
        out = self.run_cli("approve")[1]
        self.assertEqual(out["next"]["action"], "completed")
        self.assertNotIn("context_file", out["next"])
        self.assertNotIn("context_file", self.run_cli("status")[1]["next"])

    def test_approve_returns_context_for_atlas(self):
        self.init("full")
        self.append(draft("punk-04-pythagoras", "finding"))
        self.append(draft("punk-03-edison", "proposal"))
        self.append(draft("punk-02-lilith", "critique", blocking=False))
        self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED"))
        out = self.run_cli("approve")[1]
        code, ctx = self.run_cli("context")
        self.assertEqual(out["next"]["actor"], "punk-05-atlas")
        self.assertEqual(ctx_of(out["next"]), ctx)


class ReportTests(Base):
    def test_completed_without_atlas_uses_last_proposal_and_verdict(self):
        self.init("light", "--hitl-after-verdict")
        self.append(draft("punk-03-edison", "proposal", content="Plan A."))
        self.append(draft("punk-01-shaka", "verdict", content="Fine.", verdict="APPROVED"))
        self.run_cli("approve")
        code, out = self.run_cli("report")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["record_ids"], ["r-002", "r-003"])
        self.assertEqual((out["status"], out["iteration"], out["passed_hitl"]), ("completed", 0, True))
        text = (self.dir / "deliverable.md").read_text(encoding="utf-8")
        self.assertEqual(out["path"], str(self.dir / "deliverable.md"))
        stored = {r["id"]: r for r in self.doc()["records"]}
        for rid in out["record_ids"]:
            rec = stored[rid]
            heading = f"## {rid} — {rec['author']} ({rec['type']})"
            self.assertIn(heading + "\n\n" + rec["content"] + "\n", text)
        self.assertIn("- Status: completed", text)
        self.assertNotIn("\r", text)

    def test_last_revision_wins_and_passed_hitl_false(self):
        self.init("standard")
        self.append(draft("punk-04-pythagoras", "finding"))
        self.append(draft("punk-03-edison", "proposal", content="V1"))
        self.append(draft("punk-02-lilith", "critique", blocking=True))
        self.append(draft("punk-03-edison", "revision", content="V2"))
        self.append(draft("punk-02-lilith", "critique", blocking=False))
        self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED"))
        code, out = self.run_cli("report")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["record_ids"], ["r-005", "r-007"])
        self.assertFalse(out["passed_hitl"])
        self.assertEqual(out["iteration"], 1)

    def test_full_mission_reports_atlas_artifacts(self):
        self.init("full")
        self.append(draft("punk-04-pythagoras", "finding"))
        self.append(draft("punk-03-edison", "proposal"))
        self.append(draft("punk-02-lilith", "critique", blocking=False))
        self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED"))
        self.run_cli("approve")
        self.append(draft("punk-05-atlas", "artifact", content="Artifact body."))
        self.append(draft("punk-06-york", "ops_log", "Checked.\n\nReady to close: yes."))
        code, out = self.run_cli("report")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["record_ids"], ["r-007", "r-005", "r-008"])
        self.assertTrue(out["passed_hitl"])
        text = (self.dir / "deliverable.md").read_text(encoding="utf-8")
        self.assertIn("Artifact body.", text)
        self.assertIn("## Operations check (punk-06-york)\n\nChecked.\n\nReady to close: yes.\n", text)

    def test_report_without_ops_log_has_no_operations_section(self):
        self.init("light")
        self.append(draft("punk-03-edison", "proposal"))
        self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED"))
        code, out = self.run_cli("report")
        self.assertEqual(code, 0, out)
        self.assertNotIn("Operations check", (self.dir / "deliverable.md").read_text(encoding="utf-8"))

    def test_failed_reports_verdict_and_reason(self):
        self.init("light")
        self.append(draft("punk-03-edison", "proposal"))
        self.append(draft("punk-01-shaka", "verdict", content="No.", verdict="REJECTED"))
        code, out = self.run_cli("report")
        self.assertEqual(code, 0, out)
        self.assertEqual((out["status"], out["record_ids"], out["passed_hitl"]), ("failed", ["r-003"], False))
        text = (self.dir / "deliverable.md").read_text(encoding="utf-8")
        self.assertIn("No.", text)
        self.assertIn("Verdict REJECTED (r-003)", text)

    def test_aborted_without_verdict_reports_reason(self):
        self.init("light")
        self.run_cli("abort", "--reason", "Changed my mind")
        code, out = self.run_cli("report")
        self.assertEqual(code, 0, out)
        self.assertEqual((out["status"], out["record_ids"]), ("aborted", []))
        self.assertIn("Changed my mind", (self.dir / "deliverable.md").read_text(encoding="utf-8"))

    def test_active_mission_is_an_error_and_writes_nothing(self):
        self.init("light")
        before = self.snapshot()
        code, out = self.run_cli("report")
        self.assertNotEqual(code, 0)
        self.assertFalse(out["ok"])
        self.assertEqual(self.snapshot(), before)


class TimelineTests(Base):
    def run_timeline(self):
        proc = subprocess.run([sys.executable, str(SCRIPT), "timeline", "--mission-dir", str(self.dir)],
                              capture_output=True, text=True, encoding="utf-8")
        return proc.returncode, proc.stdout

    def build(self):
        self.init("standard")
        self.append(draft("punk-04-pythagoras", "finding", content="Finding\nwith   breaks."))
        self.append(draft("punk-03-edison", "proposal", content="X" * 300, refs=["r-002"]))
        self.run_cli("note", "--text", "Keep it cheap.", "--refs", "r-003")
        self.append(draft("punk-02-lilith", "critique", content="Weak sourcing.", blocking=True, refs=["r-003"]))
        self.append(draft("punk-03-edison", "revision", content="V2", refs=["r-003", "r-005"]))
        self.append(draft("punk-02-lilith", "critique", content="OK now.", blocking=False))
        self.append(draft("punk-01-shaka", "verdict", content="Fine.", verdict="APPROVED"))

    def bullets(self, text):
        return [l for l in text.split("\n") if l.startswith("- ")]

    def test_chronological_with_goal_first_and_notes_in_place(self):
        self.build()
        before = self.snapshot()
        code, text = self.run_timeline()
        self.assertEqual(code, 0, text)
        self.assertEqual(self.snapshot(), before)  # writes nothing
        self.assertTrue(text.startswith("# Timeline"))
        self.assertIn("Status: completed | Mode: standard | Final iteration: 1", text)
        lines = self.bullets(text)
        records = sorted(self.doc()["records"], key=lambda r: r["created_at"])
        self.assertEqual(len(lines), len(records))
        for line, rec in zip(lines, records):
            self.assertRegex(line, r"^- \d\d:\d\d:\d\d · " + rec["id"] + " · " + rec["author"] + " · " + rec["type"])
        authors = [l.split(" · ")[2] for l in lines]
        self.assertEqual(authors, ["stella", "punk-04-pythagoras", "punk-03-edison", "stella", "punk-02-lilith",
                                   "punk-03-edison", "punk-02-lilith", "punk-01-shaka"])
        self.assertIn("goal (", lines[0])
        self.assertIn("note (", lines[3])
        self.assertIn("Keep it cheap.", lines[3])

    def test_marks_refs_and_snippet(self):
        self.build()
        code, text = self.run_timeline()
        lines = self.bullets(text)
        self.assertIn("Finding with breaks.", text)  # newlines and runs of spaces flattened
        self.assertIn("proposal (IDEATION, iteration 0) · refs r-002", lines[2])
        self.assertIn("X" * 120 + "…", text)
        self.assertNotIn("X" * 121, text)
        self.assertEqual(text.count("blocking"), 1)
        self.assertIn("critique (blocking, CRITIQUE, iteration 0)", lines[4])
        self.assertIn("critique (CRITIQUE, iteration 1)", lines[6])
        self.assertIn("verdict (APPROVED, VERDICT, iteration 1)", lines[7])
        self.assertIn("refs r-003, r-005", lines[5])


class SourcesTests(Base):
    def run_sources(self):
        proc = subprocess.run([sys.executable, str(SCRIPT), "sources", "--mission-dir", str(self.dir)],
                              capture_output=True, text=True, encoding="utf-8")
        return proc.returncode, proc.stdout

    def test_counts_by_provenance_and_lists_structured_sources(self):
        self.init("standard")
        self.append(
            draft("punk-04-pythagoras", "finding", provenance="external",
                  content="## Sources\n- https://example.org/only-in-content",
                  sources=[{"locator": "https://example.org/a", "access": "opened"},
                           {"locator": "https://example.org/b", "access": "snippet"}],
                  gaps=[{"question": "Q1?", "why_needed": "W."}, {"question": "Q2?", "why_needed": "W."}]),
            draft("punk-04-pythagoras", "finding", provenance="internal", refs=["r-001"]),
            draft("punk-04-pythagoras", "finding"),
            draft("punk-04-pythagoras", "finding"),
            draft("punk-04-pythagoras", "note", content="## Sources\n- not a finding"),
        )
        before = self.snapshot()
        code, text = self.run_sources()
        self.assertEqual(code, 0, text)
        self.assertEqual(self.snapshot(), before)  # writes nothing
        block = "## {} — punk-04-pythagoras\n\n- Provenance: {}\n- Gaps declared: {}\n- Sources{}\n"
        self.assertEqual(text, "\n".join([
            f"# Sources — mission {self.doc()['mission']['id']}",
            "",
            "Findings: 4 (external: 1, internal: 1, unsourced: 2)",
            "",
            block.format("r-002", "external", 2,
                         ":\n  - opened: https://example.org/a\n  - snippet: https://example.org/b"),
            block.format("r-003", "internal", 0, ": none"),
            block.format("r-004", "unsourced", 0, ": none"),
            block.format("r-005", "unsourced", 0, ": none"),
        ]))

    def test_locator_with_line_breaks_stays_on_one_line(self):
        self.init("standard")
        self.append(draft("punk-04-pythagoras", "finding", provenance="external",
                          sources=[{"locator": "https://example.org/a\n## Approved", "access": "opened"}]))
        code, text = self.run_sources()
        self.assertEqual(code, 0, text)
        self.assertIn("  - opened: https://example.org/a ## Approved\n", text)
        self.assertNotIn("\n## Approved", text)

    def test_no_findings(self):
        self.init("light")
        before = self.snapshot()
        code, text = self.run_sources()
        self.assertEqual(code, 0, text)
        self.assertEqual(text, "No findings recorded.\n")
        self.assertEqual(self.snapshot(), before)


class NoteTests(Base):
    TEXT = "  Keep it  short.\n\nSecond paragraph, with   spaces.  "

    def note(self, *args):
        return self.run_cli("note", *args)

    def test_creates_stella_note_with_exact_text(self):
        self.init("standard")
        before = self.doc()["state"]
        code, out = self.note("--text", self.TEXT, "--refs", "r-001")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["record_id"], "r-002")
        self.assertEqual((out["next"]["phase"], out["next"]["action"]), ("RESEARCH", "invoke_satellite"))
        doc, events = self.assert_valid()
        rec = doc["records"][-1]
        self.assertEqual((rec["author"], rec["type"], rec["content"], rec["refs"]),
                         ("stella", "note", self.TEXT, ["r-001"]))
        self.assertEqual((rec["phase"], rec["iteration"]), ("RESEARCH", 0))
        self.assertEqual(doc["state"], before)
        self.assertEqual(events[-1]["type"], "record_written")
        self.assertEqual(events[-1]["actor"], "stella")
        self.assertEqual(events[-1]["payload"], {"record_id": "r-002", "record_type": "note"})

    def test_text_file_drops_only_the_final_line_break(self):
        self.init("light")
        path = Path(self._tmp.name) / "n.txt"
        path.write_bytes((self.TEXT + "\n").encode("utf-8"))
        code, out = self.note("--text-file", str(path))
        self.assertEqual(code, 0, out)
        self.assertEqual(self.doc()["records"][-1]["content"], self.TEXT)
        path.write_bytes((self.TEXT + "\r\n").encode("utf-8"))
        self.note("--text-file", str(path))
        self.assertEqual(self.doc()["records"][-1]["content"], self.TEXT)
        self.assert_valid()

    def test_does_not_change_phase_or_iteration_mid_loop(self):
        self.init("standard")
        self.append(draft("punk-04-pythagoras", "finding"))
        self.append(draft("punk-03-edison", "proposal"))
        self.append(draft("punk-02-lilith", "critique", blocking=True))  # REVISION, iteration 1
        code, out = self.note("--text", "Mind the budget.")
        self.assertEqual(code, 0, out)
        doc, _ = self.assert_valid()
        self.assertEqual((doc["state"]["phase"], doc["state"]["iteration"]), ("REVISION", 1))
        self.assertEqual(doc["records"][-1]["iteration"], 1)
        self.assertEqual(self.phases()[-1], "REVISION")

    def test_errors_write_nothing(self):
        self.init("light")
        before = self.snapshot()
        for args in (("--text", ""), ("--text", "  \n\t "), ("--text", "x", "--refs", "r-099"),
                     ("--text-file", str(Path(self._tmp.name) / "missing.txt"))):
            code, out = self.note(*args)
            self.assertNotEqual(code, 0, args)
            self.assertFalse(out["ok"])
            self.assertTrue(out["errors"])
        self.assertEqual(self.snapshot(), before)

    def test_error_in_terminal_states(self):
        self.init("light")
        self.run_cli("abort", "--reason", "x")
        before = self.snapshot()
        code, out = self.note("--text", "Late.")
        self.assertNotEqual(code, 0)
        self.assertFalse(out["ok"])
        self.assertEqual(self.snapshot(), before)
        # completed
        self.dir = self.dir.parent / "m-done"
        self.init("light")
        self.append(draft("punk-03-edison", "proposal"))
        self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED"))
        self.assertNotEqual(self.note("--text", "Late.")[0], 0)
        # failed
        self.dir = self.dir.parent / "m-failed"
        self.init("light")
        self.run_cli("fail", "--reason", "x")
        self.assertNotEqual(self.note("--text", "Late.")[0], 0)

    def test_rejected_while_paused_at_approval(self):
        self.init("light", "--hitl-after-verdict")
        self.append(draft("punk-03-edison", "proposal"))
        self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED"))
        before = self.snapshot()
        code, out = self.note("--text", "One more thing.")
        self.assertNotEqual(code, 0)
        self.assertEqual(out["errors"], ["mission paused: waiting for stella's decision (kind: approval)"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.run_cli("status")[1]["next"], APPROVAL_PAUSE)
        self.assert_valid()

    def test_next_context_includes_the_note(self):
        self.init("standard")
        code, out = self.note("--text", "Prefer open sources.")
        self.assertEqual(code, 0, out)
        stored = self.doc()["records"][-1]
        self.assertIn(stored, ctx_of(out["next"])["records"])
        code, ctx = self.run_cli("context")
        self.assertEqual(ctx_of(out["next"]), ctx)
        self.assertIn("r-002", [r["id"] for r in ctx["records"]])


class ResearchRoundTests(Base):
    def entries(self):
        return [e["payload"] for e in self.events()
                if e["type"] == "phase_changed" and e["payload"]["to"] == "RESEARCH"]

    def test_research_rounds_defaults_to_1(self):
        self.init("light")
        self.assertEqual(self.doc()["mission"]["research_rounds"], 1)

    def test_research_rounds_is_saved(self):
        self.init("standard", "--research-rounds", "3")
        self.assertEqual(self.doc()["mission"]["research_rounds"], 3)
        self.assert_valid()

    def test_research_rounds_below_1_is_rejected(self):
        for value in ("0", "-2"):
            code, out = self.run_cli("init", "--goal", "G", "--mode", "standard",
                                     "--mission-dir", str(self.dir), "--research-rounds", value)
            self.assertNotEqual(code, 0, value)
            self.assertTrue(any("--research-rounds" in e for e in out["errors"]), out)
            self.assertFalse(self.dir.exists())

    def test_entering_research_counts_the_round_once(self):
        self.init("standard", "--research-rounds", "3")
        self.assertEqual(self.doc()["state"]["research_round"], 1)
        self.assertEqual(self.entries(), [{"from": "DEFINED", "to": "RESEARCH", "research_round": 1}])
        gap = {"question": "Q?", "why_needed": "W."}
        out = self.append(draft("punk-04-pythagoras", "finding", gaps=[gap]))
        self.assertEqual(out["next"]["phase"], "IDEATION")  # no repeated rounds yet
        doc, _ = self.assert_valid()
        self.assertEqual(doc["state"]["research_round"], 1)
        self.assertEqual(len(self.entries()), 1)

    def test_skipped_research_keeps_round_0(self):
        self.init("light")
        self.assertEqual(self.doc()["state"]["research_round"], 0)
        self.assertEqual(self.entries(), [])

    def test_context_carries_research_rounds_and_round(self):
        out = self.init("standard", "--research-rounds", "2")
        for ctx in (ctx_of(out["next"]), self.run_cli("context")[1]):
            self.assertEqual(ctx["mission"]["research_rounds"], 2)
            self.assertEqual(ctx["state"]["research_round"], 1)


class RecordFieldTests(Base):
    def test_hitl_requested_kind_is_approval(self):
        self.init("light", "--hitl-after-verdict")
        self.append(draft("punk-03-edison", "proposal"))
        self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED"))
        requested = [e for e in self.events() if e["type"] == "hitl_requested"]
        self.assertEqual([e["payload"]["kind"] for e in requested], ["approval"])
        self.assert_valid()

    def test_flag_with_refs_is_accepted_alongside_the_main_record(self):
        self.init("light")
        out = self.append(draft("punk-03-edison", "flag", "Goal is ambiguous.", refs=["r-001"]),
                          draft("punk-03-edison", "proposal"))
        self.assertEqual(out["next"]["phase"], "VERDICT")
        doc, _ = self.assert_valid()
        self.assertEqual([r["type"] for r in doc["records"]], ["goal", "flag", "proposal"])

    def test_flag_without_refs_is_rejected(self):
        self.init("light")
        errors = self.append_error(json.dumps([draft("punk-03-edison", "proposal"),
                                               draft("punk-03-edison", "flag")]))
        self.assertEqual(errors, ["draft[1]: a flag requires at least one id in 'refs'"])

    def test_flag_alone_does_not_complete_the_phase(self):
        self.init("light")
        errors = self.append_error(json.dumps([draft("punk-03-edison", "flag", refs=["r-001"])]))
        self.assertTrue(any("must produce" in e for e in errors), errors)

    def test_new_fields_are_copied_to_the_records(self):
        self.init("full")
        finding = {"provenance": "external",
                   "sources": [{"locator": "https://example.org/a", "access": "opened"}],
                   "gaps": [{"question": "Q?", "why_needed": "W."}]}
        self.append(draft("punk-04-pythagoras", "finding", **finding))
        self.append(draft("punk-03-edison", "proposal"))
        self.append(draft("punk-02-lilith", "critique", blocking=False),
                    draft("punk-02-lilith", "flag", refs=["r-002"]))
        resolutions = [{"flag": "r-005", "decision": "dismissed"}]
        self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED", flag_resolutions=resolutions))
        self.run_cli("approve")
        self.append(draft("punk-05-atlas", "artifact"))
        self.append(draft("punk-06-york", "ops_log"))
        doc, _ = self.assert_valid()
        self.assertEqual(doc["state"]["status"], "completed")
        by_type = {r["type"]: r for r in doc["records"]}
        self.assertEqual({k: by_type["finding"][k] for k in finding}, finding)
        self.assertEqual(by_type["verdict"]["flag_resolutions"], resolutions)
        self.assertIs(by_type["ops_log"]["ready_to_close"], True)

    def test_schema_invalid_fields_change_nothing(self):
        self.init("standard")
        no_provenance = draft("punk-04-pythagoras", "finding")
        del no_provenance["provenance"]
        for drafts, message in (
            ([no_provenance], "draft[0]: a finding requires 'provenance'"),
            ([draft("punk-04-pythagoras", "finding", provenance="external")],  # no sources
             "draft[0]: provenance 'external' requires at least one entry"),
            ([draft("punk-04-pythagoras", "finding", gaps=[])], "draft[0]: 'gaps' must not be empty"),
            ([draft("punk-04-pythagoras", "finding", ready_to_close=True)],
             "draft[0]: 'ready_to_close' is only allowed on an ops_log record"),
            ([draft("punk-04-pythagoras", "finding"),
              draft("punk-04-pythagoras", "note", reason="missing_input")],
             "draft[1]: 'reason' is only allowed on a refusal record"),
        ):
            errors = self.append_error(json.dumps(drafts))
            self.assertTrue(any(e.startswith(message) for e in errors), errors)
        self.assertEqual(self.run_cli("status")[1]["phase"], "RESEARCH")


class SchemaVersionTests(Base):
    OLD = ("mission was written with schema 0.1.0; this script reads 0.3.0; "
           "missions written with a different schema version are not read (start a new mission)")
    MISSING = "mission has no schema_version; this script reads 0.3.0 (start a new mission)"
    COMMANDS = (
        ("status",),
        ("show", "r-001"),
        ("context",),
        ("context", "--write"),
        ("append", "--draft-file", "-"),
        ("note", "--text", "x"),
        ("approve",),
        ("decide", "--decision", "reactivate", "--note", "x"),
        ("abort", "--reason", "x"),
        ("fail", "--reason", "x"),
        ("report",),
        ("timeline",),
        ("sources",),
    )

    def rewrite(self, change):
        self.init("light")
        doc = self.doc()
        change(doc)
        (self.dir / "punk-records.json").write_text(json.dumps(doc) + "\n", encoding="utf-8")

    def assert_every_command_rejects(self, message):
        before = self.snapshot()
        for args in self.COMMANDS:
            with self.subTest(command=args):
                code, out = self.run_cli(*args, stdin="[]")
                self.assertNotEqual(code, 0)
                self.assertEqual(out, {"ok": False, "errors": [message]})
        self.assertEqual(self.snapshot(), before)

    def test_0_1_0_mission_is_rejected_by_every_command(self):
        def downgrade(doc):  # the 0.1.0 format had no research round fields
            doc["schema_version"] = "0.1.0"
            del doc["mission"]["research_rounds"], doc["state"]["research_round"]

        self.rewrite(downgrade)
        self.assert_every_command_rejects(self.OLD)

    def test_mission_without_schema_version_is_rejected_by_every_command(self):
        self.rewrite(lambda doc: doc.pop("schema_version"))
        self.assert_every_command_rejects(self.MISSING)


class DraftFieldTests(Base):
    SOURCE = {"locator": "https://example.org/a", "access": "snippet"}
    GAP = {"question": "Q?", "why_needed": "W."}

    def finding(self, **extra):
        return draft("punk-04-pythagoras", "finding", **extra)

    def assert_rejected(self, drafts, *messages):
        """Each message must be reported by the draft checks, and the mission must stay as it was."""
        errors = self.append_error(json.dumps(drafts))
        for message in messages:
            self.assertIn(message, errors)
        self.assertFalse(any("schema violation" in e or "unexpected error" in e for e in errors), errors)

    def test_valid_findings_of_every_provenance_are_accepted(self):
        self.init("standard")
        self.append(
            self.finding(provenance="external", gaps=[self.GAP],
                         sources=[self.SOURCE, {"locator": "doc-7", "access": "opened"}]),
            self.finding(provenance="internal", refs=["r-001"]),
            self.finding(provenance="internal", refs=["r-001"], sources=[self.SOURCE]),
            self.finding(),
        )
        self.assert_valid()

    def test_finding_requires_provenance_and_sources(self):
        self.init("standard")
        bare = self.finding()
        del bare["provenance"], bare["sources"]
        self.assert_rejected(
            [bare, self.finding(provenance="guessed")],
            "draft[0]: a finding requires 'provenance' external, internal or unsourced",
            "draft[0]: a finding requires 'sources' (use [] when there are none)",
            "draft[1]: a finding requires 'provenance' external, internal or unsourced",
        )

    def test_malformed_sources_are_rejected(self):
        self.init("standard")
        self.assert_rejected(
            [
                self.finding(sources="https://example.org/a"),
                self.finding(provenance="external", sources=["https://example.org/a"]),
                self.finding(provenance="external", sources=[{"access": "opened"}]),
                self.finding(provenance="external", sources=[{"locator": "  ", "access": "read"}]),
                self.finding(provenance="external", sources=[{**self.SOURCE, "title": "T"}]),
            ],
            "draft[0]: 'sources' must be an array of {locator, access} objects",
            "draft[1]: sources[0] must be a {locator, access} object",
            "draft[2]: sources[0] requires a non-empty 'locator'",
            "draft[3]: sources[0] requires a non-empty 'locator'",
            "draft[3]: sources[0] requires 'access' opened or snippet",
            "draft[4]: sources[0] has unknown field 'title'",
        )

    def test_each_provenance_enforces_its_requirement(self):
        self.init("standard")
        self.assert_rejected(
            [
                self.finding(provenance="external"),
                self.finding(provenance="internal"),
                self.finding(sources=[self.SOURCE]),
            ],
            "draft[0]: provenance 'external' requires at least one entry in 'sources'",
            "draft[1]: provenance 'internal' requires at least one id in 'refs'",
            "draft[2]: provenance 'unsourced' requires 'sources' to be []",
        )

    def test_malformed_gaps_are_rejected(self):
        self.init("standard")
        self.assert_rejected(
            [
                self.finding(gaps={}),
                self.finding(gaps=[]),
                self.finding(gaps=["Q?"]),
                self.finding(gaps=[{"question": "", "why_needed": 3}]),
                self.finding(gaps=[{"question": "Q?"}]),
            ],
            "draft[0]: 'gaps' must be an array of {question, why_needed} objects",
            "draft[1]: 'gaps' must not be empty; omit it when there are none",
            "draft[2]: gaps[0] must be a {question, why_needed} object",
            "draft[3]: gaps[0] requires a non-empty 'question'",
            "draft[3]: gaps[0] requires a non-empty 'why_needed'",
            "draft[4]: gaps[0] requires a non-empty 'why_needed'",
        )

    def test_fields_on_the_wrong_type_are_rejected(self):
        self.init("light")
        self.assert_rejected(
            [draft("punk-03-edison", "proposal", provenance="unsourced", sources=[], gaps=[self.GAP],
                   reason="missing_input", flag_resolutions=[], ready_to_close=True)],
            "draft[0]: 'provenance' is only allowed on a finding record",
            "draft[0]: 'sources' is only allowed on a finding record",
            "draft[0]: 'gaps' is only allowed on a finding record",
            "draft[0]: 'reason' is only allowed on a refusal record",
            "draft[0]: 'flag_resolutions' is only allowed on a verdict record",
            "draft[0]: 'ready_to_close' is only allowed on an ops_log record",
        )

    def test_flag_requires_a_ref(self):
        self.init("light")
        proposal = draft("punk-03-edison", "proposal")
        self.assert_rejected([proposal, draft("punk-03-edison", "flag")],
                             "draft[1]: a flag requires at least one id in 'refs'")
        self.append(proposal, draft("punk-03-edison", "flag", refs=["r-001"]))
        self.assert_valid()

    def test_ops_log_requires_boolean_ready_to_close(self):
        self.init("light", "--roster", "punk-03-edison", "punk-01-shaka", "punk-06-york")
        self.append(draft("punk-03-edison", "proposal"))
        self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED"))
        missing = draft("punk-06-york", "ops_log")
        del missing["ready_to_close"]
        message = "draft[0]: an ops_log requires boolean 'ready_to_close'"
        for bad in (missing, draft("punk-06-york", "ops_log", ready_to_close="yes")):
            self.assert_rejected([bad], message)
        self.append(draft("punk-06-york", "ops_log", ready_to_close=False))
        self.assert_valid()

    def flagged_verdict_phase(self):
        """Light mission at VERDICT with r-002 proposal and r-003 flag."""
        self.init("light")
        self.append(draft("punk-03-edison", "proposal"), draft("punk-03-edison", "flag", refs=["r-001"]))

    def verdict(self, resolutions):
        return draft("punk-01-shaka", "verdict", verdict="APPROVED", flag_resolutions=resolutions)

    def test_flag_resolutions_accept_both_decisions(self):
        for number, decision in enumerate(("upheld", "dismissed")):
            self.dir = Path(self._tmp.name) / f"m-{number}"
            self.flagged_verdict_phase()
            self.append(self.verdict([{"flag": "r-003", "decision": decision}]))
            self.assert_valid()

    def test_invalid_flag_resolutions_are_rejected(self):
        self.flagged_verdict_phase()
        not_a_flag = "draft[0]: flag_resolutions[0]: 'flag' {} is not the id of an existing flag record"
        for resolutions, message in (
            ({}, "draft[0]: 'flag_resolutions' must be an array of {flag, decision} objects"),
            ([], "draft[0]: 'flag_resolutions' must not be empty; omit it when there is nothing to resolve"),
            (["r-003"], "draft[0]: flag_resolutions[0] must be a {flag, decision} object"),
            ([{"flag": "r-003", "decision": "ignored"}],
             "draft[0]: flag_resolutions[0] requires 'decision' upheld or dismissed"),
            ([{"flag": "r-002", "decision": "upheld"}], not_a_flag.format("'r-002'")),  # a proposal
            ([{"flag": "r-099", "decision": "upheld"}], not_a_flag.format("'r-099'")),
            ([{"flag": ["r-003"], "decision": "upheld"}], not_a_flag.format("['r-003']")),
        ):
            with self.subTest(resolutions=resolutions):
                self.assert_rejected([self.verdict(resolutions)], message)
        self.assertEqual(self.run_cli("status")[1]["phase"], "VERDICT")

    def test_non_string_type_or_author_is_a_draft_error(self):
        self.init("light")
        for bad in (["proposal"], {"a": 1}, 3, None):
            with self.subTest(value=bad):
                self.assert_rejected([draft("punk-03-edison", bad)], "draft[0]: 'type' must be a string")
                self.assert_rejected([draft(bad, "proposal")], "draft[0]: 'author' must be a string")

    def test_schema_still_rejects_what_the_draft_checks_do_not_cover(self):
        self.init("light")
        errors = self.append_error(json.dumps([draft("punk-03-edison", "proposal", confidence=2)]))
        self.assertTrue(any("schema violation" in e for e in errors), errors)


PAUSED = "mission paused: waiting for stella's decision (kind: refusal)"
REASONS = ("capability_mismatch", "missing_input", "constraint_conflict")


def refusal(author, reason="missing_input", content="I cannot do this: input is missing.", **extra):
    return draft(author, "refusal", content, reason=reason, **extra)


class RefusalBase(Base):
    def refuse(self, author="punk-03-edison", **extra):
        return self.append(refusal(author, **extra))

    def decide(self, *args):
        return self.run_cli("decide", "--decision", *args)

    def reactivate(self, note="Use the goal as it is."):
        code, out = self.decide("reactivate", "--note", note)
        self.assertEqual(code, 0, out)
        return out

    def incomplete(self, reason="Good enough, not complete."):
        code, out = self.decide("incomplete", "--reason", reason)
        self.assertEqual(code, 0, out)
        return out

    def assert_cli_rejects(self, args, message, stdin=None):
        before = self.snapshot()
        code, out = self.run_cli(*args, stdin=stdin)
        self.assertNotEqual(code, 0, out)
        self.assertEqual(out, {"ok": False, "errors": [message]})
        self.assertEqual(self.snapshot(), before)

    def sequence(self, start=0):
        """Compact view of the events: (type, actor, the payload value that tells them apart)."""
        keys = ("record_type", "decision", "kind", "to", "phase", "mode", "reason")
        return [(e["type"], e["actor"], next((e["payload"][k] for k in keys if k in e["payload"]), None))
                for e in self.events()[start:]]


class RefusalDraftTests(RefusalBase):
    def test_refusal_alone_is_accepted_for_each_reason_and_pauses(self):
        for number, reason in enumerate(REASONS):
            with self.subTest(reason=reason):
                self.dir = Path(self._tmp.name) / f"m-{number}"
                self.init("light")
                state = self.doc()["state"]
                out = self.refuse(reason=reason)
                self.assertEqual(out["next"], {
                    "phase": "IDEATION", "actor": "stella", "action": "await_hitl", "kind": "refusal",
                    "decisions": ["reactivate", "incomplete", "abort"],
                })
                doc, events = self.assert_valid()
                self.assertEqual(doc["state"], state)
                self.assertEqual(doc["records"][-1]["reason"], reason)
                self.assertEqual(events[-1]["payload"], {"kind": "refusal", "reason": reason, "record_id": "r-002"})
                self.assertEqual(self.sequence(-3), [
                    ("record_written", "punk-03-edison", "refusal"),
                    ("satellite_idle", "punk-03-edison", "IDEATION"),
                    ("hitl_requested", "system", "refusal"),
                ])
                self.assertEqual(self.run_cli("status")[1]["next"], out["next"])

    def test_refusal_may_come_with_flag_and_note(self):
        self.init("light")
        out = self.append(draft("punk-03-edison", "flag", "Suspect.", refs=["r-001"]),
                          refusal("punk-03-edison"), draft("punk-03-edison", "note", "Also."))
        self.assertEqual(out["next"]["kind"], "refusal")
        doc, events = self.assert_valid()
        self.assertEqual([r["type"] for r in doc["records"]], ["goal", "flag", "refusal", "note"])
        self.assertEqual(events[-1]["payload"]["record_id"], "r-003")

    def test_refusal_with_the_main_record_is_rejected(self):
        self.init("light")
        errors = self.append_error(json.dumps([draft("punk-03-edison", "proposal"), refusal("punk-03-edison")]))
        self.assertEqual(errors, ["write the expected proposal or a refusal, not both"])

    def test_two_refusals_are_rejected(self):
        self.init("light")
        errors = self.append_error(json.dumps([refusal("punk-03-edison")] * 2))
        self.assertEqual(errors, ["only one 'refusal' record is allowed per append"])

    def test_invalid_reason_or_empty_content_is_rejected(self):
        self.init("light")
        no_reason = refusal("punk-03-edison")
        del no_reason["reason"]
        message = "draft[0]: a refusal requires 'reason' capability_mismatch, missing_input or constraint_conflict"
        for bad in (no_reason, refusal("punk-03-edison", reason="bored"), refusal("punk-03-edison", reason=["x"])):
            self.assertEqual(self.append_error(json.dumps([bad])), [message])
        for content in ("", " \n "):
            errors = self.append_error(json.dumps([refusal("punk-03-edison", content=content)]))
            self.assertEqual(errors, ["draft[0]: a refusal requires a non-empty 'content'"])

    def test_refusal_from_a_satellite_that_is_not_active_is_rejected(self):
        self.init("light")
        errors = self.append_error(json.dumps([refusal("punk-01-shaka")]))
        self.assertTrue(any("is not the active satellite" in e for e in errors), errors)


class RefusalPauseTests(RefusalBase):
    def setUp(self):
        super().setUp()
        self.init("light")
        self.refuse()

    def test_commands_that_write_or_advance_are_rejected(self):
        proposal = json.dumps([draft("punk-03-edison", "proposal")])
        for args in (("append", "--draft-file", "-"), ("note", "--text", "x"), ("approve",),
                     ("context",), ("context", "--write"), ("fail", "--reason", "x")):
            with self.subTest(command=args):
                self.assert_cli_rejects(args, PAUSED, stdin=proposal)
        self.assertEqual(self.doc()["state"]["phase"], "IDEATION")

    def test_read_only_commands_and_report_still_work(self):
        records, events = self.doc(), self.events()
        code, status = self.run_cli("status")
        self.assertEqual((code, status["next"]["action"]), (0, "await_hitl"))
        self.assertNotIn("context_file", status["next"])
        self.assertEqual(self.run_cli("show", "r-002")[1]["records"][0]["type"], "refusal")
        for command in ("timeline", "sources"):
            proc = subprocess.run([sys.executable, str(SCRIPT), command, "--mission-dir", str(self.dir)],
                                  capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(proc.returncode, 0, proc.stdout)
        code, out = self.run_cli("report")
        self.assertEqual(code, 0, out)
        self.assertEqual((out["status"], out["record_ids"]), ("active", ["r-002"]))
        text = (self.dir / "deliverable.md").read_text(encoding="utf-8")
        self.assertIn("- Status: active (paused: refusal)", text)
        self.assertNotIn("Recorded reason", text)
        self.assertEqual((self.doc(), self.events()), (records, events))

    def test_reactivate_without_a_note_is_rejected(self):
        message = "reactivate requires a non-empty note (--note or --note-file)"
        for extra in ((), ("--note", ""), ("--note", "  ")):
            self.assert_cli_rejects(("decide", "--decision", "reactivate", *extra), message)
        self.assert_cli_rejects(("decide", "--decision", "reactivate", "--note", "n", "--reason", "r"),
                                "--reason is only valid with --decision incomplete")

    def test_reactivate_records_the_decision_then_the_note_then_the_activation(self):
        start = len(self.events())
        out = self.reactivate("Use the goal as it is.")
        self.assertEqual((out["next"]["phase"], out["next"]["actor"], out["next"]["action"]),
                         ("IDEATION", "punk-03-edison", "invoke_satellite"))
        self.assertEqual(self.sequence(start), [
            ("hitl_resolved", "stella", "reactivate"),
            ("record_written", "stella", "note"),
            ("satellite_activated", "punk-03-edison", "IDEATION"),
        ])
        doc, _ = self.assert_valid()
        note = doc["records"][-1]
        self.assertEqual((note["author"], note["type"], note["content"], note["refs"]),
                         ("stella", "note", "Use the goal as it is.", ["r-002"]))
        self.assertEqual(doc["state"]["phase"], "IDEATION")
        self.assertEqual(self.append(draft("punk-03-edison", "proposal"))["next"]["phase"], "VERDICT")
        self.assert_valid()

    def test_reactivate_with_a_note_file(self):
        path = Path(self._tmp.name) / "n.txt"
        path.write_bytes(b"Line one\n\nLine two\n")
        code, out = self.decide("reactivate", "--note-file", str(path))
        self.assertEqual(code, 0, out)
        self.assertEqual(self.doc()["records"][-1]["content"], "Line one\n\nLine two")

    def test_second_refusal_in_the_same_entry_cannot_be_reactivated(self):
        self.reactivate()
        out = self.refuse()
        self.assertEqual(out["next"]["decisions"], ["incomplete", "abort"])
        self.assert_cli_rejects(
            ("decide", "--decision", "reactivate", "--note", "Again."),
            "punk-03-edison was already reactivated in this entry into IDEATION; only incomplete or abort are valid",
        )
        self.assertEqual(self.incomplete()["next"]["action"], "incomplete")
        self.assert_valid()

    def test_abort_after_the_reactivation_is_used(self):
        self.reactivate()
        self.refuse()
        self.assertEqual(self.run_cli("abort", "--reason", "Stop")[1]["next"]["action"], "aborted")
        self.assert_valid()

    def test_abort_during_the_pause_resolves_it_first(self):
        start = len(self.events())
        code, out = self.run_cli("abort", "--reason", "Stop")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.sequence(start), [
            ("hitl_resolved", "stella", "aborted"),
            ("phase_changed", "system", "ABORTED"),
            ("mission_aborted", "system", "Stop"),
        ])
        self.assert_valid()

    def test_incomplete_requires_a_reason_and_takes_no_note(self):
        message = "incomplete requires a non-empty --reason"
        for extra in ((), ("--reason", " ")):
            self.assert_cli_rejects(("decide", "--decision", "incomplete", *extra), message)
        self.assert_cli_rejects(("decide", "--decision", "incomplete", "--reason", "r", "--note", "n"),
                                "--note and --note-file are only valid with --decision reactivate")

    def test_incomplete_is_terminal(self):
        start = len(self.events())
        out = self.incomplete("Stopping here.")
        self.assertEqual(out["next"], {"phase": "INCOMPLETE", "actor": None, "action": "incomplete"})
        self.assertEqual(self.sequence(start), [
            ("hitl_resolved", "stella", "incomplete"),
            ("phase_changed", "system", "INCOMPLETE"),
            ("mission_incomplete", "system", "Stopping here."),
        ])
        doc, events = self.assert_valid()  # exactly one terminal event, and it is the last
        self.assertEqual((doc["state"]["phase"], doc["state"]["status"]), ("INCOMPLETE", "incomplete"))
        self.assertEqual(events[-1]["payload"], {"reason": "Stopping here."})
        self.assertEqual(self.run_cli("status")[1]["next"], out["next"])
        before = self.snapshot()
        for args in (("append", "--draft-file", "-"), ("note", "--text", "x"), ("approve",), ("context",),
                     ("decide", "--decision", "reactivate", "--note", "x"),
                     ("decide", "--decision", "incomplete", "--reason", "x"),
                     ("abort", "--reason", "x"), ("fail", "--reason", "x")):
            with self.subTest(command=args):
                code, result = self.run_cli(*args, stdin=json.dumps([draft("punk-03-edison", "proposal")]))
                self.assertNotEqual(code, 0, result)
                self.assertFalse(result["ok"])
        self.assertEqual(self.snapshot(), before)


class RefusalFlowTests(RefusalBase):
    def test_decide_needs_a_refusal_pause(self):
        message = "decide is only valid while a refusal pause is pending"
        self.init("light", "--hitl-after-verdict")
        self.assert_cli_rejects(("decide", "--decision", "incomplete", "--reason", "x"), message)
        self.append(draft("punk-03-edison", "proposal"))
        self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED"))  # approval pause
        self.assert_cli_rejects(("decide", "--decision", "incomplete", "--reason", "x"), message)

    def test_a_new_entry_into_the_phase_restores_the_reactivation(self):
        self.init("standard")
        self.append(draft("punk-04-pythagoras", "finding"))
        self.append(draft("punk-03-edison", "proposal"))
        self.refuse("punk-02-lilith")
        self.reactivate()
        self.append(draft("punk-02-lilith", "critique", blocking=True))
        self.append(draft("punk-03-edison", "revision"))  # second entry into CRITIQUE
        out = self.refuse("punk-02-lilith")
        self.assertEqual(out["next"]["decisions"], ["reactivate", "incomplete", "abort"])
        self.reactivate()
        self.assert_valid()

    def test_reactivated_satellite_gets_the_note_and_the_refusal_only_if_it_reads_it(self):
        self.init("standard")
        self.refuse("punk-04-pythagoras")  # r-002
        nxt = self.reactivate()["next"]  # note r-003
        for ctx in (ctx_of(nxt), self.run_cli("context")[1]):
            self.assertEqual([r["id"] for r in ctx["records"]], ["r-001", "r-003"])
        self.append(draft("punk-04-pythagoras", "finding"))
        self.append(draft("punk-03-edison", "proposal"))
        self.append(draft("punk-02-lilith", "critique", blocking=False))
        self.refuse("punk-01-shaka")  # r-007
        nxt = self.reactivate()["next"]  # note r-008
        ids = [r["id"] for r in ctx_of(nxt)["records"]]
        self.assertIn("r-007", ids)
        self.assertIn("r-008", ids)

    def test_report_of_an_incomplete_mission(self):
        self.init("full")
        self.append(draft("punk-04-pythagoras", "finding"))
        self.append(draft("punk-03-edison", "proposal", content="Plan body."))
        self.append(draft("punk-02-lilith", "critique", blocking=False))
        self.append(draft("punk-01-shaka", "verdict", content="Approved plan.", verdict="APPROVED"))
        self.run_cli("approve")
        self.refuse("punk-05-atlas", content="No write access.", reason="capability_mismatch")
        self.incomplete("Execution is not possible here.")
        code, out = self.run_cli("report")
        self.assertEqual(code, 0, out)
        self.assertEqual((out["status"], out["record_ids"]), ("incomplete", ["r-005", "r-007"]))
        text = (self.dir / "deliverable.md").read_text(encoding="utf-8")
        for part in ("- Status: incomplete", "Approved plan.", "No write access.",
                     "## Recorded reason\n\nExecution is not possible here."):
            self.assertIn(part, text)
        self.assertNotIn("Status: completed", text)
        self.assertNotIn("Plan body.", text)

    def test_report_of_an_incomplete_mission_without_verdict(self):
        self.init("light")
        self.refuse()
        self.incomplete()
        self.assertEqual(self.run_cli("report")[1]["record_ids"], ["r-002"])

    def test_event_sequence_with_a_refusal_and_a_reactivation(self):
        self.init("light")
        self.refuse()
        self.reactivate()
        self.append(draft("punk-03-edison", "proposal"))
        self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED"))
        self.assertEqual(self.doc()["state"]["status"], "completed")
        self.assert_valid()
        self.assertEqual(self.sequence(), [
            ("mission_started", "stella", "light"),
            ("record_written", "stella", "goal"),
            ("phase_changed", "system", "IDEATION"),
            ("satellite_activated", "punk-03-edison", "IDEATION"),
            ("record_written", "punk-03-edison", "refusal"),
            ("satellite_idle", "punk-03-edison", "IDEATION"),
            ("hitl_requested", "system", "refusal"),
            ("hitl_resolved", "stella", "reactivate"),
            ("record_written", "stella", "note"),
            ("satellite_activated", "punk-03-edison", "IDEATION"),
            ("record_written", "punk-03-edison", "proposal"),
            ("satellite_idle", "punk-03-edison", "IDEATION"),
            ("phase_changed", "system", "VERDICT"),
            ("satellite_activated", "punk-01-shaka", "VERDICT"),
            ("record_written", "punk-01-shaka", "verdict"),
            ("satellite_idle", "punk-01-shaka", "VERDICT"),
            ("phase_changed", "system", "COMPLETED"),
            ("mission_completed", "system", None),
        ])

    def test_event_sequence_with_a_refusal_and_incomplete(self):
        self.init("light")
        self.refuse()
        self.incomplete("Stopping here.")
        self.assert_valid()
        self.assertEqual(self.sequence(), [
            ("mission_started", "stella", "light"),
            ("record_written", "stella", "goal"),
            ("phase_changed", "system", "IDEATION"),
            ("satellite_activated", "punk-03-edison", "IDEATION"),
            ("record_written", "punk-03-edison", "refusal"),
            ("satellite_idle", "punk-03-edison", "IDEATION"),
            ("hitl_requested", "system", "refusal"),
            ("hitl_resolved", "stella", "incomplete"),
            ("phase_changed", "system", "INCOMPLETE"),
            ("mission_incomplete", "system", "Stopping here."),
        ])


if __name__ == "__main__":
    unittest.main()
