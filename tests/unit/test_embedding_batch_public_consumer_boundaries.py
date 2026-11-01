"""Closed public consumers with an explicitly invalid private metadata return.

This tests cheap family guards, not current source authority, PG or physical execution.
"""

from contextlib import contextmanager, nullcontext
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_workflow_runner import reference_query_cpu_batch as cpu_module
from eom_workflow_runner.document_embedding_batch_context import (
    OriginalDocumentEmbeddingBatchContext,
)
from eom_workflow_runner.reference_query_cpu_batch import CatalogCpuReferenceQueryBatchGroup
from eom_workflow_runner.reference_query_owner_admission import CatalogReferenceQueryOwnerAdmission

from tests.unit.document_embedding_cuda_fixtures import document_cuda_case
from tests.unit.private_chat_batch_plan_fixtures import private_planning_case
from tests.unit.test_embedding_batch_plan import planning_case


def test_document_consumer_denies_private_selection_before_request_or_anchor_access(
    tmp_path, monkeypatch
):
    value = document_cuda_case(tmp_path, monkeypatch)
    context = value.adapter.context
    private = private_planning_case()

    @contextmanager
    def invalid_source(*_args):
        yield NS(selection=private.selection, policy=private.policy)

    monkeypatch.setattr(context.operation.admission, "admit", invalid_source)
    validate = Mock(
        side_effect=AssertionError("private selection reached public request validation")
    )
    monkeypatch.setattr(OriginalDocumentEmbeddingBatchContext, "validate_request", validate)
    try:
        with pytest.raises(ValueError, match="DOCUMENT_BATCH_CONTEXT_INVALID"):
            OriginalDocumentEmbeddingBatchContext(
                context.operation, context.parent, context.decision, context.owner, context.request
            )
        validate.assert_not_called()
    finally:
        value.engine.dispose()


def test_cpu_reference_consumer_denies_private_selection_before_public_anchor_access(monkeypatch):
    private = private_planning_case(status="BUSY")
    # Explicit synthetic source/root seams. This path cannot reach any launcher.
    owner = object.__new__(CatalogReferenceQueryOwnerAdmission)
    owner.catalog = object()
    owner.configuration = NS(registry=NS(space=private.policy.cpu.profile.space))

    @contextmanager
    def invalid_source(*_args):
        yield NS(selection=private.selection, policy=private.policy)

    operation = NS(
        admission=NS(catalog=owner.catalog, admit=invalid_source),
        publisher=NS(sessions=NS(begin=lambda: nullcontext(object()))),
    )
    monkeypatch.setattr(
        cpu_module,
        "require_original_cpu_batch_route",
        lambda *_args: NS(route=private.route, bound=None),
    )
    with pytest.raises(ValueError, match="REFERENCE_QUERY_CPU_BATCH_INVALID"):
        CatalogCpuReferenceQueryBatchGroup(
            operation, planning_case(purpose="REFERENCE_QUERY").request, object(), owner
        )
