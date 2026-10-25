"""No numeric/GPU authority is provided by a metadata publication adapter."""

from typing import cast

import pytest
from eom_workflow_runner.document_embedding_execution import OwnedDocumentEmbedding
from eom_workflow_runner.index_membership_publication import MembershipOnlyEmbeddingExecution

from tests.unit.local_embedding_admission_fixtures import native_fixture
from tests.unit.local_embedding_service_fixtures import service_fixture


def test_exact_original_runtime_identity_does_not_provide_compute_authority():
    request = native_fixture().request
    backend = MembershipOnlyEmbeddingExecution(request)
    assert backend.device == request.resource_profile.device
    backend.assert_current_runtime(request)
    with pytest.raises(ValueError, match="REQUEST_MISMATCH"):
        backend.assert_current_runtime(service_fixture().request)
    with pytest.raises(ValueError, match="NUMERICAL_EXECUTION_FORBIDDEN"):
        backend.observe(cast(object, None))
    with pytest.raises(ValueError, match="NUMERICAL_EXECUTION_FORBIDDEN"):
        backend.execute(cast(OwnedDocumentEmbedding, None), source=None, transaction=None)
