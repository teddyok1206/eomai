# Original native QUERY Job allocation

2026-10-17 UTC. Design before implementation; not a new execution grant.

1. Boundary: extend original native launch allocation to PRIVATE_CHAT_QUERY by
   reusing the current Orchestrator Job/protocol/event repository. Keep reference
   Workflow admission, live Chat authorization, SQL command leases and physical
   native-purpose admission separate. This library cannot authorize a launch.
2. Canonical source: the caller-fenced immutable Workflow intent and exact launch
   association. Use the already-released closed private intent/launch schemas;
   no new schema, migration, queue, table, service actor or public endpoint.
3. Identity: Job ID, Workflow/step IDs, request hash, protocol, private basis and
   launch hash remain distinct. The request stored in Job is metadata only, never
   the private question text or numerical input/vector bytes.
4. Resolution: validate exact typed request/launch families and all parent/control/
   basis pins before any write. Read back canonical protocol, Job hash, task type,
   original event, state transition and association; mixed families fail closed.
5. Access patterns: one unique indexed idempotency key lookup, one indexed event
   lookup and the existing protocol primary key. No history/corpus scan.
6. Structure: a shared launch-record application adapter for both typed purposes
   and the retained reference wrappers, not a generic queue framework. Preserve the reference key and bytes.
   Private key binds original Workflow/step/attempt (not mutable request content),
   so changing an intent cannot create a second launch for the same private step.
7. Complexity: bounded metadata validation plus indexed DB lookups; existing Job
   and event indexes/unique constraints are sufficient at one launch per step.
8. Transaction: require the caller's active root, never a nested-only allocation;
   caller retains Workflow→command fences. Existing Job uniqueness arbitrates
   concurrent first creation; a losing root rolls back rather than inventing a
   replacement key or assuming its new Job ID won. No model or file IO in SQL.
9. Dependencies: workflow contracts own immutable values; Orchestrator adapters
   own Job/events and transaction checks. Runner/source/physical launch ownership
   stays outside this module. Public reference wrappers preserve exception/API
   behavior; no caller reaches into private infrastructure helpers.
10. Failure/replay: same original launch is returned on exact replay; foreign
    protocol/request/basis/event or terminal state inconsistency is explicit.
    Failed history is never rewritten. Protocol registration and original Job/
    events commit or roll back with the caller root; no automatic execution retry.
11. Alternative: copying the existing launch allocator would duplicate the same
    transaction/protocol/hash/event invariants. Relabeling a reference launch as a
    private query would violate purpose/source/result contracts. Extract the
    existing shared storage boundary and add only private-specific closure/key.

This does not admit a private Workflow, widen result CHECKs, authorize a Chat turn,
install/start a numerical unit or deliver a Chat tool result. Actual admission must
bind the live Chat origin, current public Catalog permission and original command
before calling this adapter. Those remain necessary for the complete C4 goal.

## Verified checkpoint — 2026-10-17 UTC

SOURCE_PASS / DISPOSABLE_DB_PASS / NOT_INSTALLED / NOT_ACTIVE.
The current reference allocator and protocol/root checks now delegate to the
shared storage adapter; old reference keys, request/event bytes, checkpoint phases
and public wrapper exception behavior remain compatible. Private SQL allocation
conflicts return a content-free error and require caller-root rollback and original
key inspection, not new IDs/keys or inference retry.

- Existing reference execution/continuation source regression:93 PASS.
- Final focused private publication/execution/storage/handoff/dependency regression:
  154 PASS, including12 new storage checks. Counts overlap other historical suites;
  do not add them to unrelated checkpoint totals.
- Strict type2 files, Ruff/format and shell/diff checks PASS.
- The existing guarded `embedding-stage-tests` purpose now includes five private
  allocation cases: **213 PASS with no skips**, actual disposable PostgreSQL,
  cleanup PASS. Same-key replay, exact original Job/events, caller-root rollback,
  concurrent first allocation, changed private intent and mixed-purpose denial
  were exercised. IAM/source/native and the private Workflow/step authority are
  explicit synthetic seams; this is not a genuinely admitted private Workflow.
- First full run:189 PASS/24 FAIL. One new concurrent test exposed an unnormalized
  SQL uniqueness conflict;23 older application tests used a stale anchor fixture
  signature. The SQL error boundary was corrected for the new private purpose
  without changing the legacy reference exception contract. The fixture now accepts
  the current optional reader and validates its Session when supplied.
- Second full run:212 PASS/1 FAIL, because the first fixture correction incorrectly
  required an optional reader on the completed-read branch. The final fixture
  follows the actual optional port contract. The final full213-case gate passed;
  neither SQL/source authorization nor runtime checks were relaxed.

Failure evidence remains in the root-owned directories
`/opt/eom/embedding-benchmark-os-evidence/private-query-allocation-6G1w5KLe`
and`/opt/eom/embedding-benchmark-os-evidence/private-query-allocation-final-KXlIItl0`.
Final evidence:
`/opt/eom/embedding-benchmark-os-evidence/private-query-allocation-accepted-C1bPQP3h`.
Final operator raw SHA-256:
`19d080e6f8499fef020add7b036bc38a1f8e43bf57676fd3011a88534068902c`;
test stdout raw SHA-256:
`a48ce79d9b5eba95edd93a3e124b5367ff76ec00511f91ccdead1657d1f928a4`.
All three disposable databases/roles were removed via exact manifest/marker cleanup;
failed logs are preserved. Production data/services and model runs were unchanged.

The [actual original HTTP result-read timeout](../status/REFERENCE_QUERY_HTTP_READ_TIMEOUT_2026-10-17.md)
is now the next priority within the unchanged goal. Private origin-bound Workflow
admission, complete checkpoints/physical execution/tool delivery, installed source
activation, other consumers and CPU/CUDA/default verification remain incomplete.

### Candidate packaging

Code candidate`4e0fcb9194c150cd7fc55017714e3b8c594bb551` passed the standard
three-wheel/RECORD build. An isolated`python -I -S -B` proof loaded165 EOM modules
only from two pinned archives, checked both closed request/launch families and
the unchanged reference/new private keys. No checkout/test/ML imports or actual
DB/socket/model/install calls occurred in that archive proof. The actual Job/
event transaction evidence remains the separate213-case PostgreSQL gate above.

- platform wheel raw SHA-256:
  `d5b27e1bd3fdad2dd28f4091fe93c06df5f98d0922f7eda3e0a58820a368240f`.
- API-contract wheel raw SHA-256:
  `507a6b6c95667072fc1463623a4934e70c4ca650ca99314b1ea59b78f72d516d`.
- application-API wheel raw SHA-256:
  `8534341de4d5e92c0404118d830a8e3f22cbb9c37adf954da65ae61c07cc4f2c`.
- archive proof script raw SHA-256:
  `3a78c57732703ef7f2bc44837affef8ada7483104652376ccb6edc6d91b3ca59`.
- synthetic metadata-only fixture raw SHA-256:
  `1516a589faff658b972d938aa2bf98a03a014c58c550aec86698ee5d15dc412c`.

Packaging does not activate private Workflow/native execution or close the actual
HTTP result delivery, C4 or the full goal. No production component was replaced.
