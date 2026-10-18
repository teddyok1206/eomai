# Chat ranked candidate read checkpoint — 2026-10-18 UTC

Design: [Catalog-ranked Chat metadata](../architecture/GENERAL_CHAT_RANKED_CANDIDATE_READ.md).
Part of the original full incremental-RAG goal; **not operating activation or C4 completion**.
Source baseline before this change: `a4241843`.

## Implemented boundary

- Closed `chat-ranked-candidate-read/1.0` request/reply, source/resource raw SHA
  `100b2f8bdabf426655bad774748a3fd3e2afd593564893c8438810e886e39b40`.
- At most64 ordered Item/component association keys; request/reply bounds32/16KiB
  including newline. No question/report/vector/path bytes or actor role hints.
- Existing Catalog RAG owner reuses current actor, released policy/source-class
  permission and exact semantic Graph validation, then the official discovery
  adapter in the **same repeatable-read/read-only transaction**.
- One metadata preflight checks exact Item/component/Graph relations and current
  revision ownership. Canonical Item manifest SHA is read from Registry, not
  substituted with the analyzed component SHA.
- Shared discovery SQL applies TOPIC/source/current/approved filters before LIMIT,
  orders the native pool by its supplied rank and emits at most one placement card
  per revision. No reranking just the old six cards, title-side unrestricted scan,
  per-candidate query loop or score mixing. Valid historical approved/superseded
  pins are filtered from current discovery without choosing their successor;
  missing/revoked/wrong-hash/foreign-current relations fail explicitly.
- Shared card/query projection and bounded Catalog transport replace duplicate
  interpretations. Ordinary RECENT/EXAM/search behavior and frozen V4/tool2,
  original private prepare/source contracts, policies and migrations are unchanged.
- Fixed private Chat peer can use this exact read operation; no worker socket/DB/
  NAS permission, new role, execution grant, model invocation or automatic retry.

This filters a native global top64 pool; it is **not exact filtered top-K**.
The existing provenance companion preserves that limitation. Output is metadata
offers only, not materialized source Evidence, approval or same-solution probability.

## Source verification

**526 PASS / 18 suites / 65.83s / no skips**, including46 new contract/SQL-owner/
temporary Unix/client tests and existing discovery, RAG owner/contract/native,
Catalog boundary/resources, continuation, provenance, file-set, historical318-
schema freeze and dependency suites. Strict mypy6 production modules, Ruff/format12
files, whitespace and fresh-process no-ML-import checks PASS. No new dependency.
Do not sum these with earlier132/202 or standalone46 source runs.

## Guarded PostgreSQL verification

Existing supported `testdb_run.sh chat-knowledge-tests` ran **85/85, no skips**,
including8 new cases on10,000 temporary Item rows:

-64 input keys versus1 use the same number of SQL queries; manifest/component
  hashes remain distinct and native order is preserved;
- dropping the first10 nonmatching candidates still returns candidates11–16,
  proving filters run before LIMIT;
- wrong component hash, foreign current-revision ownership and retirement fail
  before title projection;
- valid superseded history is excluded without latest substitution;
- actual SQL role-assignment revocation denies the next read;
- actual transaction settings are `repeatable read`/read-only; real
  `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` uses revision and Item primary-key
  indexes and returns at most7 rows before presentation.

The existing cohort's migration/admission/persistence/limited-role regressions
also passed. The new corpus/Graph/Identity rows are **synthetic shadow fixtures**
in a guarded disposable PostgreSQL database, not real user login, production
Graph/Artifact byte authority, native admission or an installed Chat canary.

Original protected evidence:
`/opt/eom/embedding-benchmark-os-evidence/chat-ranked-lwwhqPyD`.
Local diagnostic stage: `/tmp/eom-chat-ranked-db.lwwhqPyD`.

- Exact source-pinned helper raw SHA:
  `e3a32ef8b1157571700bcb8b74477f808e3e3a4d540805bcd8f98e8fc060ad91`.
-208 source hashes plus frozen Git HEAD/diff/untracked-name state checked before
  each bounded action; source was not edited during the gate.
- Tests stdout raw SHA:
  `4ddaa7abcbc815abc1b55f7eb4b2d865bdf83ae07a8e763b37bc8688e41cf3a9`.
- Independent readonly observer raw SHA:
  `83d1fbeedc15f14de5b7d0f752021880a1befb1728dfee433035b711aef44654`;
  observation stdout raw SHA:
  `17a97aa271b75d9faf9329e540f910a6a8d278b2078507b888b661121dad9f83`.
- Independent observer confirmed85 tests,208 then-current source pins, inspection
  identity PASS/head `20261017_0057`/zero other connections and exact removal of
  `/tmp/eom-api-testdb-20261018055917_828ecbf6`. Cleanup PASS. This was disposable
  migration state, not a production migration. Documentation finalized afterward.

Used existing valid noninteractive sudo in `%89`; no login prompt, credential
storage, auth-lifetime change or human fresh-auth bypass. Protected verification
helpers/evidence were installed; **the product feature/runtime was not installed**.
Operating DB/corpus/services, numerical prefix and CPU default were unchanged.

## Remaining original scope

Status: **SOURCE_PASS / DISPOSABLE_POSTGRESQL_PASS / NOT_INSTALLED / NOT_ACTIVE**.
Next: wire the optional live-ticket/origin native-query client and this metadata
read into the existing broker, merge native/ordinary offers without mixing scores,
and use the existing same-Artifact provenance producer. PENDING/unavailable must
remain explicit, never fabricated EMPTY/READY; hash/permission errors fail closed.
Current source/report/claim reauthorization and coherent protected deployment/live
delivery remain required. Full C1–C5 activation, complete seed/delta/current audit,
genuine CPU/CUDA comparisons and conditional coherent default/rollback remain open.

## Clean-source package evidence

Candidate `739f08f91f9eebf1eaed3324f647396bcc586e04` is pushed to `origin/main`.
The build-only release gate passed three-wheel/RECORD/installed simulation.
Eight contract/resource/registry/server/shared-discovery/client members match
the clean source byte-for-byte. Worker protocol and migration paths have no diff
against the source baseline. Build directory:
`/tmp/eom-api-build/739f08f91f9eebf1eaed3324f647396bcc586e04.3qeB1J/dist`.

| Wheel | Raw SHA-256 |
|---|---|
| platform | `19698558f2b846571761efdccb189ac0e764c95a57ac5455fbb2e1b002e12152` |
| API contracts | `5eba80360e9bbd4eb22c3c45a5300f1e565d7b478e6a5bd4699515985d1f2317` |
| API | `a51e86583a9b9f6b7c68fdf436cdb9ee899a47f5d246613075c5cd71aa9303ea` |

These are **build-only artifacts, not an installed/active product feature**.
The due thirty-minute readonly INDEX observation at2026-10-18 05:58:30.731045 UTC
recorded857 view encodings/bindings,221 revisions/6 logical indexes and latest
coverage269/545,289/545,299/545. Still PARTIAL; not857 distinct Items or a full
canonical/source/lease audit. Latest-five-only work states:2 REQUESTED,1 RUNNING,
2 COMPLETED, not a global failure count. Evidence:
`/tmp/eom-index-observation.OhZYYmMz/index-observation.json`.
Next routine read is not before06:28:30.732 UTC. No interactive authentication
before2026-10-19 05:10 UTC; the original human fresh-auth denial is unchanged.
