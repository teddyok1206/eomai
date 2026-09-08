# Content-team mock-exam Item protocol V3

## Decision

Introduce an additive content-team Item family for future mock-exam generation:

- canonical `AssessmentItemContentV3` / `eom.assessment.item-content/3.0`;
- workflow-role protocol `workflow-role/1.19.0` and result schemas `authoring-result@9.0`,
  `image-result@9.0`, `review-result@9.0`, and `registration-result@9.0`;
- workflow definition `generic-item-development@1.9.0`;
- Content Pack `generated-knowledge-item@1.14.0`; and
- Standard/Graph-backed execution preset bootstraps V8/V5.

`AssessmentItemContentV2`, every `@8.0` result schema, workflow `1.8.0`, Content Pack `1.13.0`,
and their hashes remain immutable and readable. The new family exists because the reviewed
content-team source format preserves a decimal score, while V2 accidentally excluded the valid
`1.5` spelling required by the released 25-slot mock-exam policy.

## Boundary and canonical source

The Catalog Item revision remains the logical entity. Its immutable revision pins one canonical
JSON member, one deterministic content-team Markdown member, their independent hashes, and any
separate image Artifact Revisions. V3 changes the small semantic value only: `score_display` is one
of `1.5`, `2`, `2.5`, or `3`. It neither embeds binary data nor changes Item, revision, component,
or artifact identity.

The byte-preserved content-team authoring prompt is still the content authority and the reviewed
HwpQuestionEditor handoff is still the executable presentation authority. Platform additions are
limited to typed score/slot equality, provenance, pointer safety, and the already deployed SVG
sanitizer boundary. No subject, unit, or sample content is introduced.

## Pointers and resolution

The authoring and review prompts receive the canonical reviewed brief. For a production occurrence,
its `mock_exam_slot` pins policy revisions, hashes, position, point value, curriculum unit, and the
slot hash. Registration accepts V3 only when:

1. `score_display` equals `mock_exam_slot.points_milli / 1000` in canonical spelling;
2. authoring metadata equals the orchestrator-derived grounding mode (`graph_grounded` whenever an
   educational-retrieval pointer is present);
3. workflow/result/release pointers resolve to their exact pinned revisions and hashes; and
4. each IMAGE slot resolves to the exact ordered immutable PNG Artifact Revision.

Missing, stale, mismatched, or hash-invalid pointers fail explicitly. No implicit latest revision is
used.

## Access patterns and structures

Frequent operations are O(1) schema/result dispatch by keyed maps, O(1) membership checks by frozen
sets, and ordered O(v) traversal of at most two visual slots. Registration performs one bounded
ordered pass over workflow artifact pointers and one bounded pass over visual pointers. No new DB
query, queue, cache, full scan, N+1 query, or large persisted value is introduced. JSON and Markdown
remain small immutable values; PNG and HWPX bytes remain artifact members outside PostgreSQL.

## Transactions, concurrency, retry, and idempotency

The existing Workflow/Catalog application-service transaction remains the commit boundary. A V3
artifact idempotency key includes the workflow identity and canonical content hash, so replay returns
the same immutable content revision. Schema validation, score/provenance validation, Markdown
round-trip, and image pointer resolution all precede Item registration. Failures leave no partial
Item revision and are safe to retry with the same pinned inputs.

## Dependency direction

HWPX and Catalog contract packages own value/schema definitions. Workflow contracts depend on those
stable contracts. Catalog and HWPX infrastructure adapters interpret the new version through their
existing interfaces. Domain models do not import SQLAlchemy, filesystem, HWPX, HTTP, or worker
implementations. Workers still return structured local results and never orchestrate or write NAS.

## Safe SVG projection

The V9 image result keeps the existing generated-drawing structure but rejects active/external SVG
markers and SVG paint-server/gradient constructs at schema and Pydantic validation. Its prompt names
the exact existing safe subset (bounded 800x500 canvas, allowed primitive tags and attributes,
literal flat colors, no `url()`, gradient, style, script, external/data reference, filters, masks,
or embedded image). Catalog still reconstructs the SVG through the authoritative fail-closed
sanitizer before rasterization; prompt/schema checks are defense in depth, not a replacement.

## Failure model and simpler alternative

Stable failures cover unsupported score spelling, production slot score mismatch, grounding-mode
mismatch, unsafe SVG text, non-round-trippable Markdown, and unresolved artifact pointers. Existing
V2/@8 values retain their former validation behavior.

The historical direct `mock-exam-assembly-manifest/1.0` creation path remains V2-only. It bulk
checks that every selected revision exposes exactly one canonical ordinal-zero V2 Item-content
component and rejects V3, mixed, missing, ambiguous, or structurally incomplete pointers before
persisting an Assembly revision. V3 is supported only by the server-authored plan V2 / manifest V3
path, which carries the content pointers needed for reproducible HWPX rendering.

Adding `1.5` directly to V2 and reinterpreting `@8.0` would be simpler, but would mutate already
pinned schemas and invalidate reproducibility. Filtering reviewer findings or overriding the score
only at assembly would also be smaller, but it would preserve a false source value. The additive V3
boundary is therefore the smallest versioned correction that keeps source, registration, review,
and final HWPX presentation truthful.

## Immutable successor boundary design

1. **Responsibility and boundary.** The API contracts own public projections and resumable
   checkpoints; Catalog contracts own private wire messages and immutable review artifacts; HWPX
   owns render requests. Each installed schema identity remains historical and successors carry the
   V3 capability.
2. **Canonical source.** Files under `schemas/` are canonical. Package resources are byte-exact
   mirrors checked at build time; Pydantic models validate materialized values but do not redefine a
   previously published schema identity.
3. **Entity and revision model.** Item, Workflow, review, execution, assembly, and artifact logical
   IDs remain separate from immutable revision IDs and SHA-256 values. A protocol successor changes
   only the typed envelope, never those identities.
4. **Pointers and resolution.** Content V3 must resolve its pinned Item-content artifact, editorial
   Markdown member/hash/schema, review-result@9 artifact, decision/2.0, Graph snapshot, plan V2, and
   renderer 3.0 pointers. Every boundary rejects absent, stale, hash-mismatched, or mixed-family
   pointers rather than selecting a latest revision.
5. **Access patterns.** Protocol selection is constant-time lookup by operation plus the explicit
   content/review schema discriminator. Candidate listing remains an indexed database query followed
   by ordered immutable projection; checkpoint loading dispatches once by `schema_version`.
6. **Data structures and indexes.** Read-only route maps and discriminated unions provide O(1)
   family selection. Existing indexed IDs and component ordinals remain authoritative; no new scan,
   cache, or persisted derived field is introduced.
7. **Scale and complexity.** One execution contains exactly 25 ordered Item runs, so validation is
   O(25) time and space. Catalog wire and candidate dispatch are O(1) beyond their existing query and
   artifact-resolution costs.
8. **Transaction and concurrency.** Catalog import/review publication continues in its existing
   application-service transaction. Checkpoints remain append-only immutable revisions with CAS on
   the current pointer; the successor version cannot change during a revision chain.
9. **Dependency direction.** Routers and clients select exported contracts, application services
   orchestrate, domain models validate, and storage/HWPX adapters implement existing ports. Contract
   packages import no database, filesystem, socket, or renderer implementation.
10. **Failure, retry, and idempotency.** Unknown discriminators and V1/V2/V3 mixtures fail before
    persistence with stable contract/integrity errors. Exact replay returns the pinned receipt;
    retries reuse IDs and hashes and never rewrite an older schema.
11. **Rejected simpler alternative.** Widening Catalog v10/v11, candidate/execution/review API v1,
    review artifact v1, Workflow-start v1, or the `urn:eom:schema:api:v1:hwpx` document in place is
    smaller but invalidates installed hashes and historical replay. Additive v12/v2 schemas are the
    minimum safe correction.

The closed successor matrix is: Catalog item/review wire v12; production candidate view 2.0;
production execution checkpoint 2.0; review-eligibility observation 2.0; review decision,
publication result, and eligibility result 2.0; and `urn:eom:schema:api:v2:hwpx`. Historical v10,
v11, all listed v1 schemas, and Workflow-start v1 remain byte-pinned and readable.

## Operator rollout (not performed by this change)

`deploy_release.sh` installs the API/platform code and schema resources only; the isolated HWPX
builder has its own reviewed release boundary. Neither script imports the Workflow definition,
publishes either control preset, releases/activates the Content Pack, or replaces the operator-owned
runner definition. Keep `eom-workflow-runner.service` inactive under the reviewed deployment hold
until the preceding production cohort has been retired and all commands below have succeeded.

Use the installed CLI and the exact reviewed Git commit:

```bash
cd /home/eom/EOM
SOURCE_COMMIT="$(git rev-parse HEAD)"
EOMCTL=/srv/eom/conda/envs/eom-api/bin/eomctl
ACTOR_ID=<VALID_ADMIN_OPERATOR_ID>

scripts/api/deploy_release.sh --install-preserve-workflow-runner-inactive
test "$(git rev-parse HEAD)" = "${SOURCE_COMMIT}"
scripts/hwpx/deploy_builder.sh --install
scripts/hwpx/deploy_builder.sh --verify
test "$(git rev-parse HEAD)" = "${SOURCE_COMMIT}"

"${EOMCTL}" workflow definition validate \
  /home/eom/EOM/config/workflows/generic-item-development.v1.9.yaml
"${EOMCTL}" workflow definition import \
  /home/eom/EOM/config/workflows/generic-item-development.v1.9.yaml
"${EOMCTL}" workflow definition admission

"${EOMCTL}" control-plane bootstrap-standard \
  --config-directory /home/eom/EOM/config/control-plane/standard-item-v8 \
  --content-directory /home/eom/EOM/content \
  --source-commit "${SOURCE_COMMIT}" \
  --actor-id "${ACTOR_ID}" \
  --evaluation-cases-total 4
"${EOMCTL}" control-plane bootstrap-knowledge-item \
  --config-directory /home/eom/EOM/config/control-plane/knowledge-grounded-item-v5 \
  --source-commit "${SOURCE_COMMIT}" \
  --actor-id "${ACTOR_ID}" \
  --evaluation-cases-total 4

"${EOMCTL}" content pack validate \
  /home/eom/EOM/content/packs/generated-knowledge-item/1.14.0
PACK_JSON="$("${EOMCTL}" content pack import \
  /home/eom/EOM/content/packs/generated-knowledge-item/1.14.0)"
PACK_RELEASE_ID="$(printf '%s' "${PACK_JSON}" | \
  /srv/eom/conda/envs/eom-api/bin/python -c \
  'import json,sys; print(json.load(sys.stdin)["content_pack_release_id"])')"
"${EOMCTL}" content pack release "${PACK_RELEASE_ID}" --actor-id "${ACTOR_ID}"
"${EOMCTL}" content pack activate "${PACK_RELEASE_ID}" \
  --environment development --actor-id "${ACTOR_ID}"
"${EOMCTL}" content pack resolve \
  --pack-key generated-knowledge-item --environment development

sudo -n /home/eom/EOM/scripts/workflow/install_runner_configuration.sh
sha256sum /etc/eom/workflows/generic-item-development.yaml
```

Workflow import sets `active=true` only because the installed admission table contains the exact
identity `generic-item-development@1.9.0 -> workflow-role/1.19.0`; there is no separate activation
command. Re-import is an immutable/hash-checked replay. The two bootstrap commands create the
evaluation evidence and release the resulting preset revisions in the same application-service
transaction; retain their returned `preset_id`, `preset_revision_id`, policy hash, evaluation ID,
and (for the knowledge preset) exact base preset revision ID. Pack IDs are generated durable IDs,
so the release ID must be taken from the import response as above rather than predicted.

Before allowing new work, compare the returned and installed values with this closed inventory:

| Identity | Expected value |
|---|---|
| Workflow definition | `generic-item-development@1.9.0` |
| Workflow source bytes | `sha256:87edfedf01c9c78ba9356f47487254c130ffe07596d84e2497c1c8e1c8346e7e` |
| Compiled Workflow | `sha256:698a800f7d02e1974833f290bf14e6b823477d8ea0b62d5d1ee069a71824eed6` |
| Role schema bundle | `workflow-role/1.19.0`, `sha256:4074b06eea595f8dcfbee29c902d16cd0a97bd593963cc474640df0b90c33c6c` |
| Standard preset bootstrap | `standard-item`, `standard-control-bootstrap/8.0`, source `sha256:34aeff9f1f92b59db91c54c6da149326ec8f73c87d52f0d0a3de9daf8c61b06b` |
| Graph preset bootstrap | `knowledge-grounded-item`, `knowledge-item-control-bootstrap/5.0`, source `sha256:00fc0ef3d268610c0f26ce27c831632766614a314283e7b5ee940250166cf5ab` |
| Content-team authoring authority | `sha256:62f245320a4776a2ee3dcd273fb1180b6f3c431a45d2504d125816102f017435` |
| Handoff Markdown / archive authority | `sha256:6fdfd8f9dbc67abfcac9ef2761059bbe841a8b994640925fef30388d95a00ee5` / `sha256:dc1c9e254a31fc235824eddbb366a5fac52a4d03e3b334bd5e325fb52391ea91` |
| Content Pack source | `generated-knowledge-item@1.14.0`, `sha256:31f15f4811090045a92ad3a465e94f91ec430e638fe7b07f132c024e079a5792` |
| Content Pack bundle / manifest | `sha256:b5f224b6f2d0cdf08cef66787fe2a51b0e3d2dd829650c3ed3e87825b0711a68` / `sha256:fa03705ada92b2645115c3aaa865645e61555239c396bdb5edbb952dff1e7c44` |
| Production plan | `productionplan_f5de90cbffb98909cdf358b410353ffc`, `sha256:f5de90cbffb98909cdf358b410353ffc81386f1589afaaaa960f9c12ab7f36d6` |
| Generation block | revision `2.0`, `sha256:977601f0e1060f9f6304c5b58be357723758359adf1b18c931d6f82a35ae4c81` |
| HWPX V3 schema bundle | `sha256:43b7659bb96845f97fc2c29f5b26eaf561b4ba36ed0a1ee811088aa7cd9675a8` |

The installed runner definition must produce the Workflow source-byte hash shown above. Only after
the retirement receipt and these pointer/hash checks pass may the reviewed retirement runbook
release the persistent hold and start the runner. Do not use the normal deploy path while the hold
is required: it would restart the runner. Historical Workflow 1.8, Pack 1.13, V2 Item, @8 results,
and HWPX V2 remain installed and readable; new production plan V2 requires the exact V3 family and
rejects a mixed manifest, content, review, or renderer tuple.
