"""Original Job/receipt ordering in disposable SQLite; source and byte reader are synthetic."""

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkLaunchReceipt,
    BenchmarkNearTieReference,
    embedding_device_benchmark_bytes,
)
from eom_identifiers import sha256_bytes
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkLaunchAuthorization

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_cpu_reference import cpu_reference
from tests.unit.test_embedding_benchmark_launch_history import (
    invocation_for,
    receipt_for,
)
from tests.unit.test_embedding_benchmark_launch_history import (
    storage as storage,
)


def original_second_launch(storage, fault=None):
    sessions, admission, reader, journal, _job = storage
    first = invocation_for(storage, 1)
    with sessions() as session, session.begin():
        journal.reserve(session, admission.request, first)
    receipt = receipt_for(storage, first)
    reference, pointer, raw, binary = cpu_reference(
        first,
        admission.request,
        receipt.worker_result.artifact_id,
        receipt.worker_result.artifact_revision_id,
    )
    if fault == "foreign-request":
        body = reference.model_dump(mode="json")
        body["request_sha256"] = "sha256:" + "f" * 64
        reference = BenchmarkNearTieReference.model_validate(seal(body, "reference_sha256"))
        raw = embedding_device_benchmark_bytes(reference)
        pointer = pointer.model_copy(update={"sha256": sha256_bytes(raw)})
    reader.members[pointer.sha256] = raw
    reader.members[reference.score_binary.sha256] = binary
    if fault != "legacy":
        body = receipt.model_dump(mode="json") | {"evidence": pointer.model_dump(mode="json")}
        receipt = BenchmarkLaunchReceipt.model_validate(seal(body, "receipt_sha256"))
    with sessions() as session, session.begin():
        journal.record(session, admission.request, receipt)
    second = invocation_for(storage, 2)
    with sessions() as session, session.begin():
        journal.reserve(session, admission.request, second)
    return BenchmarkLaunchAuthorization(sessions, admission.request, second, journal), pointer


def test_authorization_resolves_recorded_cpu_seal_in_current_original_root(storage):
    authorization, pointer = original_second_launch(storage)
    assert authorization.require_cpu_reference() == pointer
    assert storage[2].reads[-1] == pointer
    with storage[0]() as session, session.begin():
        history = storage[3].read(session, storage[1].request, job_id=storage[4])
        assert len(history.launches) == 2 and history.launches[1].receipt is None


@pytest.mark.parametrize("fault", ("legacy", "foreign-request", "missing", "revoked"))
def test_old_absent_foreign_or_revoked_reference_never_creates_a_replacement(storage, fault):
    authorization, pointer = original_second_launch(storage, fault)
    if fault == "missing":
        storage[2].members.pop(pointer.sha256)
    if fault == "revoked":
        storage[1].late_error = ValueError("synthetic revoked current source")
    with pytest.raises((ValueError, KeyError)):
        authorization.require_cpu_reference()
    storage[1].late_error = None
    with storage[0]() as session, session.begin():
        history = storage[3].read(session, storage[1].request, job_id=storage[4])
        assert len(history.launches) == 2 and history.launches[1].receipt is None
