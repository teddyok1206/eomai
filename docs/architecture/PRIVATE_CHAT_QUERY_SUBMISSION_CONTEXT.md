# Original private Chat QUERY submission context

2026-10-17 UTC. Required design before schema/persistence changes. The missing
boundary is the crash interval between original Workflow/START submission and
the first native allocation; this is not another queue or authorization service.

1. Responsibility: workflow contracts own a closed, text-free submission context;
   the existing Runner owns atomic Workflow/START persistence and replay. This
   step supplies the immutable storage invariant, not an execution grant.
2. Canonical source: the actual live origin resolved by the existing Chat owner,
   matched with the exact private request by the current source/control owner.
   `WorkflowInstanceRecord.runtime_context` is the canonical submitted origin.
   Later native ALLOCATION/receipt history pins and compares that same value.
3. Identity: distinguish Workflow ID, request semantic hash, context semantic hash,
   actual message/dispatch Artifact revisions and native launch Job. A pure
   context can validate pins but cannot authenticate its claimed actor/claim.
4. Resolution: keep the existing private request/launch/coordinator schemas
   unchanged. Add JSON Schema2020-12 before the new Pydantic value. Require exact
   actor/basis/request closure, current source reauthorization before mutation,
   immutable original context on replay and no source/latest substitution.
5. Access: one original private numerical request per authenticated Chat turn;
   repeated tool calls reuse the original work. Use the existing idempotency key
   lookup and an exact `(actor, conversation, turn)` lookup. Different claims,
   keys or new source pins cannot generate a second original Workflow for that
   turn. A genuinely new user turn is a different logical request.
6. Structures/index: one small frozen context in the existing JSONB metadata,
   including the native runtime's existing empty `artifact_pointers` value. Add
   a unique partial B-tree expression index for the private turn key, not a new
   table, binary column, GIN scan or mutable cache. New contexts are append-only
   with the parent Workflow; no worker gets DB/NAS access.
7. Complexity/scale: indexed O(log W) original lookup/unique arbitration and
   bounded context validation (64KiB maximum). One metadata row per used turn;
   expected scale tracks normal Chat use, not the public Item/vector corpus.
8. Transaction/concurrency: source admission stays in the exact caller root.
   Original context, Workflow and START must commit/roll back together. Replays
   compare the context and native identity, never recreate a missing START or
   replace expired execution. Unique turn identity reinforces the domain key
   across different supplied idempotency keys and concurrent processes.
9. Dependency: pure workflow/contracts contain no SQL. Runner persistence models
   reinforce metadata shape/parent closure; a frozen additive migration supplies
   the unique index and private-only mutation/delete guard. Keep ordinary/INDEX/
   reference Workflow behavior unchanged. No new dependency or cross-owner write.
10. Failure/downgrade: closed/hash/mixed-purpose/authority extras return a stable
    content-free contract error. The DB rejects missing private context and
    mutation of its origin/audit/payload; all failures roll back the caller root.
    Refuse downgrade when any private history remains, rather than remove its
    protection. No production migration/activation follows from source tests.
11. Simpler alternative: ALLOCATION alone loses the origin if a crash precedes
    the first claim. An untyped runtime-context key is mutable and unbound to
    replay. A new origin registry or a cascade of request/launch schema versions
    is unnecessary: use the existing runtime metadata field with one closed
    value, original fingerprint, DB guard and unique turn identity.

The DB enforces parent/shape/immutability/uniqueness. Application JSON Schema and
Pydantic remain the single implementation of complete message/hash validation;
do not add a second JSON canonicalizer or cryptographic extension to PostgreSQL.
The partial index covers private definition rows only. No full-table turn scan,
new public query API or private question/embedding enrollment is introduced.

Historical/completed read authorization is separate from a live execution origin.
A later Chat claim may read an already completed original result only through an
explicit current owned-message/result read contract; it cannot relabel the old
origin or create another numerical launch. Uncertain/pending outcomes require
supported reconciliation, not a new key or a latest-ticket lookup.

For this persistence prerequisite, leave private definition admission, application
step/result CHECK, automatic queue routing and actual executor OFF until their
implementation is complete and verified. Synthetic metadata rows in disposable
DB tests are not genuinely admitted private Workflows. The full goal still
requires actual source/claim-bound execution, tool delivery, protected compatible
installation, C1–C5 runtime acceptance and the frozen CPU/CUDA comparison.

The source migration successor is exactly `20261017_0056` after `20261014_0055`.
The release operator has additive context/admission `1.5` and two exact `0056`
callbacks. Historical `1.0`–`1.4` schema bytes, callbacks and receipts keep their
original migration meanings; arbitrary `head` and old-context retargeting remain
rejected. Updating source does not migrate the installed database or update its
protected release helper. Those remain separate compatible-installation gates.

## Source verification checkpoint

Source regression before the ID-pattern correction: **537 PASS across19 nonoverlapping suites** (private source/
execution/checkpoint/publication/contracts and release/resource/deployment
compatibility). The dependency-boundary inventory passed separately **6/6**.
Strict mypy4 production modules, Ruff/format17 Python files, shell syntax and
diff whitespace checks PASS. Earlier177/303/234 overlap and are not summed again.

The new actual-PostgreSQL inventory adds16 synthetic metadata cases to the
existing219-case `embedding-stage-tests` purpose: closed parent context and
NULL/extra/basis/payload/bounds rejection, readback, immutable origin/audit/payload
and DELETE rejection, empty-history migration round trip, retained-history
downgrade refusal and two concurrent requests with distinct keys/fingerprints but
the same actor/turn. Collection235 is not an execution PASS. The finite guarded
run and cleanup must finish before recording disposable-persistence acceptance.

The first marked PostgreSQL run (`private-context-KsmXuk07`) is preserved as
**228 PASS/7 FAIL, cleanup PASS**, not acceptance. The seven positive private
cases exposed a new source guard defect: the draft SQL assumed `chatconv_`, while
the existing closed Chat origin/ticket contract uses `chat_`. Both the new model
guard and not-yet-released migration now use that exact existing pattern; no old
contract or authority rule was widened. A dedicated source regression binds the
SQL ID patterns to a valid closed origin. Reverification uses a new disposable
database and retains the original failed evidence unchanged.

Post-correction source: **304 private/resource/version suites +234 independent
release/deployment suites =538 PASS across19 suites**, with the separate6/6
dependency inventory unchanged. This supersedes537 as the final source count;
it is not a PostgreSQL or operating-runtime acceptance claim.

## Final guarded persistence acceptance

The corrected supported `embedding-stage-tests` execution passed **235/235, no
skips; disposable database/role cleanup PASS**. This includes the existing219
native/reference/lease/root/replay regression cases and16 new private-context
cases. The definition/origin/authority fixture is explicitly synthetic and
inactive; SQL constraints/triggers/partial uniqueness and separate concurrent
transactions are real PostgreSQL. No model, real Chat claim or operating DB was
used. The original failed228/7 run remains a failure with its own cleanup proof.

Final evidence:
`/opt/eom/embedding-benchmark-os-evidence/private-context-MQbcisSm`;
finite root helper raw SHA256
`4688bb500d63fe4f7cbdd7b30a749849b04352eab163a7590e8d5b06c088e025`;
test stdout raw SHA256
`8a597f6095dc20ada30de05865bea307644e76461351368bcea421221b55c755`.
No new login prompt, credential persistence, auth/TTL change or automatic model
retry occurred. **SOURCE_PASS / DISPOSABLE_DB_PASS / NOT_INSTALLED / NOT_ACTIVE**.
Original command-bound application submission/execution, tool delivery and the
full goal's remaining consumer/CPU-CUDA gates are not completed by this leaf.

## Source candidate archive closure

Candidate `d3939f7291f882c372ca058d2be530e7619cea9a`, tree
`f328a8df98dba53a6a5ff5f12cf63cf5dce8fb85`, passed the supported
`scripts/api/deploy_release.sh --build-only` three-wheel inspection and RECORD
verification. The initial unsupported positional `build` invocation returned
usage/exit2 before building; the supported flag then passed without any install.

Wheels under
`/tmp/eom-api-build/d3939f7291f882c372ca058d2be530e7619cea9a.iWdfGI/dist`:

| Wheel | Raw SHA256 |
|---|---|
| platform | `f45c127d15d2b36b2b340c45f2d27c033815c25b656766a75abfaa80c002a092` |
| API contracts | `1b19c61e2e5349819dd533f1284b0a7bda51a7bdece5d0f31efa499c25635dc6` |
| application API | `18479c68ed4256dfe70f589f840df8cf20f0acc08ccff2746abb598f66f58ace` |

The exact two-archive isolated `-I -S -B` proof loaded310 EOM modules only from
the two pinned wheels, with no checkout/Git/test/ML import. It validated the exact
synthetic source/control/native input, built/reparsed the original submission,
checked its private text exclusion, parent/fingerprint/key, current0056 constant
and compiled partial unique index. Unknown authority extras and private compiler
admission remained denied. DB/model/socket calls0, runtime activation false.

Proof: `/tmp/eom-private-context-package.yhgYGUsK/prove_archives.py`, raw
`3a11e0cd131570e9050441996e053b5abab356d53c19801b62e84753f0a748bf`.
Synthetic input raw
`7a7eb93230b43049a3a5cac9c167a1884667c37ccc328b95c0bc437ddfa7625f`.
This is package closure, not an installed migration/private Workflow, real Chat
ownership/claim, numerical acceptance, six-run comparison or full-goal completion.

## Original-command Runner owner: implementation boundary

The next application owner composes the existing live Chat/public-source owner,
the immutable submitted context and `NativeCommandMutationFence`. Canonical
origin remains `runtime_context`; a later/current ticket never replaces it.
Definition/Workflow/command/step reads are primary-key/index lookups, with one
root-local source resolution rather than a parallel queue/authorization cache.
Small context validation is bounded; public-source work keeps its existing
bounded cost. No new table, wire schema, model dependency or source class is needed.

The actual attached rows must match the fixed private definition/hash, original
request/context fingerprint, trusted turn key and START actor/payload/source.
Fresh claims require an unused pending command; reclaimed claims require the
exact prior step, launch and nonfailed allocation with the same original origin.
Mutation/execution re-resolves actual Chat ownership plus public controls/scope
in the caller's current root, then checks the command lease again after IO.
The existing shared fenced transaction gains the explicit private request family;
it still releases every SQL root before inference and rechecks authority on exit.

The source owner's clean-root precondition becomes a named supported function,
reused before row reads to prevent autoflush of unadmitted caller writes. No
private-module import or independent rule/queue is introduced. This owner does
not commit, submit/claim a command, launch a unit or grant compiler admission.
Definition/request/context mismatches fail content-free; expiry/unknown physical
outcomes retain their original identity. A metadata-only owner that never revisits
the live Chat/source and command lease would be the simpler but unsafe alternative.
Full private submission, executor, result-CHECK/claim routing and Chat delivery
still need to compose this owner before runtime activation.

Two concrete integration constraints remain part of that same full private
vertical, not new product requirements: the closed immutable private
`runtime_context` cannot receive the existing terminal helper's mutable
`final_pointer_manifest`; the canonical private receipt must instead be resolved
from its successful step (and exact terminal history), preserving the origin.
Likewise async `ADVANCE_WORKFLOW` must be bound to its original private step and
pending command lineage, not mislabeled as a new START/numerical request. Until
those actual executor/terminal/routing pieces are implemented, this owner only
accepts the original START shape and private compiler/result-CHECK admission stays
closed. Do not enable the private runtime based on these source-owner tests.

## Original-command owner verification

`CatalogPrivateChatQueryOwnerAdmission` now validates attached fixed-definition/
request/context/fingerprint/turn-key and original START actor/source/payload/hash
before using the existing live Chat/public-source owner. Reclaimed work requires
its exact allocated nonfailed private history and original origin, not a new
attempt. Every mutation reuses `NativeCommandMutationFence` and checks expiry
after source IO. The shared fenced transaction explicitly recognizes the private
request, redacts invalid stored schema errors, retains its Workflow→command lock
order and rechecks current authority at commit. The public step reader recognizes
the private key; compiler and private step/result admission are still closed.

The first unit run16 PASS/2 FAIL correctly rejected a fixture that changed its
definition hash without changing its immutable execution policy. Test factories
now accept an explicit exact definition pin; their prior defaults are unchanged.
The guarded owner fixture uses that genuine fixed private definition hash and a
new canonical synthetic Chat identity before capture. No production policy or
pointer check was relaxed. After the guarded owner run, one fixture formatting
change was verified to have identical Python AST:
`16dd9a8874f1fa6e625b481b4566f3c15c47e58f6eaf54435cf48c6b43905720`.
The final source regression then passed434 tests across16 suites (including6
dependency tests), strict mypy5 production modules, Ruff/format13 files and shell/
diff checks. Earlier23/102/345/89 overlap; do not add them to434.

Actual PostgreSQL owner gate passed **76/76 plus235/235 in two separate guarded
databases, no skips; both cleanup PASS**. The7 new owner cases cover registered
index/control reads, read-only fresh claim, actual per-root command witness,
terminal-witness nonreuse, late claim loss, expiry after IO, changed generation,
rollback and prevention of autoflush/unallocated recovery. SQL, local Artifact
files and command locks are real; Chat/IAM/population and declared Workflow/START
remain synthetic, not genuine compiler/native admission. No model/service call.

Evidence:
`/opt/eom/embedding-benchmark-os-evidence/private-command-owner-GnP4PiCZ`;
finite helper raw `cf697186c3aa522e956ac57b6dd34302581ff415ab02163dd2d760f1ba6a12b1`;
76 stdout raw `da467328fba715e28fd164138bc735718a2c8e8ab62a3461b0ac371a6b4e4e47`;
235 stdout raw `adc8febc29bce33148ecfbbff3979b73c90ee36d2253de364d317c6c1553183e`.
The later79-case numeric-read gate includes these76; it is not79 more owner cases.
Source owner/executor admission and full C4/runtime/goal completion remain separate.

No application compiler/result CHECK is opened. No operating database migration,
service restart, private model/QUERY, unit installation or Chat tool activation
follows from source checks or synthetic metadata fixtures.
