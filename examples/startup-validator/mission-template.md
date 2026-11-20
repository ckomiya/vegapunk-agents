<!--
SPDX-License-Identifier: Apache-2.0
Copyright 2026 Christian Gonzales Komiya
-->
# Mission template

Fill in `{{IDEA}}` and `{{FOUNDER_CONSTRAINTS}}`, then paste the goal block into the engine of any flavor. Everything the satellites need is inside the goal block: they only see the goal record, not this file.

## Goal block (paste this as written)

```
Outcome: a go / no-go / pivot recommendation, with the evidence behind it and the cheapest next experiments, for this idea:
{{IDEA}}
(bullets: one-liner, users, launch market, revenue, open questions)

Constraints:
- Use only public sources; cite every fact; mark estimates as estimates and say what they rest on.
- Founder constraints: {{FOUNDER_CONSTRAINTS}}
- Write the deliverable files as Markdown in ./startup-validator-output/ (create it if missing).
- Write exactly two files in ./startup-validator-output/: validation-report.md and experiment-plan.md. Do not create any other file there.

Done-criteria:
- validation-report.md has these sections: Summary and recommendation; Problem; Target customer; Market evidence; Competitors and substitutes; Business model; Key risks; What would change the recommendation.
- experiment-plan.md has 3 experiments, each with hypothesis, method, cost, duration and success threshold, all within the founder's budget.
- Every factual claim in the report has a source or is marked as an estimate.
- York's operations record (type ops_log, in Punk Records, not a file) confirms that validation-report.md and experiment-plan.md exist and have every required section, and lists any other file left in ./startup-validator-output/ as extra.
```

## Settings (not part of the goal; tell these to Stella's engine)

- Mode full; max_iterations 2; search limit 6; draft limit 500 words.
- Approval before execution is mandatory in full mode.
- In flavor 01: paste the goal block as written and say "search limit 6, draft limit 500".
