# Refresh index membership without recomputing existing vectors

2026-10-16 UTC. **CONTRACT_AND_PURE_PLAN_SOURCE_PASS; NOT_EXECUTABLE/NOT_ACTIVE.**
This closes original goal B5/B6/B8; it is not an unrelated index framework.

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
7. Cost: O(N) membership comparison for N<=1024; bounded predecessor/member reads.
   Reuse the already validated current-root capture and avoid a second full source
   projection/parse/hash pass. No cross-root authorization or filesystem cache.
8. Transaction: compare after current owner admission; capture basis before
   submission. Validate the exact basis at initial admission and predecessor CAS
   at publication. Own committed successor must not make final receipt validation
   fail by reinterpreting the old predecessor as a new current-head requirement.
9. Ownership: pure contract below Catalog/Runner, adapters own SQL/Artifact IO.
   Numerical workers still receive staged local inputs; only Orchestrator commits.
10. Retry: identical basis returns the original request/Workflow, including FAILED
    history. A genuinely changed source/index basis is a new request, not a retry
    key workaround. Reuse existing encoding reservations; no model execution for
    all-reusable refresh. Empty/no-available populations keep explicit waiting/
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

## Source checkpoint

Characterization now executes the existing registry application against synthetic
metadata: a namespace can have all reusable bindings but no namespace head.
Another test uses actual temporary SQLite Runner persistence: the same completed
request, submitted with another key, returns its original Workflow/command without
another Job. These are explicitly synthetic source/IAM fixtures, not live authority.

The closed1.3 source/mirror, independently pinned parser and frozen basis preserve
the old1.2 source-plan Artifact pointer. A genuinely different membership basis
changes the canonical request hash; no copied Artifact or fake retry key is needed.
The existing executable dispatcher still rejects1.3, including preconstructed
subclass instances. Schema parsing is not a service/runtime authorization grant.

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

Remaining implementation is explicit: supported Catalog current-namespace read
and same-root observation,1.3 owner admission/execution/completion/replay wiring,
actual disposable-DB concurrency/crash/CAS and bounded operating acceptance. This
checkpoint does not fix live no-work reporting or enable continuous indexing.

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
