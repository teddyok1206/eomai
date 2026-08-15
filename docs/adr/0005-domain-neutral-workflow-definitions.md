# ADR 0005: Domain-Neutral Workflow Definitions

Status: Accepted

## Context

Multi-role item development needs deterministic routing, versioned meaning, and rework history
without embedding a future subject taxonomy or allowing YAML to execute code. Worker output must
not choose the next state.

## Decision

- Workflow definitions are strict YAML data validated by JSON Schema 2020-12 and frozen Pydantic
  models, then compiled to canonical JSON with a SHA-256.
- Instances snapshot definition key, semantic version, hash, platform protocol version, and role
  protocol version.
- Stored definition rows are immutable. Reimporting the same key/version/hash is idempotent and a
  different hash for that key/version is rejected.
- Step types are limited to `agent`, `decision`, `human_gate`, and `terminal`.
- Decision operators use a fixed allow-list. Definitions cannot contain shell commands, Python or
  template expressions, imports, SQL fragments, dynamic modules, or function names.
- The deterministic engine owns workflow, stage, step, approval, and command transitions. Workers
  return schema-validated artifacts and never determine the next step.
- Role handoff uses immutable artifact pointer manifests, never direct worker communication.

## Consequences

The same engine can load future domain profiles without acquiring domain rules. A definition
change requires a new semantic version. Adding an operator requires reviewed engine code and tests,
not only a YAML edit. PyYAML is the sole new runtime dependency and is used only with `safe_load` to
parse declarative configuration.
