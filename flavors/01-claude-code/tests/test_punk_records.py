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
        self.assertEqual(out["next"], {"phase": "IDEATION", "actor": "punk-03-edison", "action": "invoke_satellite"})
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
        self.assertEqual(out["next"], {"phase": "VERDICT", "actor": "punk-01-shaka", "action": "invoke_satellite"})
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
        self.assertEqual(out["next"], {"phase": "EXECUTION", "actor": "punk-05-atlas", "action": "invoke_satellite"})
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

    def test_default_mission_dir_uses_mission_id(self):
        cwd = Path(self._tmp.name)
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "init", "--goal", "G", "--mode", "light", "--mission-id", "m-1"],
            capture_output=True, text=True, cwd=cwd, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertTrue((cwd / ".vegapunk" / "missions" / "m-1" / "punk-records.json").is_file())


if __name__ == "__main__":
    unittest.main()
