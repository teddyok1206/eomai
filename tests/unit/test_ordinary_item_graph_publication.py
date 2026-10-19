"""Synthetic source-only publication contracts/fences; no database or model runs."""

from __future__ import annotations

import json
from contextlib import nullcontext
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, Mock, patch

import pytest
from eom_catalog_contracts.knowledge import KnowledgeArtifactMemberPointer
from eom_catalog_contracts.ordinary_item_graph_publication import (
    OrdinaryItemGraphPublicationResult,
    PublishOrdinaryApprovedItemAnalysesCommand,
)
from eom_catalog_contracts.validation import load_schema, validate_contract
from eom_catalog_service.curriculum_graph_structure import integrated_science_curriculum_units
from eom_catalog_service.knowledge_graph_projection import AcceptedAnalysisProposal
from eom_catalog_service.knowledge_graph_publication_service import (
    CurrentKnowledgeGraphStructure,
    KnowledgeGraphPublicationError,
    KnowledgeGraphPublicationService,
)
from eom_catalog_service.models import ItemRecord, ItemRevisionRecord
from eom_catalog_service.ordinary_item_graph_publication_service import (
    _REQUIRED_PERMISSIONS,
    OrdinaryItemGraphPublicationError,
    OrdinaryItemGraphPublicationService,
)
from eom_identifiers import content_sha256
from eom_identity_service.operator_authorization_fence import OperatorAuthorizationFence
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_workflow import WorkflowRequest
from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
)
from eom_workflow_runner.repository import workflow_business_fingerprint
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from tests.unit.registered_review_fixtures import registered_review_case
from tests.unit.test_execution_materializer import _knowledge_fixture
from tests.unit.test_graph_review_v11_protocol import _upgrade_fixture_plan_to_v12

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 19, tzinfo=UTC)
RUN = "analysisrun_" + "7" * 32
UNIT = next(row for row in integrated_science_curriculum_units() if row.unit_level == "MINOR")


def _command_value() -> dict[str, Any]:
    case = registered_review_case()
    value = {
        "operation": "PUBLISH_ORDINARY_APPROVED_ITEM_ANALYSES",
        "schema_version": "ordinary-item-graph-publication-command/1.0",
        "corpus_key": "integrated-science-textbooks",
        "sources": [
            {
                "analysis_run_id": RUN,
                "source": case.basis.source.model_dump(mode="json"),
                "accepted_result": KnowledgeArtifactMemberPointer(
                    artifact_id="artifact_" + "7" * 32,
                    artifact_revision_id="rev_" + "7" * 32,
                    sha256="sha256:" + "7" * 64,
                    schema_ref="eom://schemas/knowledge/knowledge-analysis-result/2.0",
                    media_type="application/json",
                    logical_name="accepted-result.json",
                    member_path="evidence/accepted-result.json",
                ).model_dump(mode="json"),
                "workflow_id": case.basis.review_evidence.workflow_id,
                "expected_curriculum_unit_key": UNIT.unit_key,
                "expected_plan_sha256": "sha256:" + "8" * 64,
                "review_evidence_sha256": case.basis.review_evidence.evidence_sha256,
            }
        ],
        "expected_graph_snapshot": case.basis.graph_snapshot.model_dump(mode="json"),
        "expected_graph_snapshot_sha256": "sha256:" + "9" * 64,
        "access_policy_revision_id": "accessrev_" + "1" * 32,
        "access_policy_sha256": "sha256:" + "1" * 64,
        "requested_by_operator_id": "operator_" + "1" * 32,
        "authorized_at": NOW.isoformat().replace("+00:00", "Z"),
        "idempotency_key": "ordinary-source-publication-01",
    }
    return _rehash(value)


def _rehash(value: dict[str, Any]) -> dict[str, Any]:
    value["submission_sha256"] = content_sha256(
        {
            key: item
            for key, item in value.items()
            if key not in {"idempotency_key", "submission_sha256"}
        }
    )
    return value


def _command() -> PublishOrdinaryApprovedItemAnalysesCommand:
    return PublishOrdinaryApprovedItemAnalysesCommand.model_validate(_command_value())


def test_publisher_requires_explicit_identity_fence_no_owner_inference() -> None:
    with pytest.raises(TypeError, match="identity_fence"):
        OrdinaryItemGraphPublicationService(cast(Any, Mock()), publication=Mock(), retrieval=Mock())


def test_identity_fence_denial_precedes_iam_reads_and_materialization() -> None:
    service = object.__new__(OrdinaryItemGraphPublicationService)
    service.identity_fence = Mock(spec=OperatorAuthorizationFence)
    service.identity_fence.fence_current_operator.side_effect = ValueError(
        "OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"
    )
    service.retrieval = Mock()
    session = Mock(spec=Session)
    session.scalar.side_effect = AssertionError("IAM_READ_BEFORE_IDENTITY_FENCE")
    with pytest.raises(ValueError, match="OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"):
        service._authorize(session, _command())
    service.identity_fence.fence_current_operator.assert_called_once_with(
        session, _command().requested_by_operator_id
    )
    session.scalar.assert_not_called()
    session.scalars.assert_not_called()
    service.retrieval.resolve_access_policy.assert_not_called()


@pytest.mark.parametrize("fence", (None, object()))
def test_missing_or_nonfence_value_is_not_a_noop_authority(fence: object) -> None:
    with pytest.raises(OrdinaryItemGraphPublicationError, match="IDENTITY_FENCE_UNAVAILABLE"):
        OrdinaryItemGraphPublicationService(
            cast(Any, Mock()),
            identity_fence=cast(Any, fence),
            publication=Mock(),
            retrieval=Mock(),
        )


@pytest.mark.parametrize("entry", ("initial", "preliminary_callback"))
def test_publication_entries_open_actual_session_root_before_fence(entry: str) -> None:
    seen = []

    class DenyingFence:
        def fence_current_operator(self, session: Session, operator_id: str) -> None:
            root = session.get_transaction()
            assert root is not None and root.is_active
            assert operator_id == _command().requested_by_operator_id
            seen.append(session)
            raise ValueError("OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN")

    engine = create_engine("sqlite://")
    publication = Mock()
    try:
        service = OrdinaryItemGraphPublicationService(
            engine, identity_fence=DenyingFence(), publication=publication, retrieval=Mock()
        )
        with pytest.raises(ValueError, match="OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"):
            if entry == "initial":
                service.publish(_command())
            else:
                with service.sessions() as session:
                    service._validate_current(session, _command(), ())
        assert len(seen) == 1 and seen[0].get_transaction() is None
        publication.resolve_accepted_analyses.assert_not_called()
    finally:
        engine.dispose()


@pytest.mark.parametrize("denial", (None, "state", "hash", "pointer"))
def test_append_only_graph_snapshot_retains_exact_state_hash_and_pointer_checks(
    denial: str | None,
) -> None:
    command = _command()
    snapshot = SimpleNamespace(
        state="PUBLISHED", snapshot_sha256=command.expected_graph_snapshot_sha256
    )
    if denial == "state":
        snapshot.state = "DRAFT"
    if denial == "hash":
        snapshot.snapshot_sha256 = "sha256:" + "0" * 64
    service = object.__new__(OrdinaryItemGraphPublicationService)
    service.retrieval = Mock()
    service.retrieval.resolve_snapshot_pointer.return_value = (
        None if denial == "pointer" else command.expected_graph_snapshot
    )
    session = Mock(spec=Session)
    session.scalar.return_value = snapshot
    if denial is None:
        assert service._validate_pinned_base(session, command) is snapshot
    else:
        with pytest.raises(OrdinaryItemGraphPublicationError, match="BASE_POINTER_INVALID"):
            service._validate_pinned_base(session, command)
    statement = session.scalar.call_args.args[0]
    assert "FOR SHARE" not in str(statement.compile(dialect=postgresql.dialect()))
    assert statement.get_execution_options()["populate_existing"] is True


@pytest.mark.parametrize("kind", ["command", "result"])
def test_schema_2020_12_and_installed_resource_exact(kind: str) -> None:
    relative = f"knowledge/ordinary-item-graph-publication-{kind}-v1.schema.json"
    raw = (ROOT / "schemas" / relative).read_bytes()
    assert (
        raw
        == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources" / relative
        ).read_bytes()
    )
    schema = json.loads(raw)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)
    assert load_schema(f"ordinary-item-graph-publication-{kind}") == schema


def test_command_schema_distinguishes_raw_graph_and_semantic_hash() -> None:
    command = _command()
    validate_contract("ordinary-item-graph-publication-command", command.model_dump(mode="json"))
    assert command.expected_graph_snapshot_sha256 != command.expected_graph_snapshot.manifest_sha256


@pytest.mark.parametrize(
    "mutation", ["hash", "duplicate", "source_class", "accepted_family", "extra"]
)
def test_closed_command_rejects_forged_selection(mutation: str) -> None:
    value = _command_value()
    if mutation == "hash":
        value["access_policy_sha256"] = "sha256:" + "2" * 64
    elif mutation == "duplicate":
        value["sources"] *= 2
    elif mutation == "source_class":
        value["sources"][0]["source"]["source_class"] = "PAST_EXAM"
    elif mutation == "accepted_family":
        value["sources"][0]["accepted_result"]["schema_ref"] = (
            "eom://schemas/knowledge/knowledge-analysis-result/10.0"
        )
    else:
        value["sources"][0]["trusted_admin"] = True
    with pytest.raises(ValidationError):
        PublishOrdinaryApprovedItemAnalysesCommand.model_validate(
            value if mutation == "hash" else _rehash(value)
        )


def test_model_copy_extra_is_not_erased_by_application_boundary() -> None:
    command = _command().model_copy(update={"trusted_admin": True})
    service = object.__new__(OrdinaryItemGraphPublicationService)
    with pytest.raises(ValueError, match="undeclared"):
        service.publish(command)


def _origin_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str
) -> tuple[Any, ...]:
    fixture = _knowledge_fixture(
        tmp_path, monkeypatch, manifest_schema_version="5.0", workflow_definition_version="1.11.0"
    )
    if version != "1.11.0":
        _upgrade_fixture_plan_to_v12(fixture)
    old = fixture["session"].records[ResolvedExecutionPlanRecord, str(fixture["plan_id"])]
    body = deepcopy(old.canonical_document)
    family = {"1.11.0": (11, 11), "1.15.0": (12, 17), "1.16.0": (12, 19)}[version]
    request_value = json.loads(
        (
            ROOT / "content/packs/generated-knowledge-item/1.20.12/fixtures/smoke-request.json"
        ).read_text()
    )
    from eom_catalog_contracts.curriculum import resolve_integrated_science_curriculum_scope

    request_value["item_brief"]["curriculum_scope"] = resolve_integrated_science_curriculum_scope(
        UNIT.unit_key
    ).model_dump(mode="json")
    body["retrieval_requirement"]["curriculum_root_key"] = request_value["item_brief"][
        "curriculum_scope"
    ]["graph_root_stable_key"]
    body["retrieval_requirement"]["topic_keys"] = []
    body["retrieval_requirement"]["corpus_key"] = "integrated-science-textbooks"
    body["retrieval_requirement_sha256"] = content_sha256(body["retrieval_requirement"])
    request_value["execution_preset_key"] = "knowledge-grounded-item"
    request_value["educational_retrieval"] = deepcopy(body["retrieval_requirement"])
    request = WorkflowRequest.model_validate(request_value)
    definition_body = {"schema_version": "workflow-definition/1.0", "fixture": version}
    definition = SimpleNamespace(
        definition_id="workflowdef_" + "1" * 32,
        definition_key="generic-item-development",
        definition_version=version,
        definition_hash=content_sha256(definition_body),
        canonical_definition=definition_body,
        active=False,
    )
    value = _command_value()
    source = value["sources"][0]["source"]
    workflow_id = value["sources"][0]["workflow_id"]
    body.update(
        schema_version=f"resolved-execution-plan/{family[1]}.0",
        workflow_id=workflow_id,
        workflow_definition_version=version,
        workflow_definition_sha256=definition.definition_hash,
        resolver_version=f"{family[1]}.0.0" if family[1] in {17, 19} else body["resolver_version"],
    )
    body["plan_sha256"] = content_sha256(
        {key: item for key, item in body.items() if key != "plan_sha256"}
    )
    value["sources"][0]["expected_plan_sha256"] = body["plan_sha256"]
    command = PublishOrdinaryApprovedItemAnalysesCommand.model_validate(_rehash(value))
    selected = command.sources[0]
    workflow = SimpleNamespace(
        workflow_id=workflow_id,
        definition_id=definition.definition_id,
        definition_key=definition.definition_key,
        definition_version=version,
        definition_hash=definition.definition_hash,
        role_schema_version=f"workflow-role/1.{23 if family[0] == 11 else 24}.0",
        state="COMPLETED",
        stage="COMPLETED",
        current_step_key="complete",
        completed_at=NOW,
        initial_request=request.model_dump(mode="json"),
        request_payload=request.model_dump(mode="json"),
        request_hash=workflow_business_fingerprint(cast(Any, definition), request),
        runtime_context={
            "content_pack": {
                "release_id": body["content_pack_release_id"],
                "release_sha256": body["content_pack_sha256"],
            }
        },
    )
    run = SimpleNamespace(
        analysis_run_id=RUN,
        state="ACCEPTED",
        source_kind="APPROVED_ITEM_REVISION",
        item_id=source["item_id"],
        item_revision_id=source["item_revision_id"],
        canonical_request={"schema_version": "knowledge-analysis-request/2.0", "source": source},
        accepted_result_artifact_id=selected.accepted_result.artifact_id,
        accepted_result_artifact_revision_id=selected.accepted_result.artifact_revision_id,
        accepted_result_sha256=selected.accepted_result.sha256,
    )
    revision = SimpleNamespace(
        item_id=source["item_id"],
        item_revision_id=source["item_revision_id"],
        workflow_id=workflow_id,
        revision_state="APPROVED",
        workflow_definition_version=version,
        content_pack_release_id=body["content_pack_release_id"],
    )
    item = SimpleNamespace(
        item_id=source["item_id"],
        lifecycle_state="ACTIVE",
        current_revision_id=source["item_revision_id"],
    )
    plan = SimpleNamespace(
        canonical_document=body,
        workflow_id=workflow_id,
        **{
            key: body[key]
            for key in (
                "plan_id",
                "plan_sha256",
                "preset_id",
                "preset_revision_id",
                "capacity_policy_revision_id",
                "evidence_bundle_revision_id",
            )
        },
        graph_snapshot_revision_id=body["graph_snapshot"]["graph_snapshot_revision_id"],
        resolved_at=datetime.fromisoformat(body["resolved_at"].replace("Z", "+00:00")),
    )
    return command, run, revision, item, workflow, definition, plan


@pytest.mark.parametrize("version", ["1.11.0", "1.15.0", "1.16.0"])
def test_actual_plan_families_and_product_unit_origin_without_fake_occurrence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: str,
) -> None:
    command, *rows = _origin_fixture(tmp_path, monkeypatch, version)
    OrdinaryItemGraphPublicationService._validate_origins(command, *((row,) for row in rows))


@pytest.mark.parametrize(
    "target,field,bad",
    [
        (0, "state", "RUNNING"),
        (0, "accepted_result_sha256", "sha256:" + "0" * 64),
        (1, "revision_state", "RETIRED"),
        (2, "current_revision_id", "itemrev_" + "0" * 32),
        (3, "role_schema_version", "workflow-role/1.17.0"),
        (3, "request_hash", "sha256:" + "0" * 64),
        (5, "plan_sha256", "sha256:" + "0" * 64),
    ],
)
def test_origin_negative_current_or_pinned_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: int,
    field: str,
    bad: str,
) -> None:
    command, *rows = _origin_fixture(tmp_path, monkeypatch, "1.16.0")
    setattr(rows[target], field, bad)
    with pytest.raises(OrdinaryItemGraphPublicationError, match="ORIGIN_INVALID"):
        OrdinaryItemGraphPublicationService._validate_origins(command, *((row,) for row in rows))


def test_origin_unit_cannot_be_supplied_independently_of_original_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command, *rows = _origin_fixture(tmp_path, monkeypatch, "1.16.0")
    value = command.model_dump(mode="json")
    value["sources"][0]["expected_curriculum_unit_key"] = "eom.is.middle.5-6"
    forged = PublishOrdinaryApprovedItemAnalysesCommand.model_validate(_rehash(value))
    with pytest.raises(OrdinaryItemGraphPublicationError, match="ORIGIN_INVALID"):
        OrdinaryItemGraphPublicationService._validate_origins(forged, *((row,) for row in rows))


def test_scopes_batch_exact_unit_nodes_no_per_source_queries() -> None:
    command = _command()
    session = Mock(spec=Session)
    session.execute.return_value = [
        (
            SimpleNamespace(
                curriculum_unit_id=UNIT.curriculum_unit_id,
                framework_revision_id=UNIT.framework_revision_id,
                unit_level="MINOR",
            ),
            SimpleNamespace(stable_key=UNIT.node_stable_key),
        )
    ]
    context = CurrentKnowledgeGraphStructure(
        command.corpus_key,
        "Graph",
        command.expected_graph_snapshot.graph_snapshot_revision_id,
        (),
        cast(Any, SimpleNamespace(curriculum_units=integrated_science_curriculum_units())),
    )
    scopes = OrdinaryItemGraphPublicationService._scopes(session, context, command)
    assert scopes[0].root_unit_id == UNIT.curriculum_unit_id
    assert not scopes[0].include_descendants
    session.execute.assert_called_once()
    sql = str(session.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "curriculum_unit_id IN" in sql and "JOIN knowledge_nodes" in sql
    session.execute.return_value[0][1].stable_key = "different.namespace"
    with pytest.raises(OrdinaryItemGraphPublicationError, match="UNIT_INVALID"):
        OrdinaryItemGraphPublicationService._scopes(session, context, command)


def test_final_graph_validator_runs_after_cas_before_any_graph_rows() -> None:
    service = object.__new__(KnowledgeGraphPublicationService)
    service.sessions = Mock()
    session = MagicMock(spec=Session)
    current = SimpleNamespace(revision_number=5)
    corpus = SimpleNamespace(
        lifecycle_state="ACTIVE",
        display_name="Graph",
        graph_id="graph",
        current_graph_snapshot_revision_id="prior",
        current_corpus_revision_id="prior-corpus",
    )
    session.scalar.side_effect = [None, corpus]
    session.get.side_effect = [SimpleNamespace(status="ACTIVE"), current]
    command = SimpleNamespace(
        corpus_key="integrated-science-textbooks",
        idempotency_key="fixed-key",
        published_by_operator_id="actual",
        expected_current_snapshot_revision_id="prior",
        display_name="Graph",
    )
    analyses = (cast(AcceptedAnalysisProposal, object()),)
    marker = RuntimeError("late current review revoked")

    def reject(
        actual_session: Session, actual_analyses: tuple[AcceptedAnalysisProposal, ...]
    ) -> None:
        assert actual_session is session and actual_analyses is analyses
        session.add.assert_not_called()
        session.add_all.assert_not_called()
        session.flush.assert_not_called()
        raise marker

    with (
        patch(
            "eom_catalog_service.knowledge_graph_publication_service.transaction",
            return_value=nullcontext(session),
        ),
        pytest.raises(RuntimeError) as caught,
    ):
        service._commit_database_snapshot(
            command=cast(Any, command),
            ids={"graph_id": "graph"},
            expected_revision_number=6,
            previous_corpus_revision_id="prior-corpus",
            projection=cast(Any, SimpleNamespace(analyses=analyses)),
            projection_artifact=cast(Any, None),
            manifest=cast(Any, None),
            manifest_artifact=cast(Any, None),
            structure=None,
            authorized_at=NOW,
            analysis_validator=reject,
        )
    assert caught.value is marker
    session.add_all.assert_not_called()


def test_stale_graph_cas_precedes_final_callback() -> None:
    service = object.__new__(KnowledgeGraphPublicationService)
    service.sessions = Mock()
    session = MagicMock(spec=Session)
    session.scalar.side_effect = [
        None,
        SimpleNamespace(
            lifecycle_state="ACTIVE",
            display_name="different",
            current_graph_snapshot_revision_id="prior",
        ),
    ]
    session.get.side_effect = [SimpleNamespace(status="ACTIVE"), None]
    callback = Mock()
    with (
        patch(
            "eom_catalog_service.knowledge_graph_publication_service.transaction",
            return_value=nullcontext(session),
        ),
        pytest.raises(KnowledgeGraphPublicationError, match="changed before publication"),
    ):
        service._commit_database_snapshot(
            command=cast(
                Any,
                SimpleNamespace(
                    corpus_key="x",
                    idempotency_key="k",
                    published_by_operator_id="a",
                    display_name="Graph",
                    expected_current_snapshot_revision_id="prior",
                ),
            ),
            ids={"graph_id": "g"},
            expected_revision_number=2,
            previous_corpus_revision_id="p",
            projection=cast(Any, None),
            projection_artifact=cast(Any, None),
            manifest=cast(Any, None),
            manifest_artifact=cast(Any, None),
            structure=None,
            authorized_at=NOW,
            analysis_validator=callback,
        )
    callback.assert_not_called()


def test_result_separates_raw_manifest_identity_and_semantic_graph_hash() -> None:
    command = _command()
    graph = deepcopy(command.expected_graph_snapshot.model_dump(mode="json"))
    graph["graph_snapshot_revision_id"] = "graphrev_" + "3" * 32
    value = {
        "schema_version": "ordinary-item-graph-publication-result/1.0",
        "corpus_key": command.corpus_key,
        "publication_id": "graphpub_" + "4" * 32,
        "previous_graph_snapshot": command.expected_graph_snapshot.model_dump(mode="json"),
        "previous_graph_snapshot_sha256": command.expected_graph_snapshot_sha256,
        "graph_snapshot": graph,
        "graph_snapshot_sha256": "sha256:" + "2" * 64,
        "sources": [row.model_dump(mode="json") for row in command.sources],
        "authorized_at": "2026-10-19T00:00:00Z",
        "published_at": "2026-10-19T00:00:00Z",
        "submission_sha256": command.submission_sha256,
        "outcome": "CREATED",
    }
    value["result_sha256"] = content_sha256(value)
    result = OrdinaryItemGraphPublicationResult.model_validate(value)
    validate_contract("ordinary-item-graph-publication-result", result.model_dump(mode="json"))
    assert result.graph_snapshot_sha256 != result.graph_snapshot.manifest_sha256


@pytest.mark.parametrize(
    "denial", [None, "actor", "role", "permissions", "policy_hash", "policy_sources"]
)
def test_actual_actor_and_policy_required_not_hardcoded_admin_claim(denial: str | None) -> None:
    command = _command()
    session = Mock(spec=Session)
    actor = SimpleNamespace(status="ACTIVE", deleted_at=None, must_change_password=False)
    policy_row = SimpleNamespace(state="RELEASED", content_sha256=command.access_policy_sha256)
    if denial == "actor":
        actor.status = "DISABLED"
    if denial == "policy_hash":
        policy_row.content_sha256 = "sha256:" + "0" * 64
    session.scalar.side_effect = [actor, policy_row]
    session.scalars.side_effect = [
        [SimpleNamespace(role_id="actual-role")],
        [SimpleNamespace(role_id="actual-role")],
        [SimpleNamespace(permission_id="actual-permission")],
        [SimpleNamespace(permission_id="actual-permission")],
    ]
    service = object.__new__(OrdinaryItemGraphPublicationService)
    service.identity_fence = Mock(spec=OperatorAuthorizationFence)
    service.retrieval = Mock()
    service.retrieval.resolve_access_policy.return_value = SimpleNamespace(
        allowed_requester_roles=("ADMIN",),
        allowed_query_kinds=("ITEM_PREPARATION",),
        allowed_source_classes=("CURRICULUM", "TEXTBOOK")
        if denial == "policy_sources"
        else ("APPROVED_ITEM", "CURRICULUM", "TEXTBOOK"),
        maximum_budget=SimpleNamespace(
            max_documents=8,
            max_item_revisions=0,
            max_graph_nodes=64,
            max_claims=16,
            max_context_tokens=8000,
        ),
    )
    with (
        patch(
            "eom_catalog_service.ordinary_item_graph_publication_service.active_role_assignments",
            return_value=[
                (object(), SimpleNamespace(role_key="EDITOR" if denial == "role" else "ADMIN"))
            ],
        ),
        patch(
            "eom_catalog_service.ordinary_item_graph_publication_service.effective_permissions",
            return_value=frozenset() if denial == "permissions" else _REQUIRED_PERMISSIONS,
        ),
    ):
        if denial is None:
            service._authorize(session, command)
        else:
            with pytest.raises(OrdinaryItemGraphPublicationError, match="FORBIDDEN"):
                service._authorize(session, command)
    for call in session.scalars.call_args_list + session.scalar.call_args_list:
        assert "FOR SHARE" not in str(call.args[0].compile(dialect=postgresql.dialect()))
        assert call.args[0].get_execution_options()["populate_existing"] is True
    service.identity_fence.fence_current_operator.assert_called_once_with(
        session, command.requested_by_operator_id
    )


def test_initial_forbidden_actor_fails_before_any_accepted_member_or_retrieval() -> None:
    service = object.__new__(OrdinaryItemGraphPublicationService)
    session = MagicMock(spec=Session)
    service.sessions = Mock(return_value=nullcontext(session))
    service.publication = Mock()
    with (
        patch.object(
            service, "_authorize", side_effect=OrdinaryItemGraphPublicationError("FORBIDDEN")
        ),
        patch(
            "eom_catalog_service.ordinary_item_graph_publication_service.AutomaticItemGraphPublicationService"
        ) as common,
        pytest.raises(OrdinaryItemGraphPublicationError, match="FORBIDDEN"),
    ):
        service.publish(_command())
    common.assert_not_called()
    service.publication.resolve_accepted_analyses.assert_not_called()
    session.scalar.assert_not_called()
    session.begin.assert_called_once_with()


@pytest.mark.parametrize(
    "denial",
    [None, "artifact_revoked", "artifact_missing", "job_failed", "review_hash", "late_policy"],
)
def test_current_candidate_proof_revalidated_and_locked_before_final_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    denial: str | None,
) -> None:
    command, run, revision, item, workflow, definition, plan = _origin_fixture(
        tmp_path, monkeypatch, "1.16.0"
    )
    analysis = AcceptedAnalysisProposal(
        RUN, command.sources[0].source, command.sources[0].accepted_result, cast(Any, object())
    )
    run.proposal_artifact_id, run.proposal_artifact_revision_id = (
        "artifact_" + "4" * 32,
        "rev_" + "4" * 32,
    )
    revision.manifest_artifact_id, revision.manifest_artifact_revision_id = (
        "artifact_" + "5" * 32,
        "rev_" + "5" * 32,
    )
    ids = (
        (run.proposal_artifact_id, run.proposal_artifact_revision_id),
        (
            command.sources[0].accepted_result.artifact_id,
            command.sources[0].accepted_result.artifact_revision_id,
        ),
        (
            command.expected_graph_snapshot.manifest_artifact.artifact_id,
            command.expected_graph_snapshot.manifest_artifact.artifact_revision_id,
        ),
    )
    logicals = [SimpleNamespace(logical_artifact_id=logical, approved=True) for logical, _ in ids]
    artifacts = [
        SimpleNamespace(revision_id=rev, approved=True, job_id="job-original") for _, rev in ids
    ]
    if denial == "artifact_revoked":
        artifacts[0].approved = False
    if denial == "artifact_missing":
        artifacts.pop()
    by_model = {
        KnowledgeAnalysisRunRecord: (run,),
        ItemRevisionRecord: (revision,),
        ItemRecord: (item,),
        WorkflowDefinitionRecord: (definition,),
        ResolvedExecutionPlanRecord: (plan,),
        ArtifactRecord: logicals,
        ArtifactRevisionRecord: artifacts,
        JobRecord: (
            SimpleNamespace(
                job_id="job-original", status="FAILED" if denial == "job_failed" else "SUCCEEDED"
            ),
        ),
    }
    session = MagicMock(spec=Session)
    session.new = session.dirty = session.deleted = set()
    session.scalars.side_effect = lambda statement: by_model[
        statement.column_descriptions[0]["entity"]
    ]
    service = object.__new__(OrdinaryItemGraphPublicationService)
    service.publication = Mock()
    service.publication.resolve_accepted_analyses.return_value = {
        RUN: SimpleNamespace(analysis=analysis)
    }
    service.receipts = Mock()
    evidence = registered_review_case().basis.review_evidence
    if denial == "review_hash":
        evidence = evidence.model_copy(update={"evidence_sha256": "sha256:" + "0" * 64})

    def resolve(actual_session: Session, **values: Any) -> tuple[Any, ...]:
        assert actual_session is session and values["sources"] == (command.sources[0].source,)
        values["authorize_source"](command.sources[0].source)
        return (SimpleNamespace(evidence=evidence),)

    with (
        patch.object(service, "_authorize") as authorize,
        patch.object(service, "_validate_pinned_base"),
        patch(
            "eom_catalog_service.ordinary_item_graph_publication_service.lock_registered_item_review_sources",
            return_value=SimpleNamespace(
                workflows=(workflow,), logicals=(), artifacts=(), jobs=(), assert_current=Mock()
            ),
        ),
        patch(
            "eom_catalog_service.ordinary_item_graph_publication_service.resolve_registered_item_review_solutions",
            side_effect=resolve,
        ) as resolver,
    ):
        if denial == "late_policy":
            authorize.side_effect = [None, OrdinaryItemGraphPublicationError("LATE_POLICY_REVOKED")]
        if denial is None:
            service._validate_current(session, command, (analysis,))
            assert authorize.call_count == 2
            resolver.assert_called_once()
        else:
            with pytest.raises(OrdinaryItemGraphPublicationError):
                service._validate_current(session, command, (analysis,))
        if denial in {"artifact_revoked", "artifact_missing", "job_failed"}:
            resolver.assert_not_called()
    assert session.scalars.call_count == len(by_model)
    for call in session.scalars.call_args_list:
        statement = call.args[0]
        immutable = {
            WorkflowDefinitionRecord,
            ResolvedExecutionPlanRecord,
            ArtifactRecord,
            ArtifactRevisionRecord,
        }
        entity = statement.column_descriptions[0]["entity"]
        compiled = str(statement.compile(dialect=postgresql.dialect()))
        assert ("FOR SHARE" in compiled) is (entity not in immutable)
        if entity in {ArtifactRecord, ArtifactRevisionRecord}:
            assert ".approved IS true" in compiled
        assert statement.get_execution_options()["populate_existing"] is True
    session.add_all.assert_not_called()
