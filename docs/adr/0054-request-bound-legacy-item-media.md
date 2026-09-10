# ADR 0054: Bind legacy item media to extraction inputs

## Status

Accepted.

## Responsibility and boundary

The legacy extraction result contract owns the small immutable Item content proposed by a worker.
The Orchestrator owns the validation and Artifact-commit boundary. Workers may read staged page
images but cannot create canonical media Artifacts, write NAS, or repair an Artifact identity.

## Canonical identity and pointers

The reviewed extraction request is the canonical source of allowed media identities. An Item image
block must pin the exact logical Artifact ID, immutable revision ID, member, media type, and SHA-256
of one `page_inputs[].image` pointer. The extraction result remains an immutable proposal revision.
For one already accepted historical transcription error, promotion uses an exact reviewed policy
that pins the complete source chain, bad pointer, and canonical target. It materializes a distinct
corrected Item-content Artifact without changing the extraction result, and pins the policy as an
`OTHER` component in the same Item Revision manifest. It never infers an ID from a revision or
resolves a latest revision.

## Access pattern and structure

Validation builds one set of request media identities and performs membership checks for each Item
image block. With at most 64 pages, eight Items, and 100 blocks per Item, this is O(p + b) time and
O(p) space. Request-specific worker JSON Schema uses one exact `anyOf` branch per page pointer, also
O(p) in construction and schema size. No database index or persistent schema changes are needed.

## Transaction, concurrency, and dependency direction

The strict contract-layer media validator runs before the Orchestrator stages or commits newly
admitted result bytes. Historical corpus verification deliberately retains its coverage validator,
because accepted immutable results predate the strict rule; the one known invalid historical
pointer reaches only the exact promotion policy below. Both validators have no infrastructure
dependency. The workflow package projects the typed request into a narrower worker-output schema;
the Orchestrator still performs authoritative typed validation before its sole NAS commit.
Historical correction materialization belongs to the existing Catalog promotion adapter. Its
policy and corrected content use distinct, policy-bound idempotency identities so a previously
committed invalid content Artifact cannot be replayed.

## Failure, retry, and idempotency

An invented, stale, or mismatched media identity fails as `WORKER_RESULT_INVALID` before commit.
Retry requires a fresh workflow/result identity under an explicit recovery authorization; an
already committed result is never edited. The one exact historical result instead produces a new
canonical Item-content Artifact plus immutable correction-evidence component. Exact replay returns
those same revisions only when every policy and content hash is unchanged.

## Simpler alternative rejected

Resolving an image by revision alone or retaining a bad pointer behind a runtime alias would make
canonical Item content context-dependent and erase evidence of the worker error. The selected
boundary preserves the invalid extraction result and its hash as evidence, materializes globally
valid Item content only under the exact policy, and pins that policy in the Item manifest. Deferring
the check to Item registration is insufficient because invalid results can already have been
committed and accepted, blocking FIFO promotion later.
Directly patching the database or stripping the image would likewise break immutable accepted
evidence or alter reviewed content without durable authorization, so neither is an admissible
recovery.
