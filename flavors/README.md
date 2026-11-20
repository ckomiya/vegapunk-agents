# flavors/

Runtime-specific implementations of the `core/` specification.

- **Will contain:** one self-contained folder per runtime: `01-claude-code`, `02-langgraph`, `03-crewai`, `04-anthropic-sdk`.
- **Filled in:** Phases 2, 3 and 5 (see the root roadmap).
- Each flavor has its own README and dependency file, added in its phase.
- Flavors implement `core/`; they never redefine roles or protocol.
- **Must stay use-case agnostic:** flavors never import or reference `examples/`.
