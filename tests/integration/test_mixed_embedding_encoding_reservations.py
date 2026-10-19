"""Disposable PostgreSQL mixed claims, not actual IAM, NAS or numerical execution."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.embedding_encoding_reservation_storage import (
    EmbeddingEncodingReservationStorage,
)
from eom_orchestrator.embedding_encoding_reservations import EmbeddingEncodingReservations
from eom_orchestrator.models import JobEventRecord, JobRecord
from eom_orchestrator.native_embedding_launch_identity import create_native_embedding_launch
from eom_workflow.local_embedding_encoding_ownership_v2 import EmbeddingEncodingReadResultV2
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import encoding_identity, seal
from tests.unit.local_embedding_admission_fixtures import member
from tests.unit.test_embedding_encoding_reservations import SyntheticAdmission
from tests.unit.test_mixed_native_workflow_carriers import carrier_fixture

pytestmark = pytest.mark.integration


def test_mixed_protocol_preparation_is_explicit_exact_and_preserves_numerical1(
    guarded_engine: Engine,
) -> None:
    from eom_orchestrator.embedding_encoding_reservation_storage import (
        EmbeddingEncodingReservationError,
    )
    from eom_orchestrator.models import ProtocolVersionRecord

    with guarded_engine.connect() as connection:
        connection.exec_driver_sql(
            "CREATE TEMP TABLE protocol_versions "
            "(LIKE app.protocol_versions INCLUDING ALL) ON COMMIT DROP"
        )
        with Session(bind=connection) as session:
            with pytest.raises(EmbeddingEncodingReservationError, match="PROTOCOL_UNAVAILABLE"):
                EmbeddingEncodingReservationStorage.require_mixed_ownership_protocol(session)
            EmbeddingEncodingReservationStorage.prepare_protocol(session)
            original = session.get(
                ProtocolVersionRecord, "embedding-encoding-job/1.0"
            ).schema_sha256
            EmbeddingEncodingReservationStorage.prepare_mixed_ownership_protocol(session)
            EmbeddingEncodingReservationStorage.prepare_mixed_ownership_protocol(session)
            EmbeddingEncodingReservationStorage.require_mixed_ownership_protocol(session)
            assert session.scalar(select(func.count()).select_from(ProtocolVersionRecord)) == 2
            session.execute(
                text(
                    "UPDATE pg_temp.protocol_versions SET schema_sha256=:sha "
                    "WHERE version='embedding-encoding-ownership/2.0'"
                ),
                {"sha": "sha256:" + "f" * 64},
            )
            with pytest.raises(EmbeddingEncodingReservationError, match="PROTOCOL_UNAVAILABLE"):
                EmbeddingEncodingReservationStorage.prepare_mixed_ownership_protocol(session)
            EmbeddingEncodingReservationStorage.require_protocol(session)
            assert (
                session.get(ProtocolVersionRecord, "embedding-encoding-job/1.0").schema_sha256
                == original
            )
            assert (
                session.get(ProtocolVersionRecord, "embedding-encoding-ownership/2.0").schema_sha256
                == "sha256:" + "f" * 64
            )
        connection.rollback()


def _scope(engine: Engine) -> tuple[SimpleNamespace, SimpleNamespace]:
    from eom_catalog_contracts.inference_transfer_embedding import embedding_input_set_sha256

    f = carrier_fixture()
    plan_body = f["plan"].model_dump(mode="json")
    partition = "test-" + uuid4().hex
    plan_body["namespace"]["storage_partition"] = partition
    texts = {row.encoding.encoding_sha256: row.text for row in f["input"].rows}
    encodings = {}
    for demand in plan_body["demands"]:
        encoding = encoding_identity(
            texts[demand["encoding"]["encoding_sha256"]],
            f["plan"].space,
            storage_partition=partition,
        )
        demand["encoding"] = encoding.model_dump(mode="json")
        encodings[encoding.encoding_sha256] = encoding
    plan_body["encoding_set_sha256"] = embedding_input_set_sha256(
        tuple(encodings[key] for key in sorted(encodings))
    )
    plan = type(f["plan"]).model_validate(seal(plan_body, "plan_sha256"))
    pointer = member(
        "source-plan.json", f["request"].source_plan.schema_ref, plan.model_dump(mode="json")
    )
    request = type(f["request"]).model_validate(
        seal(
            f["request"].model_dump(mode="json")
            | {
                "namespace": plan.namespace.model_dump(mode="json"),
                "source_plan": pointer.model_dump(mode="json"),
                "source_plan_sha256": plan.plan_sha256,
            },
            "request_sha256",
        )
    )
    scopes = []
    with Session(engine) as session, session.begin():
        EmbeddingEncodingReservationStorage.prepare_protocol(session)
        EmbeddingEncodingReservationStorage.prepare_mixed_ownership_protocol(session)
        for _ in range(2):
            observation = create_native_embedding_launch(
                session,
                request=request,
                workflow_id="workflow_" + uuid4().hex,
                step_run_id="steprun_" + uuid4().hex,
                command_id="wfcmd_" + uuid4().hex,
                runner_id="synthetic-mixed-claim",
                lease_generation=1,
            )
            scopes.append(
                SimpleNamespace(
                    request=request,
                    plan=plan,
                    policy=f["policy"],
                    association=SimpleNamespace(intent=observation.intent),
                )
            )
    return scopes[0], scopes[1]


def test_actual_two_mixed_launches_claim_same_numeric_batch_once_and_replay(
    guarded_engine: Engine,
) -> None:
    from eom_workflow.local_embedding_encoding_job import EmbeddingEncodingJobRequest

    left, right = _scope(guarded_engine)
    encodings = {d.encoding.encoding_sha256: d.encoding for d in left.plan.demands}
    requests = tuple(
        EmbeddingEncodingJobRequest.model_validate(
            seal(
                {
                    "schema_version": "embedding-encoding-job/1.0",
                    "record_type": "REQUEST",
                    "purpose": "LOCAL_EMBEDDING",
                    "space": left.plan.space.model_dump(mode="json"),
                    "encoding": encodings[key].model_dump(mode="json"),
                },
                "request_sha256",
            )
        )
        for key in sorted(encodings)
    )
    owners = tuple(
        EmbeddingEncodingReservations(
            build_session_factory(guarded_engine), SyntheticAdmission(scope)
        )
        for scope in (left, right)
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(owner.reserve_and_attach, requests, scope.association.intent)
            for owner, scope in zip(owners, (left, right), strict=True)
        ]
        results = tuple(future.result(timeout=30) for future in futures)
    by_encoding = {}
    for values in results:
        assert all(isinstance(value, EmbeddingEncodingReadResultV2) for value in values)
        for value in values:
            by_encoding.setdefault(value.owned_job.request.encoding.encoding_sha256, []).append(
                value
            )
    assert len(by_encoding) == len(requests)
    for values in by_encoding.values():
        assert {value.status for value in values} == {"OWNED", "BORROWED"}
        assert values[0].owned_job == values[1].owned_job
        assert values[0].owner_intent == values[1].owner_intent
    ids = tuple(value.owned_job.job_reference.job_id for value in results[0])
    with Session(guarded_engine) as session:
        before = session.scalar(
            select(func.count()).select_from(JobEventRecord).where(JobEventRecord.job_id.in_(ids))
        )
        jobs = tuple(session.scalars(select(JobRecord).where(JobRecord.job_id.in_(ids))))
        assert len(jobs) == len(requests)
        assert all(
            job.protocol_version == "embedding-encoding-job/1.0" and job.worker_slot_id is None
            for job in jobs
        )
        assert all(content_sha256(job.request) != job.request_hash for job in jobs)
        launches = tuple(
            session.scalars(
                select(JobRecord).where(
                    JobRecord.job_id.in_(
                        scope.association.intent.native_launch_job_id for scope in (left, right)
                    )
                )
            )
        )
        assert len(launches) == 2 and all(
            job.protocol_version == "embedding-encoding-ownership/2.0" for job in launches
        )
    for owner, scope, original in zip(owners, (left, right), results, strict=True):
        assert owner.reserve_and_attach(requests, scope.association.intent) == original
    with Session(guarded_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(JobEventRecord.job_id.in_(ids))
            )
            == before
        )
