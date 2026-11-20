# examples/

Use cases built ON TOP of the framework. This is the only place where domain-specific logic is allowed.

- **Will contain:** one folder per demo (currently `startup-validator/`), each self-contained.
- **Filled in:** Phase 2 (definition and first run with flavor 01); other flavors follow; more may follow.
- Examples consume `core/` and `flavors/`; the framework must never depend on anything here.
- Deleting this entire folder must leave the framework fully functional.
