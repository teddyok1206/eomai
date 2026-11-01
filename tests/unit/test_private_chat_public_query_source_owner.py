"""Real Chat read/control files and ORM roots; public Catalog/IAM leaves are synthetic.

The common DOCUMENT file/index boundary has its own real-file reader suite.
No model, live private admission, installed service or production DB is used here.
"""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryOwnerConfiguration
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.public_solution_similarity_read import CatalogPublicSolutionSimilarityRead
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_workflow.private_chat_query_execution_v2 import (
    PRIVATE_CHAT_PUBLIC_QUERY_POLICY_REF,
    PrivateChatQueryExecutionPolicyV2,
    PrivateChatQueryWorkflowRequestV2,
)
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation
from eom_workflow_runner.private_chat_query_source_read import (
    CatalogPrivateChatQuerySourceOwner,
    PrivateChatQueryOwnerConfiguration,
    ResolvedPrivateChatPublicQuerySources,
    build_private_chat_public_query_native_input,
    build_private_chat_query_native_input,
    read_pinned_private_chat_query_controls,
    read_pinned_supported_private_chat_query_controls,
    validate_current_private_chat_public_query_input,
)
from sqlalchemy import func, select, update

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_local_embedding_control_artifacts import NOW
from tests.unit.test_private_chat_public_query_execution import execution_case
from tests.unit.test_private_chat_public_query_workflow import public_completed as public_completed
from tests.unit.test_private_chat_public_similarity_service import private_public_case
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_source_owner import make_private_source_case
from tests.unit.test_private_chat_query_workflow import completed as completed


@pytest.fixture
def source(tmp_path, monkeypatch):
    return make_private_public_source_case(tmp_path, monkeypatch)


def make_private_public_source_case(tmp_path, monkeypatch, *, definition_sha256=None):
    old = make_private_source_case(tmp_path, monkeypatch)
    request, policy, _bundle = execution_case()
    policy = PrivateChatQueryExecutionPolicyV2.model_validate(
        seal(
            policy.model_dump(mode="json")
            | {
                "runtime_bundle": old.request.runtime_bundle.model_dump(mode="json"),
                "workflow_definition_sha256": definition_sha256
                or policy.workflow_definition_sha256,
            },
            "policy_sha256",
        )
    )
    saved = old.controls.publish_private_chat_public_query_policy(
        policy, idempotency_key="private-public-owner-test:policy", created_at=NOW
    )
    context = seal(
        request.context_request.model_dump(mode="json")
        | {"query_basis": old.projection.origin.basis.model_dump(mode="json")},
        "request_sha256",
    )
    request = PrivateChatQueryWorkflowRequestV2.model_validate(
        seal(
            request.model_dump(mode="json")
            | {
                "operator_audit": request.operator_audit.model_dump(mode="json")
                | {"operator_id": old.projection.origin.actor_id},
                "context_request": context,
                "native_execution_policy": saved.member.model_dump(mode="json"),
                "native_execution_policy_sha256": policy.policy_sha256,
                "runtime_bundle": old.request.runtime_bundle.model_dump(mode="json"),
                "workflow_definition_sha256": policy.workflow_definition_sha256,
            },
            "request_sha256",
        )
    )
    selected = request.context_request.views[0]
    config = PrivateChatQueryOwnerConfiguration(
        EmbeddingRegistryOwnerConfiguration(
            old.owner.configuration.registry.corpus_id,
            PublicSolutionIndexNamespace(
                storage_partition=selected.index.storage_partition,
                space_sha256=policy.spaces.document.space_sha256,
                view="CONCRETE_FACETS",
                recipe_sha256=selected.recipe.recipe_sha256,
            ),
            policy.spaces.document,
            selected.recipe,
            request.context_request.source_classes,
        ),
        saved.member,
        policy.policy_sha256,
        old.request.runtime_bundle,
    )
    owner = CatalogPrivateChatQuerySourceOwner(
        old.publisher.engine,
        config,
        chat=old.owner.chat,
        identity_fence=old.owner.identity,
        settings=old.owner.settings,
    )
    capture = replace(
        private_public_case()[1], space=policy.spaces.document, recipe=selected.recipe
    )
    reads = []

    def read(_application, session, caller, context):
        assert _application.catalog is owner.catalog
        assert session is old.fault.session
        assert caller.operator_id == old.projection.origin.actor_id
        assert context == request.context_request
        old.events.append("common_document")
        reads.append(context)
        if old.fault.public_revoked or old.fault.value == "public":
            raise SimilarityContextReadError("SOURCE_REVOKED")
        if old.fault.value == "index":
            raise SimilarityContextReadError("INDEX_POINTER_INVALID")
        return capture, object()

    monkeypatch.setattr(
        CatalogPublicSolutionSimilarityRead, "read_private_documents_in_session", read
    )
    return SimpleNamespace(**locals())


def resolve(value):
    with value.old.publisher.sessions.begin() as session:
        value.old.fault.session = session
        return value.owner.resolve_sources(session, value.request, value.old.projection.origin)


def test_common_source_owner_reads_actual_current_question_and_canonical_policy_once(source):
    result = resolve(source)
    assert type(result) is ResolvedPrivateChatPublicQuerySources
    assert result.policy == source.policy and result.bundle == source.old.bundle
    assert result.projection == source.old.projection
    assert len(result.documents.entries) == 3
    assert source.old.events == [
        "identity",
        "materialize",
        "common_document",
        "authorize",
        "identity",
        "common_document",
    ]
    assert len(source.reads) == 2 and TEXT not in repr(result)
    native = build_private_chat_public_query_native_input(
        result, job_id="job_" + "a" * 32, query_request_id="embeddingquery_" + "b" * 32
    )
    assert native.schema_version == "embedding-reference-query-input/2.0"
    assert (
        native.rows[0].text == TEXT
        and native.recipe == source.request.context_request.views[0].recipe
    )
    with source.old.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 3
        for row in session.scalars(select(JobRecord)):
            assert TEXT.encode() not in canonical_json_bytes(row.request)
        for row in session.scalars(select(ArtifactRevisionRecord)):
            assert TEXT.encode() not in canonical_json_bytes(row.result)


@pytest.mark.parametrize(
    "fault,code",
    [
        ("identity", "SOURCE_ACCESS_DENIED"),
        ("late_identity", "SOURCE_ACCESS_DENIED"),
        ("chat", "SOURCE_ACCESS_DENIED"),
        ("claim", "AUTHORITY_UNAVAILABLE"),
        ("origin", "SOURCE_REVOKED"),
        ("text", "SOURCE_POINTER_INVALID"),
        ("pending", "AUTHORITY_UNAVAILABLE"),
        ("public", "SOURCE_REVOKED"),
        ("public_during_private_auth", "SOURCE_REVOKED"),
        ("index", "INDEX_POINTER_INVALID"),
    ],
)
def test_current_actor_claim_text_and_public_changes_remain_explicit_errors(source, fault, code):
    source.old.fault.value = fault
    with source.old.publisher.sessions.begin() as session:
        source.old.fault.session = session
        with pytest.raises(SimilarityContextReadError) as error:
            source.owner.resolve_sources(session, source.request, source.old.projection.origin)
        assert error.value.code == code
        assert TEXT not in str(error.value) and "DO_NOT_DISCLOSE" not in str(error.value)
        session.rollback()


def test_common_policy_publication_replays_original_identity_without_overwriting_history(source):
    original = source.saved
    assert (
        source.old.controls.publish_private_chat_public_query_policy(
            source.policy, idempotency_key="private-public-owner-test:policy", created_at=NOW
        )
        == original
    )
    assert original.member.schema_ref == PRIVATE_CHAT_PUBLIC_QUERY_POLICY_REF
    changed = PrivateChatQueryExecutionPolicyV2.model_validate(
        seal(
            source.policy.model_dump(mode="json") | {"created_at": "2026-10-01T00:00:00Z"},
            "policy_sha256",
        )
    )
    with pytest.raises(ControlPlaneError) as conflict:
        source.old.controls.publish_private_chat_public_query_policy(
            changed, idempotency_key="private-public-owner-test:policy", created_at=NOW
        )
    assert conflict.value.code == "CONTROL_FILE_SET_CONFLICT"


def test_common_controls_do_not_activate_legacy_read_or_publication_api(source):
    with source.old.publisher.sessions.begin() as session:
        reader = PinnedArtifactReadContext(session, source.owner.settings)
        assert read_pinned_supported_private_chat_query_controls(reader, source.config) == (
            source.policy,
            source.old.bundle,
        )
        with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_CONTROL_SELECTION_INVALID"):
            read_pinned_private_chat_query_controls(reader, source.config)
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_CONTROL_INVALID"):
        source.old.controls.publish_private_chat_query_policy(
            source.policy, idempotency_key="legacy-private-cannot-publish2", created_at=NOW
        )


def test_common_policy_producer_failure_is_not_reinterpreted_as_success(source):
    with source.old.publisher.sessions.begin() as session:
        session.execute(
            update(JobRecord)
            .where(JobRecord.job_id == source.saved.owner_job_id)
            .values(status="FAILED")
        )
    with pytest.raises(SimilarityContextReadError, match="SOURCE_POINTER_INVALID"):
        resolve(source)


def test_policy_and_registry_family_cannot_be_mixed_in_owner_configuration(source):
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_OWNER_CONFIGURATION_INVALID"):
        replace(source.config, registry=source.old.owner.configuration.registry)
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_OWNER_CONFIGURATION_INVALID"):
        replace(source.old.owner.configuration, registry=source.config.registry)


@pytest.mark.parametrize("fault", ["extra", "legacy"])
def test_common_policy_publication_rejects_wrong_family_before_creating_job(source, fault):
    value = (
        source.policy.model_copy(update={"question": "DO_NOT_DISCLOSE"})
        if fault == "extra"
        else source.old.policy
    )
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_CONTROL_INVALID") as error:
        source.old.controls.publish_private_chat_public_query_policy(
            value, idempotency_key="invalid-public-policy", created_at=NOW
        )
    assert "DO_NOT_DISCLOSE" not in str(error.value)
    with source.old.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 3


def test_common_source_value_cannot_enter_legacy_input_builder(source):
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_CURRENT_INPUT_INVALID"):
        build_private_chat_query_native_input(
            resolve(source), job_id="job_" + "a" * 32, query_request_id="embeddingquery_" + "b" * 32
        )


def test_changed_canonical_policy_bytes_are_not_repaired_by_source_read(source):
    pointer = source.saved.member
    policy = (
        source.owner.settings.nas_artifact_root
        / pointer.artifact_id
        / pointer.artifact_revision_id
        / pointer.member_path
    )
    changed = policy.read_bytes() + b"invalid"
    policy.write_bytes(changed)
    with pytest.raises(SimilarityContextReadError, match="SOURCE_POINTER_INVALID"):
        resolve(source)
    assert policy.read_bytes() == changed


def test_common_original_input_reconstruction_binds_exact_launch_and_current_text(
    source, public_completed
):
    sources = resolve(source)
    native = build_private_chat_public_query_native_input(
        sources, job_id="job_" + "a" * 32, query_request_id="embeddingquery_" + "b" * 32
    )
    launch = PrivateChatQueryLaunchAssociation.model_validate(
        seal(
            public_completed.launch.model_dump(mode="json")
            | {
                "workflow_request_sha256": source.request.request_sha256,
                "context_request_sha256": source.request.context_request.request_sha256,
                "basis_sha256": source.request.context_request.query_basis.basis_sha256,
                "query_request_id": native.query_request_id,
                "query_request_sha256": native.request_sha256,
                "query_input_set_sha256": native.input_set_sha256,
                "native_launch_job_id": native.job_id,
                "recipe_sha256": native.recipe.recipe_sha256,
                "runtime_bundle": source.request.runtime_bundle.model_dump(mode="json"),
                "resource_profile_sha256": source.request.resource_profile.resource_profile_sha256,
            },
            "association_sha256",
        )
    )
    validate_current_private_chat_public_query_input(sources, launch, native)
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_CURRENT_INPUT_INVALID"):
        validate_current_private_chat_public_query_input(
            sources, launch, native.model_copy(update={"request_sha256": "sha256:" + "f" * 64})
        )
