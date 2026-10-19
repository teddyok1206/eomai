from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from eom_catalog_contracts import ApprovedItemKnowledgeSourceV2
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingVectorRowRef
from eom_catalog_contracts.registered_review_profile import RegisteredReviewSourceBasis
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.embedding_incremental_plan import (
    RegisteredEmbeddingRow,
    plan_embedding_delta,
)
from eom_catalog_service.evidence_usage_receipts import OrchestratorEvidenceUsageReceiptResolver
from eom_catalog_service.inference_transfer_item_projection import render_no_solution_item_text
from eom_catalog_service.item_content_contract import canonical_content_team_item_materialization
from eom_catalog_service.models import ItemComponentRecord, ItemRecord, ItemRevisionRecord
from eom_catalog_service.registered_item_review_solution_resolver import (
    RegisteredItemReviewSolutionResolutionError,
    resolve_registered_item_review_solution,
)
from eom_catalog_service.registered_review_embedding_entry import RegisteredReviewEmbeddingEntry
from eom_catalog_service.registered_review_projection import project_registered_review_solution
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.artifacts import stage_structured_artifact
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.evidence_usage_validation import canonical_review_evidence_set_sha256
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_workflow import ArtifactPointer, RoleWorkerInput, WorkerRequest
from eom_workflow.control_plane import (
    AuthoringEvidenceUsageValidationReceiptV2,
    AuthoringEvidenceUsageValidationReceiptV3,
    ReviewEvidenceUsageValidationReceiptV2,
    ReviewEvidenceUsageValidationReceiptV3,
)
from eom_workflow.schemas import validate_role_result
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord

from tests.unit.inference_transfer_embedding_fixtures import (
    PARTITION,
    embedding_space,
    source_binding,
    view_recipe,
)
from tests.unit.inference_transfer_experiment_fixtures import entry as legacy_entry
from tests.unit.test_execution_materializer import _knowledge_fixture
from tests.unit.test_graph_review_v11_protocol import (
    _authoring_result,
    _review_document,
    _upgrade_fixture_plan_to_v12,
    _v12_review_document,
)

NOW = datetime(2026, 10, 19, tzinfo=UTC)
ITEM_ID = "item_" + "1" * 32
ITEM_REVISION = "itemrev_" + "2" * 32
WORKFLOW_ID = "workflow_" + "8" * 32


class _Session:
    """Real ORM rows and public Artifact/receipt adapters; no live database."""

    def __init__(self) -> None:
        self.records: dict[tuple[type[Any], str], Any] = {}
        self.components: list[ItemComponentRecord] = []
        self.steps: list[WorkflowStepRunRecord] = []
        self.events: list[JobEventRecord] = []
        self.new: set[object] = set()
        self.dirty: set[object] = set()
        self.deleted: set[object] = set()
        self.fresh_reads: list[type[Any]] = []

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def get(self, model: type[Any], key: str, **options: Any) -> Any:
        if options.get("populate_existing"):
            self.fresh_reads.append(model)
        return self.records.get((model, key))

    def scalar(self, statement: Any) -> Any:
        model = statement.column_descriptions[0]["entity"]
        return next(value for (kind, _), value in self.records.items() if kind is model)

    def scalars(self, statement: Any) -> tuple[Any, ...]:
        model = statement.column_descriptions[0]["entity"]
        if model in {ItemComponentRecord, WorkflowStepRunRecord}:
            assert statement.get_execution_options()["populate_existing"] is True
        if model is ItemComponentRecord:
            assert statement.compile().params["param_1"] == 101
            return tuple(sorted(self.components, key=lambda row: (row.component_type, row.ordinal)))
        if model is WorkflowStepRunRecord:
            return tuple(row for row in self.steps if row.superseded_by_step_run_id is None)
        if model is JobEventRecord:
            return tuple(self.events)
        return tuple(value for (kind, _), value in self.records.items() if kind is model)


class _Artifacts(CatalogArtifactService):
    def __init__(self, root: Path, session: _Session) -> None:
        self.settings = CatalogSettings(nas_artifact_root=root)
        self.sessions = cast(Any, lambda: session)
        self.reads: list[str] = []

    def load_json_revision(self, **kwargs: Any) -> dict[str, Any]:
        self.reads.append(kwargs["artifact_id"])
        return super().load_json_revision(**kwargs)


def _stage_file_set(
    fixture: dict[str, Any],
    *,
    marker: str,
    name: str,
    kind: str,
    schema: str,
    document: dict[str, Any],
    metadata: bool = True,
) -> tuple[str, str, str]:
    session: _Session = fixture["session"]
    artifact_id, revision_id, job_id = (
        prefix + marker * 32 for prefix in ("artifact_", "rev_", "job_")
    )
    payload = canonical_json_bytes(document)
    root = fixture["root"] / artifact_id / revision_id
    root.mkdir(parents=True)
    (root / name).write_bytes(payload)
    entry: dict[str, Any] = {
        "file_name": name,
        "sha256": sha256_bytes(payload),
        "bytes": len(payload),
    }
    if metadata:
        entry.update(schema_ref=schema, media_type="application/json")
    manifest = {
        "manifest_version": "1.0",
        "job_id": job_id,
        "logical_artifact_id": artifact_id,
        "revision_id": revision_id,
        "artifact_type": kind,
        "primary_file": name,
        "content_hash": sha256_bytes(payload),
        "content_bytes": len(payload),
        "files": [entry],
    }
    session.records[ArtifactRecord, artifact_id] = ArtifactRecord(
        logical_artifact_id=artifact_id, job_id=job_id, artifact_type=kind, approved=True
    )
    session.records[ArtifactRevisionRecord, revision_id] = ArtifactRevisionRecord(
        revision_id=revision_id,
        logical_artifact_id=artifact_id,
        job_id=job_id,
        content_hash=sha256_bytes(payload),
        content_bytes=len(payload),
        manifest_hash=content_sha256(manifest),
        manifest=manifest,
        result=document,
        nas_path=str(root),
        approved=True,
    )
    session.records[JobRecord, job_id] = JobRecord(
        job_id=job_id,
        protocol_version="fixture/1.0",
        idempotency_key=marker,
        request_hash="sha256:" + "0" * 64,
        request={},
        task_type=kind,
        status="SUCCEEDED",
        logical_artifact_id=artifact_id,
        revision_id=revision_id,
        completed_at=NOW,
    )
    return artifact_id, revision_id, sha256_bytes(payload)


def _persist_role(
    fixture: dict[str, Any], key: str, raw: dict[str, Any], upstream: tuple[ArtifactPointer, ...]
) -> ArtifactPointer:
    session: _Session = fixture["session"]
    role = "item_management" if key == "registration" else key
    schema = f"{key}-result@{fixture['family']}.0"
    raw = {
        "schema_version": "1.0",
        "status": "ok",
        **raw,
        "artifact": {
            "file_name": "result.json",
            "media_type": "application/json",
            **raw["artifact"],
        },
    }
    result = validate_role_result(raw, role, schema)
    raw = result.model_dump(mode="json")
    payload = canonical_json_bytes(raw)
    pointer = ArtifactPointer(
        step_key=key,
        attempt=1,
        job_id=result.job_id,
        logical_artifact_id=result.artifact.logical_artifact_id,
        revision_id=result.artifact.revision_id,
        content_hash=sha256_bytes(payload),
        result_schema=schema,
    )
    root = fixture["root"] / pointer.logical_artifact_id / pointer.revision_id
    staged = stage_structured_artifact(
        result=raw,
        job_id=pointer.job_id,
        logical_artifact_id=pointer.logical_artifact_id,
        revision_id=pointer.revision_id,
        staging=root,
        worker_slot="01",
        created_at=fixture["manifest_at"],
    )
    manifest = staged.manifest.model_dump(mode="json")
    worker = RoleWorkerInput.model_validate(
        {
            "protocol_version": fixture["protocol"],
            "job_id": pointer.job_id,
            "workflow_id": WORKFLOW_ID,
            "step_run_id": result.step_run_id,
            "attempt": 1,
            "role": role,
            "request": WorkerRequest(
                request_name="GENERATED_KNOWLEDGE_ITEM_REQUEST", image_mode="skip"
            ),
            "upstream_artifacts": upstream,
            "artifact": result.artifact,
        }
    )
    job = JobRecord(
        job_id=pointer.job_id,
        protocol_version=fixture["protocol"],
        idempotency_key=key,
        request_hash=content_sha256(
            {
                "protocol_version": fixture["protocol"],
                "task_type": f"workflow_{role}",
                "request": worker.model_dump(mode="json"),
            }
        ),
        request=worker.model_dump(mode="json"),
        task_type=f"workflow_{role}",
        status="SUCCEEDED",
        logical_artifact_id=pointer.logical_artifact_id,
        revision_id=pointer.revision_id,
        completed_at=NOW,
        worker_slot_id="01",
    )
    session.records[JobRecord, pointer.job_id] = job
    session.records[ArtifactRecord, pointer.logical_artifact_id] = ArtifactRecord(
        logical_artifact_id=pointer.logical_artifact_id,
        job_id=pointer.job_id,
        artifact_type=f"workflow_{role}",
        approved=True,
    )
    session.records[ArtifactRevisionRecord, pointer.revision_id] = ArtifactRevisionRecord(
        revision_id=pointer.revision_id,
        logical_artifact_id=pointer.logical_artifact_id,
        job_id=pointer.job_id,
        content_hash=pointer.content_hash,
        content_bytes=len(payload),
        manifest_hash=staged.manifest_hash,
        manifest=manifest,
        result=raw,
        nas_path=str(root),
        approved=True,
    )
    step = WorkflowStepRunRecord(
        step_run_id=result.step_run_id,
        workflow_id=WORKFLOW_ID,
        step_key=key,
        step_type="agent",
        worker_role=role,
        result_schema=schema,
        attempt=1,
        state="SUCCEEDED",
        platform_job_id=pointer.job_id,
        superseded_by_step_run_id=None,
        input_pointer_manifest={
            "upstream_artifacts": [p.model_dump(mode="json") for p in upstream]
        },
        output_pointer_manifest=pointer.model_dump(mode="json"),
    )
    session.steps.append(step)
    component = ItemComponentRecord(
        item_revision_id=ITEM_REVISION,
        component_type={
            "authoring": "UPPER_STEM",
            "review": "REVIEW_REPORT",
            "registration": "METADATA",
        }[key],
        ordinal=0,
        schema_ref=schema,
        media_type="application/json",
        artifact_id=pointer.logical_artifact_id,
        artifact_revision_id=pointer.revision_id,
        sha256=pointer.content_hash,
        logical_name=f"{key}-result",
        required=True,
        metadata_json={},
    )
    session.components.append(component)
    fixture[key] = result
    fixture[key + "_pointer"] = pointer
    fixture[key + "_step"] = step
    return pointer


def _fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    family: int = 11,
    microseconds: int = 0,
) -> dict[str, Any]:
    (tmp_path / "knowledge").mkdir()
    knowledge = _knowledge_fixture(
        tmp_path / "knowledge",
        monkeypatch,
        manifest_schema_version="5.0",
        workflow_definition_version="1.11.0",
    )
    if family == 12:
        _upgrade_fixture_plan_to_v12(knowledge)
    plan = knowledge["session"].records[ResolvedExecutionPlanRecord, str(knowledge["plan_id"])]
    document = deepcopy(plan.canonical_document)
    document["workflow_id"] = WORKFLOW_ID
    document["plan_sha256"] = content_sha256(
        {k: v for k, v in document.items() if k != "plan_sha256"}
    )
    plan = ResolvedExecutionPlanRecord(
        **{
            field: document[field]
            for field in (
                "plan_id",
                "workflow_id",
                "preset_id",
                "preset_revision_id",
                "capacity_policy_revision_id",
                "evidence_bundle_revision_id",
                "plan_sha256",
                "resolver_version",
            )
        },
        graph_snapshot_revision_id=document["graph_snapshot"]["graph_snapshot_revision_id"],
        canonical_document=document,
        resolved_at=datetime.fromisoformat(document["resolved_at"].replace("Z", "+00:00")),
    )
    session = _Session()
    session.records[ResolvedExecutionPlanRecord, plan.plan_id] = plan
    fixture: dict[str, Any] = {
        "session": session,
        "root": tmp_path / "artifacts",
        "family": family,
        "manifest_at": NOW.replace(microsecond=microseconds),
        "graph_snapshot": document["graph_snapshot"],
        "protocol": "workflow-role/1.24.0" if family == 12 else "workflow-role/1.23.0",
    }
    authoring = _authoring_result(knowledge).model_dump(mode="json")
    authoring["protocol_version"] = fixture["protocol"]
    authoring_pointer = _persist_role(fixture, "authoring", authoring, ())
    review = _v12_review_document(knowledge) if family == 12 else _review_document(knowledge)
    review["output"]["evidence_usage_attestation"]["authoring_artifact"] = {
        "logical_artifact_id": authoring_pointer.logical_artifact_id,
        "revision_id": authoring_pointer.revision_id,
        "content_hash": authoring_pointer.content_hash,
        "result_schema": authoring_pointer.result_schema,
    }
    review_pointer = _persist_role(fixture, "review", review, (authoring_pointer,))
    _persist_role(
        fixture,
        "registration",
        {
            "protocol_version": fixture["protocol"],
            "job_id": "job_" + "9" * 32,
            "workflow_id": WORKFLOW_ID,
            "step_run_id": "steprun_" + "9" * 32,
            "role": "item_management",
            "artifact": {
                "logical_artifact_id": "artifact_" + "9" * 32,
                "revision_id": "rev_" + "9" * 32,
            },
            "completed_at": NOW.isoformat(),
            "output": {
                "registration": {
                    "result": "ready_for_registration",
                    "summary": "The exact reviewed draft is ready.",
                }
            },
        },
        (authoring_pointer, review_pointer),
    )
    common = {
        field: document[field]
        for field in (
            "plan_id",
            "plan_sha256",
            "evidence_bundle_id",
            "evidence_bundle_revision_id",
            "retrieval_request_id",
            "retrieval_request_sha256",
            "evidence_manifest_artifact",
            "evidence_manifest_sha256",
            "evidence_context_artifact",
        )
    }
    common.update(
        schema_version=f"evidence-usage-validation-receipt/{3 if family == 12 else 2}.0",
        graph_snapshot_revision_id=document["graph_snapshot"]["graph_snapshot_revision_id"],
        graph_snapshot_sha256=document["graph_snapshot"]["manifest_sha256"],
    )
    authoring_ref = {
        field: getattr(authoring_pointer, field)
        for field in ("logical_artifact_id", "revision_id", "content_hash", "result_schema")
    }
    citation_sha = content_sha256(
        {
            "schema_version": "evidence-citation-set/1.0",
            "citations": fixture["authoring"].output.evidence_usage.model_dump(mode="json")[
                "citations"
            ],
        }
    )
    for key, pointer, model in (
        (
            "authoring",
            authoring_pointer,
            AuthoringEvidenceUsageValidationReceiptV3
            if family == 12
            else AuthoringEvidenceUsageValidationReceiptV2,
        ),
        (
            "review",
            review_pointer,
            ReviewEvidenceUsageValidationReceiptV3
            if family == 12
            else ReviewEvidenceUsageValidationReceiptV2,
        ),
    ):
        value = {
            **common,
            "step_key": key,
            "result_artifact": {
                field: getattr(pointer, field)
                for field in ("logical_artifact_id", "revision_id", "content_hash", "result_schema")
            },
            "authoring_citation_set_sha256": citation_sha,
        }
        if key == "review":
            value.update(
                authoring_artifact=authoring_ref,
                review_citation_set_sha256=citation_sha,
                citation_sets_equal=True,
                independent_review_report_sha256=content_sha256(
                    fixture["review"].output.independent_review_report
                ),
                review_evidence_set_sha256=canonical_review_evidence_set_sha256(fixture["review"]),
            )
        receipt = model.model_validate({**value, "receipt_sha256": content_sha256(value)})
        fixture[key + "_receipt"] = receipt
        next(
            c for c in session.components if c.artifact_id == pointer.logical_artifact_id
        ).metadata_json = {"evidence_usage_validation_receipt_sha256": receipt.receipt_sha256}
        session.events.append(
            JobEventRecord(
                job_id=pointer.job_id,
                sequence=1,
                from_state="COMMITTING",
                to_state="SUCCEEDED",
                event="ARTIFACT_COMMITTED",
                data={
                    "logical_artifact_id": pointer.logical_artifact_id,
                    "revision_id": pointer.revision_id,
                    "content_hash": pointer.content_hash,
                    "evidence_usage_validation_receipt": receipt.model_dump(mode="json"),
                },
            )
        )
    content = canonical_content_team_item_materialization(fixture["authoring"].output.draft)
    content_id, content_rev, content_sha = _stage_file_set(
        fixture,
        marker="a",
        name="assessment-item-content.json",
        kind="assessment-item-content",
        schema="eom.assessment.item-content/3.0",
        document=content.model_dump(mode="json"),
    )
    session.components.append(
        ItemComponentRecord(
            item_revision_id=ITEM_REVISION,
            component_type="ITEM_CONTENT",
            ordinal=0,
            schema_ref="eom.assessment.item-content/3.0",
            media_type="application/json",
            artifact_id=content_id,
            artifact_revision_id=content_rev,
            sha256=content_sha,
            logical_name="assessment-item-content.json",
            required=True,
            metadata_json={"authoring_artifact_revision_id": authoring_pointer.revision_id},
        )
    )
    manifest = {
        "schema_version": "1.0",
        "item_id": ITEM_ID,
        "item_revision_id": ITEM_REVISION,
        "revision_number": 1,
        "content_pack": {
            "release_id": "packrel_" + "1" * 32,
            "pack_key": "generated-knowledge-item",
            "version": "1.17.0",
            "sha256": "sha256:" + "1" * 64,
        },
        "source_intake": {"batch_ids": []},
        "workflow": {
            "workflow_id": WORKFLOW_ID,
            "definition_key": "generic-item-development",
            "definition_version": document["workflow_definition_version"],
        },
        "components": [
            {
                field: getattr(c, field)
                for field in (
                    "component_type",
                    "ordinal",
                    "schema_ref",
                    "media_type",
                    "artifact_id",
                    "artifact_revision_id",
                    "sha256",
                    "logical_name",
                    "required",
                )
            }
            for c in sorted(session.components, key=lambda c: (c.component_type, c.ordinal))
        ],
        "metadata": {
            "schema_ref": "eom://metadata/content-team-item@1.0",
            "sha256": content_sha256({}),
        },
        "provenance": [],
        "created_at": NOW.isoformat(),
    }
    manifest_id, manifest_rev, manifest_sha = _stage_file_set(
        fixture,
        marker="b",
        name="item-revision-manifest.json",
        kind="item-revision-manifest",
        schema="eom://schemas/item-registry/item-revision-manifest-v1",
        document=manifest,
        metadata=False,
    )
    session.records[ItemRecord, ITEM_ID] = ItemRecord(
        item_id=ITEM_ID, lifecycle_state="ACTIVE", current_revision_id=ITEM_REVISION
    )
    session.records[ItemRevisionRecord, ITEM_REVISION] = ItemRevisionRecord(
        item_id=ITEM_ID,
        item_revision_id=ITEM_REVISION,
        revision_number=1,
        revision_state="APPROVED",
        workflow_id=WORKFLOW_ID,
        workflow_definition_version=document["workflow_definition_version"],
        content_pack_release_id="packrel_" + "1" * 32,
        source_workflow_step_run_id=fixture["registration_step"].step_run_id,
        manifest_artifact_id=manifest_id,
        manifest_artifact_revision_id=manifest_rev,
        manifest_sha256=manifest_sha,
        metadata_json={},
        metadata_sha256=content_sha256({}),
        approved_at=NOW,
        approved_by="operator",
    )
    session.records[WorkflowInstanceRecord, WORKFLOW_ID] = WorkflowInstanceRecord(
        workflow_id=WORKFLOW_ID,
        definition_key="generic-item-development",
        definition_version=document["workflow_definition_version"],
        role_schema_version=fixture["protocol"],
        state="COMPLETED",
    )
    fixture.update(
        content=content,
        manifest=manifest,
        artifacts=_Artifacts(fixture["root"], session),
        receipts=OrchestratorEvidenceUsageReceiptResolver(cast(Any, lambda: session)),
        auth=[],
    )
    fixture["source"] = ApprovedItemKnowledgeSourceV2.model_validate(
        {
            "source_class": "APPROVED_ITEM",
            "item_id": ITEM_ID,
            "item_revision_id": ITEM_REVISION,
            "artifact_member": {
                "artifact_id": content_id,
                "artifact_revision_id": content_rev,
                "member_path": "assessment-item-content.json",
                "materialized_path": "source/item-content.json",
                "sha256": content_sha,
                "bytes": len(canonical_json_bytes(content)),
                "schema_ref": "eom.assessment.item-content/3.0",
                "media_type": "application/json",
                "logical_name": "item-content.json",
            },
        }
    )
    return fixture


def _resolve(fixture: dict[str, Any]) -> Any:
    return resolve_registered_item_review_solution(
        cast(Any, fixture["session"]),
        source=fixture["source"],
        artifacts=fixture["artifacts"],
        receipts=fixture["receipts"],
        authorize_source=fixture["auth"].append,
    )


@pytest.mark.parametrize("family", [11, 12])
@pytest.mark.parametrize("microseconds", [0, 123456])
def test_real_role_files_and_public_receipt_owner_resolve_exact_registered_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    family: int,
    microseconds: int,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch, family=family, microseconds=microseconds)
    result = _resolve(fixture)
    assert result.evidence.evidence_kind == "REGISTERED_ITEM_REVIEW_SOLUTION"
    assert result.evidence.review.artifact.sha256 == fixture["review_pointer"].content_hash
    assert result.report == fixture["review"].output.independent_review_report
    assert result.draft == fixture["authoring"].output.draft
    assert result.report is result.review.output.independent_review_report
    assert result.draft is result.authoring.output.draft
    assert result.review_completed_at == fixture["review"].completed_at
    assert fixture["artifacts"].reads == [
        fixture[key + "_pointer"].logical_artifact_id
        for key in ("authoring", "review", "registration")
    ]
    assert fixture["auth"] == [fixture["source"], fixture["source"]]
    assert ItemRevisionRecord in fixture["session"].fresh_reads
    assert _resolve(fixture).evidence == result.evidence


@pytest.mark.parametrize("family", [11, 12])
def test_resolved_envelopes_compose_into_delta_and_replay_without_second_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, family: int
) -> None:
    fixture = _fixture(tmp_path, monkeypatch, family=family)
    resolved = _resolve(fixture)
    artifact_reads = tuple(fixture["artifacts"].reads)

    def no_io(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("pure registered-review composition reread Artifact/database")

    for method in ("get", "scalar", "scalars"):
        monkeypatch.setattr(fixture["session"], method, no_io)
    monkeypatch.setattr(fixture["artifacts"], "load_json_revision", no_io)
    monkeypatch.setattr(
        "eom_catalog_service.registered_item_review_solution_resolver.resolve_pinned_artifact_member",
        no_io,
    )
    profile = project_registered_review_solution(
        source_basis=RegisteredReviewSourceBasis(
            source=resolved.evidence.source,
            graph_snapshot=fixture["graph_snapshot"],
            review_evidence=resolved.evidence,
        ),
        authoring=resolved.authoring,
        review=resolved.review,
        created_at=resolved.review_completed_at,
    )
    content = render_no_solution_item_text(
        item=canonical_content_team_item_materialization(resolved.draft),
        original_source=resolved.evidence.source.artifact_member,
        recipe=view_recipe(),
    )
    entry = RegisteredReviewEmbeddingEntry(profile=profile, content=content)
    space = embedding_space()
    plan = plan_embedding_delta(
        (entry,),
        space=space,
        storage_partition=PARTITION,
        views=("CONTENT_ONLY", "CONCRETE_FACETS"),
    )
    assert {demand.view for demand in plan.demands} == {"CONTENT_ONLY", "CONCRETE_FACETS"}
    assert len(plan.new_inputs) == 2
    # Pure planned row references are not a claim of actual model execution/publication.
    shard = source_binding(legacy_entry("a")).row_ref.shard_manifest
    rows = tuple(
        RegisteredEmbeddingRow(
            row.encoding,
            EmbeddingVectorRowRef(
                shard_manifest=shard, row_index=index, encoding_sha256=row.encoding.encoding_sha256
            ),
        )
        for index, row in enumerate(plan.new_inputs)
    )
    replay = plan_embedding_delta(
        (entry,),
        space=space,
        storage_partition=PARTITION,
        registered_rows=rows,
        views=("CONTENT_ONLY", "CONCRETE_FACETS"),
    )
    assert replay.demands == plan.demands
    assert replay.new_inputs == () and len(replay.reusable_rows) == 2
    assert replay.unavailable_views == ()
    assert tuple(fixture["artifacts"].reads) == artifact_reads


@pytest.mark.parametrize(
    "case", ["missing", "unapproved", "retired", "stale", "cross_item", "metadata"]
)
def test_current_source_failures_stop_before_any_role_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    session = fixture["session"]
    revision = session.records[ItemRevisionRecord, ITEM_REVISION]
    if case == "missing":
        del session.records[ItemRevisionRecord, ITEM_REVISION]
    elif case == "unapproved":
        revision.revision_state = "IN_REVIEW"
    elif case == "retired":
        session.records[ItemRecord, ITEM_ID].lifecycle_state = "RETIRED"
    elif case == "stale":
        session.records[ItemRecord, ITEM_ID].current_revision_id = "itemrev_" + "f" * 32
    elif case == "cross_item":
        revision.item_id = "item_" + "f" * 32
    else:
        revision.metadata_json = {"changed": True}
    with pytest.raises(RegisteredItemReviewSolutionResolutionError, match="SOURCE_INELIGIBLE"):
        _resolve(fixture)
    assert fixture["artifacts"].reads == []


@pytest.mark.parametrize(
    "case",
    [
        "source_hash",
        "component_hash",
        "component_schema",
        "duplicate_component",
        "manifest_tamper",
        "manifest_component",
        "registration_step",
        "duplicate_final",
        "failed_job",
        "revoked_artifact",
        "job_request",
        "role_bytes",
        "db_result",
        "review_input",
        "registration_input",
        "content_origin",
        "missing_receipt",
        "receipt_hash",
        "receipt_event_duplicate",
    ],
)
def test_exact_registered_closure_rejects_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    session = fixture["session"]
    pointer = fixture["review_pointer"]
    component = next(c for c in session.components if c.component_type == "REVIEW_REPORT")
    if case == "source_hash":
        fixture["source"] = fixture["source"].model_copy(
            update={
                "artifact_member": fixture["source"].artifact_member.model_copy(
                    update={"sha256": "sha256:" + "f" * 64}
                )
            }
        )
    elif case == "component_hash":
        component.sha256 = "sha256:" + "f" * 64
    elif case == "component_schema":
        component.schema_ref = "review-result@10.0"
    elif case == "duplicate_component":
        session.components.append(component)
    elif case == "manifest_tamper":
        rev = session.records[ItemRevisionRecord, ITEM_REVISION]
        root = Path(
            session.records[ArtifactRevisionRecord, rev.manifest_artifact_revision_id].nas_path
        )
        (root / "item-revision-manifest.json").write_bytes(b"{}")
    elif case == "manifest_component":
        component.required = False
    elif case == "registration_step":
        session.records[ItemRevisionRecord, ITEM_REVISION].source_workflow_step_run_id = (
            "steprun_" + "f" * 32
        )
    elif case == "duplicate_final":
        session.steps.append(fixture["review_step"])
    elif case == "failed_job":
        session.records[JobRecord, pointer.job_id].status = "FAILED"
    elif case == "revoked_artifact":
        session.records[ArtifactRecord, pointer.logical_artifact_id].approved = False
    elif case == "job_request":
        session.records[JobRecord, pointer.job_id].request["workflow_id"] = "workflow_" + "f" * 32
    elif case == "role_bytes":
        root = Path(session.records[ArtifactRevisionRecord, pointer.revision_id].nas_path)
        (root / "result.json").write_bytes(b"{}")
    elif case == "db_result":
        session.records[ArtifactRevisionRecord, pointer.revision_id].result = {}
    elif case == "review_input":
        fixture["review_step"].input_pointer_manifest["upstream_artifacts"] = []
    elif case == "registration_input":
        fixture["registration_step"].input_pointer_manifest["upstream_artifacts"] = []
    elif case == "content_origin":
        next(c for c in session.components if c.component_type == "ITEM_CONTENT").metadata_json = {}
    elif case == "missing_receipt":
        component.metadata_json = {}
    elif case == "receipt_hash":
        component.metadata_json["evidence_usage_validation_receipt_sha256"] = "sha256:" + "f" * 64
    else:
        session.events.append(session.events[-1])
    with pytest.raises(RegisteredItemReviewSolutionResolutionError):
        _resolve(fixture)


def test_denied_actual_source_authorization_performs_no_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)

    def deny(_source: ApprovedItemKnowledgeSourceV2) -> None:
        raise PermissionError("actual source denied")

    with pytest.raises(PermissionError, match="actual source denied"):
        resolve_registered_item_review_solution(
            cast(Any, fixture["session"]),
            source=fixture["source"],
            artifacts=fixture["artifacts"],
            receipts=fixture["receipts"],
            authorize_source=deny,
        )
    assert fixture["session"].fresh_reads == []
    assert fixture["artifacts"].reads == []


def test_late_authorization_denial_does_not_return_materialized_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    calls: list[ApprovedItemKnowledgeSourceV2] = []

    def authorize(source: ApprovedItemKnowledgeSourceV2) -> None:
        calls.append(source)
        if len(calls) == 2:
            raise PermissionError("source revoked")

    with pytest.raises(PermissionError, match="source revoked"):
        resolve_registered_item_review_solution(
            cast(Any, fixture["session"]),
            source=fixture["source"],
            artifacts=fixture["artifacts"],
            receipts=fixture["receipts"],
            authorize_source=authorize,
        )
    assert len(calls) == 2


def test_past_exam_cannot_be_relabelled_as_registered_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    fixture["source"] = fixture["source"].model_copy(update={"source_class": "PAST_EXAM"})
    with pytest.raises(RegisteredItemReviewSolutionResolutionError, match="SOURCE_INVALID"):
        _resolve(fixture)
    assert fixture["auth"] == []


def test_pending_session_mutation_is_not_silently_refreshed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    fixture["session"].dirty.add(object())
    with pytest.raises(RegisteredItemReviewSolutionResolutionError, match="PENDING_MUTATION"):
        _resolve(fixture)
    assert fixture["session"].fresh_reads == []


def _rewrite_file_set(fixture: dict[str, Any], revision_id: str, document: dict[str, Any]) -> str:
    """Keep all storage hashes consistent so semantic closure, not a hash typo, rejects."""
    revision = fixture["session"].records[ArtifactRevisionRecord, revision_id]
    payload = canonical_json_bytes(document)
    manifest = deepcopy(revision.manifest)
    primary = manifest["primary_file"]
    digest = sha256_bytes(payload)
    (Path(revision.nas_path) / primary).write_bytes(payload)
    manifest["content_hash"] = digest
    manifest["content_bytes"] = len(payload)
    manifest["files"][0].update(sha256=digest, bytes=len(payload))
    revision.manifest = manifest
    revision.manifest_hash = content_sha256(manifest)
    revision.content_hash = digest
    revision.content_bytes = len(payload)
    revision.result = document
    return digest


def test_hash_consistent_other_registered_content_is_not_the_reviewed_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    session = fixture["session"]
    component = next(c for c in session.components if c.component_type == "ITEM_CONTENT")
    document = fixture["content"].model_dump(mode="json")
    document["stem"] += " 추가된 조건이다."
    component.sha256 = _rewrite_file_set(fixture, component.artifact_revision_id, document)
    source = fixture["source"].model_dump(mode="json")
    source["artifact_member"].update(
        sha256=component.sha256, bytes=len(canonical_json_bytes(document))
    )
    fixture["source"] = ApprovedItemKnowledgeSourceV2.model_validate(source)
    registered = deepcopy(fixture["manifest"])
    next(c for c in registered["components"] if c["component_type"] == "ITEM_CONTENT")["sha256"] = (
        component.sha256
    )
    revision = session.records[ItemRevisionRecord, ITEM_REVISION]
    revision.manifest_sha256 = _rewrite_file_set(
        fixture, revision.manifest_artifact_revision_id, registered
    )

    with pytest.raises(
        RegisteredItemReviewSolutionResolutionError, match="MATERIALIZATION_INVALID"
    ):
        _resolve(fixture)


def test_old_review_without_independent_report_is_explicitly_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    fixture["session"].records[
        WorkflowInstanceRecord, WORKFLOW_ID
    ].role_schema_version = "workflow-role/1.20.0"
    with pytest.raises(RegisteredItemReviewSolutionResolutionError, match="REVIEW_UNAVAILABLE"):
        _resolve(fixture)
    assert fixture["artifacts"].reads == []


def test_role_manifest_requires_the_exact_typed_producer_hash_not_an_alternate_encoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch, microseconds=0)
    revision = fixture["session"].records[
        ArtifactRevisionRecord, fixture["authoring_pointer"].revision_id
    ]
    dictionary_hash = content_sha256(revision.manifest)
    assert dictionary_hash != revision.manifest_hash
    revision.manifest_hash = dictionary_hash
    with pytest.raises(
        RegisteredItemReviewSolutionResolutionError, match="ROLE_PROVENANCE_INVALID"
    ):
        _resolve(fixture)


@pytest.mark.parametrize("nested", [False, True])
def test_copied_source_undeclared_fields_are_rejected_before_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nested: bool
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    source = fixture["source"]
    fixture["source"] = (
        source.model_copy(
            update={
                "artifact_member": source.artifact_member.model_copy(
                    update={"unknown": "not authority"}
                )
            }
        )
        if nested
        else source.model_copy(update={"unknown": "not authority"})
    )
    with pytest.raises(ValueError, match="undeclared fields"):
        _resolve(fixture)
    assert fixture["auth"] == []
    assert fixture["session"].fresh_reads == []
