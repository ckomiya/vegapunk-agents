# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Christian Gonzales Komiya
"""Cross-consistency validator for core/.

Checks that the schemas, examples, architecture tables and role prompts agree
with each other. Dev/CI tool only. Dependencies: jsonschema, pyyaml,
rfc3339-validator (see requirements.txt). Exit code 0 if every check passes,
1 otherwise.
"""

import copy
import json
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"
PROMPTS = CORE / "prompts"
SCHEMAS = CORE / "schemas"

DEFINITION = "Multi-Agent Architecture Pattern (and Conceptual Framework)"
SECTIONS = [
    "Identity",
    "Cognitive bias",
    "Counterweight",
    "Responsibilities",
    "What you read",
    "What you write",
    "Rules",
    "Failure modes to avoid",
    "Example output",
]
SATELLITES = [
    "punk-01-shaka",
    "punk-02-lilith",
    "punk-03-edison",
    "punk-04-pythagoras",
    "punk-05-atlas",
    "punk-06-york",
]
ROLE_FILES = SATELLITES + ["stella"]
FRONT_MATTER_KEYS = ["id", "name", "role", "cognitive_bias", "reads", "writes", "active_phases"]
SPDX_LINES = [
    "# SPDX-License-Identifier: Apache-2.0",
    "# Copyright 2026 Christian Gonzales Komiya",
]
HTML_HEADER = (
    "<!-- SPDX-License-Identifier: Apache-2.0 -->\n"
    "<!-- Copyright 2026 Christian Gonzales Komiya -->\n"
)
# Terms that must not appear anywhere in core/ (this file is excluded from the scan).
FORBIDDEN = ["startup", "duckduckgo", "examples/startup"]
FORMAT_CHECKER = FormatChecker()


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def md_cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def ticks(text):
    return re.findall(r"`([^`]+)`", text)


def strip_fences(text):
    return re.sub(r"```.*?```", "", text, flags=re.S)


def parse_architecture(all_types):
    """Return (components, phases): id -> (role, bias, reads, writes), satellite -> phases."""
    text = (CORE / "architecture.md").read_text(encoding="utf-8")
    components = {}
    phases = {}
    in_phase_table = False
    for line in text.splitlines():
        if line.startswith("| `punk-"):
            c = md_cells(line)
            reads = all_types if c[4] == "all" else ticks(c[4])
            components[ticks(c[0])[0]] = (c[2], c[3], reads, ticks(c[5]))
        if line.startswith("| `DEFINED`"):
            in_phase_table = True
        if in_phase_table:
            if not line.startswith("|"):
                in_phase_table = False
                continue
            c = md_cells(line)
            for actor in ticks(c[1]):
                phases.setdefault(actor, []).extend(ticks(c[0]))
    return components, phases


class Report:
    def __init__(self):
        self.failed = False

    def check(self, label, errors, detail=""):
        if errors:
            self.failed = True
            print(f"FAIL  {label}")
            for e in errors:
                print(f"        - {e}")
        else:
            print(f"PASS  {label}" + (f" ({detail})" if detail else ""))


def check_schemas(ps, es):
    errors = []
    for name, schema in (("punk-records.schema.json", ps), ("event.schema.json", es)):
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:  # jsonschema.SchemaError and friends
            errors.append(f"{name} is not a valid draft 2020-12 schema: {exc}")
    for key in ("satelliteId", "authorId", "phase", "recordType"):
        if ps["$defs"].get(key) != es["$defs"].get(key):
            errors.append(f"$defs.{key} differs between the two schemas")
    return errors


def check_semantics(doc, events):
    """Rules over a whole mission that the schemas cannot express."""
    errors = []
    seen = {}  # record id -> type, for records already read
    resolved = set()
    for rec in doc["records"]:
        if rec["type"] == "verdict":
            targets = [r["flag"] for r in rec.get("flag_resolutions", [])]
            for target in targets:
                if target not in seen:
                    errors.append(f"verdict {rec['id']} resolves {target}, which does not appear earlier")
                elif seen[target] != "flag":
                    errors.append(f"verdict {rec['id']} resolves {target}, which is not a flag")
            for rid, rtype in seen.items():
                if rtype == "flag" and rid not in resolved and rid not in targets:
                    errors.append(f"verdict {rec['id']} leaves flag {rid} unresolved")
            resolved.update(targets)
        seen[rec["id"]] = rec["type"]

    current, limit = doc["state"]["research_round"], doc["mission"]["research_rounds"]
    if current > limit:
        errors.append(f"state.research_round {current} exceeds mission.research_rounds {limit}")
    entries = [e for e in events if e["type"] == "phase_changed" and e["payload"].get("to") == "RESEARCH"]
    if len(entries) != current:
        errors.append(f"{len(entries)} events enter RESEARCH, but state.research_round is {current}")
    for order, event in enumerate(entries, 1):
        given = event["payload"].get("research_round", order)
        if given != order:
            errors.append(f"event seq {event['seq']}: research_round {given}, expected {order}")
    return errors


def check_examples(pv, ev):
    errors = []
    doc = load_json(SCHEMAS / "examples" / "punk-records.example.json")
    errors += [f"mission: {e.message}" for e in pv.iter_errors(doc)]
    seen = set()
    for rec in doc["records"]:
        for ref in rec["refs"]:
            if ref not in seen:
                errors.append(f"record {rec['id']} refs {ref}, which does not appear earlier")
        seen.add(rec["id"])
    lines = [
        ln
        for ln in (SCHEMAS / "examples" / "events.example.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    events = [json.loads(ln) for ln in lines]
    for i, ev_ in enumerate(events, 1):
        errors += [f"events line {i}: {e.message}" for e in ev.iter_errors(ev_)]
    if [e["seq"] for e in events] != list(range(1, len(events) + 1)):
        errors.append("event seq is not monotonic starting at 1")
    written = [e["payload"]["record_id"] for e in events if e["type"] == "record_written"]
    if written != [r["id"] for r in doc["records"]]:
        errors.append("record_written events do not match the example records")
    errors += check_semantics(doc, events)
    return errors, doc, events


def with_record(doc, **fields):
    """Copy of doc with one extra record, built from the goal record plus fields."""
    d = copy.deepcopy(doc)
    record = copy.deepcopy(d["records"][0])
    record.update({"id": "r-900", "refs": [d["records"][0]["id"]]})
    record.update(fields)
    d["records"].append(record)
    return d


def with_event(events, source_type, **fields):
    """Copy of the first event of source_type, with fields replaced."""
    e = copy.deepcopy(next(x for x in events if x["type"] == source_type))
    e.update(fields)
    return e


def check_negatives(pv, ev, doc, events):
    def idx(rec_type):
        return next(i for i, r in enumerate(doc["records"]) if r["type"] == rec_type)

    cases = []

    d = copy.deepcopy(doc)
    d["records"][idx("finding")]["author"] = "punk-05-atlas"
    cases.append(("atlas writes a finding", pv, d))

    d = copy.deepcopy(doc)
    del d["records"][idx("verdict")]["verdict"]
    cases.append(("verdict record without verdict field", pv, d))

    d = copy.deepcopy(doc)
    d["records"][idx("goal")]["verdict"] = "APPROVED"
    cases.append(("verdict field on a non-verdict record", pv, d))

    d = copy.deepcopy(doc)
    d["mission"]["roster"] = ["punk-03-edison"]
    cases.append(("roster without punk-01-shaka", pv, d))

    e = copy.deepcopy(next(x for x in events if x["type"] == "phase_changed"))
    del e["payload"]["to"]
    cases.append(("phase_changed without 'to'", ev, e))

    d = copy.deepcopy(doc)
    del d["records"][idx("critique")]["blocking"]
    cases.append(("critique without blocking", pv, d))

    d = copy.deepcopy(doc)
    d["records"][idx("proposal")]["blocking"] = True
    cases.append(("blocking on a proposal", pv, d))

    d = copy.deepcopy(doc)
    del d["records"][idx("finding")]["provenance"]
    cases.append(("finding without provenance", pv, d))

    d = copy.deepcopy(doc)
    d["records"][idx("finding")].update(provenance="external", sources=[])
    cases.append(("external finding with sources []", pv, d))

    d = copy.deepcopy(doc)
    d["records"][idx("finding")].update(provenance="internal", refs=[])
    cases.append(("internal finding with refs []", pv, d))

    d = copy.deepcopy(doc)
    d["records"][idx("proposal")]["provenance"] = "internal"
    cases.append(("provenance on a proposal", pv, d))

    d = copy.deepcopy(doc)
    d["records"][idx("finding")]["gaps"] = []
    cases.append(("gaps []", pv, d))

    d = with_record(doc, author="punk-05-atlas", type="refusal")
    cases.append(("refusal without reason", pv, d))

    d = with_record(doc, author="stella", type="refusal", reason="missing_input")
    cases.append(("refusal written by stella", pv, d))

    d = copy.deepcopy(doc)
    d["records"][idx("flag")]["refs"] = []
    cases.append(("flag without refs", pv, d))

    d = with_record(doc, author="punk-06-york", type="ops_log")
    cases.append(("ops_log without ready_to_close", pv, d))

    d = with_record(doc, author="punk-05-atlas", type="artifact", ready_to_close=True)
    cases.append(("ready_to_close on an artifact", pv, d))

    d = copy.deepcopy(doc)
    d["records"][idx("critique")]["flag_resolutions"] = copy.deepcopy(
        d["records"][idx("verdict")]["flag_resolutions"]
    )
    cases.append(("flag_resolutions on a critique", pv, d))

    d = copy.deepcopy(doc)
    d["schema_version"] = "0.1.0"
    cases.append(('schema_version "0.1.0"', pv, d))

    e = with_event(events, "mission_completed", type="mission_incomplete", payload={})
    cases.append(("mission_incomplete without reason", ev, e))

    e = with_event(events, "hitl_requested")
    del e["payload"]["kind"]
    cases.append(("hitl_requested without kind", ev, e))

    d = copy.deepcopy(doc)
    d["records"][idx("finding")].update(provenance="unsourced", sources=d["records"][idx("finding")]["sources"][:1])
    cases.append(("unsourced finding with a source", pv, d))

    d = copy.deepcopy(doc)
    d["records"][idx("finding")]["provenance"] = "recalled"
    cases.append(('finding with provenance "recalled"', pv, d))

    # Schema-valid mutations that only check_semantics can catch.
    semantic = []

    d = copy.deepcopy(doc)
    d["records"][idx("verdict")]["flag_resolutions"].append(
        {"flag": d["records"][idx("finding")]["id"], "decision": "dismissed"}
    )
    semantic.append(("flag_resolutions targets a non-flag record", d, "is not a flag"))

    d = copy.deepcopy(doc)
    del d["records"][idx("verdict")]["flag_resolutions"]
    semantic.append(("flag left unresolved by the verdict", d, "unresolved"))

    errors = []
    for label, instance, expected in semantic:
        if not pv.is_valid(instance):
            errors.append(f"semantic mutation is not schema-valid: {label}")
        if not any(expected in e for e in check_semantics(instance, events)):
            errors.append(f"semantic error not detected: {label}")
    for label, validator, instance in cases:
        if validator.is_valid(instance):
            errors.append(f"was accepted but must be rejected: {label}")
    return errors, len(cases) + len(semantic)


def check_positives(pv, ev, doc, events):
    cases = []

    d = with_record(doc, author="punk-05-atlas", type="refusal", reason="capability_mismatch")
    cases.append(("refusal by punk-05-atlas", pv, d))

    d = with_record(doc, author="stella", type="flag")
    cases.append(("flag written by stella", pv, d))

    d = with_record(doc, author="punk-06-york", type="ops_log", ready_to_close=False)
    cases.append(("ops_log with ready_to_close false", pv, d))

    d = copy.deepcopy(doc)
    d["state"].update(phase="INCOMPLETE", status="incomplete")
    cases.append(("state INCOMPLETE / incomplete", pv, d))

    d = with_record(
        doc, author="punk-04-pythagoras", type="finding", provenance="unsourced", sources=[], refs=[]
    )
    cases.append(("unsourced finding with sources [] and refs []", pv, d))

    e = with_event(
        events, "mission_completed", type="mission_incomplete", payload={"reason": "Work left unfinished."}
    )
    cases.append(("mission_incomplete with reason", ev, e))

    e = with_event(events, "hitl_resolved", payload={"decision": "reactivate"})
    cases.append(("hitl_resolved with decision reactivate", ev, e))

    errors = []
    for label, validator, instance in cases:
        errors += [f"{label}: {e.message[:100]}" for e in validator.iter_errors(instance)]
    return errors, len(cases)


def check_prompts(ps, record_validator, all_types):
    errors = []
    components, phases = parse_architecture(all_types)
    phase_enum = ps["$defs"]["phase"]["enum"]
    for name in ROLE_FILES:
        path = PROMPTS / f"{name}.md"
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            errors.append(f"{name}: front matter does not start on line 1")
            continue
        match = re.match(r"---\n(.*?)\n---\n", text, re.S)
        if not match:
            errors.append(f"{name}: front matter is not closed")
            continue
        fm_text = match.group(1)
        for line in SPDX_LINES:
            if line not in fm_text.splitlines():
                errors.append(f"{name}: missing front matter comment '{line}'")
        try:
            fm = yaml.safe_load(fm_text) or {}
        except yaml.YAMLError as exc:
            errors.append(f"{name}: front matter does not parse: {exc}")
            continue
        for key in FRONT_MATTER_KEYS:
            if key not in fm:
                errors.append(f"{name}: front matter missing '{key}'")
        if fm.get("id") != name:
            errors.append(f"{name}: id '{fm.get('id')}' does not match the filename")
        for t in list(fm.get("reads", [])) + list(fm.get("writes", [])):
            if t not in all_types:
                errors.append(f"{name}: unknown record type '{t}'")
        for p in fm.get("active_phases", []):
            if p not in phase_enum:
                errors.append(f"{name}: unknown phase '{p}'")
        if name in components:
            role, bias, reads, writes = components[name]
            if fm.get("role") != role:
                errors.append(f"{name}: role differs from architecture.md")
            if fm.get("cognitive_bias") != bias:
                errors.append(f"{name}: cognitive_bias differs from architecture.md")
            if sorted(fm.get("reads", [])) != sorted(reads):
                errors.append(f"{name}: reads {fm.get('reads')} != architecture.md {reads}")
            if fm.get("writes") != writes:
                errors.append(f"{name}: writes {fm.get('writes')} != architecture.md {writes}")
        else:  # stella is described in prose, not in the satellite table
            if sorted(fm.get("reads", [])) != sorted(all_types):
                errors.append("stella: reads must be all record types")
            if fm.get("writes") != ["goal", "approval", "flag", "note"]:
                errors.append("stella: writes must be goal, approval, flag, note")
        if fm.get("active_phases") != phases.get(name):
            errors.append(f"{name}: active_phases {fm.get('active_phases')} != architecture.md {phases.get(name)}")
        body = text[match.end():]
        if name in SATELLITES:
            headings = re.findall(r"^## (.+)$", strip_fences(body), re.M)
            if headings != SECTIONS:
                errors.append(f"{name}: sections {headings} != {SECTIONS}")
        blocks = re.findall(r"```json\n(.*?)\n```", body, re.S)
        if not blocks:
            errors.append(f"{name}: no example JSON block")
            continue
        try:
            drafts = json.loads(blocks[-1])
        except json.JSONDecodeError as exc:
            errors.append(f"{name}: example JSON does not parse: {exc}")
            continue
        if not isinstance(drafts, list) or not drafts:
            errors.append(f"{name}: example output must be a non-empty JSON array")
            continue
        for n, draft in enumerate(drafts, 1):
            if draft.get("author") != name:
                errors.append(f"{name}: draft {n} has author '{draft.get('author')}'")
            runtime = {"id", "phase", "iteration", "created_at"} & set(draft)
            if runtime:
                errors.append(f"{name}: draft {n} contains runtime fields {sorted(runtime)}")
            full = dict(draft, id="r-900", phase="DEFINED", iteration=0, created_at="2026-01-01T00:00:00Z")
            errors += [f"{name}: draft {n}: {e.message[:100]}" for e in record_validator.iter_errors(full)]
    # Shared protocol and README: HTML-comment header, no front matter.
    for fname in ("_shared-protocol.md", "README.md"):
        if not (PROMPTS / fname).read_text(encoding="utf-8").startswith(HTML_HEADER):
            errors.append(f"{fname}: missing HTML comment SPDX/copyright header")
    return errors


def check_domain_agnostic():
    errors = []
    me = Path(__file__).resolve()
    for path in sorted(CORE.rglob("*")):
        if not path.is_file() or path.resolve() == me or "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8").lower()
        except UnicodeDecodeError:
            continue
        for term in FORBIDDEN:
            if term in text:
                errors.append(f"{path.relative_to(ROOT).as_posix()} contains '{term}'")
    return errors


def check_definition():
    errors = []
    for rel in ("README.md", "core/architecture.md", "core/prompts/_shared-protocol.md"):
        if DEFINITION not in (ROOT / rel).read_text(encoding="utf-8"):
            errors.append(f"{rel} does not contain the official definition verbatim")
    return errors


def main():
    ps = load_json(SCHEMAS / "punk-records.schema.json")
    es = load_json(SCHEMAS / "event.schema.json")
    report = Report()

    errors = check_schemas(ps, es)
    report.check("a) schemas valid (draft 2020-12), shared $defs identical", errors)
    if errors:  # nothing else can run on broken schemas
        return 1

    pv = Draft202012Validator(ps, format_checker=FORMAT_CHECKER)
    ev = Draft202012Validator(es, format_checker=FORMAT_CHECKER)
    record_validator = Draft202012Validator(
        {"$ref": "#/$defs/record", "$defs": ps["$defs"]}, format_checker=FORMAT_CHECKER
    )
    all_types = ps["$defs"]["recordType"]["enum"]

    errors, doc, events = check_examples(pv, ev)
    report.check(
        "b) examples validate, refs resolve, events consistent",
        errors,
        f"{len(doc['records'])} records, {len(events)} events",
    )

    errors, n = check_negatives(pv, ev, doc, events)
    report.check("c) negative fixtures are rejected", errors, f"{n} fixtures")

    report.check(
        "d) role prompts consistent with architecture.md and schemas",
        check_prompts(ps, record_validator, all_types),
        f"{len(ROLE_FILES)} role files",
    )
    report.check("e) core/ is domain-agnostic", check_domain_agnostic())
    report.check("f) official definition present verbatim", check_definition())
    errors, n = check_positives(pv, ev, doc, events)
    report.check("g) positive fixtures are accepted", errors, f"{n} fixtures")

    print("\nRESULT: " + ("FAIL" if report.failed else "PASS"))
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
