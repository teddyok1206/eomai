# Private Chat QUERY: official DOCUMENT source/index read

2026-10-17 UTC. Design before behavior. This closes a concrete C4 source-owner
gap, not another search engine or a permission grant.

1. Responsibility: extend the existing Catalog registry verifier with private
   request preparation and pinned DOCUMENT read methods. Existing Graph/source,
   accepted-report, IAM and Artifact/registry owners remain authoritative. The
   current reference-only anchor adapter cannot accept a private question; do not
   fabricate an approved anchor to pass it.
2. Canonical source: the exact released Graph/policy/source/report and registered
   DOCUMENT index/shard revisions. The Chat owner independently owns the private
   message/claim. Public preparation contains only small source/profile/report
   pointers and coverage/truncation metadata, never private text or QUERY vectors.
3. Identity: preserve request hash, Graph/policy/source/report and index Artifact
   revisions separately. Every call reauthorizes the actual operator; no machine
   indexing identity, caller-supplied role or implicit latest substitution.
4. Resolution: reuse `_document_view_owner`, the official source capture and the
   common pinned-index application. Validate the private request's closed existing
   schema, source-class subset, recipe/space and current-root ownership. Resolve
   exact files/schema/media/hash/approved producers and index/binding membership.
5. Access: bounded full population selection plus keyed source/profile/encoding
   joins and one ordered fixed CONTENT_ONLY view. Missing reports and vectors
   remain partial coverage, never permission to invent an analysis or fake Item.
6. Structures: one frozen owner-local prepared scope and the existing root-local
   Artifact reader/window. Source/profile maps and set validation reuse the common
   document validator. No DB/schema/index/queue/cache table or wire change.
7. Complexity: O(authorized sources + selected index rows + vector dimensions),
   max1024 sources. Reuse immutable file decoding within the caller root, never
   cache authority. No repeated all-source reads for each individual binding.
8. Concurrency: require the exact clean nonnested caller root; never open/commit
   another transaction. Capture before and freshly recapture after numerical
   DOCUMENT materialization, using a separate capture owner that has no retained
   read-window shortcut. Root changes, pending ORM writes and source/report/policy/
   lifecycle revocation fail explicitly before delivery.
9. Dependencies: Catalog owns these read use cases and registry adapters. Pure
   private/context contracts do not import storage. Actual Chat source and native
   QUERY owners compose the read methods later; workers gain no DB/NAS interface.
10. Failure/replay: compare the current prepared scope with the exact original
    request/source set on replay. Denial/stale/hash corruption is an explicit
    error, not an empty-success or latest head. A truly absent optional index has
    no numerical read but still receives full before/after source authorization.
11. Simpler alternative: coercing a private request into the released reference
    request would falsely assert an approved anchor and self-exclusion semantics.
    Duplicating Graph/index readers would split current-source checks. Extend the
    same owner with two typed private methods and reuse its existing window.

The existing private request/response JSON Schema2020-12 is unchanged. The new
prepared scope is an internal frozen value, not an aggregate or persisted cache.
Native policy/installation/admission, current Chat origin/claim checks and actual
tool activation remain separate mandatory gates. These methods cannot compute a
question vector, publish data, submit a Workflow or turn read access into approval.

Tests: closed/mixed-purpose/coerced input; exact caller root and actual operator
capture; no anchor or question text in public source work; complete start/end
recapture; late source/report/permission/root/producer changes; missing-index
behavior; original typed scope replay; real pinned file/hash/index/binary closure;
current reference/new-authoring/25-cohort and read-window regressions. Source/IAM
fixtures are synthetic unless an explicit guarded current-runtime test says so.

## Source implementation and verification scope

The existing registry verifier now exposes two small public adapter methods:
`prepare_private_chat_document_scope_in_session` and
`read_private_chat_document_index_in_session`. Their implementation lives in
`private_chat_document_read.py`; the bounded root-local window is shared with
existing reference/authoring/cohort consumers through
`similarity_document_read_window.py`. There is no new persistence, independent
registry reader, SQL writer, dependency or wire schema.

The prepared frozen value holds the private request hash, exact public source/
profile/report pointers and truncation only. The actual private message, origin,
claim, question vector and current authentication stay with their respective
owners. A prepared value is not a permission token. Optional absent index reads
still require fresh full start/end source capture, while a selected index reuses
the same registered revision/binding/encoding and four-file numeric resolver as
the other consumers. The final capture uses a different owner without a retained
numerical window, so immutable-byte reuse cannot suppress current authorization.

The final focused source suite passed **318 tests across8 suites**, including26
new private read cases, existing reference/authoring, fixed exam observation,
private/context services, registration and private schema contracts. Earlier
26/185 runs overlap this inventory and are not added. Strict mypy4 production
files, Ruff/format and shell syntax PASS. The first CONTENT_ONLY tests exposed a
test fixture retaining a METADATA_ONLY shard lookup; the reusable fixture now
takes an explicit view with its old default unchanged. The private contract was
not broadened. A wrong test import/path prevented collection in earlier local
invocations; those runs are not counted as tests or PASS.

The supported guarded `embedding-tests` inventory includes eight new actual
PostgreSQL cases: registered metadata plus Orchestrator-published result/shard/
vector/index files, exact caller root, no SQL writes/head lock, late public-source
or permission revocation, and actual corruption of each of the four files.
Source population/operator IAM remain explicit synthetic seams; the DB and
file-set publishers/readers are real. This does not establish current-user Chat
authorization or native question execution. The final source-pinned finite gate
passed **64/64, no skips, disposable cleanup PASS**. Its eight new cases include
the missing-publication negative; the other56 are the preserved Artifact/registry/
native persistence cohort, not64 private Chat end-to-end cases.

The first actual gate kept all56 existing cases passing but the seven new reads
were refused before numerical delivery: the relational fixture seeded a Graph
snapshot without its required publication row. The unchanged Catalog guard
correctly rejected it. The fixture now adds an explicit synthetic publication;
an eighth case preserves rejection when that record is absent. No production
code or authorization/Graph requirement was relaxed. The failed gate and its
successful disposable cleanup remain at
`/opt/eom/embedding-benchmark-os-evidence/private-document-read-sEJKQznT`.

Accepted gate:
`/opt/eom/embedding-benchmark-os-evidence/private-document-read-0bzH3knl`.
Root helper raw SHA256
`8f8a97a9f933a2d8d4d23d6f787f121439c6b1814791d7f766466dbb4e16aca8`;
test stdout raw SHA256
`b328e12214c978dd338c1707f4a4af7815546ecd5c6a07927e090da97be635c3`.
No interactive authentication, production DB test, model call, migration or
operating activation occurred. The supported existing disposable test purpose
was extended, not replaced with an unguarded invocation. Separate documentation/
dependency/package-resource27 PASS overlaps earlier broad tests and is not added
to the318-case focused source inventory.

## Release archive verification

Committed/pushed code candidate:
`680849e9fd59c5479bc0dd927be22291b88219aa`.
Standard three-wheel build and RECORD verification PASS, build-only; no installed
package or service changed. Dist:
`/tmp/eom-api-build/680849e9fd59c5479bc0dd927be22291b88219aa.9zB8mc/dist`.

- platform raw `c123ec9da8f2f9923ded7c6ee14b0f4e3cfc008257b0531f632b7813fe11bf9b`;
- API-contract raw `ac0c969da325dbe19c22c2370c527d7be8f620c8c1e7cab1df6cc93e74bc30bf`;
- API raw `884c87d721fd97d6019197100fe83deb5f128a4ec181cf70677ab3793a08e567`.

Explicit Conda `-I -S -B` archive proof imported240 EOM modules from the exact
platform/contracts wheels only, including the two new public adapter methods,
private read module and shared read-window identity. It checked the frozen
public-only scope value. No checkout, installed EOM fallback, tests or optional
ML module was imported. DB/model/current-user admission/activation calls0. This
is import/package closure, not another numeric or Chat runtime acceptance.
Proof `/tmp/eom-private-document-package.WrotY1u0/prove_archives.py`, raw
`e5bbca3c7c3f53206c5ce618eb946c08def69022d8bb485b7d4a9fabcd0bef01`.

Remaining next boundary: compose this public read owner with the actual Chat
message/session/claim owner and original-command/root-bound private Runner
submission/allocation/execution. Then verify protected installation and actual
tool delivery. The existing compiler/result CHECK is still intentionally closed
to unimplemented execution. **NOT_INSTALLED / NOT_ACTIVE; C4 and full goal OPEN.**
