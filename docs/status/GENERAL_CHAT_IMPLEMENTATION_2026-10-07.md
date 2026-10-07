# General chat implementation checkpoint — 2026-10-07 UTC

Status: `SOURCE_INTERFACE_VERIFIED`; overall feature `IN_PROGRESS`.
Runtime deployment, dedicated resident capacity and model answers: `NOT_ACTIVATED`.
This is not a completion or live acceptance report.

## Verified first slice

- `일반 → ChatGPT` navigation and a separately styled conversation workspace.
- New conversation, history selector, multiline composer, Enter/Shift+Enter and
  Korean IME handling, fenced code/copy, explicit pending/failure states.
- Authenticated API/BFF routes, dedicated `general_chat:read/write` permissions,
  additive migration `20261007_0047` (not applied to production).
- Public JSON Schema2020-12 with frozen API/Web mirrors and input/result worker
  contracts. Browser cannot supply an operator, native thread, NAS or auth pointer.
- Retain the same submission identity after uncertain HTTP outcomes; guard stale
  selection/owner responses and message identity across ordered pages.
- An absent execution owner returns `UNAVAILABLE`/503, not fake availability.

## Execution evidence and limitations

Explicit interpreter: `/srv/eom/conda/envs/eom-api/bin/python`.
Source suites: API + Web + general-chat worker contracts + migration identifier
checks: **917 PASS,18 SKIP**, one existing Starlette test-client deprecation warning.
Skipped cases need disposable PostgreSQL, privileged isolation, live deployment
or real-systemd opt-in; none are claimed PASS. No production pytest was run.

Ruff check/format, strict mypy for ten changed core modules, deterministic OpenAPI
export, shell syntax and diff whitespace checks passed. Node DOM/state regressions
cover uncertain-send replay, A→B stale responses, owner reset and disabled runtime.
These are executable simulated DOM checks, not a real HTTPS browser acceptance.

Worker-contract tests cover context/request hashes, stale claims, other conversation
identity, immutable values, context byte budget and failure/partial-answer rejection.
They do not prove runtime isolation, persistence concurrency or inference quality.

## Existing release-inventory repair

The broad suite exposed a pre-existing Image Contract resource inventory mismatch.
Replace the duplicated, incomplete142-entry literal image schema map with a sorted
map derived from the canonical schema directory. Four already-packaged contracts
had no canonical-directory mirror; add byte-identical mirrors without modifying
their schema IDs/versions/meaning. Build validation now checks all236 schemas and
wheel RECORD/content equality. Tests exercise the actual resource-map expression
and canonical/package byte parity, not literal strings in a deployment script.

No image generation, model installation, training, image policy activation or GPU
runtime changes were performed. The paused image goal remains paused.

## Required next work — not yet delivered

1. Orchestrator-owned persistent conversation/turn metadata, canonical transcript
   pointers and owner-scoped receipts; indexed claims, uniqueness and fair serialization.
2. Disposable PostgreSQL owner/isolation/idempotency/concurrent-claim tests.
3. Isolated dedicated identity and resident execution adapter, exact installed Codex
   capability admission, authentication enrollment and forbidden-access negatives.
4. API composition binding and coordinated compatible deployment, including migration.
5. Real answer + follow-up, two user sessions, restart/unknown-turn handling, and
   existing-six-slot regression. Actual streaming only from native model events.

No dedicated Linux identity/service has been created yet. No existing slot is reused.
No inference calls or model-credit consumption were made for this first slice.
Only read-only native CLI version/feature/schema introspection was performed.
See [ADR0212](../adr/0212-general-chat-dedicated-capacity.md) for scope and exit gates.
