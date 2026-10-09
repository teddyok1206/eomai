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

## 2026-10-09 follow-up: ordinary prose is not the default alternative to DATA

Status: repository implementation candidate; no runtime activation, deployment, new model run,
historical Item rewrite, or HWPX rebuild is performed by this follow-up.

The user clarified two complementary editorial requirements: ordinary explanatory material is
introduced naturally in the upper stem, without an automatic `<자료>` heading/box; tabulating that
same information is often better even when it is short or can be expressed in prose. Removing an
unnecessary DATA block must not favor TEXT over TABLE.

### Actual source inspection

The following canonical page PNGs were inspected visually, not just through extracted text. Their
bytes were checked against the pinned extraction batch's page hashes. This is a small qualitative
sample, not a new census of the 520 approved analyses or a measured TABLE frequency.

| Original source / physical page | Item | Observed presentation |
|---|---|---|
| 2018-11-21 고1 통합과학 / 2 | 8 | A figure and a separate table of explanatory examples; the cells contain sentences, not measurements. No `<자료>` title. |
| Same page | 7 | Real experimental steps remain boxed; qualitative observations are tabulated inside the result section. |
| Same source / 4 | 19 | Experiment-specific volumes and temperatures are grouped in a comparison table. Shared conditions remain in the upper stem. |
| 2023-06-01 고1 통합과학 / 1 | 2 | Named formation stages and prose descriptions are paired in ordered, connected boxes. A text-heavy stimulus is not necessarily one continuous paragraph. |
| Same source / 3 | 12 | A compact atomic-property table contains only a few given values and an unknown. Few numbers do not make prose preferable. |

2018 source PDF: `artifact_abd5747c442341b98e5143bd67221cb9` /
`rev_882e220e41e447f48234ca467ac41e1c`, member
`source/legacyentry_95f41a2efe7831c2528a3628d341b25b.pdf`, SHA
`sha256:1020a6ba1fb173b98214d7111b35a8cd0b2984fc7e87f6e07ca67c21b02ca080`.
Page PNGs: `artifact_5bb9530cdf3b4e3e98e35e27b87bddaa` /
`rev_e7b5a7ead7ce4426a0a9d6696500cd73`:

- `pages/problem-2.png`: `sha256:73d12b3d13ba68244f45f3b29f6a38bf9afd5f7c949f9f1752259f6eeb842670`.
- `pages/problem-4.png`: `sha256:b1520bfeb055ac5a2dd741b83f0a69f337d22522bf628826a79b8fe3b9d05fb8`.

2023 source PDF: `artifact_5cc6e9ca50fc4aff9a08dc45c599d1ed` /
`rev_6bdfe441b63c49109e2a024a882d071a`, member
`source/legacyentry_f8a9dd25a592819b8107292ba08c3198.pdf`, SHA
`sha256:17a2875d3dda14d61e91ec2bc9b9a16da8a7057cd32b6ba2b571ef881f773797`.
Page PNGs: `artifact_d8e12a92dd2e46ac97c5c2164eda5737` /
`rev_3263868a1d2b49cdb794da430b4f298b`:

- `pages/problem-1.png`: `sha256:bc4be4fb39facd0a220e87846c1567936fe8521f0bb7b0e9cb1af8148e754d36`.
- `pages/problem-3.png`: `sha256:7d8871a163d9cb00ab598c95bf1943ca0cd5816b8978580641ed705c8c5323b9`.

The existing handoff supports 2–5 columns and at most two independent general visuals. The original
single-column text table, six-column measurement table and five-stage connected diagram above are
observations, not authorization to silently expand the contract, drop data, or reproduce unsupported
geometry. Equivalent new tables
can choose supported orientation/rows when the reviewed intent permits; an incompatible pinned
structure still fails explicitly. This follow-up changes selection guidance, not those limits.

### Bias and decision

The legacy V1 handoff describes an explicit DATA block "when a boxed source is needed" but does not
distinguish ordinary explanation from an independent boxed source. The image guide says prose
explanation belongs outside the figure; the IMAGE/NONE authoring rule says explanatory facts belong
in the stem. Neither means that all material forms should move numerical or qualitative comparisons
into prose. AUTO previously offered little selection guidance beyond "an appropriate layout".
No automatic prose-vs-table parser heuristic was found; the change belongs at the editorial boundary,
not in a renderer that guesses from Korean words or number counts.

The single source of the clarification is
`config/control-plane/references/guidance/content-team-hwp-question-editor-handoff-v2.md`.
Content Pack `generated-knowledge-item@1.20.15` materializes its presentation-intent section into
both authoring and review prompts, with the complete source SHA. The immutable V1 workspace
reference remains the supported grammar authority. V2 clarifies when that grammar's boxed source is
needed; it does not require a new reference-bundle path or alter the original team-lead files.
No instruction to open an unstaged V2 file is sent to a worker.

This is a declared build-time materialization boundary for a small immutable rule value, not a second
runtime source or arbitrary payload copying. One generator and exact-byte tests keep the two role
materializations identical. Installed Catalog prompt rendering consumes only the compiled, pinned
Pack artifact; it does not read this repository or select the latest guidance at runtime.

Responsibility, canonical content and transaction ownership remain as specified above: planning and
AUTO authoring select an allowed structure, review checks student-visible placement, and the
orchestrator validates/commits the result. Canonical Item V3 and deterministic Markdown already
represent natural paragraphs, native qualitative/numeric TABLEs and both mixed orders. No JSON
Schema, Pydantic DTO, DB migration, queue, index, worker protocol, image policy or Preview/HWPX
renderer change is needed. The only new release identity is the compatible Content Pack; authoring
and review profile versions advance to `12.2.1`.

The dominant operation is immutable keyed Pack resolution and ordered prompt/visual iteration.
The build does one bounded section extraction and one pass over the Pack files, O(p) time/space in
their total bytes; no new persistent cache or derived DB counter is added. Pack publication retains
existing hash verification and idempotency. Existing executions and production plans retain their
exact old Pack pins. Rollback selects the predecessor for new executions, never edits old outputs.

Review reuses existing finding codes only for a substantiated placement/duplication defect or exact
typed-form mismatch. A possible alternative table, or a preference for one format, is not alone a
blocking finding. Explicit DATA, genuine CONDITION and actual inquiry-result tables remain valid.
TEXT/TABLE/IMAGE requirements cannot be changed by a worker to implement a style preference.

Overwriting V1 or the released Pack was rejected because it would invalidate reproducible history.
New control/bootstrap/output schemas were rejected as unnecessary: the clarification is compatible
with the existing typed forms and V1's conditional box grammar. Regex label stripping or Preview-only
hiding was rejected because it would leave canonical placement wrong.

Validation covers untouched original/V1 hashes, Pack compile/compatibility and restricted prompt
rendering, deterministic materialization, existing labeled-box/inquiry replay, and pure Markdown
round-trips for prose, small numeric/qualitative tables and both mixed orders without artificial DATA.
These are structural/source gates, not a claim that a live model has already chosen a better table
or that educational/visual quality has been accepted. Publication and runtime activation remain a
separate operational step.

Catalog's explicit release membership checks also admit the successor to the same Brief V5 and
reference-image family. Repeated lists are consolidated into immutable membership sets in their
existing owner, not an inferred semver range. The existing image label-clearance policy remains
unchanged: Orchestrator and Catalog resolve the enforcing release through a shared immutable
version/hash map in `eom_image_contracts`, which preserves the exact `1.20.14` bundle and adds only
the byte-verified `1.20.15` bundle. A different version/hash pair is not silently accepted. No
provider model, GPU prompt, SVG policy revision, or image result schema is changed.

### Source verification at 2026-10-09 14:10 UTC

- Focused presentation/Pack/label-layout and predecessor tests: **67 PASS**.
- Catalog authoring/image/knowledge/registration and historical Pack regressions: **42 PASS**.
- HWPX handoff integrity tests in the explicit `eom-hwpx` environment: **4 PASS**.
- Total: **113 PASS**; formatter, Ruff, strict focused mypy (4 source files), generator replay and
  `git diff --check`: **PASS**.
- An initial mixed API/Builder test invocation could not import `eom_hwpx_builder`. The API cases
  and Builder cases were rerun under their explicit component environments; no dependency was
  installed into the API environment to conceal the separation.
- V2 guidance SHA: `sha256:a669142b75b222833f87195cddc02aee424c96bd45eaff25caca474a9e07a66e`.
- Deterministic candidate Pack bundle SHA:
  `sha256:63785945ceaa226dcb63a278cb08cbc82f8dcf35b0a9e7df9b65dde5810f6f6c`.
- Original authoring, illustration and V1 handoff bytes: **UNCHANGED**, SHA-verified.
- Operational publication/activation/deployment: **NOT_PERFORMED**. Model/GPU/HWPX delivery runs:
  **0**. DB/NAS canonical data, existing Items, approved revisions and historical outputs:
  **UNCHANGED**. No claim of live editorial behavior or educational quality acceptance is made.

### Operational activation at 2026-10-09 14:35 UTC

The user explicitly authorized deployment/activation after the source checkpoint above. This
follow-up supersedes its NOT_PERFORMED operational status, not its historical test scope.

- Source commit: `578ddd9a8f23a1a3aa9be3ee6e256344230d98aa`; source tree:
  `ea2438c17a7b20fb86a40c3b0584a3b9a5be9915`.
- Installed source archive SHA:
  `sha256:949b96c4eb9fb0aff23414b1ecc448ca0d987ede06b63b33dc3f576cd8e78882`.
- Shared platform deployment: `scripts/api/deploy_release.sh --install`, run as the repository
  operator using the authenticated `EOM:5` pane. Sudo's timestamp is terminal-scoped; no credential
  was copied, exposed or supplied in chat to make another terminal inherit it.
- Current worker-lease preflight: **0**. Mock-exam deployment admission: **READY**, 17 terminal
  executions. The supported installer reran admission before package replacement.
- Schema migration remains `20261008_0049`; no new migration/control/preset/Graph publication.
- Wheel RECORD, installed imports, dependency check, runtime isolation, authenticated
  login/me/refresh/logout smoke, live/ready health and post-install `--verify`: **PASS**.
- API, Catalog application runner, Workflow runner/maintenance and HWPX application runner were
  refreshed by the supported installer and are **ACTIVE**. Existing worker units/auth/model and
  the six-slot configuration were not reinstalled. Web source
  `67fafe99fec99e1f9bcd2293fe970c9ed18d8449` remains installed and **ACTIVE**.
- Dedicated chat remains **ACTIVE** with its separate release pin
  `d32f3ba75bc7a0b34305204d3dba43a009e99617`; no chat activation/restart was claimed. Its unchanged
  code and existing pin are distinct from the newly installed shared environment's wheel source.

The installed `eomctl` used the existing local operator composition and supported import → exact
hash inspection → release → activate operations. Actor
`operator_b205356d5b08052e981f4972c0befff6` was verified ACTIVE/ADMIN with release/activate
permissions. The Studio's existing pack-key/environment selection requires no extra default file.

| Identity | Committed value |
| --- | --- |
| Pack | `generated-knowledge-item@1.20.15`, **RELEASED** |
| Release | `packrel_8dde7e96f50542e4932f55c8e76b8083` |
| Activation | `activation_88c2e332a784425fa17d3c7702756839`, environment `development` |
| Bundle Artifact / Revision | `artifact_26e457e0bdc44d98bf6afb33ddf795c1` / `rev_c685d933dd3e4ba6afc508de4d474653` |
| Bundle SHA | `sha256:63785945ceaa226dcb63a278cb08cbc82f8dcf35b0a9e7df9b65dde5810f6f6c` |
| Pack source-tree SHA | `sha256:e511a1361ee2b6b23957011703fa3d18031b100493d38eee6b7233d759b8d040` |
| Pack manifest SHA | `sha256:5066344a005740dbb0523daeb176fd834fd2170e0270f35943419560d0e3c0aa` |

Publication uses the Catalog application and its existing Orchestrator Artifact commit adapter,
not direct row updates or NAS copies. Only the new activation pointer changes; existing Items,
executions, production plans and historical result pins remain unchanged.

Installed read-only proof ran under `python -I` with PostgreSQL transaction-read-only enforcement:
`ContentPackService.resolve/inspect` → `WorkflowCatalogService.bind_request` →
`PackResourceResolver.read` → public `render_prompt`. It read the committed Pack, not this
checkout's prompt files. Brief V5 binding, exact bundle/SVG-policy map, authoring/review profile
`12.2.1`, one V2 section each, its complete source SHA and resolved template variables all **PASS**.
Template SHAs:

- Authoring: `sha256:7e886718642a8493d8515cf2ccd9cd64ebbac5f4de8d7450f33cc3eb4c992bdc`.
- Review: `sha256:0a15f38ea807a51d731e2b97decfbe3e0f14e45024cfdd6f9582ab16eb4351b3`.

This was a synthetic-context rendering check, with **0 new model/Item/GPU/HWPX executions**;
`prepare_prompt` and worker dispatch were not invoked. There is no new claim of educational
quality, table-choice quality, Hancom visual acceptance or whole-exam acceptance. The original
113 source PASS and independent 102 regression PASS are overlapping checks, not a summed count
of distinct tests. The deployment turn also reran the 52 focused presentation tests successfully.

Rollback for new requests reactivates predecessor
`packrel_752cb927d929471eaefa374a1f581580` using the same supported CLI; do not delete new or old
history. If runtime rollback is necessary, first restore the eligible predecessor activation and
reinstall the three byte-verified wheels retained at
`/tmp/eom-api-build/d32f3ba75bc7a0b34305204d3dba43a009e99617.u0uqpR/dist`, preserving compatible
service configuration. The installed release record is
`/var/lib/eom-api/deployments/578ddd9a8f23a1a3aa9be3ee6e256344230d98aa.json`.
Task-local operator/proof logs are temporary materialization at
`/tmp/eom-presentation-release-20261009.Q2zUUW`; they are not a canonical content store or Git
payload. Source, installed release, active Pack and documentation commits remain separate identities.

### 2026-10-09 design: bounded review-result correction, before implementation

The next actual request produced a successful authoring Artifact and a successful review Artifact,
but failed in post-result escalation classification: the reviewer reported structural complexity 2
for a typed draft with zero visuals and three statements (deterministic score 1). A general exception
became `WORKFLOW_STEP_FAILED`, bypassing the existing content-feedback loop. The user requests
correction through second/third proofs rather than an immediate full-workflow failure.

1. **Responsibility/boundary:** Workflow schedules review-result corrections through Catalog and
   Orchestrator. Workers neither contact one another nor schedule retries. Content rework and
   stronger-review escalation retain their existing responsibilities.
2. **Canonical source:** the accepted authoring/image Artifacts and immutable submitted review
   remain unchanged. The deterministic domain policy computes expected routing metadata; a model
   cannot authorize or alter that policy. Corrected review output is a new Artifact Revision.
3. **Identity/revisions:** preserve workflow, authoring/image/Graph/Pack/plan pins. Create only a new
   review step/job/result identity, with an explicit link to the submitted review being corrected.
4. **Pointers/checks:** a new additive JSON Schema 2020-12 correction directive precedes behavior.
   Its typed model carries exact authoring/review pointers, prior/next attempts, bounded proof
   number, stable error code, expected/observed small policy values and a self-hash. Resolver checks
   schema, hash, workflow/job identity, approved Artifact and exact content hash before feedback.
5. **Access patterns:** indexed step/attempt lookup and immutable Artifact resolution; ordered
   correction chain. No corpus scan, copied Item, new queue, or independent result store.
6. **Structures/indexes:** reuse the existing step input manifest, append-only Workflow events,
   unique step attempt and idempotent command keys. A bounded typed directive replaces matching
   exception strings or storing arbitrary traceback text.
7. **Complexity/scale:** O(component count) deterministic scoring; at most two correction successors
   per exact authoring revision/review tier (initial proof + second + third). Existing overall step
   limits also apply. The released content rule remains maximum three authoring↔review rework
   cycles; do not silently rewrite its predecessor into a different total-pass contract.
8. **Concurrency/transaction:** under the existing command lease fence and row locks, retain the
   submitted result pointer, mark that review step superseded/rejected for workflow use, create its
   successor and enqueue one advance command atomically. Replay must reuse identities and cannot
   create an extra model invocation. Same-authoring correction count cannot reset on replay or a
   proven infrastructure retry.
9. **Dependencies/ownership:** typed directive/error/domain policy live in Workflow contracts;
   Catalog owns validated source resolution and feedback prompt materialization; Workflow Runner
   owns scheduling. Domain imports no SQL/filesystem/Catalog. No new dependency or migration.
10. **Failure/retry:** catch only declared repairable routing-metadata defects, not general
    `ValueError`. Pass expected values plus the pinned previous review to the next reviewer, without
    regenerating a correct authoring result. Hash/permission/foreign identity/evidence-receipt or
    source-pointer corruption stays fail-closed. After the third incorrect proof, terminate with a
    specific exhausted correction code and preserve evidence; never loop or publish invalid output.
11. **Simpler alternative:** silently normalizing the accepted review would overwrite the meaning
    of its immutable hash; blindly rerunning the existing failed-job path would violate its proven
    pre-commit-only boundary and omit feedback. Both are rejected. Extend the existing step/command
    machinery with one narrow correction contract, not a general retry framework.

The new runtime correction supplement is a declared prompt materialization boundary. Original
team-lead files and released Pack template bytes remain unchanged. Exact feedback and source-result
pins participate in context/prompt hashes, and pinned prompt replay must preserve the same correction
directive. Tests must cover exact feedback, successful second/third proof, exhaustion, concurrent
command/replay, unchanged authoring/image pins, primary/escalated context preservation, no extra
content-rework count, and fail-closed trust failures. Source implementation, deployment and recovery
of the already FAILED historical request are separate states; the latter is not silently rewritten.

### Correction implementation and regression evidence — 2026-10-09 (UTC)

Canonical schema is `schemas/workflow/workflow-review-correction-directive-v1.schema.json`;
the byte-identical `eom_workflow/resources` copy is its explicit installed-wheel materialization.
The domain owns the closed correction error and independent expected-value calculation. Catalog
resolves exact rejected sources and appends a declared, context/prompt-hashed feedback supplement.
Released Pack/template/envelope bytes and the worker role schema bundle remain unchanged.

Runner preserves the rejected Step as `FAILED` with its committed output pointer and stable issue
code; the platform Job remains `SUCCEEDED`. It creates one successor/advance command transactionally.
Third-proof exhaustion is `WORKFLOW_REVIEW_CORRECTION_EXHAUSTED`, never a fourth correction.
Immutable prompt replay, command lease fences, unique attempts and exact-result idempotent adoption
protect crash/replay and two distinct simultaneous commands. An exact bounded supersession chain
plus append-only pre-commit retry evidence preserves proof number across infrastructure failures.
Malformed bindings fail terminally inside the shared error boundary; they do not leave an orphan
RUNNING Workflow. Already terminal Step error history is never overwritten by a late command.

Source gates: **175 PASS**, including domain/correction prompt/source-pin negatives, unchanged
predecessor policies, dependency direction and real wheel/resource isolated-import verification.
Strict mypy on 25 relevant sources and Ruff/format/diff checks PASS. Correction-specific disposable
PostgreSQL gate: **22 PASS**. These cover second/third success, no fourth proof, unchanged image and
stronger-review pins, lost command recovery, same/different concurrent commands, proof-budget
tampering, missing retry evidence and correction→existing authoring feedback. Focused and combined
runs overlap; their counts are not cumulative distinct acceptance counts.

The combined original Workflow Engine + submission idempotency + correction PostgreSQL suite is
**66 PASS**, including the correction 22. The first full run exposed an error-summary regression
and an old test fixture that attempted to UPDATE an immutable historical definition. The original
sanitized failure summary was restored. The fixture now uses supported exact-definition import /
replay, preserves its existing canonical bytes/hash/active value, and confirms the DB still rejects
changing that value. Neither the production immutability guard nor admission policy was weakened.

### Correction operational installation — 2026-10-09 15:29 UTC

Installed shared API/Catalog/Orchestrator source:
`2bf5dd75b1356384f5748d4c396c0af4926816ee`; tree
`3645ddb4395b28d3ccbef1fdcd5f84f875ab6ae0`; archive SHA
`sha256:f70ff3357da2d16cf668493466a26736626e57ddf63cebf752c9ee8005c60d1a`.
Build timestamp is `2026-10-09T15:26:14Z`, not the observation timestamp above.

Supported `scripts/api/deploy_release.sh --install` completed with wheel/RECORD/pip checks,
migration-owner preflight (no migration beyond `20261008_0049`), isolation, authenticated API smoke
and post-install `--verify` PASS. Active worker lease preflight was zero. API, Catalog, Workflow
runner/maintenance, HWPX manager, Web and both general-chat units are active. The first task-local
shell wrapper invocation failed before invoking the installer (line continuation); it changed no
runtime state. The corrected wrapper performed one actual supported installation successfully.

An installed `python -I` proof enforced PostgreSQL transaction-read-only and resolved the exact
authoring/review incident sources through public Catalog Artifact resolution (identity, approved
revision, member, media/storage boundary and SHA checks). The new domain returns
`REVIEW_STRUCTURAL_COMPLEXITY_MISMATCH`, expected 1 / observed 2, builds a schema/self-hashed 2교
directive, and independently validates that directive against both exact source results. The
historical Workflow remains FAILED / `WORKFLOW_STEP_FAILED`, rework count zero. This is read-only
installed-boundary evidence, not a new model run or a historical recovery claim.

Pack release `packrel_8dde7e96f50542e4932f55c8e76b8083` / version `1.20.15` and bundle SHA
`sha256:63785945ceaa226dcb63a278cb08cbc82f8dcf35b0a9e7df9b65dde5810f6f6c` remain unchanged.
Web and the separate chat activation retain their preceding source pins; neither was redeployed.
Model/Item/GPU/HWPX executions: zero. Full live corrected-review dispatch remains NOT_RUN.
The task-owned disposable DB and credential directory were removed via guarded cleanup after all
test processes ended. Production data, accepted Artifacts and failed histories were not removed.

Release record:
`/var/lib/eom-api/deployments/2bf5dd75b1356384f5748d4c396c0af4926816ee.json`.
Task-local materialization/evidence is `/tmp/eom-presentation-release-20261009.Q2zUUW`:
`install-review-correction-run2.log`, `review-correction-verify.log`,
`verify-review-correction.py` and `review-correction-testdb-cleanup.log`.
Runtime rollback restores the immediately preceding compatible `578ddd9a` wheels at
`/tmp/eom-api-build/578ddd9a8f23a1a3aa9be3ee6e256344230d98aa.wpTTGb/dist`, without deleting
new correction history or changing Pack activation. Installed release and later documentation
commit identities remain separate.
