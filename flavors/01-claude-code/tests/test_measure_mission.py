# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Christian Gonzales Komiya
"""Tests for tools/measure_mission.py, on synthetic data in a temporary folder."""
from __future__ import annotations

import contextlib
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema

FLAVOR_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = FLAVOR_DIR.parent.parent
sys.path.insert(0, str(FLAVOR_DIR / "tools"))

import measure_mission as mm  # noqa: E402

EVENT_SCHEMA = json.loads((REPO_ROOT / "core" / "schemas" / "event.schema.json").read_text(encoding="utf-8"))
MISSION_ID = "m-test-001"
SESSION_ID = "11111111-2222-3333-4444-555555555555"
SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"


def ts(clock: str) -> str:
    return f"2026-11-20T{clock}.000Z"


def event(seq, clock, kind, actor, payload=None):
    return {"ts": ts(clock), "mission_id": MISSION_ID, "seq": seq, "type": kind,
            "actor": actor, "payload": payload or {}}


def default_events():
    sat = "punk-01-shaka"
    return [
        event(1, "10:00:00", "mission_started", "stella", {"mode": "light", "roster": [sat]}),
        event(2, "10:00:10", "phase_changed", "stella", {"from": "DEFINED", "to": "RESEARCH", "research_round": 1}),
        event(3, "10:00:20", "satellite_activated", sat, {"phase": "RESEARCH"}),
        event(4, "10:01:00", "satellite_idle", sat, {"phase": "RESEARCH"}),
        event(5, "10:01:10", "phase_changed", "stella", {"from": "RESEARCH", "to": "VERDICT"}),
        event(6, "10:01:20", "hitl_requested", "system", {"reason": "approval", "kind": "approval"}),
        event(7, "10:01:50", "hitl_resolved", "stella", {"decision": "approved"}),
        event(8, "10:02:00", "mission_completed", "stella"),
    ]


def log_entry(clock, msg_id, req_id, usage, model=SONNET):
    return {"timestamp": ts(clock), "requestId": req_id,
            "message": {"id": msg_id, "model": model, "usage": usage}}


def usage(inp=100, out=50, cr=0, cc=0, split=None):
    u = {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": cr,
         "cache_creation_input_tokens": cc}
    if split is not None:
        u["cache_creation"] = {"ephemeral_5m_input_tokens": split[0], "ephemeral_1h_input_tokens": split[1]}
    return u


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8", newline="\n")


class Fixture:
    """A fake mission dir and a fake projects dir (one session, optional subagents)."""

    def __init__(self, root: Path, events=None, engine=None, subagents=None, sessions=1,
                 mission=None, state=None):
        self.mission_dir = root / "mission"
        self.projects_dir = root / "projects"
        self.mission_dir.mkdir()
        (self.mission_dir / "punk-records.json").write_text(json.dumps({
            "mission": mission or {"id": MISSION_ID, "max_iterations": 3},
            "state": state or {"status": "completed", "iteration": 1},
        }), encoding="utf-8")
        events = default_events() if events is None else events
        validator = jsonschema.Draft202012Validator(EVENT_SCHEMA)
        for ev in events:
            validator.validate(ev)
        write_jsonl(self.mission_dir / "events.jsonl", events)
        engine = engine if engine is not None else [log_entry("10:00:05", "e1", "r1", usage())]
        marker = {"type": "user", "timestamp": ts("09:59:00"), "content": f"mission {MISSION_ID}"}
        self.session = self.projects_dir / "proj" / f"{SESSION_ID}.jsonl"
        write_jsonl(self.session, [marker, *engine])
        for name, rows in (subagents or {}).items():
            write_jsonl(self.projects_dir / "proj" / SESSION_ID / "subagents" / f"{name}.jsonl", rows)
        if sessions == 2:
            write_jsonl(self.projects_dir / "proj" / "other-session.jsonl", [marker])

    def measure(self, **kw):
        return mm.measure(self.mission_dir, "t1", self.projects_dir, **kw)


class MeasureTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    # 1
    def test_dedup_by_message_and_request_id(self):
        engine = [
            log_entry("10:00:05", "e1", "r1", usage(out=10)),
            log_entry("10:00:05", "e1", "r1", usage(out=50)),  # streaming repeat: last wins
            log_entry("10:00:06", "e1", "r2", usage()),         # same message id, other request
            log_entry("10:00:07", "e2", "r1", usage()),         # other message id, same request
        ]
        res = Fixture(self.root, engine=engine).measure()
        self.assertEqual(res["summary"]["engine_calls"], 3)
        self.assertEqual(res["calls"][0]["output"], 50)

    # 2
    def test_engine_phases_including_setup_and_report(self):
        engine = [
            log_entry("09:59:50", "a", "ra", usage()),
            log_entry("10:00:05", "b", "rb", usage()),
            log_entry("10:00:15", "c", "rc", usage()),
            log_entry("10:01:15", "d", "rd", usage()),
            log_entry("10:02:30", "e", "re", usage()),
        ]
        res = Fixture(self.root, engine=engine).measure()
        phases = [r["phase"] for r in res["calls"] if r["actor"] == "engine"]
        self.assertEqual(phases, ["SETUP", "DEFINED", "RESEARCH", "VERDICT", "REPORT"])

    # 3
    def test_subagents_assigned_by_interval_with_retry(self):
        subs = {
            "agent-a": [log_entry("10:00:22", "s1", "q1", usage())],
            "agent-b": [log_entry("10:00:40", "s2", "q2", usage())],
        }
        res = Fixture(self.root, subagents=subs).measure()
        sat = [r for r in res["calls"] if r["actor"] != "engine"]
        self.assertEqual([(r["actor"], r["invocation"], r["phase"]) for r in sat],
                         [("punk-01-shaka", 1, "RESEARCH"), ("punk-01-shaka", 2, "RESEARCH")])
        self.assertEqual(res["summary"]["satellite_invocations"], 2)
        self.assertEqual(res["summary"]["retries"], 1)
        self.assertEqual(res["warnings"], [])

    def test_subagent_without_interval_is_unassigned(self):
        subs = {"agent-x": [log_entry("10:01:40", "s9", "q9", usage())]}
        res = Fixture(self.root, subagents=subs).measure()
        row = [r for r in res["calls"] if r["actor"] != "engine"][0]
        self.assertEqual(row["actor"], "unassigned-subagent")
        self.assertTrue(any("unassigned-subagent" in w for w in res["warnings"]))

    def test_subagent_margin_of_five_seconds(self):
        subs = {"agent-a": [log_entry("10:00:16", "s1", "q1", usage())]}  # 4 s before activation
        res = Fixture(self.root, subagents=subs).measure()
        self.assertEqual([r["actor"] for r in res["calls"] if r["actor"] != "engine"], ["punk-01-shaka"])

    # 4
    def test_cost_exact_with_breakdown(self):
        call = self._call(usage(inp=1000, out=500, cr=2000, cc=4000, split=(3000, 1000)))
        self._price(call)
        self.assertAlmostEqual(call.usd_base, 0.0187, places=9)
        self.assertAlmostEqual(call.usd_upper, 0.0187, places=9)
        self.assertTrue(call.exact)

    def test_cost_range_without_breakdown(self):
        call = self._call(usage(inp=1000, out=500, cr=2000, cc=4000))
        self._price(call)
        self.assertAlmostEqual(call.usd_base, 0.0172, places=9)
        self.assertAlmostEqual(call.usd_upper, 0.0232, places=9)
        self.assertFalse(call.exact)

    def test_haiku_tiers_by_prompt_size(self):
        small = self._call(usage(inp=90_000, out=1000), HAIKU)
        big = self._call(usage(inp=150_000, out=1000), HAIKU)
        edge = self._call(usage(inp=100_000, out=0), HAIKU)
        for c in (small, big, edge):
            self._price(c)
        self.assertAlmostEqual(small.usd_base, 0.0095, places=9)
        self.assertAlmostEqual(big.usd_base, 0.0775, places=9)
        self.assertAlmostEqual(edge.usd_base, 0.01, places=9)  # exactly 100k is the lower tier

    def test_unknown_model_has_empty_cost_and_warning(self):
        engine = [log_entry("10:00:05", "e1", "r1", usage(inp=10, out=5), model="claude-mystery-1")]
        res = Fixture(self.root, engine=engine).measure()
        row = res["calls"][0]
        self.assertEqual((row["usd_base"], row["usd_upper"], row["total_tokens"]), ("", "", 15))
        self.assertEqual(res["summary"]["usd_base"], "")
        self.assertTrue(any("claude-mystery-1" in w for w in res["warnings"]))

    # 5
    def test_zero_candidate_sessions_error(self):
        fx = Fixture(self.root)
        empty_dir = self.root / "empty"
        empty_dir.mkdir()
        with self.assertRaises(mm.MeasureError) as ctx:
            mm.measure(fx.mission_dir, "t", empty_dir)
        self.assertIn("--session", str(ctx.exception))

    def test_two_candidate_sessions_error_lists_them(self):
        fx = Fixture(self.root, sessions=2)
        with self.assertRaises(mm.MeasureError) as ctx:
            fx.measure()
        msg = str(ctx.exception)
        self.assertIn("--session", msg)
        self.assertIn(f"{SESSION_ID}.jsonl", msg)
        self.assertIn("other-session.jsonl", msg)
        res = fx.measure(session=fx.session)  # --session resolves it
        self.assertEqual(res["summary"]["engine_calls"], 1)

    def test_cli_reports_error_with_exit_code_1(self):
        fx = Fixture(self.root, sessions=2)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = mm.main(["measure", "--mission-dir", str(fx.mission_dir),
                            "--projects-dir", str(fx.projects_dir)])
        self.assertEqual(code, 1)
        self.assertIn("ERROR:", err.getvalue())

    # 6
    def test_compare_joins_in_given_order(self):
        paths = []
        for name, total in (("second-run", 20), ("first-run", 10)):
            d = self.root / name
            d.mkdir()
            row = {c: "" for c in mm.SUMMARY_COLUMNS}
            row.update(label=name, total_tokens=total)
            mm.write_csv(d / "summary.csv", mm.SUMMARY_COLUMNS, [row])
            paths.append(str(d / "summary.csv"))
        out = self.root / "cmp.csv"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(mm.main(["compare", *paths, "--out", str(out)]), 0)
        with open(out, encoding="utf-8", newline="") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0], ["metric", "second-run", "first-run"])
        total_row = [r for r in rows if r[0] == "total_tokens"][0]
        self.assertEqual(total_row[1:], ["20", "10"])
        self.assertIn("second-run", buf.getvalue())

    # end to end
    def test_measure_cli_writes_outputs_and_summary_values(self):
        subs = {"agent-a": [log_entry("10:00:22", "s1", "q1", usage(cc=100, split=(100, 0)))]}
        fx = Fixture(self.root, subagents=subs)
        out = self.root / "out"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = mm.main(["measure", "--mission-dir", str(fx.mission_dir), "--label", "run-a",
                            "--projects-dir", str(fx.projects_dir), "--out", str(out)])
        self.assertEqual(code, 0)
        for name in ("calls.csv", "summary.csv", "summary.json"):
            self.assertTrue((out / name).is_file(), name)
        s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual((s["label"], s["mode"], s["status"], s["max_iterations"]), ("run-a", "light", "completed", 3))
        self.assertEqual((s["engine_calls"], s["satellite_calls"]), (1, 1))
        self.assertEqual((s["satellite_work_seconds"], s["hitl_wait_seconds"], s["total_seconds"]), (60.0, 30.0, 120.0))
        self.assertTrue(s["cost_exact"])
        self.assertIn("actor", buf.getvalue())
        self.assertIn("phase", buf.getvalue())
        self.assertNotIn(b"\r\n", (out / "calls.csv").read_bytes())

    # adjustments after real-mission measurement
    def test_zero_is_a_valid_numeric_value(self):
        fx = Fixture(self.root, mission={"id": MISSION_ID, "max_iterations": 0},
                     state={"status": "completed", "iteration": 0})
        s = fx.measure()["summary"]
        self.assertEqual((s["final_iteration"], s["max_iterations"]), (0, 0))

    def test_missing_numeric_keys_stay_empty(self):
        fx = Fixture(self.root, mission={"id": MISSION_ID}, state={"status": "completed"})
        s = fx.measure()["summary"]
        self.assertEqual((s["final_iteration"], s["max_iterations"]), ("", ""))

    def test_mission_id_is_read_from_mission_id_key_with_events_fallback(self):
        events = [dict(e, mission_id="from-events") for e in default_events()]
        fx = Fixture(self.root, events=events, mission={"id": MISSION_ID})
        # the session mentions MISSION_ID only, so finding it proves mission.id was used
        self.assertEqual(fx.measure()["summary"]["mission_id"], MISSION_ID)
        fb = self.root / "fb"
        fb.mkdir()
        fx2 = Fixture(fb, mission={"note": "no id"})
        self.assertEqual(fx2.measure()["summary"]["mission_id"], MISSION_ID)  # events fallback

    def test_phase_table_follows_cycle_order(self):
        engine = [log_entry("09:59:50", "a", "ra", usage()),
                  log_entry("10:00:15", "c", "rc", usage()),
                  log_entry("10:01:15", "d", "rd", usage()),
                  log_entry("10:02:30", "e", "re", usage())]
        res = Fixture(self.root, engine=engine).measure()
        self.assertEqual([r["name"] for r in res["by_phase"]], ["SETUP", "RESEARCH", "VERDICT", "REPORT"])
        names = sorted(["REPORT", "EXECUTION", "SETUP", "DEFINED", "HITL_APPROVAL", "IDEATION"],
                       key=mm.phase_sort_key)
        self.assertEqual(names, ["SETUP", "DEFINED", "IDEATION", "HITL_APPROVAL", "EXECUTION", "REPORT"])

    def test_mission_incomplete_is_a_terminal_event(self):
        events = default_events()[:-1] + [
            event(8, "10:02:00", "mission_incomplete", "system", {"reason": "stopped"})]
        s = Fixture(self.root, events=events, state={"iteration": 0}).measure()["summary"]
        self.assertEqual((s["status"], s["total_seconds"]), ("incomplete", 120.0))

    # helpers
    @staticmethod
    def _call(u, model=SONNET):
        return mm.call_from_entry(log_entry("10:00:05", "x", "y", u, model))

    @staticmethod
    def _price(call):
        mm.price_call(call, mm.load_pricing(), [], set())


if __name__ == "__main__":
    unittest.main()
