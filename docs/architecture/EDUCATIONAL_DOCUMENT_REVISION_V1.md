# Educational Document Revision V1

Status: implementation design
Date: 2026-08-25 (UTC)
Scope: purchased/licensed textbook and reference-document canonicalization

## Decision

EOM represents a reusable educational document as a stable logical document with immutable
revisions. A revision is a small pointer manifest over three independently immutable Artifact
Revisions:

```text
EducationalDocument
  -> current EducationalDocumentRevision
       -> original PDF Artifact member
       -> canonical analysis-bundle Artifact member
       -> source-bound rights-attestation Artifact member
       -> revision-manifest Artifact member
```

The original PDF is committed once. PostgreSQL stores identities, lifecycle state, relationships,
hashes, and bounded descriptive values; it never stores PDF or extracted-page bytes. Analysis
Markdown is a derived canonical Artifact, not a replacement for the purchased original.

This is an additive boundary. Existing Content Intake and Knowledge Analysis V2 contracts remain
byte-for-byte unchanged. A later Knowledge Analysis V3 may accept a pinned
`DOCUMENT_REVISION`; V2 must not be widened to accept large or multi-member documents.

## 1. Responsibility and boundary

The Catalog application service owns document identity, revision selection, rights eligibility,
and registration transactions. The Catalog Artifact adapter delegates all staging and immutable
NAS commit operations to the Orchestrator artifact implementation. The operator CLI supplies local
materialization paths only at the explicit registration boundary. Paths are not persisted as
identity and are not returned by inspection APIs.

Workers remain outside this boundary. They neither register documents nor write to NAS. Future
Knowledge Analysis workers receive a bounded, locally staged subset resolved from an approved
Document Revision through the Orchestrator.

## 2. Canonical source

The canonical source is the approved original-PDF Artifact Revision member pinned by:

- logical Artifact ID;
- immutable Artifact Revision ID;
- member path;
- media type and schema reference;
- SHA-256 and byte count.

The purchased staging file is untrusted input and remains a protected recovery copy until a
separate operator-confirmed cleanup. The extracted Markdown bundle is derived evidence. It can be
regenerated into a later Document Revision without rewriting the PDF Artifact or historical
revisions.

## 3. Logical entity and revision model

`EducationalDocument` is keyed by a stable normalized `document_key`, such as
`textbook-miraen-integrated-science-i`. Its mutable fields are limited to lifecycle state and the
current-revision pointer.

`EducationalDocumentRevision` is immutable. It records document identity, edition metadata,
revision number, source/analysis/rights/revision-manifest pointers and hashes, page count, and the
actor/time that approved registration. Revision identity is derived from the full source-bound
registration content so an interrupted replay resolves the same identity.

The initial textbook corpus uses one logical document per publisher and volume. A corrected
analysis or renewed rights statement creates a new revision and moves only the logical document's
current pointer. Historical workflows and graph snapshots pin the old revision.

## 4. Pointers and resolution checks

Every dereference must verify:

1. logical Artifact and pinned Artifact Revision both exist and are approved;
2. the revision belongs to the logical Artifact;
3. member path is normalized, relative, bounded, and free of traversal;
4. member manifest has the expected schema, media type, SHA-256, and byte count;
5. Artifact root remains below the configured NAS root;
6. every path component is non-symlink and the target is a regular file;
7. bytes rehash to the pinned SHA-256;
8. the rights attestation is `CLEARED_LICENSED`, is source-SHA-bound, and permits the requested
   internal processing purpose;
9. the analysis bundle's canonical source pointer exactly matches the revision's original-PDF
   pointer;
10. the document's current pointer is used only for new retrieval; reproducible runs pin a
    specific revision.

Missing, stale, mismatched, retired, or withdrawn targets fail with stable document error codes.
No resolver silently substitutes the latest revision.

## 5. Dominant access patterns

| Access pattern | Structure |
|---|---|
| document lookup | unique B-tree on `document_key` |
| current revision | direct foreign-key pointer |
| revision lookup | primary key |
| ordered revision history | unique `(document_id, revision_number)` B-tree |
| idempotent registration | unique `registration_key` |
| source deduplication/audit | B-tree on `source_sha256` |
| publisher/volume discovery | composite B-tree on normalized revision metadata |
| graph/retrieval provenance | immutable `document_revision_id` reference |

At the expected scale (initially 10 textbooks, later thousands of documents and tens of thousands
of revisions), lookups are `O(log n)` through B-tree indexes. Artifact member verification is
`O(member bytes)` because security requires a fresh hash at the materialization boundary. Bundle
validation is `O(page count + mapping count)` using maps/sets for member and anchor membership.
No repeated list scan is used for keyed member resolution.

## 6. Artifact layout

Each Document Revision references four artifacts:

```text
original artifact
  source/original.pdf

analysis artifact
  analysis/manifest.json        # bundle_state=CANONICAL
  analysis/index.md
  analysis/pages/page-NNNNNN.md

rights artifact
  rights/attestation.json

revision-manifest artifact
  document/document-revision.json
```

All manifests are canonical JSON and self-hashed where defined. Artifact metadata records the
member schema and media type. The analysis manifest retains bundle-local paths (`index.md`,
`pages/...`) and the Document Revision contract fixes `analysis/` as the artifact root, avoiding
path ambiguity without rewriting every page pointer.

## 7. Rights contract

The initial company-provided textbooks are recorded as `CLEARED_LICENSED` using the user's explicit
statement that the files were purchased and their use was negotiated. The evidence is bound to each
PDF SHA-256 and records:

- basis `PURCHASED_AND_NEGOTIATED`;
- permitted internal uses (archive, extraction, knowledge analysis, graph indexing, item-authoring
  grounding, internal review);
- authorized roles;
- conservative `answer_bearing=true` treatment;
- reviewer identity and UTC timestamp;
- withdrawal behavior `RETIRE_FROM_NEW_RETRIEVAL`.

No contract number or license term is invented. A future legal document can be attached through a
new attestation revision. Withdrawal stops new retrieval but cannot reinterpret pinned historical
provenance.

## 8. Transaction, concurrency, and idempotency

Registration validates all local bytes before mutation. Artifact publication then proceeds in the
dependency order original -> rights -> analysis -> revision manifest. Each publication uses a
content-bound idempotency key and the platform's request-hash conflict detection. An interruption
may leave an approved, unreferenced Artifact Revision; replay reuses it and completes the Catalog
transaction. It never creates a second canonical copy for the same key/content.

The Catalog first writes a bounded `DocumentRegistration` saga reservation containing only the
request hash, reserved revision identity/number, state, and timestamps. It contains no path or
document bytes. Database unique constraints on registration key, request hash, and reserved
revision identity close concurrent duplicate creation. Artifact publication replays against that
reservation. The final Catalog transaction locks both registration and logical document, inserts
one immutable revision, atomically updates the current pointer, and marks the saga committed. A
different payload under the same registration key fails closed.

Artifact commit and Catalog registration cannot be one distributed transaction. Content-addressed
idempotent replay is the recovery mechanism; deletion is not.

## 9. Dependency direction and ownership

```text
eomctl operator adapter
  -> EducationalDocumentService (Catalog application use case)
     -> catalog contracts / identifiers / SQLAlchemy repository
     -> CatalogArtifactService adapter
        -> Orchestrator artifact staging and NAS commit
```

Contracts do not import SQLAlchemy, filesystem, or service packages. The CLI contains presentation
validation only. The service owns validation, transaction boundaries, idempotency, and pointer
assembly. Filesystem/NAS behavior remains in infrastructure adapters.

## 10. Failure and retry behavior

- unsafe file, symlink, hardlink, permission drift, size/hash/page mismatch: fail before commit;
- invalid schema/Pydantic/self-hash: fail before commit;
- rights mismatch or missing permission: fail before commit;
- Artifact idempotency conflict: fail without substitution;
- partial Artifact publication: preserve evidence and replay the same registration key;
- a failed saga blocks a different next revision until the exact source-bound request is replayed
  successfully; replay moves only that same reservation back to `PREPARED`;
- concurrent duplicate: unique constraint selects one winner; retry inspects exact hashes;
- DB failure after Artifact commit: preserve unreferenced Artifact; replay completes registration;
- current pointer mismatch or retired document: explicit error;
- source withdrawal: prevent new retrieval, preserve pinned history.

Registration itself does not start Knowledge Analysis, graph publication, a workflow, or an HWPX
build. Those are separately authorized state transitions.

## 11. Simpler alternatives considered

**Raise Content Intake/worker file limits.** Rejected because it would reinterpret V2, stage up to
289 MiB into a one-shot worker, and still would not model editions or multi-member analysis.

**Store PDF/Markdown in PostgreSQL.** Rejected because it duplicates large bytes, harms backup and
query behavior, and violates the Artifact boundary.

**Use filesystem paths as document IDs.** Rejected because paths are mutable locations and cannot
provide reproducible provenance.

**One self-referencing mega-artifact.** Rejected because the canonical analysis manifest needs an
already known approved PDF pointer. Separate immutable artifacts make dependencies explicit and
permit independent revisions without duplicating the source.

**Use only the existing legacy inventory rights document.** Rejected because these purchased files
were supplied directly for this corpus and are not entries in the earlier inventory snapshot. A
source-SHA-bound attestation is narrower and cannot be accidentally reused for another file.

## 12. Validation and rollout gates

Required tests cover JSON Schema/Pydantic parity, self-hashes, source-bound rights, unsafe paths,
symlink/hardlink rejection, bundle member/hash/anchor closure, immutable revision rows, current
pointer updates, idempotent replay, request conflict, Artifact pointer resolution, absence of binary
DB values, index/constraint presence, migration upgrade/downgrade, runtime privileges, package
resources, and historical V2 schema-byte preservation.

Rollout order:

1. merge reviewed schemas/models/service/migration and deploy dual-read Catalog code;
2. migrate once and reconcile least-privilege grants;
3. register the ten protected textbook sources and validate Artifact/revision pointers;
4. preserve staging originals until separate operator confirmation;
5. introduce additive Knowledge Analysis V3 and a new immutable workflow protocol/version;
6. run bounded document analyses, human review, and graph snapshot publication;
7. expose retrieval through revision-pinned Evidence Bundles.

No external LLM API, direct worker-to-worker message, worker NAS write, or generated binary in Git is
introduced by this design.
