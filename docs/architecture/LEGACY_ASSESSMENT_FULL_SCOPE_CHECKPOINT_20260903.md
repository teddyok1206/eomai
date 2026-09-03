# Legacy Assessment Full-Scope Checkpoint

Checkpoint: 2026-09-03 UTC
Status: READY_BEFORE_QUEUE_SUBMISSION

## Frozen observation

The protected source root was scanned read-only with the existing fd-relative inventory adapter.
The scan observed 551 regular entries (965,307,504 bytes): 550 original-source candidates
(965,298,517 bytes) and one excluded CSV entry (8,987 bytes) rejected as `UNSUPPORTED_MEDIA`
because its content was not valid UTF-8 under the current scanner contract. No source bytes or
metadata were changed.

- inventory ID: `legacyinventory_860a215a723862c9af1316f993e35212`
- source-set SHA: `sha256:860a215a723862c9af1316f993e352122ae29668df97661476e0e58b975379cc`
- inventory SHA: `sha256:c6c94987c18865e6cb78cd1374721badd82ba5c028f277e51b15764adfec08b4`
- manifest Artifact: `artifact_74447e67f5564db0b96cd4bc6430a3d3`
- manifest Artifact Revision: `rev_20828620f9124c6cac591346712f325f`

The manifest is the only full-corpus source observation currently committed. It is not a rights
review, bundle revision, expected-item manifest, extraction request, or acceptance.

## Candidate projection

The immutable inventory currently projects 147 deterministic directory-level bundle proposals:
136 without structural conflicts and 11 with blocking missing/ambiguous-source conflicts. This
projection is a review queue only. A directory or filename does not establish an examination
occurrence or rights decision.

## Queue boundary

No full-corpus Content Intake, reviewed bundle registration, layout observation registration,
extraction batch creation, work-unit claim, worker submission, Item import, Markdown publication,
or Graph publication has been performed. The next permitted write is an explicitly reviewed
bundle/rights/expected-item manifest followed by a pointer-only batch manifest. The supplied
content-team prompt is preserved byte-for-byte in the Standard Item V5 bootstrap input and pinned
by SHA-256. It is not released or deployed yet; the released V5 instruction and reference bundle
revision must be recorded before any batch manifest is created.

The additive batch contract and design note are present in the working tree as a pre-submission
implementation checkpoint. They are not deployed and must not be used to submit work until the
prompt, rights, bundle revisions, and expected item numbers are reviewed and pinned.

## Resume checklist

1. Bootstrap, evaluate, and release Standard Item V5 so the exact content-team prompt becomes a
   versioned reference Artifact member; do not paste it into a worker ad hoc.
2. Resolve the 147 proposals into reviewed bundle/occurrence revisions; keep the 11 conflicts
   explicit and unresolved until reviewed.
3. Produce deterministic layout observations and expected item-number sets.
4. Create the pointer-only extraction batch/work-unit manifest with `CONTINUE_AND_COLLECT`, one
   attempt per work unit, and exact inventory/bundle/rights/prompt hashes.
5. Stop for final pre-submission audit before any worker claim.
