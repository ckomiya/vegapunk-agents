# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Christian Gonzales Komiya
"""Tests for .claude/vegapunk/punk_records.py (run: python -m unittest discover -s <this dir>)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

VEGAPUNK_DIR = Path(__file__).resolve().parent.parent / ".claude" / "vegapunk"
SCRIPT = VEGAPUNK_DIR / "punk_records.py"
TERMINAL_EVENTS = {"mission_completed", "mission_failed", "mission_aborted"}


def load_schema(name: str) -> Draft202012Validator:
    schema = json.loads((VEGAPUNK_DIR / name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


RECORDS_VALIDATOR = load_schema("punk-records.schema.json")
EVENT_VALIDATOR = load_schema("event.schema.json")


def draft(author, rtype, content="Content.", refs=None, **extra):
    d = {"author": author, "type": rtype, "content": content, "refs": refs or []}
    d.update(extra)
    return d


def without_context(nxt):
    return {k: v for k, v in nxt.items() if k != "context"}


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
        return {p.name: p.read_bytes() for p in sorted(self.dir.iterdir())}

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
        self.assertEqual(out["next"], {"phase": "HITL_APPROVAL", "actor": "stella", "action": "await_hitl"})
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
        self.assertEqual(out["next"], {"phase": "HITL_APPROVAL", "actor": "stella", "action": "await_hitl"})
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

    def test_search_limit_defaults_to_3(self):
        out = self.init("light")
        engine = json.loads((self.dir / "engine.json").read_text(encoding="utf-8"))
        self.assertEqual(engine["search_limit"], 3)
        limits = {"web_searches": 3, "draft_words": 250}
        self.assertEqual(out["next"]["context"]["runtime_limits"], limits)
        code, ctx = self.run_cli("context")
        self.assertEqual(code, 0, ctx)
        self.assertEqual(ctx["runtime_limits"], limits)

    def test_search_limit_reaches_context_and_next_context(self):
        out = self.init("standard", "--search-limit", "6")
        limits = {"web_searches": 6, "draft_words": 250}
        self.assertEqual(out["next"]["context"]["runtime_limits"], limits)
        code, ctx = self.run_cli("context")
        self.assertEqual(code, 0, ctx)
        self.assertEqual(ctx["runtime_limits"], limits)
        nxt = self.append(draft("punk-04-pythagoras", "finding"))["next"]
        self.assertEqual(nxt["context"]["runtime_limits"], limits)

    def test_search_limit_zero_is_allowed(self):
        out = self.init("light", "--search-limit", "0")
        self.assertEqual(out["next"]["context"]["runtime_limits"]["web_searches"], 0)

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
        self.assertEqual(ctx["runtime_limits"], {"web_searches": 3, "draft_words": 250})

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
        self.assertEqual(out["next"]["context"]["runtime_limits"]["draft_words"], 250)

    def test_draft_words_reaches_context_and_next_context(self):
        out = self.init("standard", "--draft-words", "500")
        self.assertEqual(out["next"]["context"]["runtime_limits"]["draft_words"], 500)
        code, ctx = self.run_cli("context")
        self.assertEqual(code, 0, ctx)
        self.assertEqual(ctx["runtime_limits"]["draft_words"], 500)
        nxt = self.append(draft("punk-04-pythagoras", "finding"))["next"]
        self.assertEqual(nxt["context"]["runtime_limits"]["draft_words"], 500)

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
            "schema_version": "0.1.0",
            "mission": {"id": "m-hand", "goal": "G", "mode": "standard", "constraints": [],
                        "roster": roster or ["punk-04-pythagoras", "punk-03-edison", "punk-02-lilith", "punk-01-shaka"],
                        "max_iterations": 2, "created_at": ts},
            "state": {"phase": phase, "iteration": iteration, "status": "active", "updated_at": ts},
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
                                          "max_iterations": 2})
        self.assertEqual(out["state"], {"phase": "RESEARCH", "iteration": 0})

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
        self.assertEqual(out["state"], {"phase": "VERDICT", "iteration": 2})
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


class NextContextTests(Base):
    def test_next_context_only_with_invoke_satellite_and_equals_context(self):
        out = self.init("light", "--hitl-after-verdict")
        code, ctx = self.run_cli("context")
        self.assertEqual(out["next"]["context"], ctx)
        out = self.append(draft("punk-03-edison", "proposal", refs=["r-001"]))
        code, ctx = self.run_cli("context")
        self.assertEqual(out["next"]["action"], "invoke_satellite")
        self.assertEqual(out["next"]["context"], ctx)
        out = self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED", refs=["r-002"]))
        self.assertEqual(out["next"]["action"], "await_hitl")
        self.assertNotIn("context", out["next"])
        out = self.run_cli("approve")[1]
        self.assertEqual(out["next"]["action"], "completed")
        self.assertNotIn("context", out["next"])
        self.assertNotIn("context", self.run_cli("status")[1]["next"])

    def test_approve_returns_context_for_atlas(self):
        self.init("full")
        self.append(draft("punk-04-pythagoras", "finding"))
        self.append(draft("punk-03-edison", "proposal"))
        self.append(draft("punk-02-lilith", "critique", blocking=False))
        self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED"))
        out = self.run_cli("approve")[1]
        code, ctx = self.run_cli("context")
        self.assertEqual(out["next"]["actor"], "punk-05-atlas")
        self.assertEqual(out["next"]["context"], ctx)


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
        self.append(draft("punk-06-york", "ops_log", "Done."))
        code, out = self.run_cli("report")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["record_ids"], ["r-007", "r-005"])
        self.assertTrue(out["passed_hitl"])
        self.assertIn("Artifact body.", (self.dir / "deliverable.md").read_text(encoding="utf-8"))

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

    def test_valid_at_await_hitl_without_context(self):
        self.init("light", "--hitl-after-verdict")
        self.append(draft("punk-03-edison", "proposal"))
        self.append(draft("punk-01-shaka", "verdict", verdict="APPROVED"))
        code, out = self.note("--text", "One more thing.")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["next"], {"phase": "HITL_APPROVAL", "actor": "stella", "action": "await_hitl"})
        self.assert_valid()

    def test_next_context_includes_the_note(self):
        self.init("standard")
        code, out = self.note("--text", "Prefer open sources.")
        self.assertEqual(code, 0, out)
        stored = self.doc()["records"][-1]
        self.assertIn(stored, out["next"]["context"]["records"])
        code, ctx = self.run_cli("context")
        self.assertEqual(out["next"]["context"], ctx)
        self.assertIn("r-002", [r["id"] for r in ctx["records"]])


if __name__ == "__main__":
    unittest.main()
