"""Disposable PostgreSQL official closure/replay; OS/source/Artifact leaves synthetic."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.embedding_gpu_control import EmbeddingGpuAllocationRequest
from eom_catalog_contracts.embedding_work_batch import EmbeddingWorkBatchScope
from eom_catalog_service.embedding_unbound_failure_read import ResolvedUnboundControlFailure
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore
from eom_orchestrator.models import JobEventRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.embedding_batch_plan import (
    EmbeddingBatchAllocation,
    EmbeddingBatchPlanRequest,
    EmbeddingBatchSelection,
)
from eom_workflow.embedding_unbound_control_failure import (
    UNBOUND_CONTROL_FAILURE_SCHEMA,
    UnboundEmbeddingControlFailure,
)
from eom_workflow_runner import embedding_unbound_plan_failure as application
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_plan import member, planning_case
from tests.unit.test_embedding_unbound_control_failure import proof_document

pytestmark = pytest.mark.integration


@pytest.fixture
def original(guarded_engine, monkeypatch):
    case = planning_case(purpose="INDEX", batch_id="embeddingbatch_" + uuid4().hex)
    scope = EmbeddingWorkBatchScope.model_validate(
        seal(
            case.request.scope.model_dump(mode="json")
            | dict(
                actor_kind="LOCAL_INDEXING_SERVICE", actor_id="localindexservice_" + uuid4().hex
            ),
            "scope_sha256",
        )
    )
    selection = EmbeddingBatchSelection.model_validate(
        seal(
            case.selection.model_dump(mode="json")
            | dict(scope=scope.model_dump(mode="json"), views=["CONTENT_ONLY"]),
            "selection_sha256",
        )
    )
    request = EmbeddingBatchPlanRequest.model_validate(
        seal(
            case.request.model_dump(mode="json")
            | dict(
                scope=scope.model_dump(mode="json"),
                selection_sha256=selection.selection_sha256,
                selection_manifest=member(
                    "selection.json", request_schema(), selection, "1"
                ).model_dump(mode="json"),
                child_selection_sha256s=list(selection.child_selection_sha256s),
            ),
            "request_sha256",
        )
    )
    control = EmbeddingGpuAllocationRequest.model_validate(
        seal(
            case.allocation.control_request.model_dump(mode="json")
            | dict(
                parent_request_sha256=request.request_sha256,
                child_set_sha256=content_sha256(list(request.child_selection_sha256s)),
            ),
            "message_sha256",
        )
    )
    allocation = EmbeddingBatchAllocation.model_validate(
        seal(
            case.allocation.model_dump(mode="json")
            | dict(
                request_sha256=request.request_sha256,
                control_request=control.model_dump(mode="json"),
            ),
            "record_sha256",
        )
    )
    store = EmbeddingBatchPlanStore(request, selection, case.policy)
    with Session(guarded_engine) as session, session.begin():
        allocated, _ = store.allocate(session, allocation)
    proof = UnboundEmbeddingControlFailure.model_validate(
        proof_document(
            parent_plan_job_id=allocated.job_id,
            parent_request_sha256=request.request_sha256,
            allocation_attempt_id=control.allocation_attempt_id,
            allocation_request_sha256=control.message_sha256,
        )
    )
    raw = canonical_json_bytes(proof)
    evidence = ArtifactMemberPointer(
        artifact_id="artifact_" + uuid4().hex,
        artifact_revision_id="rev_" + uuid4().hex,
        member_path=application.UNBOUND_CONTROL_FAILURE_MEMBER,
        media_type="application/json",
        schema_ref=UNBOUND_CONTROL_FAILURE_SCHEMA,
        sha256=sha256_bytes(raw),
    )
    state = SimpleNamespace(
        engine=guarded_engine,
        store=store,
        proof=proof,
        evidence=evidence,
        late=False,
        barrier=None,
        payload=raw,
    )

    @contextmanager
    def physical(value):
        assert value == proof
        if state.barrier is not None:
            state.barrier.wait(timeout=10)
        yield ResolvedUnboundControlFailure(value, control)
        if state.late:
            raise ValueError("SYNTHETIC_ORIGINAL_CONTROL_CHANGED")

    class Reader:
        def prefetch(self, values):
            assert values == ((evidence.artifact_id, evidence.artifact_revision_id),)

        def read_pinned(self, **kwargs):
            assert kwargs["sha256"] == evidence.sha256
            return SimpleNamespace(payload=state.payload)

        def revalidate_provenance(self):
            pass

    monkeypatch.setattr(application, "read_unbound_embedding_control_failure", physical)
    monkeypatch.setattr(
        application, "resolve_embedding_batch_plan_controls", lambda *a: (selection, case.policy)
    )
    monkeypatch.setattr(application.PinnedArtifactReadContext, "for_session", lambda *a: Reader())
    return state


def request_schema():
    return "eom://schemas/workflow/embedding-batch-plan/1.0#/$defs/selection"


def apply(case):
    with Session(case.engine) as session, session.begin():
        return application.record_unbound_embedding_plan_failure(session, case.proof, case.evidence)


def test_actual_owner_transaction_and_concurrent_exact_replay(original):
    original.barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: apply(original), range(2)))
    assert results[0] == results[1] and results[0].state == "FAILED"
    original.barrier = None
    assert apply(original) == results[0]
    with Session(original.engine) as session, session.begin():
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(
                    JobEventRecord.job_id == results[0].job_id,
                    JobEventRecord.event == "EMBEDDING_PLAN_FAILED",
                )
            )
            == 1
        )


@pytest.mark.parametrize("fault", ("late_physical", "artifact", "published"))
def test_changed_or_published_evidence_rolls_back(original, monkeypatch, fault):
    if fault == "late_physical":
        original.late = True
    elif fault == "artifact":
        original.payload = b"{}"
    else:
        monkeypatch.setattr(
            application, "batch_execution_publication_exists", lambda *a, **kw: True
        )
    with pytest.raises(ValueError):
        apply(original)
    with Session(original.engine) as session, session.begin():
        current = original.store.read(session)
    assert current.state == "CLAIMED" and current.failure is None
