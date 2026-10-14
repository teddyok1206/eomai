"""Service owner over actual temporary controls and explicit synthetic source/IAM IO.

No actual PostgreSQL authentication, service unit, source pixels, model or GPU is
admitted. The original shared owner/lease/Artifact algorithms are exercised here.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_catalog_service.embedding_registry_catalog_adapter import (
    EmbeddingRegistryOwnerConfiguration,
)
from eom_catalog_service.embedding_registry_indexing_authority import (
    CatalogIndexingRegistrySourceAuthority,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryServiceCaller,
    ResolvedEmbeddingLookup,
)
from eom_catalog_service.local_indexing_source_authority import CatalogLocalIndexingSourceAuthority
from eom_catalog_service.local_indexing_source_ports import LocalIndexingSourceError
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactResolutionError
from eom_catalog_service.settings import CatalogSettings
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_orchestrator.models import ArtifactRevisionRecord
from eom_orchestrator.native_embedding_index_systemd import FixedNativeIndexLauncher
from eom_workflow.local_embedding_request import LocalEmbeddingServiceWorkflowRequest
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.local_embedding_admission import ResolvedLocalEmbeddingAdmission
from eom_workflow_runner.local_embedding_native_executor import CatalogNativeEmbeddingExecutor
from eom_workflow_runner.local_embedding_owner_admission import (
    CatalogLocalEmbeddingOwnerAdmission,
    LocalEmbeddingOwnerConfiguration,
)
from sqlalchemy.orm import Session

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_service_fixtures import ServiceNativeFixture, service_fixture
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_local_embedding_control_artifacts import NOW
from tests.unit.test_local_embedding_owner_admission import mutation_rows
from tests.unit.test_local_embedding_runner_admission import scope_fixture
from tests.unit.test_local_indexing_runtime_admission import installed as installed
from tests.unit.test_postgres_local_indexing_fence import case as case


@dataclass
class ServiceOwnerCase:
    owner: CatalogLocalEmbeddingOwnerAdmission
    publisher: object
    controls: LocalEmbeddingControlArtifactPublisher
    fixture: ServiceNativeFixture
    scope: ResolvedLocalEmbeddingAdmission
    current: ResolvedEmbeddingLookup
    source_authority: CatalogIndexingRegistrySourceAuthority
    calls: list[tuple[str, Session]] = field(default_factory=list)
    deny: bool = False
    deny_after_lookup: bool = False


@pytest.fixture
def service_owner(case, tmp_path, monkeypatch):
    fence, _synthetic_sql = case
    _scope, compiled = scope_fixture()
    fixture = service_fixture(
        service=fence.pin.service,
        runtime_configuration_sha256=fence.pin.configuration_sha256,
        workflow_definition_sha256=compiled.sha256,
    )
    publisher, _engine = _publisher(tmp_path)
    publisher.settings = replace(publisher.settings, workspace_root=tmp_path)
    controls = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    saved_plan = controls.publish_source_plan(
        fixture.base.plan, idempotency_key="synthetic-service-plan", created_at=NOW
    )
    saved_policy = controls.publish_service_policy(
        fixture.policy, idempotency_key="synthetic-service-policy", created_at=NOW
    )
    request = LocalEmbeddingServiceWorkflowRequest.model_validate(
        seal(
            fixture.request.model_dump(mode="json")
            | {
                "source_plan": saved_plan.member.model_dump(mode="json"),
                "native_execution_policy": saved_policy.member.model_dump(mode="json"),
            },
            "request_sha256",
        )
    )
    gate = CatalogIndexingRegistrySourceAuthority(
        CatalogLocalIndexingSourceAuthority(Mock(), fence),
        fixture.grant.access_policy_revision_id,
        fixture.grant.content_sha256,
        fixture.policy.policy_sha256,
        request.resource_profile.resource_profile_sha256,
    )
    config = LocalEmbeddingOwnerConfiguration(
        EmbeddingRegistryOwnerConfiguration(
            request.corpus_id,
            request.namespace,
            request.space,
            fixture.base.plan.recipe,
            ("PAST_EXAM",),
        ),
        saved_policy.member,
        saved_policy.semantic_sha256,
    )
    owner = CatalogLocalEmbeddingOwnerAdmission.for_indexing_service(
        publisher.engine,
        config,
        source_authority=gate,
        settings=CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root),
    )
    result = ServiceOwnerCase(
        owner,
        publisher,
        controls,
        fixture,
        ResolvedLocalEmbeddingAdmission(request, fixture.base.plan, fixture.policy),
        ResolvedEmbeddingLookup(
            request.corpus_id,
            request.space,
            fixture.base.plan.recipe,
            fixture.base.plan.sources,
            fixture.base.entries,
        ),
        gate,
    )

    def source_io(_self, session, intent):
        # Deliberate unit-only IAM/data seam. The production concrete method and
        # actual runtime/DB gate have separate tests and are NOT replaced by wiring.
        result.calls.append(("source-fence", session))
        assert session.get_transaction() is not None
        assert intent.service_policy_sha256 == fixture.grant.content_sha256
        assert intent.access_policy_revision_id == request.access_policy_revision_id
        assert intent.access_policy_revision_id != intent.service_policy_revision_id
        if result.deny:
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_FORBIDDEN")
        return fixture.grant

    def authorize(session, caller, query):
        assert type(caller) is EmbeddingRegistryServiceCaller and not hasattr(caller, "operator_id")
        gate.authorize_scope(session, caller, query, config.registry)

    def lookup(session, caller, query):
        authorize(session, caller, query)
        result.calls.append(("lookup", session))
        if result.deny_after_lookup:
            result.deny = True
        return result.current

    monkeypatch.setattr(CatalogLocalIndexingSourceAuthority, "authorize_scope", source_io)
    monkeypatch.setattr(owner.catalog, "authorize_scope", authorize)
    monkeypatch.setattr(owner.catalog, "resolve_lookup", lookup)
    return result


def test_current_service_and_published_successor_controls_reuse_same_root(service_owner):
    c = service_owner
    with c.publisher.sessions() as session, session.begin():
        assert c.owner.resolve_submission(session, c.scope.request) == c.scope
        assert all(actual is session for _kind, actual in c.calls)
        assert len([kind for kind, _actual in c.calls if kind == "source-fence"]) == 4
        assert c.owner.registry_caller(c.scope.request).service == c.fixture.grant.service
        with pytest.raises(ValueError, match="OPERATOR_UNAVAILABLE"):
            _ = c.owner.identity


@pytest.mark.parametrize(
    "field,value",
    [
        ("service_id", "localindexservice_" + "f" * 32),
        ("service_revision_id", "localindexservicerev_" + "f" * 32),
        ("service_identity_sha256", "sha256:" + "f" * 64),
        ("service_policy_revision_id", "accessrev_" + "f" * 32),
        ("service_policy_sha256", "sha256:" + "f" * 64),
    ],
)
def test_substituted_actor_or_service_grant_denied_before_any_io(service_owner, field, value):
    c = service_owner
    body = c.scope.request.model_dump(mode="json")
    body["actor_context"][field] = value
    request = LocalEmbeddingServiceWorkflowRequest.model_validate(seal(body, "request_sha256"))
    with (
        c.publisher.sessions() as session,
        session.begin(),
        pytest.raises(ValueError, match="FORBIDDEN"),
    ):
        c.owner.resolve_submission(session, request)
    assert not c.calls


def test_current_source_denial_precedes_control_artifact_materialization(
    service_owner, monkeypatch
):
    c = service_owner
    c.deny = True
    monkeypatch.setattr(
        "eom_workflow_runner.local_embedding_owner_admission.PinnedArtifactReadContext",
        lambda *_a: pytest.fail("control read before actual source fence"),
    )
    with (
        c.publisher.sessions() as session,
        session.begin(),
        pytest.raises(ValueError, match="FORBIDDEN"),
    ):
        c.owner.resolve_submission(session, c.scope.request)
    assert [kind for kind, _actual in c.calls] == ["source-fence"]


def test_correct_saved_audit_cannot_replace_revoked_current_authority(service_owner):
    c = service_owner
    c.deny_after_lookup = True
    with (
        c.publisher.sessions() as session,
        session.begin(),
        pytest.raises(ValueError, match="FORBIDDEN"),
    ):
        c.owner.resolve_submission(session, c.scope.request)
    assert c.calls[-2][0] == "lookup" and c.calls[-1][0] == "source-fence"


def test_wrong_authorization_audit_does_not_match_actual_resolved_grant(service_owner):
    c = service_owner
    body = c.scope.request.model_dump(mode="json")
    body["actor_context"]["authorization_audit_sha256"] = "sha256:" + "f" * 64
    request = LocalEmbeddingServiceWorkflowRequest.model_validate(seal(body, "request_sha256"))
    with (
        c.publisher.sessions() as session,
        session.begin(),
        pytest.raises(ValueError, match="FORBIDDEN"),
    ):
        c.owner.resolve_submission(session, request)
    assert [kind for kind, _actual in c.calls] == ["source-fence"]


def test_changed_actual_service_policy_bytes_fail_without_latest_fallback(service_owner):
    c = service_owner
    pointer = c.scope.request.native_execution_policy
    with c.publisher.sessions() as session:
        row = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
        path = Path(row.nas_path) / pointer.member_path
    path.write_bytes(b"{}")
    with (
        c.publisher.sessions() as session,
        session.begin(),
        pytest.raises(PinnedArtifactResolutionError),
    ):
        c.owner.resolve_submission(session, c.scope.request)
    assert "lookup" not in [kind for kind, _actual in c.calls]


def test_service_policy_publication_replays_and_cannot_use_old_operator_api(service_owner):
    c = service_owner
    same = c.controls.publish_service_policy(
        c.fixture.policy, idempotency_key="synthetic-service-policy", created_at=NOW
    )
    assert same.member == c.scope.request.native_execution_policy
    with pytest.raises(ValueError):
        c.controls.publish_policy(
            c.fixture.policy, idempotency_key="wrong-operator-policy", created_at=NOW
        )


def test_service_readiness_uses_same_numerical_runtime_without_claiming_authentication(
    service_owner,
):
    c = service_owner
    launcher = Mock(spec=FixedNativeIndexLauncher)
    executor = CatalogNativeEmbeddingExecutor(
        owner=c.owner,
        publisher=c.publisher,
        launcher=launcher,
        runtime_profile=c.fixture.policy.profiles[0],
        source_commit="a" * 40,
    )
    assert executor.evaluate(c.scope.request).ready
    launcher.assert_current_runtime.assert_called_once()
    launcher.run.assert_not_called()
    assert not c.calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("lease_owner", "other"),
        ("lease_token", "wflease_" + "f" * 32),
        ("lease_generation", 2),
        ("state", "CANCELLED"),
    ],
)
def test_service_mutation_preserves_shared_real_command_fence(
    service_owner, monkeypatch, field, value
):
    c = service_owner
    session, command, _workflow, lease = mutation_rows(c, monkeypatch)
    try:
        c.owner.fence_mutation(session, c.scope.request, lease)
        setattr(command, field, value)
        with pytest.raises(WorkflowError):
            c.owner.fence_mutation(session, c.scope.request, lease)
    finally:
        session.close()


def test_service_cannot_relabel_saved_workflow_as_human(service_owner, monkeypatch):
    c = service_owner
    session, _command, workflow, lease = mutation_rows(c, monkeypatch)
    workflow.created_actor_type = "human"
    try:
        with pytest.raises(ValueError, match="SUBMISSION_REPLAY_INVALID"):
            c.owner.fence_mutation(session, c.scope.request, lease)
    finally:
        session.close()
