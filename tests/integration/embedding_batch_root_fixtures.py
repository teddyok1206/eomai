"""Synthetic root/OS/model leaves; real source, parent DB and publication remain."""

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

from eom_catalog_contracts.embedding_work_batch_binary import validate_embedding_work_batch_binary
from eom_catalog_service.embedding_batch_owner_channel import EmbeddingBatchOwnerChannel
from eom_catalog_service.embedding_batch_owner_workspace import StagedOwnerEmbeddingBatch
from eom_workflow_runner import embedding_batch_execution as batch_execution
from eom_workflow_runner.embedding_batch_result_read import VerifiedLocalEmbeddingBatchResult

from tests.unit.embedding_batch_execution_fixtures import execution_case
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_owner_control import RELEASE, control_frames


def configure_synthetic_batch_runtime(value, monkeypatch):
    """No actual unit/GPU/auth proof. SQL source/Job/Artifact boundaries are not replaced."""
    value.frames = control_frames(request=value.allocation.control_request)
    channel = object.__new__(EmbeddingBatchOwnerChannel)
    channel.request, channel.side, channel.controller_release = (
        value.allocation.control_request,
        "OWNER",
        RELEASE,
    )
    channel.require_direct_peer = Mock()
    channel.receive_allocation = Mock(return_value=value.frames.ready)
    channel.send_binding = Mock()
    channel.close = Mock()
    value.channel, value.acked, value.dispatches = channel, False, []
    listener = SimpleNamespace(accept_root=Mock(return_value=channel))

    @contextmanager
    def listen(staged):
        assert staged == value.allocation.control_request
        yield listener

    monkeypatch.setattr(batch_execution, "stage_embedding_batch_control", lambda request: request)
    monkeypatch.setattr(batch_execution, "owner_embedding_batch_listener", listen)
    monkeypatch.setattr(
        batch_execution,
        "dispatch_embedding_batch_control",
        lambda original: value.dispatches.append(original),
    )

    def stage(request, ready, binding, batch):
        value.numeric = execution_case(
            planned=SimpleNamespace(allocation=value.allocation, batch=batch, bound=binding)
        )
        value.numeric.completed = type(value.numeric.completed).model_validate(
            seal(
                value.numeric.completed.model_dump(mode="json")
                | {"retired_at": datetime.now(UTC).isoformat().replace("+00:00", "Z")},
                "message_sha256",
            )
        )
        value.staged = StagedOwnerEmbeddingBatch(value.numeric.frames.bound, batch, (), ())
        value.verified = VerifiedLocalEmbeddingBatchResult(
            value.staged,
            ready,
            value.numeric.completed,
            value.numeric.result,
            validate_embedding_work_batch_binary(
                batch, value.numeric.result, value.numeric.vectors
            ),
            (),
            (),
        )
        checks = iter(batch.children)

        def next_check(authorize):
            child = next(checks, None)
            if child is None:
                return value.numeric.completed
            authorize(batch.request_sha256, child.request.request_sha256)
            return None

        channel.authorize_next = Mock(side_effect=next_check)
        return value.staged

    def read_verified(channel, ready, staged, *, authorization):
        authorization.authorize_batch()
        assert (channel, ready, staged) == (value.channel, value.frames.ready, value.staged)
        return value.verified

    def ack(verify):
        verify(value.numeric.completed)
        value.acked = True

    def terminal(actual):
        assert actual is value.channel and value.acked and value.channel.close.called
        return value.numeric.completed

    channel.acknowledge_completion = Mock(side_effect=ack)
    monkeypatch.setattr(batch_execution, "stage_owner_embedding_batch", stage)
    monkeypatch.setattr(batch_execution, "read_verified_embedding_batch_result", read_verified)
    monkeypatch.setattr(VerifiedLocalEmbeddingBatchResult, "assert_current", lambda _: None)
    monkeypatch.setattr(EmbeddingBatchOwnerChannel, "acknowledged_completion", property(terminal))
    value.operation = batch_execution.CatalogEmbeddingBatchExecution(
        value.owner, value.publisher, source_commit="a" * 40, controller_release=RELEASE
    )
