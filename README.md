# vegapunk-agents

> A **Multi-Agent Architecture Pattern (and Conceptual Framework)**: split hard reasoning across biased specialists that share one memory.

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24384581.svg)](https://doi.org/10.5281/zenodo.24384581)
[![Cite this repository](https://img.shields.io/badge/Cite-this%20repository-informational.svg)](CITATION.cff)
![Status: work in progress](https://img.shields.io/badge/status-work%20in%20progress-orange.svg)

## What is this?

`vegapunk-agents` is, first and foremost, a **pattern**: a way of structuring multi-agent reasoning that is independent of any tool. Reference implementations ("flavors") come second and show how to apply it on specific runtimes.

A single, general-purpose agent tends to be agreeable, shallow, and inconsistent: it brainstorms and judges in the same breath, so it does neither well. `vegapunk-agents` takes the opposite approach, inspired by Dr. Vegapunk from *One Piece*, whose mind is split into specialized satellites.

Each satellite has a **deliberate cognitive bias** (the optimist, the critic, the researcher, the brute-force worker...). Bias is a feature: it makes each role sharp and predictable. Quality emerges from the *friction* between them, coordinated through a shared memory (**Punk Records**) and supervised by a human (**Stella**).

The framework is use-case agnostic and implementation agnostic: one specification in `core/`, many runtimes in `flavors/`.

## Architecture overview

- **Stella** — the orchestrator, i.e. you. Sets goals, picks the activation mode, and approves critical actions (human-in-the-loop).
- **Punk Records** — the shared memory. Every satellite reads from and writes to this central knowledge/state store.
- **Satellites** — six specialized agents:

| ID | Name | Role | Cognitive bias |
|----|------|------|----------------|
| Punk-01 | Shaka | Logic & Architecture: validates coherence, rules, security; final approval | Rigor and consistency |
| Punk-02 | Lilith | Critique / Red Teaming: devil's advocate, finds flaws and biases | Skepticism |
| Punk-03 | Edison | Ideation & Strategy: unfiltered brainstorming, initial solution design | Divergent optimism |
| Punk-04 | Pythagoras | Research & Data: sources, metrics, structures findings into Punk Records | Evidence over opinion |
| Punk-05 | Atlas | Execution / Brute Force: high-volume work (mass code, assets, batches) | Throughput over elegance |
| Punk-06 | York | Operations & Maintenance: cleanup, formatting, logs, deliverable checks | Tidiness and completeness |

### Activation modes

| Mode | Satellites | Use when |
|------|-----------|----------|
| Light | 2 | Quick, low-stakes tasks |
| Standard | 4 | Most everyday work |
| Full Egghead | 6 | High-stakes or complex problems |

```mermaid
flowchart TD
    S([Stella<br/>orchestrator / human])
    PR[(Punk Records<br/>shared memory)]
    P1[Punk-01 Shaka]
    P2[Punk-02 Lilith]
    P3[Punk-03 Edison]
    P4[Punk-04 Pythagoras]
    P5[Punk-05 Atlas]
    P6[Punk-06 York]

    S --> P1 & P2 & P3 & P4 & P5 & P6
    P1 <--> PR
    P2 <--> PR
    P3 <--> PR
    P4 <--> PR
    P5 <--> PR
    P6 <--> PR
```

## Shared vocabulary

The role names also work as a shared vocabulary for a team, with or without AI. It is closer to a pattern language, in the sense of Christopher Alexander and the Gang of Four, than to the ubiquitous language of DDD. Edward de Bono's *Six Thinking Hats* is a precedent for naming modes of thinking.

It helps in two ways:

- It separates modes of thinking that tend to get mixed, for example no criticism during ideation.
- It takes the personal edge off criticism: "let me play Lilith for a moment".

Examples:

- **Edison:** "First an Edison: unfiltered ideas, no criticism yet."
- **Pythagoras:** "We need a Pythagoras here: where does that number come from?"
- **Lilith:** "Run it past a Lilith before showing it to the client."
- **Shaka:** "Has it been through Shaka?" (has someone checked it against the rules?)
- **Atlas:** "This is Atlas work now: it's decided, we just have to produce it."
- **York:** "Have York clean it up before we close."
- **Stella:** "Who is Stella here?" (who decides?)
- **Punk Records:** "Is it in Punk Records?" (was the decision recorded?)

## When not to use it

A team of satellites is not always the right tool. For a short, one-pass task, a single agent is enough.

In one comparison on a single task, with 3 runs of a single agent (Sonnet 5.5) and one run of the Claude Code team, the team run cost 9 to 15 times as much as a single-agent run. The order of magnitude is the defensible part. All three single-agent runs recommended the same as the team and met 8/8 sections and 3/3 experiments.

What the team adds is labeled claims, critique, approval, verification and an auditable record (Punk Records). It is a trade-off, not superiority.

Caveats:

- One task only.
- The Claude Code implementation uses a model as coordinator; with a coordinator written in code, the cost difference could be smaller.
- The rubric and the partially blind reading were done by a model.
- Decision quality was not measured.

Other flavors are not measured yet, so nothing is claimed about them. Details: [Post 2](https://dev.to/ckomiya/six-agents-one-blackboard-what-i-saw-in-their-blocks-refusals-and-verdicts-24ck).

## Flavors

A flavor is an implementation of the `core/` spec on a specific runtime.

| Flavor | Folder | Status |
|--------|--------|--------|
| Claude Code (native) | `flavors/01-claude-code` | ✅ Available (v0.3.1) |
| LangGraph | `flavors/02-langgraph` | 🚧 Planned |
| CrewAI | `flavors/03-crewai` | 🚧 Planned |
| Anthropic SDK | `flavors/04-anthropic-sdk` | 🚧 Planned |

v0.3.1: the JSON output contract now covers only the satellite's final response; satellites use their tools before it.

## Repo structure

```
vegapunk-agents/
├── README.md
├── CLAUDE.md
├── LICENSE
├── .gitignore
├── core/            # Spec + canonical prompts (single source of truth)
│   ├── README.md
│   ├── architecture.md
│   ├── punk-records.md
│   ├── schemas/
│   │   ├── punk-records.schema.json
│   │   ├── event.schema.json
│   │   └── examples/
│   │       ├── punk-records.example.json
│   │       └── events.example.jsonl
│   └── prompts/
├── flavors/         # Runtime-specific implementations of core/
│   ├── 01-claude-code/
│   ├── 02-langgraph/
│   ├── 03-crewai/
│   └── 04-anthropic-sdk/
├── visualizer/      # Egghead Monitor (use-case agnostic)
└── examples/        # Use cases built ON the framework
    └── startup-validator/
```

**Decoupling rule:** the framework (`core/`, `flavors/`, `visualizer/`) is 100% decoupled from use cases (`examples/`). Nothing in the framework may import, reference, or assume anything from `examples/`. Examples consume the framework, never the other way around.

## Roadmap

- [x] Phase 0 — Repo init
- [x] Phase 1 — Core spec & prompts
- [x] Phase 2 — Claude Code native flavor
- [x] Phase 2.5 — Core v0.3: `refusal` records that pause the mission, finding provenance, flags that gate the verdict, research rounds, York's `ready_to_close` and an `incomplete` state.
- [ ] Phase 3 — LangGraph flavor + Startup Validator demo
- [ ] Phase 4 — Egghead Monitor visualizer
- [ ] Phase 5 — CrewAI & Anthropic SDK flavors

## Posts

The story behind the design decisions, with measured runs, is published as a series on dev.to:

- English: [vegapunk-agents series](https://dev.to/ckomiya/series/47100)
- Español: [serie vegapunk-agents (español)](https://dev.to/ckomiya/series/47103)

## Contributing

Contributions are welcome: the core spec and flavor 01 exist, and the next work is Phase 3. Feel free to open issues with ideas or feedback. Contributions are accepted under the Apache License 2.0. Please read `CLAUDE.md` for the project's ground rules, especially the decoupling rule.

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

## Authorship, Citation & Inspiration Note

### Authorship

Created and maintained by Christian Gonzales Komiya ([@ckomiya](https://github.com/ckomiya)), original author of the vegapunk-agents pattern. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

### Citation

See [CITATION.cff](CITATION.cff), or use GitHub's "Cite this repository" button. The DOI below is the Zenodo concept DOI, which always resolves to the latest version; each release also has its own version DOI (see the release page on Zenodo).

```bibtex
@software{gonzaleskomiya2026vegapunk,
  author  = {Gonzales Komiya, Christian},
  title   = {vegapunk-agents: A Multi-Agent Architecture Pattern (and Conceptual Framework)},
  year    = {2026},
  version = {0.3.1},
  doi     = {10.5281/zenodo.24384581},
  url     = {https://github.com/ckomiya/vegapunk-agents}
}
```

APA: Gonzales Komiya, C. (2026). *vegapunk-agents: A Multi-Agent Architecture Pattern (and Conceptual Framework)* (Version 0.3.1) [Computer software]. https://doi.org/10.5281/zenodo.24384581

### Inspiration note

Inspired by the character Dr. Vegapunk from *One Piece*, created by Eiichiro Oda / Shueisha. This project is not affiliated with or endorsed by Eiichiro Oda, Shueisha, or Toei Animation. Names are used for thematic reference only, with no intent of commercial infringement. This repository contains no official artwork or assets from the series.
