"""Synthetic source admission for storage tests only; never a live operator/source grant."""

from contextlib import contextmanager
from uuid import uuid4

from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    BenchmarkStagedInputs,
    embedding_device_benchmark_bytes,
)
from eom_identifiers import sha256_bytes

from tests.unit.embedding_device_benchmark_fixtures import owner_request, staged_inputs
from tests.unit.inference_transfer_embedding_fixtures import seal


def benchmark_case():
    identifier = uuid4().hex
    body = staged_inputs().model_dump(mode="json")
    body.update(
        benchmark_id="embeddingbenchmark_" + identifier,
        benchmark_revision_id="embeddingbenchmarkrev_" + identifier,
    )
    inputs = BenchmarkStagedInputs.model_validate(body)
    body = owner_request().model_dump(mode="json")
    body.update(
        benchmark_id=inputs.benchmark_id, benchmark_revision_id=inputs.benchmark_revision_id
    )
    body["input_manifest"]["sha256"] = sha256_bytes(embedding_device_benchmark_bytes(inputs))
    return BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256")), inputs


class SyntheticBenchmarkAdmission:
    def __init__(self, request, inputs):
        self.request, self.inputs = request, inputs
        self.entered = self.exited = 0
        self.late_error = None

    @contextmanager
    def admit_in_session(self, session, request):
        assert request == self.request and not session.in_nested_transaction()
        self.entered += 1
        yield self.inputs
        if self.late_error is not None:
            raise self.late_error
        self.exited += 1
