from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_api.services.mock_exam_production_application import (
    MockExamAccessPolicyPointer,
    MockExamProductionApplicationError,
    MockExamProductionApplicationService,
    MockExamProductionDeliverableService,
)
from eom_api.services.mock_exam_production_composition import (
    build_mock_exam_production_runtime,
)
from eom_api.services.mock_exam_production_coordinator import MockExamProductionCoordinator
from eom_api.services.mock_exam_production_release_resolver import (
    RELEASED_ANALYSIS_POLICY_REVISION_ID,
    RELEASED_ANALYSIS_POLICY_SHA256,
    DatabaseAnalysisPolicyPointerReader,
    MockExamProductionReleaseError,
    ReleasedMockExamProductionResolver,
)
from eom_api_contracts.control_plane import (
    ExecutionPresetRevisionView,
    ExecutionPresetView,
    PresetRetrievalPolicyInput,
)
from eom_api_contracts.deliverables import DeliverableView
from eom_api_contracts.mock_exam_execution import (
    MockExamAnalysisPolicyPointerV1,
    MockExamAssemblyIntentV1,
    MockExamGenerationBlockResolutionV1,
    MockExamGraphPublicationInputV1,
    MockExamProductionExecutionV1,
    MockExamRatingPolicyPointerV1,
)
from eom_catalog_contracts import (
    build_integrated_science_mock_exam_production_plan,
    load_integrated_science_editorial_outline,
    load_integrated_science_mock_exam_layout_policy,
    load_integrated_science_mock_exam_policy,
)
from eom_catalog_contracts.mock_exam_production_plan import (
    MockExamProductionPlanV1,
    MockExamProductionPlanV3,
)
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey
from sqlalchemy import create_engine

NOW = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)
OPERATOR_ID = "operator_" + "a" * 32
SESSION_ID = "apisession_" + "b" * 32
PRODUCTION_REQUEST_ID = "productionreq_" + "c" * 32
ACCESS = MockExamAccessPolicyPointer(
    access_policy_revision_id="accessrev_" + "d" * 32,
    access_policy_sha256="sha256:" + "d" * 64,
)
ANALYSIS = MockExamAnalysisPolicyPointerV1(
    risk_policy_revision_id=RELEASED_ANALYSIS_POLICY_REVISION_ID,
    risk_policy_sha256=RELEASED_ANALYSIS_POLICY_SHA256,
)
RATING = MockExamRatingPolicyPointerV1(
    rating_policy_revision_id="ratingpolicyrev_" + "e" * 32,
    rating_policy_sha256="sha256:" + "e" * 64,
)


def _plan() -> MockExamProductionPlanV1:
    return build_integrated_science_mock_exam_production_plan(
        policy=load_integrated_science_mock_exam_policy(),
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        outline=load_integrated_science_editorial_outline(),
    )


def _actor(
    *,
    operator_id: str = OPERATOR_ID,
    permissions: frozenset[PermissionKey] = frozenset(PermissionKey),
    authenticated_at: datetime = NOW,
) -> ActorContext:
    return ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=operator_id,
        session_id=SESSION_ID,
        request_id="mockexam-runtime-test",
        authentication_time=authenticated_at,
        permissions=permissions,
        source=ActorSource.CLI,
    )


def _generation() -> MockExamGenerationBlockResolutionV1:
    block = _plan().one_item_generation_block
    return MockExamGenerationBlockResolutionV1(
        generation_block_key=block.block_key,
        generation_block_revision=block.block_revision,
        generation_block_sha256=block.block_sha256,
        workflow_definition_key=block.workflow_definition_key,
        workflow_definition_version=block.workflow_definition_version,
        workflow_definition_sha256="sha256:" + "1" * 64,
        content_pack_release_id="packrel_" + "2" * 32,
        content_pack_key=block.content_pack_key,
        content_pack_version=block.content_pack_version,
        content_pack_release_sha256="sha256:" + "2" * 64,
        content_pack_source_tree_sha256=block.content_pack_source_tree_sha256,
        execution_preset_id="execpreset_" + "3" * 32,
        execution_preset_revision_id="execpresetrev_" + "4" * 32,
        execution_preset_key=block.execution_preset_key,
        execution_preset_sha256="sha256:" + "4" * 64,
        resolved_at=NOW,
    )


class _RiskReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def resolve_analysis_policy(
        self, *, revision_id: str, expected_sha256: str
    ) -> MockExamAnalysisPolicyPointerV1:
        self.calls.append((revision_id, expected_sha256))
        return MockExamAnalysisPolicyPointerV1(
            risk_policy_revision_id=revision_id,
            risk_policy_sha256=expected_sha256,
        )


class _PresetReader:
    def __init__(self, generation: MockExamGenerationBlockResolutionV1) -> None:
        retrieval = PresetRetrievalPolicyInput.model_construct(
            access_policy_revision_id=ACCESS.access_policy_revision_id,
            access_policy_sha256=ACCESS.access_policy_sha256,
            allowed_corpus_keys=("integrated-science-textbooks",),
        )
        revision = ExecutionPresetRevisionView.model_construct(
            preset_revision_id=generation.execution_preset_revision_id,
            preset_id=generation.execution_preset_id,
            state="RELEASED",
            content_sha256=generation.execution_preset_sha256,
            retrieval_policy=retrieval,
        )
        self.value = ExecutionPresetView.model_construct(
            preset_id=generation.execution_preset_id,
            preset_key=generation.execution_preset_key,
            state="ACTIVE",
            revisions=(revision,),
        )

    def preset(self, preset_id: str) -> ExecutionPresetView:
        assert preset_id == self.value.preset_id
        return self.value


def test_released_resolver_builds_static_25_plan_and_exact_policy_pointers() -> None:
    risk = _RiskReader()
    resolver = ReleasedMockExamProductionResolver(
        analysis_policies=risk,
        presets=_PresetReader(_generation()),
    )

    plan = resolver.production_plan()
    assert isinstance(plan, MockExamProductionPlanV3)
    assert plan.one_item_generation_block.workflow_definition_version == "1.10.0"
    assert plan.one_item_generation_block.content_pack_version == "1.15.1"
    assert plan.one_item_generation_block.trusted_evidence_usage_receipts_required is True
    assert len(plan.workflow_calls) == 25
    assert tuple(call.item_brief.mock_exam_slot.position for call in plan.workflow_calls) == tuple(
        range(1, 26)
    )
    assert resolver.production_plan() is plan
    assert resolver.analysis_policy() == ANALYSIS
    assert risk.calls == [(RELEASED_ANALYSIS_POLICY_REVISION_ID, RELEASED_ANALYSIS_POLICY_SHA256)]
    assert resolver.rating_policy().rating_policy_revision_id.startswith("ratingpolicyrev_")
    assert resolver.access_policy(_generation()) == ACCESS


def test_released_resolver_accepts_pinned_revision_after_logical_preset_retirement() -> None:
    generation = _generation()
    presets = _PresetReader(generation)
    presets.value = presets.value.model_copy(update={"state": "RETIRED"})
    resolver = ReleasedMockExamProductionResolver(
        analysis_policies=_RiskReader(),
        presets=presets,
    )

    assert resolver.access_policy(generation) == ACCESS


def test_released_resolver_rejects_stale_preset_revision() -> None:
    generation = _generation()
    presets = _PresetReader(generation)
    presets.value = presets.value.model_copy(update={"preset_key": "substituted-preset"})
    resolver = ReleasedMockExamProductionResolver(
        analysis_policies=_RiskReader(),
        presets=presets,
    )

    with pytest.raises(MockExamProductionReleaseError) as raised:
        resolver.access_policy(generation)
    assert raised.value.code == "PRODUCTION_EXECUTION_PRESET_POINTER_STALE"


def test_database_analysis_policy_reader_validates_exact_released_pointer(
    tmp_path: Path,
) -> None:
    policy_path = (
        Path(__file__).resolve().parents[2]
        / "config/knowledge-analysis/default-risk-policy.v1.json"
    )
    canonical_document = json.loads(policy_path.read_text(encoding="utf-8"))
    record = SimpleNamespace(
        state="RELEASED",
        risk_policy_revision_id=RELEASED_ANALYSIS_POLICY_REVISION_ID,
        content_sha256=RELEASED_ANALYSIS_POLICY_SHA256,
        canonical_document=canonical_document,
    )

    class Session:
        def get(self, _: Any, revision_id: str) -> Any:
            assert revision_id == RELEASED_ANALYSIS_POLICY_REVISION_ID
            return record

    @contextmanager
    def sessions() -> Iterator[Session]:
        yield Session()

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'policy.db'}")
    try:
        reader = DatabaseAnalysisPolicyPointerReader(engine)
        reader._sessions = sessions  # type: ignore[assignment]
        assert (
            reader.resolve_analysis_policy(
                revision_id=RELEASED_ANALYSIS_POLICY_REVISION_ID,
                expected_sha256=RELEASED_ANALYSIS_POLICY_SHA256,
            )
            == ANALYSIS
        )

        record.content_sha256 = "sha256:" + "9" * 64
        with pytest.raises(MockExamProductionReleaseError) as stale:
            reader.resolve_analysis_policy(
                revision_id=RELEASED_ANALYSIS_POLICY_REVISION_ID,
                expected_sha256=RELEASED_ANALYSIS_POLICY_SHA256,
            )
        assert stale.value.code == "PRODUCTION_ANALYSIS_POLICY_STALE"

        record.content_sha256 = RELEASED_ANALYSIS_POLICY_SHA256
        record.state = "RETIRED"
        with pytest.raises(MockExamProductionReleaseError) as missing:
            reader.resolve_analysis_policy(
                revision_id=RELEASED_ANALYSIS_POLICY_REVISION_ID,
                expected_sha256=RELEASED_ANALYSIS_POLICY_SHA256,
            )
        assert missing.value.code == "PRODUCTION_ANALYSIS_POLICY_MISSING"
    finally:
        engine.dispose()


class _DeliverableBoundary:
    def __init__(self) -> None:
        self.requests: list[Any] = []
        self.views: dict[str, DeliverableView] = {}

    def create_deliverable(self, request: Any, actor: ActorContext) -> tuple[str, str, int]:
        self.requests.append((request, actor.actor_id))
        suffix = request.deliverable_key.removeprefix("mock-exam-production-")
        deliverable_id = "deliverable_" + suffix
        if deliverable_id not in self.views:
            self.views[deliverable_id] = DeliverableView(
                deliverable_id=deliverable_id,
                deliverable_key=request.deliverable_key,
                deliverable_type=request.deliverable_type,
                title=request.title,
                edition=request.edition,
                lifecycle_state="PLANNED",
                deliverable_revision_id="delivrev_" + suffix,
                revision_number=1,
                created_at=NOW,
            )
        return "command_" + "f" * 32, deliverable_id, 1

    def deliverable(self, deliverable_id: str) -> DeliverableView:
        return self.views[deliverable_id]


def test_deliverable_service_replays_one_exact_mock_exam_per_request() -> None:
    boundary = _DeliverableBoundary()
    service = MockExamProductionDeliverableService(boundary, boundary)

    first = service.ensure_assembly_intent(PRODUCTION_REQUEST_ID, _actor())
    second = service.ensure_assembly_intent(PRODUCTION_REQUEST_ID, _actor())

    assert first == second
    assert first.deliverable_id == "deliverable_" + "c" * 32
    assert first.deliverable_revision_id == "delivrev_" + "c" * 32
    assert first.form_key == "production-" + "c" * 32
    assert len(boundary.views) == 1
    assert all(row[0].deliverable_type == "MOCK_EXAM" for row in boundary.requests)


def test_deliverable_service_rejects_same_key_with_different_metadata() -> None:
    boundary = _DeliverableBoundary()
    service = MockExamProductionDeliverableService(boundary, boundary)
    service.ensure_assembly_intent(PRODUCTION_REQUEST_ID, _actor())
    deliverable_id = "deliverable_" + "c" * 32
    boundary.views[deliverable_id] = boundary.views[deliverable_id].model_copy(
        update={"title": "foreign"}
    )

    with pytest.raises(MockExamProductionApplicationError) as raised:
        service.ensure_assembly_intent(PRODUCTION_REQUEST_ID, _actor())
    assert raised.value.code == "PRODUCTION_DELIVERABLE_REPLAY_CONFLICT"


class _Releases:
    def __init__(self) -> None:
        self.plan = _plan()

    def production_plan(self) -> MockExamProductionPlanV1:
        return self.plan

    @staticmethod
    def analysis_policy() -> MockExamAnalysisPolicyPointerV1:
        return ANALYSIS

    @staticmethod
    def rating_policy() -> MockExamRatingPolicyPointerV1:
        return RATING

    @staticmethod
    def access_policy(_: MockExamGenerationBlockResolutionV1) -> MockExamAccessPolicyPointer:
        return ACCESS


class _Runner:
    def __init__(self, releases: _Releases) -> None:
        self.releases = releases
        self.current: MockExamProductionExecutionV1 | None = None
        self.calls: list[tuple[str, Any]] = []

    def initialize(
        self,
        plan: MockExamProductionPlanV1,
        actor: ActorContext,
        *,
        production_request_id: str,
        at: datetime,
    ) -> MockExamProductionExecutionV1:
        self.calls.append(("initialize", production_request_id))
        self.current = MockExamProductionCoordinator.initialize(
            plan,
            production_request_id=production_request_id,
            operator_id=actor.actor_id,
            at=at,
        )
        return self.current

    def get(self, execution_id: str) -> MockExamProductionExecutionV1:
        assert self.current is not None and self.current.execution_id == execution_id
        return self.current

    def advance_items(self, *_: Any, **__: Any) -> MockExamProductionExecutionV1:
        self.calls.append(("items", None))
        assert self.current is not None
        return self.current

    def retire_items(self, *_: Any, **__: Any) -> Any:
        self.calls.append(("retire", None))
        assert self.current is not None
        return {"retired_execution_id": self.current.execution_id}

    def advance_analyses(self, *_: Any, **__: Any) -> MockExamProductionExecutionV1:
        self.calls.append(("analyses", None))
        assert self.current is not None
        return self.current

    def review_analyses(self, *_: Any, **__: Any) -> MockExamProductionExecutionV1:
        self.calls.append(("analysis-review", None))
        assert self.current is not None
        return self.current

    def publish_next_graph_batch(self, *_: Any, **__: Any) -> MockExamProductionExecutionV1:
        self.calls.append(("graph", None))
        assert self.current is not None
        return self.current

    def publish_ratings(self, *_: Any, **__: Any) -> MockExamProductionExecutionV1:
        self.calls.append(("ratings", None))
        assert self.current is not None
        return self.current

    def advance_assembly(
        self,
        _: MockExamProductionPlanV1,
        __: str,
        ___: ActorContext,
        intent: MockExamAssemblyIntentV1,
        *,
        at: datetime,
    ) -> MockExamProductionExecutionV1:
        self.calls.append(("assembly", intent))
        assert self.current is not None
        self.current = self.current.model_copy(
            update={"assembly_intent": intent, "checkpointed_at": at}
        )
        return self.current

    def advance_hwpx(self, *_: Any, **__: Any) -> MockExamProductionExecutionV1:
        self.calls.append(("hwpx", None))
        assert self.current is not None
        return self.current


def _application() -> tuple[
    MockExamProductionApplicationService,
    _Runner,
    _DeliverableBoundary,
]:
    releases = _Releases()
    runner = _Runner(releases)
    boundary = _DeliverableBoundary()
    return (
        MockExamProductionApplicationService(
            runner=runner,  # type: ignore[arg-type]
            releases=releases,
            deliverables=MockExamProductionDeliverableService(boundary, boundary),
            fresh_auth_seconds=900,
            clock=lambda: NOW,
        ),
        runner,
        boundary,
    )


def test_application_requires_real_session_and_phase_permissions_before_mutation() -> None:
    application, runner, _ = _application()
    unauthorized = _actor(permissions=frozenset({PermissionKey.WORKFLOW_READ}))

    with pytest.raises(MockExamProductionApplicationError) as raised:
        application.initialize(PRODUCTION_REQUEST_ID, unauthorized)
    assert raised.value.code == "PRODUCTION_OPERATOR_PERMISSION_DENIED"
    assert runner.calls == []

    checkpoint = application.initialize(PRODUCTION_REQUEST_ID, _actor())
    application.advance_items(checkpoint.execution_id, _actor())
    assert [row[0] for row in runner.calls] == ["initialize", "items"]


def test_advance_items_requires_knowledge_graph_retrieval_permission() -> None:
    application, runner, _ = _application()
    permissions = frozenset(
        permission
        for permission in PermissionKey
        if permission is not PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE
    )
    actor = _actor(permissions=permissions)
    checkpoint = application.initialize(PRODUCTION_REQUEST_ID, actor)

    with pytest.raises(MockExamProductionApplicationError) as raised:
        application.advance_items(checkpoint.execution_id, actor)
    assert raised.value.code == "PRODUCTION_OPERATOR_PERMISSION_DENIED"
    assert [row[0] for row in runner.calls] == ["initialize"]


def test_application_enforces_owner_and_fresh_authentication() -> None:
    application, runner, _ = _application()
    checkpoint = application.initialize(PRODUCTION_REQUEST_ID, _actor())

    with pytest.raises(MockExamProductionApplicationError) as owner:
        application.get(checkpoint.execution_id, _actor(operator_id="operator_" + "9" * 32))
    assert owner.value.code == "PRODUCTION_EXECUTION_OPERATOR_MISMATCH"

    stale = _actor(authenticated_at=NOW - timedelta(seconds=901))
    with pytest.raises(MockExamProductionApplicationError) as item_freshness:
        application.advance_items(checkpoint.execution_id, stale)
    assert item_freshness.value.code == "PRODUCTION_OPERATOR_REAUTHENTICATION_REQUIRED"
    assert [row[0] for row in runner.calls] == ["initialize"]

    with pytest.raises(MockExamProductionApplicationError) as freshness:
        application.advance_analyses(checkpoint.execution_id, stale)
    assert freshness.value.code == "PRODUCTION_OPERATOR_REAUTHENTICATION_REQUIRED"
    assert [row[0] for row in runner.calls] == ["initialize"]


def test_historical_retirement_ignores_current_plan_but_revalidates_pinned_checkpoint() -> None:
    application, runner, _ = _application()
    checkpoint = application.initialize(PRODUCTION_REQUEST_ID, _actor())

    # A held install may make the corrected V2 plan current before the exact V1 occurrence is
    # retired. Only the retirement use case is historical; all other phase methods retain their
    # current-plan gate.
    runner.releases.plan = runner.releases.plan.model_copy(
        update={
            "production_plan_id": "productionplan_" + "9" * 32,
            "plan_sha256": "sha256:" + "9" * 64,
        }
    )
    assert application.retire_items(checkpoint.execution_id, _actor()) == {
        "retired_execution_id": checkpoint.execution_id
    }
    assert [row[0] for row in runner.calls] == ["initialize", "retire"]

    runner.current = checkpoint.model_copy(update={"production_plan_sha256": "sha256:" + "8" * 64})
    with pytest.raises(MockExamProductionApplicationError) as tampered:
        application.retire_items(checkpoint.execution_id, _actor())
    assert tampered.value.code == "PRODUCTION_HISTORICAL_CHECKPOINT_INVALID"
    assert [row[0] for row in runner.calls] == ["initialize", "retire"]

    runner.current = checkpoint
    with pytest.raises(MockExamProductionApplicationError) as foreign_operator:
        application.retire_items(
            checkpoint.execution_id,
            _actor(operator_id="operator_" + "9" * 32),
        )
    assert foreign_operator.value.code == "PRODUCTION_EXECUTION_OPERATOR_MISMATCH"
    assert [row[0] for row in runner.calls] == ["initialize", "retire"]


def test_graph_phase_accepts_only_access_policy_from_pinned_preset() -> None:
    application, runner, _ = _application()
    checkpoint = application.initialize(PRODUCTION_REQUEST_ID, _actor())
    runner.current = checkpoint.model_copy(update={"generation_block_resolution": _generation()})
    authorization = {
        "current_graph_snapshot_revision_id": "graphrev_" + "5" * 32,
        "current_graph_snapshot_sha256": "sha256:" + "5" * 64,
        "access_policy_revision_id": "accessrev_" + "6" * 32,
        "access_policy_sha256": "sha256:" + "6" * 64,
        "authorized_at": NOW.isoformat().replace("+00:00", "Z"),
        "supersedes_authorization_sha256": None,
    }
    mismatched = MockExamGraphPublicationInputV1.model_validate(
        {**authorization, "authorization_sha256": content_sha256(authorization)}
    )

    with pytest.raises(MockExamProductionApplicationError) as raised:
        application.publish_graph(checkpoint.execution_id, _actor(), mismatched)
    assert raised.value.code == "PRODUCTION_ACCESS_POLICY_POINTER_MISMATCH"
    assert [row[0] for row in runner.calls] == ["initialize"]

    exact_authorization = {
        **authorization,
        "access_policy_revision_id": ACCESS.access_policy_revision_id,
        "access_policy_sha256": ACCESS.access_policy_sha256,
    }
    exact = MockExamGraphPublicationInputV1.model_validate(
        {
            **exact_authorization,
            "authorization_sha256": content_sha256(exact_authorization),
        }
    )
    application.publish_graph(checkpoint.execution_id, _actor(), exact)
    assert [row[0] for row in runner.calls] == ["initialize", "graph"]


def test_assembly_phase_provisions_and_replays_same_intent_only_when_ready() -> None:
    application, runner, boundary = _application()
    checkpoint = application.initialize(PRODUCTION_REQUEST_ID, _actor())

    with pytest.raises(MockExamProductionApplicationError) as not_ready:
        application.advance_assembly(checkpoint.execution_id, _actor())
    assert not_ready.value.code == "PRODUCTION_ASSEMBLY_NOT_READY"
    assert boundary.requests == []

    runner.current = checkpoint.model_copy(update={"state": "ASSEMBLY"})
    first = application.advance_assembly(checkpoint.execution_id, _actor())
    second = application.advance_assembly(checkpoint.execution_id, _actor())
    assert first.assembly_intent == second.assembly_intent
    assert len(boundary.views) == 1
    assert [row[0] for row in runner.calls] == ["initialize", "assembly", "assembly"]


def test_composition_wires_existing_adapters_behind_application_boundary(
    tmp_path: Path,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    services = SimpleNamespace(
        engine=engine,
        commands=object(),
        queries=object(),
        catalog_application=object(),
        control_plane=object(),
        exam_hwpx=object(),
        auth=object(),
        settings=SimpleNamespace(auth=SimpleNamespace(fresh_auth_seconds=900)),
    )
    checkpoint_root = tmp_path / "mock-exam-production"
    try:
        runtime = build_mock_exam_production_runtime(  # type: ignore[arg-type]
            services,
            checkpoint_root=checkpoint_root,
        )
    finally:
        engine.dispose()

    assert runtime.application.__class__.__name__ == "MockExamProductionApplicationService"
    assert runtime.authenticator.__class__.__name__ == "MockExamOperatorAuthenticator"
    assert checkpoint_root.is_dir()
