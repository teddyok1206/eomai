# ADR 0076: Content-team prompt-to-HWPX preflight

## Status

Accepted.

## Responsibility and boundary

The byte-frozen content-team authoring prompt and HwpQuestionEditor handoff guide define the
editorial and layout rules. Authoring and review workers read both sources through orchestrator-
materialized, revision-pinned references. Standard control bootstrap 13 and knowledge-item
bootstrap 10 add the same pair to the image role without changing their bytes. Content Pack 1.15.9
projects their visual responsibility split into the image worker instruction. The image worker
produces only the ordered typed IMAGE members requested by the approved draft. Catalog validates
and commits one final PNG Artifact Revision per image. The HWPX manager resolves those immutable
pointers and the isolated builder projects them into the reviewed handoff archive. Workers never
communicate directly or write NAS.

The canonical source remains the approved Item Revision. Its Item Content and deterministic
Markdown are two members of one Artifact Revision; generated PNGs and the handoff archive are
separate immutable Artifact Revisions. HWPX is a derived deliverable and stores only those pointers,
revision IDs, schemas, media types, dimensions, and hashes in its request and manifest.

## Decision

No new wire schema, database row, or duplicate validation receipt is introduced. Existing JSON
Schema 2020-12 and Pydantic contracts already express every required value:

- the exact authoring-prompt and reviewed handoff-archive hashes;
- at most two ordered IMAGE/TABLE visual members;
- the canonical zero-, one-, and two-visual layouts and labels;
- each PNG's logical Artifact ID, immutable revision ID, member, schema, media type, dimensions,
  ordinal, label, and SHA-256; and
- the builder result, package manifest, structural report, and output SHA-256.

One pure contract-layer projection is the executable authority for expected IMAGE bindings. It
walks the approved draft's ordered visual tuple once and compares the resulting ordinal/label/file
signature with the HWPX request's image tuple. Both the manager and isolated builder use it. This
prevents their copies of the two team-lead rules from drifting:

| Draft shape | PNG members | HWPX panel labels |
| --- | --- | --- |
| no IMAGE | none | none |
| one IMAGE | one PNG at its actual zero-based visual ordinal | none |
| two IMAGE members | two distinct PNGs in ordinal order | editable `(가)`, `(나)` cells |

Scientific labels such as `A` and `B` remain part of the worker-authored deterministic overlay.
Panel labels never enter PNG pixels. IMAGE/TABLE and TABLE/IMAGE retain their actual array ordinal
and remain unlabeled, as required by the original prompt.

## Access pattern and data structures

The dominant operation is ordered validation over an immutable tuple bounded to two entries.
Tuple comparison is O(n) time and O(n) transient space for `n <= 2`; a set would lose presentation
order. Artifact and revision lookups remain batched maps keyed by indexed IDs, so exam rendering
uses two indexed queries rather than an N+1 scan. No image or HWPX bytes are stored in PostgreSQL.

## Materialization, transaction, and concurrency

Every external member is untrusted. The manager opens a source with `O_NOFOLLOW`, checks it is a
regular file, streams it into a fresh `O_EXCL` workspace member, computes SHA-256 during that copy,
and compares the source fd identity before and after reading. A pinned caller also supplies the
expected hash. The builder cannot start until every staged member matches. Builder JSON and HWPX
results are read or hashed through the same stable-fd boundary.

The workspace copy is temporary materialization, never canonical identity. Artifact publication
still occurs only after the isolated builder exits, result/schema/manifest/output checks pass, and
the existing orchestrator transaction records the immutable Artifact Revision and SUCCEEDED event.
No new lock, queue, mutable cache, or cross-service transaction is added.

## Failure, retry, and idempotency

Count, ordinal, label, file-name, schema, media, dimension, pointer, or hash drift fails before the
builder side effect with the existing stable HWPX error family. A changed/truncated source or an
existing staging target also fails closed. Failed builds retain their immutable attempt record;
retry uses the existing application idempotency contract and never substitutes a latest revision.

Tests cover zero, one, mixed, and two-image shapes; wrong count/order/label/path/hash; source
replacement or growth during staging; nonexclusive targets; exact PNG identity; editable HWPX panel
labels; and prior prompt/archive byte hashes. Three local canaries cover no image, one image, and two
images before any deployment.

## Simpler alternative and trade-off

Keeping separate ordinal/label loops in the manager and builder is shorter locally but permits two
copies of the team-lead layout rule to diverge. Adding a new persisted receipt would duplicate
identities already present in the Item and HWPX request. The shared pure projection plus stable file
materialization is the smallest change that closes the observed boundary without expanding the
protocol surface.
