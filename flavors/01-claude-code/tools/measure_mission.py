# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Christian Gonzales Komiya
"""Measure tokens and cost of a Vegapunk mission (development tool, not runtime).

Reads the Claude Code session logs under ~/.claude/projects/ plus the
mission's events.jsonl and punk-records.json, and reports tokens and USD per
call, per phase and per satellite. Prices come from tools/pricing.yaml.

Usage:
    python measure_mission.py measure --mission-dir DIR [--label TEXT]
                              [--projects-dir DIR] [--session FILE] [--out DIR]
    python measure_mission.py compare SUMMARY_CSV [SUMMARY_CSV ...] [--out FILE]

Outputs of `measure` (in --out, default <mission-dir>/measurement/):
    calls.csv      level 1: one row per model call
    summary.csv    level 2: one row per mission
    summary.json   same as summary.csv, as JSON
Output of `compare`: level 3, one column per test (summary.csv), in the given order.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

TOOLS_DIR = Path(__file__).resolve().parent
PRICING_PATH = TOOLS_DIR / "pricing.yaml"
DEFAULT_PROJECTS_DIR = Path.home() / ".claude" / "projects"

MARGIN = timedelta(seconds=5)
TIER_LIMIT = 100_000
TERMINAL_EVENTS = {"mission_completed", "mission_incomplete", "mission_failed", "mission_aborted"}
TERMINAL_STATUS = {
    "mission_completed": "completed",
    "mission_incomplete": "incomplete",
    "mission_failed": "failed",
    "mission_aborted": "aborted",
}
UNASSIGNED = "unassigned-subagent"
ENGINE = "engine"

CALL_COLUMNS = [
    "label", "mission_id", "seq", "timestamp", "phase", "actor", "invocation", "model",
    "input", "cache_write_5m", "cache_write_1h", "cache_write_unsplit", "cache_read",
    "output", "total_tokens", "usd_base", "usd_upper",
]
TOKEN_FIELDS = ["input", "cache_write_5m", "cache_write_1h", "cache_write_unsplit", "cache_read", "output"]
SUMMARY_COLUMNS = [
    "label", "mission_id", "mode", "roster", "max_iterations", "final_iteration", "status",
    "satellite_invocations", "satellite_calls", "retries", "engine_calls",
    *TOKEN_FIELDS, "total_tokens", "usd_base", "usd_upper",
    "engine_share_tokens", "engine_share_usd_base",
    "satellite_work_seconds", "hitl_wait_seconds", "total_seconds", "cost_exact",
]


class MeasureError(Exception):
    pass


# --------------------------------------------------------------------------- helpers

def parse_ts(value: str) -> datetime:
    """Parse an RFC 3339 timestamp (accepts a trailing 'Z') into an aware datetime."""
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue  # a partially written trailing line is not fatal
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def as_int(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def seconds(a: datetime, b: datetime) -> float:
    return round((b - a).total_seconds(), 3)


# --------------------------------------------------------------------------- pricing

def load_pricing(path: Path = PRICING_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except OSError as exc:
        raise MeasureError(f"cannot read pricing file {path}: {exc}") from exc
    models = data.get("models")
    if not isinstance(models, dict):
        raise MeasureError(f"{path}: missing 'models' mapping")
    return models


PRICE_KEYS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")


def select_price(entry: dict, prompt_tokens: int) -> dict | None:
    """Flat price entry, or the right tier for tiered models. None if malformed."""
    if "up_to_100k" in entry and "over_100k" in entry:
        entry = entry["up_to_100k"] if prompt_tokens <= TIER_LIMIT else entry["over_100k"]
    if isinstance(entry, dict) and all(isinstance(entry.get(k), (int, float)) for k in PRICE_KEYS):
        return entry
    return None


# --------------------------------------------------------------------------- calls

@dataclass
class Call:
    timestamp: datetime
    model: str
    input: int
    cache_write_5m: int
    cache_write_1h: int
    cache_write_unsplit: int
    cache_read: int
    output: int
    phase: str = ""
    actor: str = ENGINE
    invocation: int | None = None
    usd_base: float | None = None
    usd_upper: float | None = None

    @property
    def total_tokens(self) -> int:
        return (self.input + self.cache_write_5m + self.cache_write_1h
                + self.cache_write_unsplit + self.cache_read + self.output)

    @property
    def prompt_tokens(self) -> int:
        return (self.input + self.cache_read + self.cache_write_5m
                + self.cache_write_1h + self.cache_write_unsplit)

    @property
    def exact(self) -> bool:
        """True when no cache-write tokens lack the 5m/1h breakdown."""
        return self.cache_write_unsplit == 0


def call_from_entry(entry: dict) -> Call | None:
    msg = entry.get("message")
    if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
        return None
    ts = entry.get("timestamp")
    if not isinstance(ts, str):
        return None
    try:
        when = parse_ts(ts)
    except ValueError:
        return None
    usage = msg["usage"]
    cw5 = cw1 = 0
    unsplit = as_int(usage.get("cache_creation_input_tokens"))
    cc = usage.get("cache_creation")
    if isinstance(cc, dict) and ("ephemeral_5m_input_tokens" in cc or "ephemeral_1h_input_tokens" in cc):
        cw5 = as_int(cc.get("ephemeral_5m_input_tokens"))
        cw1 = as_int(cc.get("ephemeral_1h_input_tokens"))
        unsplit = max(0, unsplit - cw5 - cw1)
    return Call(
        timestamp=when,
        model=str(msg.get("model") or "unknown"),
        input=as_int(usage.get("input_tokens")),
        cache_write_5m=cw5,
        cache_write_1h=cw1,
        cache_write_unsplit=unsplit,
        cache_read=as_int(usage.get("cache_read_input_tokens")),
        output=as_int(usage.get("output_tokens")),
    )


def read_calls(path: Path) -> list[Call]:
    """Calls of one session file, deduplicated by (message.id, requestId).

    Streaming can log the same response several times; the last copy wins
    (it carries the final output_tokens) and keeps the first copy's position.
    """
    slots: list[Call | None] = []
    index: dict[tuple, int] = {}
    for n, entry in enumerate(read_jsonl(path)):
        call = call_from_entry(entry)
        if call is None:
            continue
        msg_id, req_id = entry["message"].get("id"), entry.get("requestId")
        if msg_id is None and req_id is None:
            slots.append(call)
            continue
        key = (msg_id, req_id)
        if key in index:
            slots[index[key]] = call
        else:
            index[key] = len(slots)
            slots.append(call)
    return [c for c in slots if c is not None]


def price_call(call: Call, pricing: dict, warnings: list[str], warned: set[str]) -> None:
    """Set usd_base / usd_upper on the call, or leave them empty with a one-time warning."""
    entry = pricing.get(call.model)
    price = select_price(entry, call.prompt_tokens) if isinstance(entry, dict) else None
    if price is None:
        if call.model not in warned:
            warned.add(call.model)
            warnings.append(f"model {call.model!r} is not priced in pricing.yaml: costs left empty (tokens still counted)")
        return
    fixed = (call.input * price["input"] + call.output * price["output"]
             + call.cache_read * price["cache_read"]
             + call.cache_write_5m * price["cache_write_5m"]
             + call.cache_write_1h * price["cache_write_1h"])
    call.usd_base = (fixed + call.cache_write_unsplit * price["cache_write_5m"]) / 1_000_000
    call.usd_upper = (fixed + call.cache_write_unsplit * price["cache_write_1h"]) / 1_000_000


# --------------------------------------------------------------------------- sessions

def find_session(projects_dir: Path, mission_id: str, explicit: Path | None) -> Path:
    if explicit is not None:
        if not explicit.is_file():
            raise MeasureError(f"--session file not found: {explicit}")
        return explicit
    if not projects_dir.is_dir():
        raise MeasureError(f"projects directory not found: {projects_dir} (use --projects-dir or --session)")
    candidates = []
    for path in sorted(projects_dir.rglob("*.jsonl")):
        if "subagents" in path.relative_to(projects_dir).parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if mission_id in text:
            candidates.append(path)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise MeasureError(
            f"no session under {projects_dir} mentions mission_id {mission_id!r}; "
            "use --session to point at the engine session file"
        )
    listing = "\n".join(f"  {p}" for p in candidates)
    raise MeasureError(
        f"{len(candidates)} sessions mention mission_id {mission_id!r}; "
        f"pick one with --session:\n{listing}"
    )


# --------------------------------------------------------------------------- mission timeline

@dataclass
class Interval:
    satellite: str
    start: datetime
    end: datetime
    phase: str
    invocations: int = 0


@dataclass
class Timeline:
    mission_id: str
    started: datetime | None = None
    terminal_ts: datetime | None = None
    terminal_type: str | None = None
    mode: str = ""
    roster: list[str] = field(default_factory=list)
    phases: list[tuple[datetime, str]] = field(default_factory=list)
    intervals: list[Interval] = field(default_factory=list)
    last_idle: datetime | None = None
    hitl_wait: float = 0.0

    def phase_at(self, when: datetime) -> str:
        if self.started is None or when < self.started:
            return "SETUP"
        if self.terminal_ts is not None and when > self.terminal_ts:
            return "REPORT"
        phase = "DEFINED"
        for ts, to in self.phases:
            if ts <= when:
                phase = to
            else:
                break
        return phase


def build_timeline(events: list[dict]) -> Timeline:
    if not events:
        raise MeasureError("events.jsonl has no events")
    events = sorted(events, key=lambda e: e.get("seq", 0))
    tl = Timeline(mission_id=str(events[0].get("mission_id", "")))
    open_acts: dict[str, tuple[datetime, str | None]] = {}
    hitl_open: list[datetime] = []
    ends: list[Interval] = []
    for ev in events:
        try:
            ts = parse_ts(ev["ts"])
        except (KeyError, ValueError, AttributeError):
            continue
        kind, actor = ev.get("type"), ev.get("actor")
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
        if kind == "mission_started" and tl.started is None:
            tl.started = ts
            tl.mode = str(payload.get("mode", ""))
            tl.roster = list(payload.get("roster") or [])
        elif kind == "phase_changed":
            tl.phases.append((ts, str(payload.get("to", ""))))
        elif kind == "satellite_activated":
            open_acts[actor] = (ts, payload.get("phase"))
        elif kind == "satellite_idle":
            tl.last_idle = ts
            if actor in open_acts:
                start, phase = open_acts.pop(actor)
                ends.append(Interval(actor, start, ts, phase or tl.phase_at(start)))
        elif kind == "hitl_requested":
            hitl_open.append(ts)
        elif kind == "hitl_resolved" and hitl_open:
            tl.hitl_wait += seconds(hitl_open.pop(0), ts)
        elif kind in TERMINAL_EVENTS and tl.terminal_ts is None:
            tl.terminal_ts, tl.terminal_type = ts, kind
    far_future = datetime.max.replace(tzinfo=timezone.utc) - timedelta(days=1)
    for actor, (start, phase) in open_acts.items():  # activated but never idle
        ends.append(Interval(actor, start, tl.terminal_ts or far_future, phase or tl.phase_at(start)))
    tl.intervals = sorted(ends, key=lambda i: i.start)
    return tl


def match_interval(tl: Timeline, when: datetime) -> Interval | None:
    """Interval containing `when` (with the margin); the closest one if several match."""
    best, best_gap = None, None
    for iv in tl.intervals:
        if iv.start - MARGIN <= when <= iv.end + MARGIN:
            gap = max(timedelta(0), iv.start - when, when - iv.end)
            if best is None or gap < best_gap:
                best, best_gap = iv, gap
    return best


# --------------------------------------------------------------------------- measurement

def first(*values):
    """First value that is present. 0 and False count as present; None and "" do not."""
    for v in values:
        if v is not None and v != "":
            return v
    return None


def blank(value):
    """Empty string for a missing value (None); every real value, including 0, is kept."""
    return "" if value is None else value


def measure(mission_dir: Path, label: str | None = None, projects_dir: Path | None = None,
            session: Path | None = None, pricing_path: Path = PRICING_PATH) -> dict:
    records_path, events_path = mission_dir / "punk-records.json", mission_dir / "events.jsonl"
    for p in (records_path, events_path):
        if not p.is_file():
            raise MeasureError(f"missing mission file: {p}")
    try:
        records = json.loads(records_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MeasureError(f"{records_path}: invalid JSON: {exc}") from exc
    mission = records.get("mission") if isinstance(records.get("mission"), dict) else {}
    state = records.get("state") if isinstance(records.get("state"), dict) else {}

    tl = build_timeline(read_jsonl(events_path))
    mission_id = first(mission.get("id"), tl.mission_id)  # events.jsonl is only the fallback
    if not mission_id:
        raise MeasureError("cannot determine mission_id from events.jsonl or punk-records.json")
    pricing = load_pricing(pricing_path)
    warnings: list[str] = []
    warned: set[str] = set()

    session_file = find_session(projects_dir or DEFAULT_PROJECTS_DIR, mission_id, session)
    calls: list[Call] = []
    for call in read_calls(session_file):
        call.phase, call.actor = tl.phase_at(call.timestamp), ENGINE
        calls.append(call)

    subagent_dir = session_file.parent / session_file.stem / "subagents"
    sub_files = []
    if subagent_dir.is_dir():
        for path in sorted(subagent_dir.glob("*.jsonl")):
            sub_calls = sorted(read_calls(path), key=lambda c: c.timestamp)
            if sub_calls:
                sub_files.append((path, sub_calls))
    sub_files.sort(key=lambda item: item[1][0].timestamp)

    per_sat: dict[str, int] = {}
    unassigned_n = 0
    for path, sub_calls in sub_files:
        iv = match_interval(tl, sub_calls[0].timestamp)
        if iv is None:
            actor, phase = UNASSIGNED, None
            unassigned_n += 1
            invocation = unassigned_n
            warnings.append(
                f"subagent log {path.name} (first call {sub_calls[0].timestamp.isoformat()}) "
                "matches no satellite interval: assigned to 'unassigned-subagent'"
            )
        else:
            actor, phase = iv.satellite, iv.phase
            per_sat[actor] = per_sat.get(actor, 0) + 1
            invocation = per_sat[actor]
            iv.invocations += 1
        for call in sub_calls:
            call.actor, call.invocation = actor, invocation
            call.phase = phase or tl.phase_at(call.timestamp)
            calls.append(call)

    retries = sum(max(0, iv.invocations - 1) for iv in tl.intervals)
    for call in calls:
        price_call(call, pricing, warnings, warned)
    calls.sort(key=lambda c: c.timestamp)  # stable: keeps file order for ties

    rows = []
    for seq, c in enumerate(calls, 1):
        rows.append({
            "label": None, "mission_id": mission_id, "seq": seq,
            "timestamp": c.timestamp.isoformat(), "phase": c.phase, "actor": c.actor,
            "invocation": "" if c.invocation is None else c.invocation, "model": c.model,
            **{f: getattr(c, f) for f in TOKEN_FIELDS},
            "total_tokens": c.total_tokens,
            "usd_base": fmt_usd(c.usd_base), "usd_upper": fmt_usd(c.usd_upper),
        })
    label = label or mission_dir.resolve().name
    for r in rows:
        r["label"] = label

    summary = build_summary(label, mission_id, mission, state, tl, calls, retries, sub_files)
    return {
        "calls": rows, "summary": summary, "warnings": warnings,
        "by_actor": aggregate(calls, lambda c: c.actor),
        "by_phase": aggregate(calls, lambda c: c.phase, phase_sort_key),
        "session": session_file,
    }


def fmt_usd(value: float | None):
    return "" if value is None else round(value, 6)


def usd_sum(calls: list[Call], attr: str) -> float | None:
    values = [getattr(c, attr) for c in calls if getattr(c, attr) is not None]
    return sum(values) if values else None


def build_summary(label, mission_id, mission, state, tl: Timeline, calls: list[Call],
                  retries: int, sub_files: list) -> dict:
    engine = [c for c in calls if c.actor == ENGINE]
    tokens = {f: sum(getattr(c, f) for c in calls) for f in TOKEN_FIELDS}
    total = sum(tokens.values())
    usd_base, usd_upper = usd_sum(calls, "usd_base"), usd_sum(calls, "usd_upper")
    engine_total = sum(c.total_tokens for c in engine)
    engine_usd = usd_sum(engine, "usd_base")
    work = seconds(tl.started, tl.last_idle) if tl.started and tl.last_idle else ""
    total_s = seconds(tl.started, tl.terminal_ts) if tl.started and tl.terminal_ts else ""
    status = first(state.get("status"), TERMINAL_STATUS.get(tl.terminal_type or ""), "running")
    return {
        "label": label,
        "mission_id": mission_id,
        "mode": blank(first(tl.mode, mission.get("mode"), state.get("mode"))),
        "roster": " ".join(tl.roster or mission.get("roster") or []),
        "max_iterations": blank(first(mission.get("max_iterations"), state.get("max_iterations"))),
        "final_iteration": blank(first(state.get("iteration"), state.get("current_iteration"),
                                       state.get("final_iteration"))),
        "status": status,
        "satellite_invocations": len(sub_files),
        "satellite_calls": len(calls) - len(engine),
        "retries": retries,
        "engine_calls": len(engine),
        **tokens,
        "total_tokens": total,
        "usd_base": fmt_usd(usd_base),
        "usd_upper": fmt_usd(usd_upper),
        "engine_share_tokens": round(engine_total / total, 4) if total else "",
        "engine_share_usd_base": round(engine_usd / usd_base, 4) if engine_usd is not None and usd_base else "",
        "satellite_work_seconds": work,
        "hitl_wait_seconds": round(tl.hitl_wait, 3),
        "total_seconds": total_s,
        "cost_exact": bool(calls) and all(c.exact for c in calls),
    }


PHASE_ORDER = [
    "SETUP", "DEFINED", "RESEARCH", "IDEATION", "CRITIQUE", "REVISION", "VERDICT",
    "HITL_APPROVAL", "EXECUTION", "OPERATIONS", "COMPLETED", "INCOMPLETE", "FAILED", "ABORTED", "REPORT",
]


def phase_sort_key(name: str) -> tuple:
    """Cycle order; phases not in the cycle go last, alphabetically."""
    if name in PHASE_ORDER:
        return (0, PHASE_ORDER.index(name), "")
    return (1, 0, name)


def aggregate(calls: list[Call], key, order=None) -> list[dict]:
    groups: dict[str, list[Call]] = {}
    for c in calls:
        groups.setdefault(key(c), []).append(c)
    out = []
    for name in sorted(groups, key=order):
        g = groups[name]
        out.append({
            "name": name, "calls": len(g),
            "input": sum(c.input for c in g),
            "cache_write": sum(c.cache_write_5m + c.cache_write_1h + c.cache_write_unsplit for c in g),
            "cache_read": sum(c.cache_read for c in g),
            "output": sum(c.output for c in g),
            "total": sum(c.total_tokens for c in g),
            "usd_base": fmt_usd(usd_sum(g, "usd_base")),
            "usd_upper": fmt_usd(usd_sum(g, "usd_upper")),
        })
    return out


# --------------------------------------------------------------------------- output

def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def render_table(headers: list[str], rows: list[list]) -> str:
    cells = [[str(h) for h in headers]] + [[str(v) for v in r] for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(headers))]
    lines = []
    for n, r in enumerate(cells):
        lines.append("  ".join(v.rjust(w) if i else v.ljust(w) for i, (v, w) in enumerate(zip(r, widths))))
        if n == 0:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines)


def aggregate_table(title: str, rows: list[dict]) -> str:
    headers = [title, "calls", "input", "cache_write", "cache_read", "output", "total", "usd_base", "usd_upper"]
    body = [[r["name"], r["calls"], r["input"], r["cache_write"], r["cache_read"], r["output"],
             r["total"], r["usd_base"], r["usd_upper"]] for r in rows]
    return render_table(headers, body)


def run_measure(args) -> int:
    mission_dir = Path(args.mission_dir)
    result = measure(mission_dir, args.label,
                     Path(args.projects_dir) if args.projects_dir else None,
                     Path(args.session) if args.session else None)
    out = Path(args.out) if args.out else mission_dir / "measurement"
    out.mkdir(parents=True, exist_ok=True)
    summary = result["summary"]
    write_csv(out / "calls.csv", CALL_COLUMNS, result["calls"])
    write_csv(out / "summary.csv", SUMMARY_COLUMNS, [summary])
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    print(f"Mission {summary['mission_id']} ({summary['label']}) - session {result['session']}")
    print(f"Status: {summary['status']}  mode: {summary['mode']}  calls: "
          f"{summary['engine_calls']} engine + {summary['satellite_calls']} satellite "
          f"({summary['satellite_invocations']} invocations, {summary['retries']} retries)")
    print()
    print(aggregate_table("actor", result["by_actor"]))
    print()
    print(aggregate_table("phase", result["by_phase"]))
    print()
    print(f"Total tokens: {summary['total_tokens']}  usd_base: {summary['usd_base']}  "
          f"usd_upper: {summary['usd_upper']}  cost_exact: {str(summary['cost_exact']).lower()}")
    if result["warnings"]:
        print()
        for w in result["warnings"]:
            print(f"WARNING: {w}")
    print(f"\nWrote calls.csv, summary.csv, summary.json to {out}")
    return 0


def read_summary(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
    except OSError as exc:
        raise MeasureError(f"cannot read {path}: {exc}") from exc
    if not rows:
        raise MeasureError(f"{path}: no data row")
    return rows[0]


def run_compare(args) -> int:
    summaries = [read_summary(Path(p)) for p in args.summaries]
    names, seen = [], {}
    for s in summaries:  # columns in the order given; duplicate labels get a suffix
        base = s.get("label") or "test"
        seen[base] = seen.get(base, 0) + 1
        names.append(base if seen[base] == 1 else f"{base}#{seen[base]}")
    metrics = [c for c in SUMMARY_COLUMNS if c != "label"]
    rows = [[m, *[s.get(m, "") for s in summaries]] for m in metrics]
    out = Path(args.out) if args.out else Path("compare.csv")
    with open(out, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["metric", *names])
        writer.writerows(rows)
    print(render_table(["metric", *names], rows))
    print(f"\nWrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Measure tokens and cost of Vegapunk missions.")
    sub = ap.add_subparsers(dest="command", required=True)
    m = sub.add_parser("measure", help="measure one mission")
    m.add_argument("--mission-dir", required=True, help="directory with punk-records.json and events.jsonl")
    m.add_argument("--label", help="name of this test (default: the mission directory name)")
    m.add_argument("--projects-dir", help="Claude Code projects directory (default: ~/.claude/projects)")
    m.add_argument("--session", help="engine session .jsonl (skips the automatic search)")
    m.add_argument("--out", help="output directory (default: <mission-dir>/measurement)")
    c = sub.add_parser("compare", help="join several summary.csv files into one table")
    c.add_argument("summaries", nargs="+", metavar="SUMMARY_CSV")
    c.add_argument("--out", help="output file (default: compare.csv in the current directory)")
    args = ap.parse_args(argv)
    try:
        return run_measure(args) if args.command == "measure" else run_compare(args)
    except (MeasureError, OSError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
