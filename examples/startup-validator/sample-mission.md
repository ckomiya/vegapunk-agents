<!--
SPDX-License-Identifier: Apache-2.0
Copyright 2026 Christian Gonzales Komiya
-->
# Sample mission

The idea is fictional, chosen so that public evidence exists and the satellites have real trade-offs to argue about.

Two parts: the goal block, which you paste into the engine as written, and the settings, which are instructions for the engine and not part of the goal.

## Goal block (paste this as written)

```
Outcome: a go / no-go / pivot recommendation, with the evidence behind it and the cheapest next experiments, for this idea:
- One-liner: a mobile app where neighbors rent each other household tools they rarely use (drills, ladders, pressure washers), with pickup on foot within the neighborhood.
- Users: owners with idle tools; renters (apartment dwellers, occasional DIY).
- Launch market: Lima, Peru, one district first; evidence from other cities is welcome.
- Revenue: commission on each rental (about 15%) plus an optional damage-protection fee.
- Open questions the founder already has: trust, damage and theft, enough supply and demand in a small area, why not just buy or borrow informally.

Constraints:
- Use only public sources; cite every fact; mark estimates as estimates and say what they rest on.
- Founder constraints: bootstrapped, solo founder, 3 months to the first test, under US$500 for experiments.
- Write the deliverable files as Markdown in ./startup-validator-output/ (create it if missing).
- Write exactly two files in ./startup-validator-output/: validation-report.md and experiment-plan.md. Do not create any other file there.

Done-criteria:
- validation-report.md has these sections: Summary and recommendation; Problem; Target customer; Market evidence; Competitors and substitutes; Business model; Key risks; What would change the recommendation.
- experiment-plan.md has 3 experiments, each with hypothesis, method, cost, duration and success threshold, all within the founder's budget.
- Every factual claim in the report has a source or is marked as an estimate.
- York's operations record (type ops_log, in Punk Records, not a file) confirms that validation-report.md and experiment-plan.md exist and have every required section, and lists any other file left in ./startup-validator-output/ as extra.
```

## Settings (tell these to the engine; not part of the goal)

- Mode full; max_iterations 2; search limit 6; draft limit 500 words.
- Approval before execution is mandatory in full mode.
- In flavor 01: paste the goal block as written and say "search limit 6, draft limit 500".
