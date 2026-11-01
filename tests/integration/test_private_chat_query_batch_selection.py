"""Real disposable PG publication/replay; explicit synthetic IAM, Chat and document heads."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.models import JobRecord
from eom_orchestrator.settings import Settings
from sqlalchemy import select

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.test_private_chat_query_batch_selection import selection_case

pytestmark = pytest.mark.integration


@pytest.fixture
def selected(guarded_engine, tmp_path, monkeypatch):
    nas = tmp_path / "nas"
    nas.mkdir(mode=0o700)
    publisher = ControlFileSetPublisher(
        guarded_engine,
        Settings(staging_root=tmp_path / "staging", nas_artifact_root=nas, workspace_root=tmp_path),
    )
    return selection_case(tmp_path, monkeypatch, publisher=publisher)


def test_concurrent_initial_calls_share_one_original_selection_without_compute(
    selected, monkeypatch
):
    case = selected
    ready = Barrier(2)
    original = case.selector._new_selection

    def capture(request):
        value = original(request)
        # Roots are closed before concurrent canonical publication begins.
        ready.wait(timeout=30)
        return value

    monkeypatch.setattr(case.selector, "_new_selection", capture)
    with case.value.publisher.sessions() as session:
        prior = set(session.scalars(select(JobRecord.job_id)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = [pool.submit(case.selector.prepare, case.request) for _ in range(2)]
        first, second = (run.result(timeout=45) for run in runs)
    assert first.parent == second.parent and first.manifest == second.manifest
    with case.value.publisher.sessions() as session:
        created = tuple(session.scalars(select(JobRecord).where(JobRecord.job_id.not_in(prior))))
        assert len(created) == 1
        assert created[0].task_type == "control_embedding_batch_selection"
        assert created[0].status == "SUCCEEDED"


def test_interruption_after_publication_reuses_original_without_latest_lookup(
    selected, monkeypatch
):
    case = selected
    original = case.selector._read_selection

    def interrupted(*_args):
        raise RuntimeError("synthetic-interruption-after-selection-commit")

    monkeypatch.setattr(case.selector, "_read_selection", interrupted)
    with pytest.raises(RuntimeError, match="synthetic-interruption"):
        case.selector.prepare(case.request)
    with case.value.publisher.sessions() as session:
        original_jobs = set(session.scalars(select(JobRecord.job_id)))
    case.heads.clear()
    monkeypatch.setattr(case.selector, "_read_selection", original)
    result = case.selector.prepare(case.request)
    assert result.selection == case.selection and case.captures == ["CPU", "CUDA"]
    with case.value.publisher.sessions() as session:
        assert set(session.scalars(select(JobRecord.job_id))) == original_jobs


def test_late_source_withdrawal_keeps_metadata_but_cannot_start_model_work(selected, monkeypatch):
    case = selected
    original = case.selector.controls.reuse_or_publish_batch_selection
    published = []

    def publish(*args, **kwargs):
        pointer = original(*args, **kwargs)
        published.append(pointer)
        case.value.fault.value = "public"
        return pointer

    monkeypatch.setattr(case.selector.controls, "reuse_or_publish_batch_selection", publish)
    with pytest.raises(ValueError):
        case.selector.prepare(case.request)
    with case.value.publisher.sessions() as session:
        assert len(published) == 1
        own = tuple(
            session.scalars(
                select(JobRecord).where(JobRecord.logical_artifact_id == published[0].artifact_id)
            )
        )
        assert len(own) == 1 and own[0].status == "SUCCEEDED"
    case.value.fault.value = None
    case.heads.clear()
    assert case.selector.prepare(case.request).selection == case.selection
