<!--
SPDX-License-Identifier: Apache-2.0
Copyright 2026 Christian Gonzales Komiya
-->
# Deliverables

What each satellite produces in this demo. This file does not redefine `core/`: roles, record types and the protocol are specified there. It only says what the startup-validation mission asks of each satellite.

Note: the satellites only see the goal record (and the records they may read). This file documents the demo for humans, so everything a satellite must know is in the mission itself.

Output folder: `./startup-validator-output/`, containing exactly `validation-report.md` and `experiment-plan.md`. The mission forbids creating any other file there.

Last done-criterion of the mission, verbatim:

> York's operations record (type ops_log, in Punk Records, not a file) confirms that validation-report.md and experiment-plan.md exist and have every required section, and lists any other file left in ./startup-validator-output/ as extra.

## Per satellite

| Satellite | Record | In this demo |
|---|---|---|
| `punk-04-pythagoras` | `finding` | Findings with sources on the problem, the customer, the market, competitors and substitutes, and comparable cases. Gaps are noted: what could not be found and what an estimate rests on. |
| `punk-03-edison` | `proposal` | The recommendation (go, no-go or pivot) and the plan for the two files: what each section will say, which findings it relies on, and the three experiments. |
| `punk-02-lilith` | `critique` | A critique of the evidence (weak, missing or unsourced claims), of bias (survivorship, founder optimism) and of risks the proposal leaves out. Each blocking issue is stated so it can be addressed. |
| `punk-01-shaka` | `verdict` | The verdict. Its reasoning cites findings and addresses every blocking critique. |
| `punk-05-atlas` | `artifact` | Writes both files in `./startup-validator-output/` from the approved plan and records them as artifacts (location, traceability, how to verify). |
| `punk-06-york` | `ops_log` | Checks that both files exist and have every required section, and lists any other file left in the output folder as extra. It does not delete files: in flavor 01 its tools are read and edit only. Records an ops_log in Punk Records (a record, not a file). |

## validation-report.md

Sections, in this order:

1. Summary and recommendation
2. Problem
3. Target customer
4. Market evidence
5. Competitors and substitutes
6. Business model
7. Key risks
8. What would change the recommendation

Every factual claim has a source or is marked as an estimate with what it rests on.

## experiment-plan.md

Exactly 3 experiments. Each has:

- Hypothesis
- Method
- Cost
- Duration
- Success threshold

All three fit the founder constraints stated in the idea (budget and time).

## York checklist

- [ ] `./startup-validator-output/validation-report.md` exists.
- [ ] `./startup-validator-output/experiment-plan.md` exists.
- [ ] The report has all 8 sections listed above.
- [ ] The experiment plan has 3 experiments, each with hypothesis, method, cost, duration and success threshold.
- [ ] The summed experiment cost is within the founder's budget.
- [ ] Any file in `./startup-validator-output/` other than these two is listed as extra in the ops_log.
- [ ] The ops_log is a record in Punk Records (type `ops_log`), not a file, and states whether the mission is ready to close (a "Ready to close" line).

York checks that the files exist and are complete. Judging whether claims are well sourced is Lilith's and Shaka's job.
