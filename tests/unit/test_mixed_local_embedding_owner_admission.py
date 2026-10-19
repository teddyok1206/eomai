"""Real local control bytes with synthetic IAM/source leaves; no runtime admission."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.local_indexing_mixed_policy import (
    LocalIndexingMixedAccessPolicy,
    supported_local_indexing_authorization_audit_sha256,
)
from eom_catalog_contracts.local_indexing_policy import (
    LocalIndexingAccessPolicy,
    local_indexing_authorization_audit_sha256,
)
from eom_catalog_service.embedding_registry_indexing_authority import (
    CatalogIndexingRegistrySourceAuthority,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryOwnerConfiguration,
    EmbeddingRegistryServiceCaller,
    ResolvedEmbeddingLookup,
)
from eom_catalog_service.local_indexing_source_authority import CatalogLocalIndexingSourceAuthority
from eom_catalog_service.local_indexing_source_ports import LocalIndexingSourceError
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactResolutionError
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    ControlFileSetMember,
)
from eom_orchestrator.local_embedding_control_artifacts import (
    SOURCE_PLAN_ARTIFACT_TYPE,
    LocalEmbeddingControlArtifactPublisher,
)
from eom_orchestrator.models import ArtifactRevisionRecord
from eom_workflow.compiler import compile_definition_data
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingServiceExecutionPolicy
from eom_workflow.local_embedding_request import parse_local_embedding_executable_request
from eom_workflow.local_embedding_request_v2 import parse_local_embedding_workflow_request_v2
from eom_workflow.local_embedding_source_plan_v2 import (
    LOCAL_EMBEDDING_SOURCE_PLAN_V2_SCHEMA_REF,
    parse_local_embedding_source_plan_v2,
)
from eom_workflow.local_embedding_workflow import LocalEmbeddingStep
from eom_workflow.local_embedding_workflow_v2 import LocalEmbeddingWorkflowDefinitionV2
from eom_workflow.models import TerminalStep, WorkflowLimits
from eom_workflow_runner.local_embedding_actor_authority import OperatorLocalEmbeddingActorAuthority
from eom_workflow_runner.local_embedding_admission import (
    ResolvedLocalEmbeddingAdmission,
    local_embedding_owner_request_actor,
    parse_supported_local_embedding_owner_request,
    validate_local_embedding_runner_admission,
    validate_local_embedding_submission_controls,
)
from eom_workflow_runner.local_embedding_owner_admission import (
    CatalogLocalEmbeddingOwnerAdmission,
    LocalEmbeddingOwnerConfiguration,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import member, native_fixture
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_local_embedding_runner_admission import scope_fixture
from tests.unit.test_local_embedding_source_plan_v2 import inputs
from tests.unit.test_local_indexing_mixed_policy import mixed_policy_document
from tests.unit.test_local_indexing_policy_contracts import policy_document
from tests.unit.test_local_indexing_runtime_admission import installed as installed
from tests.unit.test_mixed_native_workflow_carriers import carrier_fixture
from tests.unit.test_postgres_local_indexing_fence import case as case


def mixed_scope(*, service=None, runtime_sha="sha256:" + "3" * 64):
    f = carrier_fixture()
    compiled = compile_definition_data(
        LocalEmbeddingWorkflowDefinitionV2(
            schema_version="1.4",
            definition_key="local-embedding-index",
            definition_version="2.0.0",
            start_step="encode_batch",
            limits=WorkflowLimits(max_rework_cycles=0, max_step_attempts=1),
            steps=(
                LocalEmbeddingStep(),
                TerminalStep(key="complete", type="terminal", terminal_status="COMPLETED"),
            ),
        ).model_dump(mode="json"),
        "synthetic-mixed",
        set(),
    )
    policy_body = f["policy"].model_dump(mode="json")
    policy_body["workflow_definition_sha256"] = compiled.sha256
    if service is not None:
        policy_body["service"] = service.model_dump(mode="json")
    policy = LocalEmbeddingServiceExecutionPolicy.model_validate(seal(policy_body, "policy_sha256"))
    plan = f["plan"]
    grant = LocalIndexingMixedAccessPolicy.model_validate(
        mixed_policy_document(
            access_policy_revision_id="accessrev_" + "f" * 32,
            service=policy.service.model_dump(mode="json"),
            runtime_configuration_sha256=runtime_sha,
            corpus_id=plan.corpus_id,
            graph_id=plan.graph_snapshot.graph_id,
            source_access_policy_revision_id=plan.access_policy_revision_id,
            source_access_policy_sha256=plan.access_policy_sha256,
            namespaces=[plan.namespace.model_dump(mode="json")],
            space=plan.space.model_dump(mode="json"),
            recipe=plan.recipe.model_dump(mode="json"),
            native_execution_policy_sha256=policy.policy_sha256,
            resource_profile_sha256=policy.profiles[0].resource_profile.resource_profile_sha256,
        )
    )
    audit_sha = supported_local_indexing_authorization_audit_sha256(grant)
    request = parse_local_embedding_workflow_request_v2(
        seal(
            f["request"].model_dump(mode="json")
            | {
                "workflow_definition_sha256": compiled.sha256,
                "native_execution_policy": member(
                    "policy.json",
                    f["request"].native_execution_policy.schema_ref,
                    policy.model_dump(mode="json"),
                    "3",
                ).model_dump(mode="json"),
                "native_execution_policy_sha256": policy.policy_sha256,
                "actor_context": f["request"].actor_context.model_dump(mode="json")
                | {
                    **policy.service.model_dump(mode="json"),
                    "service_policy_revision_id": grant.access_policy_revision_id,
                    "service_policy_sha256": grant.content_sha256,
                    "authorization_audit_sha256": audit_sha,
                },
            },
            "request_sha256",
        )
    )
    return ResolvedLocalEmbeddingAdmission(request, plan, policy), compiled, grant


@pytest.fixture
def mixed_owner(case, tmp_path, monkeypatch):
    fence, _synthetic_sql = case
    scope, compiled, grant = mixed_scope(
        service=fence.pin.service, runtime_sha=fence.pin.configuration_sha256
    )
    publisher, _engine = _publisher(tmp_path)
    publisher.settings = replace(publisher.settings, workspace_root=tmp_path)
    plan_raw = canonical_json_bytes(scope.plan.model_dump(mode="json"))
    plan_path = tmp_path / "source-plan.json"
    plan_path.write_bytes(plan_raw)
    plan_path.chmod(0o600)
    saved = publisher.publish(
        members=(
            ControlFileSetMember(
                "source-plan.json",
                plan_path,
                sha256_bytes(plan_raw),
                len(plan_raw),
                LOCAL_EMBEDDING_SOURCE_PLAN_V2_SCHEMA_REF,
                "application/json",
            ),
        ),
        primary_file="source-plan.json",
        artifact_type=SOURCE_PLAN_ARTIFACT_TYPE,
        manifest_version=CONTROL_FILE_SET_PROTOCOL,
        idempotency_key="synthetic-mixed-owner-plan",
        source_commit="a" * 40,
        created_at=scope.policy.created_at,
    )
    saved_policy = LocalEmbeddingControlArtifactPublisher(
        publisher, source_commit="a" * 40
    ).publish_service_policy(
        scope.policy,
        idempotency_key="synthetic-mixed-owner-policy",
        created_at=scope.policy.created_at,
    )
    plan_member = scope.request.source_plan.model_copy(
        update={
            "artifact_id": saved.artifact_id,
            "artifact_revision_id": saved.artifact_revision_id,
            "sha256": saved.primary_sha256,
        }
    )
    request = parse_local_embedding_workflow_request_v2(
        seal(
            scope.request.model_dump(mode="json")
            | {
                "source_plan": plan_member.model_dump(mode="json"),
                "native_execution_policy": saved_policy.member.model_dump(mode="json"),
            },
            "request_sha256",
        )
    )
    scope = ResolvedLocalEmbeddingAdmission(request, scope.plan, scope.policy)
    gate = CatalogIndexingRegistrySourceAuthority(
        CatalogLocalIndexingSourceAuthority(Mock(), fence),
        grant.access_policy_revision_id,
        grant.content_sha256,
        scope.policy.policy_sha256,
        request.resource_profile.resource_profile_sha256,
    )
    config = LocalEmbeddingOwnerConfiguration(
        EmbeddingRegistryOwnerConfiguration(
            request.corpus_id,
            request.namespace,
            request.space,
            scope.plan.recipe,
            grant.source_classes,
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
    _query, original_current, bases = inputs("CONTENT_ONLY")
    current = ResolvedEmbeddingLookup(
        scope.plan.corpus_id,
        scope.plan.space,
        scope.plan.recipe,
        scope.plan.sources,
        original_current.entries,
        base_analysis_run_ids=tuple(sorted(bases.items())),
    )
    c = SimpleNamespace(
        owner=owner,
        publisher=publisher,
        scope=scope,
        compiled=compiled,
        grant=grant,
        current=current,
        calls=[],
        deny=False,
        late_deny=False,
    )

    def source_io(_self, session, intent):
        c.calls.append(("source", session))
        assert session.get_transaction() is not None
        assert intent.service_policy_sha256 == grant.content_sha256
        if c.deny:
            raise LocalIndexingSourceError("LOCAL_INDEXING_SOURCE_FORBIDDEN")
        return c.grant

    def authorize(session, caller, query):
        assert type(caller) is EmbeddingRegistryServiceCaller and not hasattr(caller, "operator_id")
        gate.authorize_scope(session, caller, query, config.registry)

    def lookup(session, caller, selection):
        authorize(session, caller, selection.scope)
        assert selection.source_revision_ids == tuple(
            s.item_revision_id for s in scope.plan.sources
        )
        c.calls.append(("lookup", session))
        if c.late_deny:
            c.deny = True
        return c.current

    monkeypatch.setattr(CatalogLocalIndexingSourceAuthority, "authorize_scope", source_io)
    monkeypatch.setattr(owner.catalog, "authorize_scope", authorize)
    monkeypatch.setattr(owner.catalog, "resolve_selected_sources", lookup)
    return c


def test_explicit_definition_request_plan_and_service_family_pairing():
    scope, compiled, _grant = mixed_scope()
    service_id = scope.request.actor_context.service_id
    assert local_embedding_owner_request_actor(scope.request) == (
        "local_indexing_service",
        service_id,
    )
    assert (
        validate_local_embedding_runner_admission(
            scope, compiled, actor_type="local_indexing_service", actor_id=service_id
        )
        == scope
    )
    assert parse_supported_local_embedding_owner_request(scope.request) == scope.request
    with pytest.raises(ValueError):
        parse_local_embedding_executable_request(scope.request)
    with pytest.raises(ValueError):
        ResolvedLocalEmbeddingAdmission(scope.request, native_fixture().plan, scope.policy)
    with pytest.raises(ValueError):
        ResolvedLocalEmbeddingAdmission(scope.request, scope.plan, native_fixture().policy)
    old = native_fixture()
    with pytest.raises(ValueError):
        ResolvedLocalEmbeddingAdmission(old.request, scope.plan, old.policy)
    with pytest.raises(ValueError, match="OPERATOR_UNAVAILABLE"):
        OperatorLocalEmbeddingActorAuthority(Mock()).registry_caller(scope.request)


def test_supported_audit_reuses_original_leaf_without_reinterpreting_old_policy():
    old = LocalIndexingAccessPolicy.model_validate(policy_document())
    assert supported_local_indexing_authorization_audit_sha256(
        old
    ) == local_indexing_authorization_audit_sha256(old)
    _scope, _compiled, grant = mixed_scope()
    assert supported_local_indexing_authorization_audit_sha256(grant)
    with pytest.raises(ValueError):
        local_indexing_authorization_audit_sha256(grant)
    with pytest.raises(ValueError):
        supported_local_indexing_authorization_audit_sha256(
            grant.model_copy(update={"roles": ["ADMIN"]})
        )


@pytest.mark.parametrize("fault", ("old_definition", "hash", "canonical"))
def test_mixed_controls_do_not_borrow_old_definition_or_forged_compiled_snapshot(fault):
    scope, compiled, _grant = mixed_scope()
    if fault == "old_definition":
        _, compiled = scope_fixture()
    elif fault == "hash":
        compiled = replace(compiled, sha256="sha256:" + "f" * 64)
    else:
        compiled = replace(compiled, canonical_bytes=b"{}")
    actor = local_embedding_owner_request_actor(scope.request)
    with pytest.raises(ValueError):
        validate_local_embedding_submission_controls(
            scope, compiled, actor_type=actor[0], actor_id=actor[1]
        )


@pytest.mark.parametrize("field", ("request", "plan", "policy"))
def test_copied_extras_fail_at_resolved_scope_boundary(field):
    scope, _compiled, _grant = mixed_scope()
    values = dict(request=scope.request, plan=scope.plan, policy=scope.policy)
    values[field] = values[field].model_copy(update={"undeclared": "invalid"})
    with pytest.raises(ValueError):
        ResolvedLocalEmbeddingAdmission(**values)


def test_same_owner_rebuilds_exact_mixed_plan_with_current_real_base_ids(mixed_owner):
    c = mixed_owner
    with c.publisher.sessions() as session, session.begin():
        resolved = c.owner.resolve_sources(session, c.scope.request)
        assert resolved.admission == c.scope
        assert len(resolved.entries) == 2
        assert len([kind for kind, _ in c.calls if kind == "source"]) == 4
        assert all(actual is session for _, actual in c.calls)
        assert c.owner.registry_caller(c.scope.request).service == c.grant.service
    with pytest.raises(ValueError, match="OPERATOR_UNAVAILABLE"):
        _ = c.owner.identity


@pytest.mark.parametrize("fault", ("deny", "legacy_grant", "wrong_audit", "actor"))
def test_current_service_policy_and_fence_precede_all_control_reads(
    mixed_owner, monkeypatch, fault
):
    c = mixed_owner
    request = c.scope.request
    if fault == "deny":
        c.deny = True
    elif fault == "legacy_grant":
        c.grant = carrier_fixture()["original"].grant
    else:
        values = request.model_dump(mode="json")
        values["actor_context"][
            "authorization_audit_sha256" if fault == "wrong_audit" else "service_id"
        ] = "sha256:" + "f" * 64 if fault == "wrong_audit" else "localindexservice_" + "f" * 32
        request = parse_local_embedding_workflow_request_v2(seal(values, "request_sha256"))
    monkeypatch.setattr(
        "eom_workflow_runner.local_embedding_owner_admission.PinnedArtifactReadContext",
        lambda *_args: pytest.fail("control bytes before service/source fence"),
    )
    with c.publisher.sessions() as session, session.begin(), pytest.raises(ValueError):
        c.owner.resolve_submission(session, request)


def test_revocation_after_source_resolution_is_not_success(mixed_owner):
    c = mixed_owner
    c.late_deny = True
    with (
        c.publisher.sessions() as session,
        session.begin(),
        pytest.raises(LocalIndexingSourceError),
    ):
        c.owner.resolve_submission(session, c.scope.request)
    assert c.calls[-2][0] == "lookup" and c.calls[-1][0] == "source"


@pytest.mark.parametrize("fault", ("missing_base", "changed_base", "missing_report"))
def test_current_base_or_review_removal_never_reuses_saved_mixed_plan(mixed_owner, fault):
    c = mixed_owner
    if fault == "missing_report":
        c.current = replace(c.current, entries=())
    else:
        bases = c.current.base_analysis_run_ids
        c.current = replace(
            c.current,
            base_analysis_run_ids=(bases[0],)
            if fault == "missing_base"
            else (bases[0], (bases[1][0], "analysisrun_" + "f" * 32)),
        )
    with c.publisher.sessions() as session, session.begin(), pytest.raises(ValueError):
        c.owner.resolve_submission(session, c.scope.request)


def test_changed_control_bytes_do_not_resolve_current_latest(mixed_owner):
    c = mixed_owner
    with c.publisher.sessions() as session:
        row = session.get(ArtifactRevisionRecord, c.scope.request.source_plan.artifact_revision_id)
        path = Path(row.nas_path) / "source-plan.json"
    path.write_bytes(b"{}")
    with (
        c.publisher.sessions() as session,
        session.begin(),
        pytest.raises(PinnedArtifactResolutionError),
    ):
        c.owner.resolve_submission(session, c.scope.request)
    assert "lookup" not in [kind for kind, _ in c.calls]


def test_zero_demand_mixed_scope_is_coverage_only_not_compute():
    scope, compiled, _grant = mixed_scope()
    values = scope.plan.model_dump(mode="json") | {
        "demands": [],
        "missing_solution_report_revision_ids": [s.item_revision_id for s in scope.plan.sources],
        "encoding_set_sha256": "unused",
    }
    from eom_catalog_contracts.inference_transfer_embedding import embedding_input_set_sha256

    values["encoding_set_sha256"] = embedding_input_set_sha256(())
    plan = parse_local_embedding_source_plan_v2(seal(values, "plan_sha256"))
    request = parse_local_embedding_workflow_request_v2(
        seal(
            scope.request.model_dump(mode="json")
            | {
                "source_plan": member(
                    "source-plan.json",
                    LOCAL_EMBEDDING_SOURCE_PLAN_V2_SCHEMA_REF,
                    plan.model_dump(mode="json"),
                    "2",
                ).model_dump(mode="json"),
                "source_plan_sha256": plan.plan_sha256,
            },
            "request_sha256",
        )
    )
    empty = ResolvedLocalEmbeddingAdmission(request, plan, scope.policy)
    actor = local_embedding_owner_request_actor(request)
    assert (
        validate_local_embedding_submission_controls(
            empty, compiled, actor_type=actor[0], actor_id=actor[1]
        )
        == empty
    )
    with pytest.raises(ValueError, match="COVERAGE_ONLY"):
        validate_local_embedding_runner_admission(
            empty, compiled, actor_type=actor[0], actor_id=actor[1]
        )
