# Content-team exact-slot control-policy successor

## Decision

Add two immutable control-policy manifests and no new Item, Workflow, Content Pack, production-plan,
or production-execution family:

- `standard-control-bootstrap/9.0`; and
- `knowledge-item-control-bootstrap/6.0`.

The Standard V9 authoring instruction makes the already typed mock-exam slot an exact five-field
contract: primary material profile, mapped difficulty, inquiry presence, score, and knowledge
provenance. Knowledge V6 projects that released Standard revision into the existing
`knowledge-grounded-item` preset while changing only evidence access in the existing way.

Content Pack `generated-knowledge-item@1.14.0`, generation block `2.0`, production plan/execution
`2.0`, Workflow `generic-item-development@1.9.0`, `workflow-role/1.19.0`, and every V9 result schema
already carry all required values and remain byte-immutable. A fresh production execution resolves
and pins the new current `knowledge-grounded-item` preset revision and hash; an older execution
keeps its old pinned preset.

## Required design procedure

1. **Responsibility and system boundary.** The Standard control preset owns cross-Pack worker
   instructions; the knowledge preset owns evidence-access projection. The Content Pack still owns
   item-format prompting, the Workflow owns step order/result schemas, Catalog owns exact output
   validation, and the production coordinator only resolves and pins dependencies. Workers still
   neither orchestrate nor persist.
2. **Canonical source.** Canonical JSON Schemas live under `schemas/workflow/control-plane/` and
   their package resources are byte-exact mirrors. Reviewed manifests and instruction bytes live in
   new `config/control-plane/standard-item-v9` and `knowledge-grounded-item-v6` directories. Older
   schema resources and configuration trees are never edited.
3. **Logical entity and revision model.** The `standard-item` and `knowledge-grounded-item` logical
   preset IDs retain append-only released revisions with independent content hashes. Workflow,
   production execution, Item, and artifact IDs/revisions/hashes remain separate. A fresh production
   checkpoint pins the resolved preset ID, immutable revision ID, and SHA-256 without changing its
   plan identity.
4. **Required pointers and resolution checks.** Standard bootstrap validates every local member,
   instruction/reference bundle pointer, media type, schema, manifest hash, and source hash before
   releasing a preset revision. Knowledge bootstrap requires the current released Standard revision,
   matching protocol, roles, references, and policy hash before deriving its revision. Production
   generation resolution requires the current released knowledge preset and records its exact ID,
   revision, key, and hash; missing, stale, incompatible, or hash-invalid pointers fail explicitly.
5. **Primary access patterns.** Bootstrap contract selection is O(1) keyed schema-version dispatch;
   current preset resolution uses indexed logical keys/revision IDs; roles use fixed keyed maps;
   instruction and reference members use bounded ordered iteration. Exact slot checks are O(1)
   comparisons against the typed reviewed brief.
6. **Chosen data structures and indexes.** Frozen Pydantic models, JSON Schema discriminators,
   immutable tuples, and fixed mapping tables match the operations. Existing unique preset keys,
   primary revision IDs, and bundle/artifact indexes remain sufficient. No database table, column,
   index, queue, cache, registry, or large persisted value is introduced.
7. **Expected complexity and scale.** Bootstrap work is O(r + m) time/space for four fixed roles and
   a small bounded member set. Runtime adds no query or payload; each worker receives one small
   instruction bundle already materialized by the existing path. Production remains exactly 25
   independent calls and its checkpoint complexity is unchanged.
8. **Transaction and concurrency boundary.** Each bootstrap retains its existing application-service
   transactions: publish validated immutable artifacts, create/evaluate a draft, then release and
   advance the logical current revision. Existing row locks serialize same-key revision creation.
   Production checkpoint compare-and-swap and workflow transactions are unchanged.
9. **Dependency direction and adapter ownership.** CLI calls orchestration application services;
   those services depend on Workflow control contracts; artifact/database behavior stays in existing
   infrastructure adapters. Contract packages import no SQLAlchemy, filesystem, subprocess, HTTP,
   renderer, or worker implementation.
10. **Failure, retry, and idempotency.** Unknown schema versions, unsafe files, changed bytes,
    missing references, incompatible protocols, stale base revisions, and pointer/hash mismatches
    fail before activation with stable control-plane errors. Exact bootstrap replay returns the same
    immutable revision/evaluation result; new bytes create a successor revision. An authoring output
    that violates the five-field slot contract is rejected by the existing Catalog review gate and
    can be reworked without partial Item registration.
11. **Simpler alternative and why insufficient.** Editing Standard V8, Knowledge V5, Pack 1.14, or
    a deployed schema in place would invalidate historical hashes. A Pack-only successor would also
    require a new immutable generation block plus plan/checkpoint successors merely to select it.
    V9 result schemas already represent all values, and the production resolver intentionally pins
    the current compatible preset revision. Two additive control manifests are therefore the
    smallest boundary that changes worker behavior while preserving all deployed production
    protocols.

## Prompt composition and exact invariant

The Content Pack renders the per-step task prompt supplied on standard input. Independently, the
resolved execution plan materializes the pinned Standard instruction bundle as workspace
`AGENTS.md`, so the new control instruction applies to the same authoring worker without changing
Pack bytes. The instruction requires, for every non-null `mock_exam_slot`:

1. `metadata.difficulty` equals `LOW -> easy`, `MEDIUM -> medium`, or `HIGH -> hard`;
2. the classified draft profile equals `mock_exam_slot.preferred_material_profiles[0]`, which is
   also the reviewed brief's pinned `task_type`;
3. an inquiry block exists exactly when `mock_exam_slot.inquiry_required` is true;
4. `draft.score_display` equals the existing canonical `points_milli` mapping; and
5. `metadata.knowledge_source_mode` equals the reviewed brief's exact provenance mode.

The remaining ordered material profiles are layout-policy planning alternatives, not permission for
the authoring worker to substitute another profile for a pinned production occurrence.

The existing Catalog validator remains the authoritative enforcement boundary after result-schema
validation. The new instruction is a reviewed behavior policy that reduces deterministic rework; it
does not trust the worker or bypass server-side validation.

## Closed source inventory

| Resource | SHA-256 |
|---|---|
| Standard V9 canonical schema and package mirror | `3b170564aacd2651e6d13bc3dc8821710053f8119ea40869cbc2564f04d9e527` |
| Knowledge V6 canonical schema and package mirror | `9b9eb9ff61ec59449b3594223d6bc8fe5fbc855993f17ed79e2c558ca208c674` |
| Standard V9 `bootstrap.yaml` | `d17e1ec5c52b20e362a01d05144bb99d263f8f1117622fc265e4e66b9c385fc8` |
| Standard V9 authoring instruction | `82d74b31fa697f55016fcd11a62c940fa8a8840d3175b91e0fdb52d1f8271e4c` |
| Standard V9 review instruction | `5613e757e33555695ee3b3536e24744d33b940c6fb14bc489ee62992d9c06cdb` |
| Standard V9 platform/image/item-management instructions | `5a3cfab6dc1c195ebc93cb13c7549cd31ea30f6229a4b134bed818d9dd69271b` / `7f9f1c9eb5dee44ef76981b04121f1a689a849e8388051f266c4d0ea80cd74ca` / `c5af5ca1137f1ef2c2e724e3a3692178d6d48eeee7eac8f293d7014e67ec156a` |
| Knowledge V6 `bootstrap.yaml` | `1e123bf26bf1527f75c26f32853ca98aa2b7630a23d48e9c65bd7f1fd1c0937a` |

Standard V9 is timestamped `2026-09-08T18:55:00Z`; Knowledge V6 is timestamped
`2026-09-08T18:58:00Z`. Both are UTC, ordered after their deployed predecessors, and ordered so the
knowledge revision cannot precede its base Standard revision.

## Integration gates

Run from the reviewed clean commit with the explicit API Conda environment. The focused gate is
non-live and makes no external LLM call:

```bash
cd /home/eom/EOM
PY=/srv/eom/conda/envs/eom-api/bin/python
RUFF=/srv/eom/conda/envs/eom-api/bin/ruff
MYPY=/srv/eom/conda/envs/eom-api/bin/mypy
export PYTHONPATH=packages/protocol:packages/identifiers:packages/workflow:packages/catalog_contracts:packages/api_contracts:packages/content_pack:packages/item_registry:services/orchestrator:services/catalog_service:services/workflow_runner:apps/application_api:apps/eomctl:packages/operator_identity:services/identity_service:packages/hwpx_contracts:services/hwpx_manager:packages/image_contracts:packages/content_intake

cmp schemas/workflow/control-plane/standard-control-bootstrap-v9.schema.json \
  packages/workflow/eom_workflow/resources/control-plane/standard-control-bootstrap-v9.schema.json
cmp schemas/workflow/control-plane/knowledge-item-control-bootstrap-v6.schema.json \
  packages/workflow/eom_workflow/resources/control-plane/knowledge-item-control-bootstrap-v6.schema.json
sha256sum \
  schemas/workflow/control-plane/standard-control-bootstrap-v9.schema.json \
  schemas/workflow/control-plane/knowledge-item-control-bootstrap-v6.schema.json \
  config/control-plane/standard-item-v9/bootstrap.yaml \
  config/control-plane/standard-item-v9/instructions/*.md \
  config/control-plane/knowledge-grounded-item-v6/bootstrap.yaml

"${RUFF}" format --check \
  packages/workflow/eom_workflow/control_schemas.py \
  services/orchestrator/eom_orchestrator/control_bootstrap.py \
  services/orchestrator/eom_orchestrator/knowledge_item_bootstrap.py \
  packages/catalog_contracts/eom_catalog_contracts/mock_exam_production_plan.py \
  scripts/api/verify_mock_exam_deployment_admission.py
"${RUFF}" check \
  packages/workflow/eom_workflow/control_schemas.py \
  services/orchestrator/eom_orchestrator/control_bootstrap.py \
  services/orchestrator/eom_orchestrator/knowledge_item_bootstrap.py \
  packages/catalog_contracts/eom_catalog_contracts/mock_exam_production_plan.py \
  scripts/api/verify_mock_exam_deployment_admission.py
"${MYPY}" \
  packages/workflow/eom_workflow/control_schemas.py \
  services/orchestrator/eom_orchestrator/control_bootstrap.py \
  services/orchestrator/eom_orchestrator/knowledge_item_bootstrap.py \
  packages/catalog_contracts/eom_catalog_contracts/mock_exam_production_plan.py \
  scripts/api/verify_mock_exam_deployment_admission.py
"${PY}" -m pytest -q \
  tests/unit/test_content_team_v3_protocol.py \
  tests/unit/test_control_bootstrap.py \
  tests/unit/test_knowledge_item_bootstrap.py \
  tests/unit/test_execution_control_contracts.py \
  tests/api/test_mock_exam_generation_block_resolver.py \
  tests/api/test_mock_exam_deployment_admission.py \
  tests/api/test_deployment_boundaries.py
```

The repository-wide gate remains `ruff format --check`, `ruff check`, strict `mypy`, and the full
non-live test suite. PostgreSQL integration is opt-in and must use an explicitly isolated test URL;
never allow the runtime secret fallback:

```bash
EOM_RUN_INTEGRATION=1 EOM_DATABASE_URL='<ISOLATED_TEST_DATABASE_URL>' \
  "${PY}" -m pytest -q tests/integration/test_control_plane_persistence.py
```

## Operator rollout (not performed by this change)

Keep the Workflow runner under the persistent reviewed deployment hold. The preceding production
execution must first be terminal or have a validated retirement receipt. The updated deployment
admission helper discriminates both checkpoint `1.0` and `2.0` through the installed contract and
must return `mock_exam_deployment_admission=READY` before wheel replacement.

```bash
cd /home/eom/EOM
SOURCE_COMMIT="$(git rev-parse HEAD)"
EOMCTL=/srv/eom/conda/envs/eom-api/bin/eomctl
ACTOR_ID=<VALID_ADMIN_OPERATOR_ID>

test -z "$(git status --porcelain)"
scripts/api/deploy_release.sh --install-preserve-workflow-runner-inactive
test "$(git rev-parse HEAD)" = "${SOURCE_COMMIT}"

umask 077
"${EOMCTL}" control-plane bootstrap-standard \
  --config-directory /home/eom/EOM/config/control-plane/standard-item-v9 \
  --content-directory /home/eom/EOM/content \
  --source-commit "${SOURCE_COMMIT}" \
  --actor-id "${ACTOR_ID}" \
  --evaluation-cases-total 4 > /tmp/eom-standard-item-v9.json

"${EOMCTL}" control-plane bootstrap-knowledge-item \
  --config-directory /home/eom/EOM/config/control-plane/knowledge-grounded-item-v6 \
  --source-commit "${SOURCE_COMMIT}" \
  --actor-id "${ACTOR_ID}" \
  --evaluation-cases-total 4 > /tmp/eom-knowledge-item-v6.json

/srv/eom/conda/envs/eom-api/bin/python -I - \
  /tmp/eom-standard-item-v9.json /tmp/eom-knowledge-item-v6.json <<'PY'
import json
import sys
from pathlib import Path

standard = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
knowledge = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
if standard.get("status") != "SUCCEEDED" or knowledge.get("status") != "SUCCEEDED":
    raise SystemExit("control-policy bootstrap failed")
if knowledge.get("base_preset_revision_id") != standard.get("preset_revision_id"):
    raise SystemExit("knowledge preset did not pin the exact Standard V9 revision")
for value in (standard, knowledge):
    if not str(value.get("preset_revision_id", "")).startswith("execpresetrev_"):
        raise SystemExit("preset revision pointer missing")
    if not str(value.get("preset_policy_sha256", "")).startswith("sha256:"):
        raise SystemExit("preset policy hash missing")
print("exact_slot_control_policy=READY")
PY
```

The two bootstrap output files contain only control-plane IDs and hashes, must remain mode `0600`,
and are not Git artifacts. Exact replay of both commands must return the same two preset revision
IDs. A fresh production request must then pin the returned Knowledge V6 revision/hash in
`generation_block_resolution`; do not resume or reinterpret an older checkpoint. No Workflow
definition import, Content Pack release/activation, plan regeneration, DB migration, or HWPX builder
deployment is part of this successor. Release the runner hold only after these gates and the normal
retirement receipt verification succeed.
