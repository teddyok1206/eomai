# ADR 0160: Natural stimulus presentation and explicit labeled-data intent

## Status

Accepted as a repository release candidate. Runtime activation and a bounded live canary remain
separate operational gates.

## Context

The canonical content-team Item model separates an upper `stem`, optional `DATA`/`CONDITION`
blocks, ordered TABLE/IMAGE visuals, and a `bottom_stem`.  Released material-requirement V1 then
tightened every IMAGE request to exactly one DATA block.  That rule was introduced to prevent an
image-required request from silently producing no meaningful image material, but it also made the
presence of an image imply a visible `<자료>` structure.

The two byte-pinned content-team authorities do not define that implication:

- the complete authoring prompt uses a natural upper stem followed by the exact `그림` marker for
  its one-image canonical case;
- the HwpQuestionEditor handoff permits an explicit `<자료>` block only **when a boxed source is
  needed**;
- neither authority requires every image to be wrapped by a labeled source block;
- visual order must follow the introductory sentence, without manufacturing another material.

A read-only audit of the current published Integrated Science Graph snapshot
`graphrev_c0e78b4e4ce6588de3d3b6c6f25fb3d9` verified all 520 pinned legacy Item Revisions and their
content hashes.  Only 2 Items contain a literal `<자료>`-family label, while 465 Items contain at
least one image or table.  Of those 465 visual Items, 417 contain a natural stem/context paragraph
before the first visual and 456 contain a prompt after the final visual.  First-paragraph forms are
286 figure-led, 120 `다음`-led, 32 table-led, and 82 other natural forms.  This is descriptive
evidence, not a phrase template: generated Items must not hardcode one Korean opening sentence.

The latest ten exact-source variation canaries expose the mismatch directly: eight authored a DATA
block even though the source corpus almost never uses an explicit `<자료>` label.  The content and
explanations are otherwise acceptable; the defect is presentation classification and placement.

## Responsibility and boundary

The reviewed material requirement owns the intended student-visible material shape.  Authoring
owns the actual prose and typed Item draft.  Review independently checks presentation fidelity.
The orchestrator validates the result and evidence citations before Artifact commit.  Preview and
HWPX are projections of the same approved Item and must not invent different label semantics.

Workers do not communicate directly, write NAS, choose storage paths, or repair released Items.
The orchestrator remains the only validated Artifact commit owner.

## Canonical source and revision model

Existing Item Content V3 already represents both required outcomes:

```text
natural flow:
  stem -> ordered visual(s) -> bottom_stem
  labeled_blocks has no DATA

explicit boxed data:
  stem -> DATA block -> ordered visual(s) -> bottom_stem
```

Item Content V3 and every released Pack remain immutable.  The missing identity belongs in a
successor reviewed material requirement, not in an inferred renderer heuristic.

Define a successor `content-team-material-requirement/2.0` before changing worker behavior.  It adds
one closed field for IMAGE presentation:

```text
image_supporting_data = NONE | LABELED_DATA
```

- `NONE` means all student-visible introductory facts belong in the upper stem or the visual
  itself.  DATA block count is exactly zero.
- `LABELED_DATA` means a genuinely separate, self-contained boxed source is pedagogically needed.
  DATA block count is exactly one.
- The field is null for non-IMAGE forms.  DATA-form Items continue to require one DATA block.
- CONDITION remains an independent optional assumption/constraint and never substitutes for the
  choice above.

The field name describes semantic intent, not typography.  It does not prescribe `다음은`,
`그림은`, or any other fixed Korean phrase.

## Presentation selection

For exact-source variation, the pinned source Item structure determines the successor requirement:

1. an explicit boxed/labeled source structure maps to `LABELED_DATA`;
2. an ordinary stem/context paragraph followed by a visual maps to `NONE`;
3. ambiguous extraction fails closed for review instead of defaulting to `<자료>`.

For general Graph-grounded generation, the planning boundary selects and pins one presentation
value from a cited PAST_EXAM representation pattern.  Authoring does not silently change it.  This
selection preserves the source's presentation **class**, not its wording.

The system may derive a bounded immutable presentation signature from the already pinned source
Item:

```text
(ordered block kinds, paragraph purposes, explicit-label presence, visual count/order)
```

This small frozen value has no independent lifecycle and does not require a new database table.
Derivation is one ordered pass over at most 100 source blocks: O(b) time and O(b) bounded output.
Label membership uses a set; block-kind and ordinal lookup use tuples/maps rather than repeated list
scans.

## Validation and evidence

The successor validation path must be closed across every layer:

1. JSON Schema 2020-12 and Pydantic validate material requirement V2 before it is accepted by API,
   Workflow, production-plan, or Catalog boundaries.
2. Structured-output projection binds exact IMAGE count and exact DATA count from
   `image_supporting_data`.
3. For `NONE`, the positive PAST_EXAM structure citation binds `/stem` and every IMAGE
   `/visuals/{ordinal}/kind`; it must not require a nonexistent DATA path.
4. For `LABELED_DATA`, the citation additionally binds the exact DATA content leaf.
5. Review adds a presentation-fidelity target that verifies the introductory prose, visual order,
   bottom prompt, and whether a separate label is justified.  It does not judge phrase identity.
6. Workflow image dispatch still requires the exact IMAGE slots.  Removing mandatory DATA must
   never restore the historical zero-image branch.
7. Registration and Graph publication consume the same trusted receipt chain as today.

## Preview and HWPX parity

Preview currently labels every DATA block as `<자료>`, while HWPX removes the DATA heading for an
IMAGE layout and nests its content with the image.  A successor Item must have one meaning in both
projections:

- `NONE`: render upper stem, then the image(s), then bottom stem; no DATA table, no `<자료>` text,
  and no hidden duplicate prose;
- `LABELED_DATA`: render the explicit DATA block consistently according to the reviewed handoff,
  followed by the ordered image presentation;
- one image has no empty second cell and no `(가)/(나)` label;
- two images retain two ordered PNGs and editable `(가)/(나)` text;
- TABLE-only remains a native editable table and never acquires a DATA label or PNG placeholder.

The HWPX application pins the typed successor intent from the exact Item component metadata and the
Manager's independent output acceptance checks it against the canonical Item and package bytes.
The isolated Builder renders the canonical Item; it does not reinterpret the intent or decide by a
Korean keyword, content length, presence of a number, or a best-effort guess.

## Transaction, concurrency, retry, and compatibility

No new DB table, migration, queue, or worker-to-worker path is required.  A successor Workflow/Pack
pins the V2 requirement and its hashes before execution.  Existing V1 requests keep their exact
one-DATA IMAGE semantics and remain replayable.  V1 and V2 dispatch use an explicit discriminated
union or version lookup; no implicit latest resolution is permitted.

Validation occurs before Artifact commit.  A same-key replay reuses the same pinned requirement and
cannot change presentation mode.  A failed successor attempt remains failed; retry uses the existing
idempotent workflow boundary and does not rewrite history.

## Required tests

- JSON Schema/Pydantic parity for both V1 and V2, including missing/extra/cross-field negatives.
- V1 byte and behavior immutability: IMAGE still requires one DATA block.
- V2 `NONE`: IMAGE present, DATA absent, natural stem preserved, exact citation paths accepted.
- V2 `LABELED_DATA`: IMAGE and exactly one DATA present, missing/duplicate DATA rejected.
- zero IMAGE rejected for both successor modes.
- exact-source structure mapping for natural image, explicit DATA, table-only, mixed order, and
  ambiguous source.
- Preview/HWPX parity for label, text order, visual ordinal, one/two-image geometry, and embedded
  package-internal PNG relationships.
- no external path, placeholder, duplicated prose, silent latest revision, or large binary DB row.
- historical Item/Pack/Workflow fixtures remain byte-stable and readable.

## Rollout order

1. Freeze material requirement V2 schema and mirrors.
2. Add frozen Pydantic models and explicit V1/V2 unions.
3. Add source-presentation derivation and focused fixtures from the dominant corpus signatures.
4. Update orchestrator schema projection, evidence validation, review gates, and Catalog validation.
5. Publish a successor Content Pack while retaining the already compatible immutable control
   preset revision; Plan V17 pins that exact preset and Pack.  Do not edit the two team-lead source
   files.
6. Align Preview and HWPX projections.
7. Run source tests, disposable persistence tests where affected, and one bounded Item canary through
   approval/Preview/HWPX before activation.

## Alternatives

**Prompt-only wording.** Rejected because the existing schema projection, material validator,
evidence validator, workflow image gate, and HWPX acceptance all independently require DATA.

**Hide `<자료>` only in Preview.** Rejected because it leaves canonical prose in the wrong field and
continues the current Preview/HWPX semantic divergence.

**Always move DATA text into stem without a typed successor.** Rejected because it silently changes
released V1 semantics and cannot distinguish the rare genuinely boxed source.

**General ordered-block rewrite of Item Content.** Deferred.  Current V3 can express the dominant
natural and labeled cases.  A broader schema is justified only if observed source orders that V3
cannot preserve become an actual product requirement.
