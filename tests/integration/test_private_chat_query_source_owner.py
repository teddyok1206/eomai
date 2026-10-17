"""Actual registered DB/control/index files; current Chat/IAM populations are synthetic."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_catalog_contracts.private_chat_similarity import PrivateChatSimilarityRequest
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.embedding_runtime_bundle_artifacts import (
    EmbeddingRuntimeBundleArtifactPublisher,
)
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_workflow.private_chat_query_execution import (
    PrivateChatQueryExecutionPolicy,
    PrivateChatQueryWorkflowRequest,
    validate_private_chat_query_request_references,
)
from eom_workflow_runner.private_chat_query_source_read import (
    CatalogPrivateChatQuerySourceOwner,
    PrivateChatQueryOwnerConfiguration,
    build_private_chat_query_native_input,
)
from sqlalchemy import func, select, update

from tests.integration.test_embedding_registry_application import CALLER
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_private_chat_document_read import registered as registered
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.local_embedding_admission_fixtures import runtime_profile
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_execution import execution_case
from tests.unit.test_private_chat_query_source import source_case

pytestmark = [
    pytest.mark.integration,
    pytest.mark.parametrize("registered", [runtime_profile("CPU").space], indirect=True),
]


@pytest.fixture
def owned(registered, guarded_engine):
    public = registered
    assert guarded_engine.dialect.name == "postgresql"
    publisher = ControlFileSetPublisher(guarded_engine, public.settings)
    request, policy, bundle = execution_case()
    bundle_seed = uuid4().hex
    bundle = type(bundle).model_validate(
        seal(
            bundle.model_dump(mode="json")
            | {
                "bundle_id": "embeddingbundle_" + bundle_seed,
                "bundle_revision_id": "embeddingbundlerev_" + bundle_seed,
            },
            "bundle_sha256",
        )
    )
    saved_bundle = EmbeddingRuntimeBundleArtifactPublisher(
        ControlArtifactPublisher(guarded_engine, public.settings), source_commit="a" * 40
    ).publish(bundle, created_at=NOW)
    with publisher.sessions.begin() as session:
        revision = session.get(
            ArtifactRevisionRecord, saved_bundle.bundle.manifest_member.artifact_revision_id
        )
        assert revision is not None
        assert Path(revision.nas_path).is_relative_to(public.settings.nas_artifact_root)
    policy = PrivateChatQueryExecutionPolicy.model_validate(
        seal(
            policy.model_dump(mode="json")
            | {
                "spaces": public.request.views[0].index.spaces.model_dump(mode="json"),
                "runtime_bundle": saved_bundle.bundle.model_dump(mode="json"),
            },
            "policy_sha256",
        )
    )
    controls = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    saved = controls.publish_private_chat_query_policy(
        policy, idempotency_key="private-source-policy:" + uuid4().hex, created_at=NOW
    )
    chat = source_case(question=TEXT)
    # Set the synthetic conversation owner before its first canonical origin capture.
    chat.repository.owner = CALLER.operator_id
    projection = chat.execution.materialize_live_private_query(chat.ticket)
    context = PrivateChatSimilarityRequest.model_validate(
        seal(
            public.request.model_dump(mode="json")
            | {"query_basis": projection.origin.basis.model_dump(mode="json")},
            "request_sha256",
        )
    )
    request = PrivateChatQueryWorkflowRequest.model_validate(
        seal(
            request.model_dump(mode="json")
            | {
                "context_request": context.model_dump(mode="json"),
                "operator_audit": request.operator_audit.model_dump(mode="json")
                | {"operator_id": projection.origin.actor_id},
                "native_execution_policy": saved.member.model_dump(mode="json"),
                "native_execution_policy_sha256": policy.policy_sha256,
                "runtime_bundle": saved_bundle.bundle.model_dump(mode="json"),
            },
            "request_sha256",
        )
    )
    validate_private_chat_query_request_references(request, policy, bundle)
    fault = SimpleNamespace(value=None, final_authorization_reached=False)

    def authorize(origin):
        fault.final_authorization_reached = True
        if fault.value == "public_during_private_auth":
            public.fault.value = "source"
        if fault.value == "claim":
            chat.repository.row.state = "FAILED"
        elif fault.value == "producer":
            with publisher.sessions.begin() as writer:
                writer.execute(
                    update(JobRecord)
                    .where(JobRecord.job_id == saved.owner_job_id)
                    .values(status="FAILED")
                )
        return chat.execution.authorize_live_private_query(origin)

    owner = CatalogPrivateChatQuerySourceOwner(
        guarded_engine,
        PrivateChatQueryOwnerConfiguration(
            public.verifier.configuration, saved.member, policy.policy_sha256, saved_bundle.bundle
        ),
        chat=SimpleNamespace(
            materialize=chat.execution.materialize_live_private_query, authorize=authorize
        ),
        identity_fence=Mock(),
        settings=public.verifier.settings,
    )
    owner.catalog.sources = public.verifier.sources
    return SimpleNamespace(
        owner=owner,
        request=request,
        origin=projection.origin,
        publisher=publisher,
        policy=policy,
        fault=fault,
    )


@pytest.mark.parametrize("fault", [None, "claim", "producer", "public_during_private_auth"])
def test_private_source_owner_reads_actual_published_controls_and_registered_index(owned, fault):
    value = owned
    value.fault.value = fault
    with value.publisher.sessions.begin() as session:
        root = session.get_transaction()
        before = session.scalar(select(func.count()).select_from(JobRecord))
        if fault is None:
            resolved = value.owner.resolve_sources(session, value.request, value.origin)
            assert len(resolved.documents.sources) == 1
            native = build_private_chat_query_native_input(
                resolved, job_id="job_" + "a" * 32, query_request_id="embeddingquery_" + "b" * 32
            )
            assert native.row.text == TEXT and TEXT not in repr(resolved)
        else:
            code = (
                "AUTHORITY_UNAVAILABLE"
                if fault == "claim"
                else "SOURCE_REVOKED"
                if fault == "public_during_private_auth"
                else "SOURCE_POINTER_INVALID"
            )
            with pytest.raises(SimilarityContextReadError, match=code):
                value.owner.resolve_sources(session, value.request, value.origin)
        assert value.fault.final_authorization_reached
        assert session.get_transaction() is root and not session.new and not session.dirty
        assert session.scalar(select(func.count()).select_from(JobRecord)) == before


def test_two_private_policy_publishers_use_one_postgres_identity(owned):
    key = "concurrent-private-policy:" + uuid4().hex
    barrier = Barrier(2)
    with owned.publisher.sessions.begin() as session:
        before = session.scalar(select(func.count()).select_from(ArtifactRevisionRecord))

    def publish(_index):
        publisher = ControlFileSetPublisher(owned.publisher.engine, owned.publisher.settings)
        barrier.wait(timeout=15)
        return LocalEmbeddingControlArtifactPublisher(
            publisher, source_commit="a" * 40
        ).publish_private_chat_query_policy(owned.policy, idempotency_key=key, created_at=NOW)

    with ThreadPoolExecutor(max_workers=2) as pool:
        left, right = tuple(pool.map(publish, range(2)))
    assert left == right
    with owned.publisher.sessions.begin() as session:
        assert (
            session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == before + 1
        )
        job = session.get(JobRecord, left.owner_job_id)
        assert job.status == "SUCCEEDED" and job.worker_slot_id is None
