"""Reject unsupported CPU budgets/devices before any parent/source/runtime access."""

from unittest.mock import Mock

import pytest
from eom_workflow_runner.document_embedding_cpu_batch_execution import (
    CatalogCpuDocumentBatchExecution,
)
from eom_workflow_runner.document_embedding_cpu_execution import FixedCpuDocumentEmbeddingExecution
from eom_workflow_runner.embedding_batch_execution import (
    CatalogEmbeddingBatchExecution,
    UnavailableEmbeddingBatchExecution,
)

from tests.unit.local_embedding_admission_fixtures import native_fixture


@pytest.mark.parametrize("device", ("CPU", "CUDA"))
def test_unbounded_or_wrong_device_cannot_be_reinterpreted_as_finite_cpu_fallback(device):
    # No real runtime authority is supplied; rejection must precede dereferencing it.
    operation = object.__new__(CatalogEmbeddingBatchExecution)
    unavailable = UnavailableEmbeddingBatchExecution(object(), object())
    request = native_fixture(device=device).request
    execution = FixedCpuDocumentEmbeddingExecution(Mock())
    with pytest.raises(ValueError, match="DOCUMENT_CPU_ROUTE_INVALID"):
        CatalogCpuDocumentBatchExecution(operation, None, unavailable, None, request, execution)
