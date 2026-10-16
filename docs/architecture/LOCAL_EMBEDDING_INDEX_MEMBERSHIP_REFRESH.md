# Refresh index membership without recomputing existing vectors

2026-10-16 UTC. **SOURCE_AND_DISPOSABLE_EXECUTION_PASS; NOT_INSTALLED/NOT_ACTIVE.**
This implements original goal B5/B6/B8 boundaries, not a separate index framework
or a claim that the corresponding operating lifecycle is already complete.

## Evidence and bounded problem

`prepare_missing_embedding_bindings` checks canonical associations, not membership
of the selected namespace's current index. Associations can already exist in a
different population namespace. All bindings may therefore be reusable even when
the selected namespace has no current index. Source withdrawal can similarly
change the desired membership without creating a new encoding demand.

The current reconciler treats no missing associations as no work. Separately,
Runner's successful-equivalence lookup reuses a completed request even with a new
idempotency key. Changing only the key, generating another copy of the same plan
Artifact, or forcing a completed Workflow to run again is not a valid correction.
Characterization tests must establish these premises before changing behavior.

## Required design boundary

1. Responsibility: Catalog compares the current namespace index with the exact
   currently admitted sources/verified bindings. Existing Orchestrator/Runner
   submits a membership refresh through the same INDEX path, not another queue.
2. Canonical source: current source/report/Graph/policy resolution, registered
   immutable numeric rows and binding origins, and the exact selected index head.
3. Revision: retain all released1.1/1.2 requests/receipts. A closed service-only
   request1.3 adds an immutable reconciliation basis. Same plan bytes keep their
   original Artifact pointer; different refresh meaning changes request identity.
4. Pointers: pin the previous index manifest and semantic hash together, or both
   absent for a missing index; pin full eligible-source and available-binding set
   hashes/counts. These values are audit/intent, never source or service authority.
5. Access: indexed unique namespace lookup, PK revision lookup, bounded binding
   set comparison and same-request replay. Source/permissions remain independently
   reauthorized; no untrusted DTO can declare its own current membership.
6. Structures: frozen small basis, ordered immutable bindings and map/set lookup,
   existing native request/claim/reservation/checkpoint/CAS structures. No new DDL.
7. Cost: O(N log N) canonical ordering and O(N) map/set comparison for N<=1024;
   bounded predecessor/member reads.
   Reuse the already validated current-root capture and avoid a second full source
   projection/parse/hash pass. No cross-root authorization or filesystem cache.
8. Transaction: compare after current owner admission; capture basis before
   submission. Admission reauthorizes current service/selected sources; validate
   the full basis before staging and predecessor CAS at registration. Do not repeat
   full corpus projection during every selected-source guard. Own committed
   successor must not fail final receipt validation by reinterpreting the old
   predecessor as a new current-head requirement.
9. Ownership: pure contract below Catalog/Runner, adapters own SQL/Artifact IO.
   Numerical workers still receive staged local inputs; only Orchestrator commits.
10. Retry: identical basis returns the original request/Workflow, including FAILED
    history. A genuinely changed source/index basis is a new request, not a retry
    key workaround. Seed/delta retains existing encoding reservations; refresh
    never reserves or runs numerical work. Empty populations keep explicit waiting/
    unavailable semantics; never create empty vector or index placeholders.
11. Simpler alternative:1.2 has no immutable membership-change identity. Broadening
    its meaning, bypassing successful equivalence, or copying control Artifacts
    loses reproducibility. One additive1.3 contract is the necessary successor.

## Stages and required evidence

- First: closed JSON Schema2020-12 and frozen values, original schema bytes and
  executable dispatch unchanged. The proposed parser alone grants no execution.
- Then: exact Catalog observation, same-root capture reuse, supported submission
  and existing execution/completion wiring, with current-source/producer checks.
- Test missing head with reusable bindings, withdrawal, membership change with
  identical selected text, no new numerical forward, failed-history replay,
  concurrent refresh/CAS and crash recovery in isolated fixtures/disposable DB.
- Finally: package/install an admitted source successor only after the currently
  running three new-grant requests are terminal; run bounded actual replay/reuse.
  Never change live source authority while original commands remain nonterminal.

Source-only contract progress must not be reported as corrected live automation.
Consumer connection and CPU/CUDA requirements remain open in the full goal ledger.

## Initial contract-only source checkpoint —6631d467

Characterization now executes the existing registry application against synthetic
metadata: a namespace can have all reusable bindings but no namespace head.
Another test uses actual temporary SQLite Runner persistence: the same completed
request, submitted with another key, returns its original Workflow/command without
another Job. These are explicitly synthetic source/IAM fixtures, not live authority.

The closed1.3 source/mirror, independently pinned parser and frozen basis preserve
the old1.2 source-plan Artifact pointer. A genuinely different membership basis
changes the canonical request hash; no copied Artifact or fake retry key is needed.
At this initial checkpoint the executable dispatcher still rejected1.3, including
preconstructed subclass instances. Schema parsing is not a service/runtime grant.

Catalog's pure`plan_index_membership_refresh` distinguishes missing index,
changed membership and identical/no-available membership. It sorts bounded tuples
and uses revision-keyed maps/sets; it retains numeric row pointers. Duplicate or
foreign sources/bindings, mixed views/spaces, changed predecessor hash/schema/media
and copied extra fields fail explicitly. Planning and request validation share
one pure predecessor-closure function. Current read/source/producer permission and
actual bytes still belong to the existing owner adapters, not these values.

Source regression **266 PASS/31.70s**, strict mypy2 production modules and Ruff/
format/whitespace PASS. Separate real wheel gates **3 PASS/15.80s** verify exact
canonical resource bytes/RECORD membership and valid request parsing from the
installed temporary package without checkout imports; native dispatch remains
denied there too. These test wheels are workspace test material, not an admitted
operating release or permission to select a different source identity.

The initial focused run retained37 PASS/2 failures: malformed float test input
was incorrectly passed through the canonical fixture serializer before the parser.
The corrected negative test passes malformed external values directly to the
parser; production float/hash validation was not relaxed. Final source and wheel
logs:`index-membership-refresh-leaf-reviewed-final.log` and
`index-membership-refresh-installed-wheel.log` in the existing development window.

At that checkpoint the remaining implementation was: supported Catalog current-
namespace read and same-root observation,1.3 admission/execution/completion/replay,
actual disposable-DB concurrency/crash/CAS and bounded operating acceptance. This
checkpoint did not fix live no-work reporting or enable continuous indexing.

## Supported Catalog predecessor read — source checkpoint

`CatalogEmbeddingRegistryVerifier.resolve_indexing_namespace_predecessor` now
provides the missing service-only official read. It authenticates through the
existing source owner before lookup, selects the exact unique namespace head
once, validates its registered canonical member and reauthorizes before return.
It performs no corpus projection, vector read, model execution or registry write.
An ordinary operator cannot call this INDEX-only owner operation as a substitute
for the supported user-facing read boundary.

The existing index-publication basis and this new read share one predecessor
validator; namespace/space/recipe/metadata/hash checks were not copied into another
adapter. Missing head returns absence; corrupt bytes, mismatched registered
metadata/namespace and a late permission denial fail explicitly. Actual service
capture is synthetic in the unit fixture, while immutable member reads are real
temporary files. **184 source tests PASS/18.78s**, strict mypy1 module and Ruff/
format PASS. This overlaps earlier contract tests; counts are not added together.

This internal owner method is not yet selected by the operating d4846220 runtime.
The1.3 admission/execution/completion and actual PostgreSQL/lifecycle gates above
remain necessary. A new source candidate must not replace current original
commands while they are nonterminal.

## Execution integration decisions

- Preserve old public request imports/serialized1.1/1.2 values. Move the common
  immutable request values to a dedicated contract module so1.3 and dispatch have
  no circular import;1.3 remains a subtype of the service request family.
- Return already verified binding values with the owner-local missing-binding
  capture. Inspect the namespace predecessor only on no-missing-binding paths;
  do not repeat full corpus projection or vector IO to plan a refresh.
- A refresh selects one existing available source as its source-plan witness.
  Its1.3 basis pins the whole desired membership. Same basis replays; changed
  basis changes the canonical request, not just the key or copied Artifact.
- Service admission still verifies actual current runtime/grant/selected source
  and canonical control bytes. Validate the whole refresh basis in the existing
  index-preparation root, before staging/publication. Its predecessor is an
  initial publication CAS condition, not a permanent "must still be current"
  check that would reject the Workflow's own committed successor on replay.
-1.3 takes the existing coordinator/index/receipt path but **never calls encoding
  reservations, dispatch or numerical launch**. All rows must already be canonical
  registered rows from Catalog. No fake owned/completed encoding Job is created.
- Validate selected-plan coverage before publication, sharing that pure rule with
  the existing receipt validator. Keep the original coordinator/checkpoint/CAS/
  receipt lifecycle and preserve partial Artifact publication on crash.
- Existing missing-vector seed/delta requests retain1.2 behavior. No new queue,
  migration, worker protocol, resource ceiling or source permission is introduced.

### Coherent append-only registry observation

Discovery uses READ COMMITTED and must not combine bindings from one SQL statement
with an anti-join executed after another registration commits. Read the bounded
binding rows first, then their immutable FK-backed encodings. Derive missing keys
from that same verified binding map in O(N), not a later mutable observation. A
binding committed after capture is work for the next observation; existing
idempotency/claim/registration rules still prevent duplicate accepted outputs.
This replaces three bounded lookup statements with two and adds no isolation,
lock, retry or cache. Missing encoding provenance remains an explicit error, not
a reason to retry arbitrary pointer corruption. Independent-writer tests must
cover commits between both reads and prove the next observation sees the result.

### Recovery before the prepared-index checkpoint

The actual disposable interruption test reproduced a staged-file/checkpoint gap:
index bytes can survive a root rollback before INDEX_PREPARED. Reassembly must not
choose a new random revision/time while the create-once staged file remains. Use
domain-separated identities derived from the already committed allocation's
unique index-producer identity, and its pinned creation time. Existing prepared/
registered/completed checkpoints still use their original stored identities.
This needs no schema/DB change, file overwrite, row repair or external retry key.
Changed current source/membership still fails validation or staged-byte identity;
determinism is not authority to reuse changed inputs. Preserve failed test evidence.

## Executable successor — source and disposable PostgreSQL checkpoint

The generic executable parser now recognizes1.3; the released1.2-specific parser
still rejects it. Public request imports remain compatible through a shared pure
value module, avoiding a circular import. No old schema bytes, persisted request,
Workflow/failed history, registry row or accepted Artifact was rewritten.

Reconciliation reuses the verified binding capture, reads the official selected
namespace predecessor and submits one stable available witness only when needed.
The original plan publication identity is reused across genuinely different
membership intents. Original successful-equivalence and failed-history behavior
remain; no new-key bypass or copied source-plan Artifact was added.

The executor bypasses numerical reservations/dispatch for1.3 and uses existing
allocation, index preparation, registration CAS, receipt and terminal transitions.
Selected-demand coverage is checked before staging and by the receipt reader
using one pure rule. Full membership is checked against the immutable request
basis, including the original predecessor, rather than requiring that predecessor
to remain current after this Workflow's successful registration.

Verified gates, not counts to sum:

- Focused source regression **607 PASS/83.00s**.
- Actual guarded PostgreSQL embedding/registry/completion suite **43 PASS/182.21s**.
  This includes8 refresh cases: another valid population namespace with globally
  reusable bindings, withdrawal, all3 checkpoint interruptions, and changed
  source/binding/predecessor basis rejection before staging. They create no new
  numerical encoding Job or launcher call during refresh. An earlier focused
  confirmation was8 PASS/35 deselected, not another independent acceptance total.
- The same PostgreSQL suite also proves coherent discovery when an independent
  writer commits between binding/encoding reads, and confirms2 bounded lookup
  statements rather than3. Source authorization is explicitly synthetic there.
- Guarded native stage/Runner/reference compatibility **127 PASS/95.74s**,
  including independent roots submitting one1.3 Workflow/START and exact service/
  namespace queue routing. Final read-only disposable inspection: identity PASS,
  head`20261014_0055`, other connections0. No production test target or migration.
- Fresh temporary installed-wheel/RECORD and dependency-boundary gates
  **16 PASS/28.71s**; no checkout imports, source/registry permission claims or
  installed production release are inferred from these test wheels.
- Existing service-loop/multiview owner regression **40 PASS/4.88s**; round-robin,
  graceful drain, no-work behavior and observation logging remain compatible.
- Strict mypy **13 production modules PASS**; Ruff, formatting and whitespace PASS.

Preserved failures distinguish test-fixture mistakes from source defects. Initial
service fixtures correctly failed the human/service capture-shape and missing
service-source-owner guards; only the fixtures were corrected. An invalid
occurrence-population fixture was replaced with closed, explicitly synthetic
occurrence metadata, without weakening provenance requirements. Actual execution
then exposed and reproduced two source defects: an empty new-numerical-shard read
and the pre-INDEX_PREPARED staged-byte/checkpoint mismatch. Both were corrected
without overwriting files, changing failed history or broadening permission.

Bounded logs remain in the existing temporary development window
`/tmp/eom-identity-provider-install.nAaycoDM/`: source
`index-refresh-wiring-reviewed-final.log`, PostgreSQL
`index-refresh-wiring-postgres-final.log`, focused refresh
`index-refresh-wiring-postgres-focused-fifth.log`, wheel
`index-refresh-post-recovery-boundaries-wheel.log`, strict
`index-refresh-reviewed-strict.log`, stage`index-refresh-wiring-stage-final.log`,
loop`index-refresh-service-loop-regression.log`, and first-through-fourth failures.
These working logs are not registered production acceptance Artifacts.

**Operating d4846220 remains unchanged.** A clean standard candidate build and
16-module/four-schema archive→wheel byte closure now PASS for`bb17912b`;
[exact immutable build selection](../operations/LOCAL_INDEXING_MEMBERSHIP_REFRESH_CANDIDATE_2026-10-16.md).
Protected installation/source identity admission, immutable service-grant/config
selection, rollback and bounded actual reuse acceptance remain necessary before
declaring this correction live. This checkpoint does not enable continuous work,
activate ordinary consumers or prove CPU/CUDA performance. The full goal remains
active with those requirements in its separate ledger.

## Partial membership must not wait for seed completion

Operational preparation found a remaining scheduling boundary: another namespace
can have reusable bindings while this namespace has no/currently stale index,
even though additional sources still need vectors. Waiting for all missing
encodings before refreshing membership delays usable partial coverage and source
withdrawal reconciliation. The actual service identity permits only the fixed
installed entry; an operator helper cannot impersonate it to force a test request.

Use the same official bounded binding/predecessor observation whenever bindings
are available, not only after the missing-vector list becomes empty. If membership
differs, submit the existing metadata-only1.3 witness first. Its reported missing
binding count stays honest. Once that index matches the available bindings, the
next ordinary observation submits missing-vector1.2 work; no duplicate numerical
job, parallel maintenance queue, new schema or automatic retry is introduced.
No-available-binding seed and exact-current partial-head behavior remain unchanged.
Add characterization and independent-root submission tests before activation.

Characterization first reproduced the unwanted1.2 seed choice with partial
bindings; its failed log remains. The one-condition scheduling correction now
passes95 focused source/owner-loop tests and128 guarded PostgreSQL stage tests,
including two independent roots submitting one1.3 request with an honest nonzero
missing-vector count. An exact-current partial head still submits ordinary1.2
missing work. Strict mypy1 module and Ruff/format PASS. No schema, permission,
runtime-entry/fence, queue or numerical policy changed. This correction needs a
new immutable candidate; the earlier bb17912b installation stays inactive.
