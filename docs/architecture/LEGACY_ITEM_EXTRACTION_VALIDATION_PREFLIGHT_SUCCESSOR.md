# Legacy item extraction validation-preflight successor

Status: implemented and source-validated; not deployed or executed, 2026-09-09 UTC

## Decision

Do not blindly continue the three terminal extraction work units. Their persisted, content-free
failure fingerprints classify three independent output-conformance failures under the unchanged
released preset, workflow, role schema, instruction, and installed schema:

- duplicate `solution.statement_explanations[].statement_id` values;
- one body element that does not match exactly one discriminated body-block branch; and
- a `representation_kind=NONE` visual observation that nevertheless declares a rendered mode,
  panel layout, or feature.

The result contract and Pydantic validators are correct and remain unchanged. Semantic
canonicalization is forbidden because choosing a statement explanation, rewriting a body block, or
discarding observed visual features could lose source evidence. Instead, publish a reviewed
immutable extraction instruction/bundle/preset successor that adds three explicit pre-submit
checks, then create a fresh `legacy-item-extraction-batch/1.1` continuation containing only the
three missing five-item ranges. Historical failed work units and their pinned preset stay intact.

## Required design procedure

1. **Responsibility and system boundary.** The successor instruction reduces model conformance
   errors; canonical JSON Schema and Pydantic remain the enforcement boundary. The Catalog batch
   coordinator owns fresh continuation identities, the Orchestrator owns validation and Artifact
   commit, and the worker remains read-only and stateless.
2. **Canonical source.** Existing Assessment Item and legacy-extraction schemas/models remain the
   semantic authority. New reviewed Markdown bytes become one immutable role-instruction Artifact
   revision, referenced by a new Instruction Bundle revision and Execution Preset revision.
3. **Logical entity and revision model.** Retain the `legacy-item-extraction` logical preset and add
   append-only successor revisions with distinct revision IDs and hashes. A continuation manifest
   uses fresh batch, work-unit, extraction-request, workflow, job, and idempotency identities while
   pinning the reviewed successor preset revision. Failed predecessors are not mutated.
4. **Pointers and resolution checks.** The successor publication must compare-and-set against the
   exact reviewed predecessor preset revision, validate instruction Artifact/bundle schema,
   media type, revision, hash, lifecycle, and source commit, and preserve the existing workflow,
   role-schema, capacity-policy, slot-06, sandbox, network, model, and knowledge-policy pointers.
   Continuation resolution rejects implicit latest substitution or any unexpected current pointer.
5. **Primary access patterns.** Preset resolution is indexed lookup by logical key and immutable
   revision ID. Continuation work-unit membership uses an exact three-ID allowlist and ordered
   iteration of three fixed five-item ranges.
6. **Data structures and indexes.** Existing frozen DTOs, immutable revision tables, B-tree identity
   indexes, unique `(batch_id, ordinal)` constraints, and FIFO claim indexes are sufficient. No new
   queue, table, large JSON value, or binary database payload is needed.
7. **Complexity and scale.** Publication is bounded by one small instruction and one role policy.
   Continuation construction and validation are `O(w + i)` for three work units and 15 item numbers;
   claim behavior remains indexed and constant-sized.
8. **Transaction and concurrency boundary.** Successor publication locks the logical preset row,
   proves the exact current predecessor, records/evaluates one draft, and atomically advances the
   current pointer. The continuation is created through the existing Catalog transaction. Slot-06
   claims remain globally lease-protected and must be time-sliced against the mock-exam hold gates.
9. **Dependency direction and adapter ownership.** A versioned control-bootstrap JSON Schema and
   Pydantic command, if required for publication, sit below the CLI application service. Database,
   filesystem, Artifact, and systemd behavior remain infrastructure adapters. The instruction does
   not move validation rules into the worker.
10. **Failure, retry, and idempotency.** Exact publication replay returns the same successor; wrong
    predecessor, changed bytes, failed evaluation, or policy drift fails closed. The continuation
    is a closed three-unit collect batch: each failed unit remains terminal, is never retried by the
    runner, and any new systematic category blocks a further successor authorization. No accepted
    predecessor range is re-executed.
11. **Simpler alternative and why insufficient.** Reusing the released predecessor repeats all
    three observed failures. Mutating its instruction violates immutable history. Server-side
    normalization risks deleting or inventing assessment meaning. A new extraction result schema is
    unnecessary because the existing contract already expresses and enforces the intended values.

## Successor instruction delta

Add only these checks to a new instruction file; retain all predecessor text unchanged:

1. Build the ordered statement-ID list for each `statement_set`, then emit exactly one explanation
   per ID with no duplicates. Check both set equality and list uniqueness before return.
2. For each body element, choose its `type` first and emit only that branch's required/allowed keys.
   Confirm the element validates exactly one of `paragraph`, `equation`, `table`, `image`, or
   `statement_set`; never combine fields from multiple branches.
3. For every visual observation with `representation_kind=NONE`, set
   `rendering_mode=TEXT_ONLY`, `panel_layout=NONE`, and `features=[]`. If rendered evidence exists,
   select the evidenced non-`NONE` representation kind instead of erasing the evidence.

The existing bootstrap V1 intentionally rejects a changed policy after release, so it must not be
reused with edited files. The reviewed implementation should add an additive successor manifest
and schema carrying the exact predecessor preset revision plus instruction revision number, and a
typed compare-and-set publication path. That is the smallest safe cross-boundary addition; the V1
schema/config/code remain byte-stable.

## Pre/post gates for continuation

- Before publication: verify the predecessor/current preset ID, revision, policy hash, workflow
  definition, role-schema bundle, instruction hashes, capacity revision, and installed schema match
  the reviewed content-free snapshot; verify no active slot-06 lease/job/workflow and no retirement
  hold conflict.
- Before execution: validate the new `legacy-item-extraction-batch/1.1` manifest by JSON Schema and
  Pydantic; assert its exact owner set is the three failed work-unit ranges, 15 unique
  `(assessment source bundle revision, item number)` occurrences, fresh identities, successor
  preset pin, and no reuse/accept action. Item numbers alone are not globally unique because two
  different assessments legitimately include overlapping local item numbers.
- After execution: require all three new work units terminal-success, 15/15 extraction results with
  canonical receipts and zero ordinal/item gaps before enabling automatic acceptance or promotion.
  Any new validation category disables automation immediately and preserves the failure.

## Implemented protocol and ownership boundaries

The implementation is additive. Historical V1 schema/config/instruction bytes and the extraction
result contract are unchanged.

- `legacy-item-extraction-control-bootstrap/2.0` carries the exact predecessor preset, capacity,
  instruction-bundle, workflow-definition, and role-schema revisions and hashes. V2 requires
  instruction revision 2; V1 serializes without V2 fields and retains its original schema.
- `legacy-item-extraction-validation-recovery/1.0` is the frozen authorization contract. It pins
  both complete preset dependency graphs, the predecessor batch manifest hash, all three failed
  work-unit/request/workflow/job identities, the hashed failure messages, diagnoses, source bundle
  revisions, five-item ranges, fresh successor identities, UTC creation time, and its own canonical
  hash.
- The Orchestrator publishes the instruction bundle with a row-locked adjacent-revision CAS. It
  accepts only the exact predecessor or an exact already-current replay. Preset release repeats the
  predecessor/current check under the preset row lock immediately before release. V2 resolves the
  installed six-slot registry, slot-06 auth identity, protocol, and capacity revision without
  upserting or republishing them, and binds new role/manifest Artifact replay to the reviewed source
  commit.
- The Catalog application service resolves the predecessor manifest by batch ID plus SHA-256,
  proves that the batch is exactly `COMPLETED_WITH_GAPS` with exactly the authorized three failed
  rows, re-resolves failure/workflow/job/step evidence, and resolves both preset dependency graphs
  by immutable IDs and hashes. Both bootstrap predecessor preflight and Catalog resolution
  cross-bind each preset, Instruction Bundle, capacity policy, and workflow canonical document to
  its persisted row and authorization pin; a valid self-hash cannot mask a different row hash or
  identity. The nested manifest Artifact SHA must also equal the SHA-256 of the exact canonical,
  newline-terminated Instruction Bundle document bytes and the bundle manifest SHA in the
  canonical preset, persisted bundle revision, and external authorization pin. Catalog creates a
  new three-unit `EXECUTE` batch through the existing batch service; it never converts a failed row
  to pending and never selects a latest revision.
- The existing Catalog runner already accepts an ordered, duplicate-free comma-separated
  `EOM_LEGACY_ITEM_AUTOMATION_BATCH_IDS` allowlist. No new scheduler, queue, retry loop, or worker
  communication path was added.

The exact predecessor owner set is closed:

| Ordinal | Failed work unit | Source bundle revision | Local items | Diagnosis |
| ---: | --- | --- | --- | --- |
| 23 | `legacyworkunit_effa66b21814add8cac3d8cde5c5881b` | `assessbundlerev_b6be31d55220e4c095d11433d394e641` | 16–20 | duplicate statement explanation ID |
| 65 | `legacyworkunit_076f5ffc97766f3831592af2d0f1fdda` | `assessbundlerev_2690a6a1e07e4789c17f9dd2e9e4cf4e` | 6–10 | body-block discriminator mismatch |
| 85 | `legacyworkunit_cd81cbb341454ec4f7d7ae5a92767729` | `assessbundlerev_4b1423ea0ceef51eb05cba9555b846ed` | 5–9 | `NONE` visual/rendering conflict |

The implementation and operator sequence are intentionally separate. Source validation does not
authorize a live worker call. Deployment, V2 bootstrap, recovery authorization construction,
continuation creation, allowlist activation, stop conditions, and postconditions are defined in
[`LEGACY_ITEM_EXTRACTION_VALIDATION_RECOVERY.md`](../operations/LEGACY_ITEM_EXTRACTION_VALIDATION_RECOVERY.md).
