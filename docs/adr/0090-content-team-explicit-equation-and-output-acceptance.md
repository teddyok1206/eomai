# Content-team explicit equation and HWPX acceptance boundary

Status: implementation decision, 2026-09-14 UTC

## Decision

Treat the ordered `equation_sources` already derived from explicit `$...$` and `$$...$$`
occurrences in the approved Item Content as the only equation authority for content-team HWPX.
The HWPX contracts package owns a pure, fail-closed projection from each supported source equation
to its canonical Hancom equation script. Builder rendering may use the pinned external handoff as an
infrastructure adapter, but it must disable that adapter's legacy inference of equations from plain
text, render explicit equations inside labeled DATA/CONDITION blocks, and prove that the finished
package contains exactly the projected equation multiset. Manager acceptance independently repeats
the contract projection and compares it with native HWPX equation scripts.

Native table text remains exact after Unicode normalization except for XML whitespace. HWPX may
split one visible text value across runs and formatting boundaries, so Manager compares text tokens
after removing whitespace while retaining exact non-whitespace characters, equation token order,
table dimensions, labels, and paragraph alignment. This is the same semantic whitespace boundary
already used for the whole Item projection; non-whitespace drift still fails.

Image placement is keyed by each image's authored `visual_ordinal`, not by its position in the
filtered image list. This preserves all canonical layouts: an image beside a table occupies its
original column, a table-only Item requires no image, and one image without a neighboring visual
remains unlabeled in the first column.

A terminal per-build validation failure must not stop the long-running HWPX application queue. The
failed build remains terminal with its stable error code, while the runner sleeps for its bounded
poll interval and continues to the next admitted build. Startup privilege and staging gates remain
fail-closed.

## Required design procedure

1. **Responsibility and boundary.** Contracts define the deterministic equation script projection;
   Builder adapts the pinned external renderer and materializes HWPX; Manager independently accepts
   package semantics; the runner owns queue liveness. No worker or Builder writes canonical NAS
   artifacts directly.
2. **Canonical source.** The approved immutable Item Content and its ordered `equation_sources` are
   canonical. The HWPX output is a validated materialization, not a replacement source. Plain text
   patterns are never an equation source.
3. **Entity and revision model.** Existing Item, Item Revision, Assembly Revision, HWPX build, and
   Artifact Revision identities are unchanged and remain separately hash-pinned. This decision adds
   no mutable alias or implicit latest resolution.
4. **Pointers and resolution.** Existing pinned Item-content, Markdown, image, handoff, Assembly,
   and output pointers continue to require exact identity, revision, schema, media type, lifecycle,
   and SHA-256 checks before bytes are used.
5. **Access patterns.** Equation verification is ordered iteration plus multiset comparison; table
   verification is ordered row/cell iteration; labeled-block lookup is keyed by the renderer's
   returned table ID; queue work is indexed FIFO claim.
6. **Structures and indexes.** Tuples preserve immutable authored order, `Counter` represents an
   equation multiset, and a table-ID map provides constant-time component lookup. Existing database
   unique constraints and requested-FIFO index remain sufficient; no migration or index is added.
7. **Complexity and scale.** Projection and verification are O(E + X + T) time and O(E + T) space
   for E approved equations, X section XML nodes, and T generated tables. Current scale is at most
   128 equations per Item and 25 Items per exam. No repeated list-membership scan or binary DB value
   is introduced.
8. **Transaction and concurrency.** Builder rewriting occurs only in its private workspace before
   result publication. Manager terminalization remains one database transaction per admitted build.
   The external-parser override is process-local, bounded by `try/finally`, and restored before the
   isolated Builder process exits.
9. **Dependency direction.** Builder and Manager depend on the contracts package. Contracts do not
   import the external handoff, filesystem, database, Builder, or Manager. External renderer behavior
   stays behind the Builder adapter.
10. **Failure, retry, and idempotency.** Unsupported projection, missing/extra equation, unsafe XML,
    stale pointer, or non-whitespace table drift fails before output commit with a stable boundary
    error. A new build uses the existing operator/idempotency contract; no failed build row is
    mutated into success. Queue continuation does not retry the failed build.
11. **Simpler alternative.** Relaxing equation count or trusting Builder-reported counts would hide
    real omissions. Comparing raw LaTeX-like source to native Hancom script rejects correct output.
    Modifying the immutable external handoff would break its pinned evidence. The pure projection and
    scoped adapter are the smallest changes that preserve independent verification.

## Verification

- Contract tests cover every supported family and reject unsupported or ambiguous sources.
- Builder tests prove plain equation-like text stays text, labeled-block equations render natively,
  and output contains the exact projected multiset.
- Manager tests accept formatting-run whitespace splits and canonical Hancom scripts, while rejecting
  non-whitespace table mutations and equation additions, removals, or script changes.
- Whole-exam tests cover divergent header resources and the live-shaped mixture of inquiry, tables,
  labeled blocks, images, and equations.
- Runner tests prove one terminal build failure does not terminate queue service.
