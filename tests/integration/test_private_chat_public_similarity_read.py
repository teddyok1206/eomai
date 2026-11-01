"""Disposable PG canonical private2 read and application composition; source IAM/math are fake.

Real Workflow/START/terminal/history/Artifact bytes and PG concurrency are tested.
The public DOCUMENT projection is synthetic, not live source admission or model proof.
"""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_orchestrator.models import JobRecord
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow_runner.native_query_prepare_driver import NativeQueryPrepareDriver
from eom_workflow_runner.private_chat_query_execution_port import PrivateChatQueryNativeExecutor
from eom_workflow_runner.private_chat_query_owner_admission import (
    CatalogPrivateChatQueryOwnerAdmission,
)
from eom_workflow_runner.private_chat_query_prepare_application import (
    NativePrivateChatQueryPreparation,
)
from sqlalchemy import func, select

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_private_chat_document_read import registered as registered
from tests.integration.test_private_chat_public_query_native_persistence import (
    make_owned_common_private_source,
)
from tests.unit.local_embedding_admission_fixtures import runtime_profile
from tests.unit.test_private_chat_public_similarity_read import (
    make_common_private_similarity_read_case,
    read,
)
from tests.unit.test_private_chat_public_similarity_read import (
    test_common_corrupt_committed_output_is_not_readable_or_disclosed as assert_corrupt_output,
)
from tests.unit.test_private_chat_query_preparation import initial_selection
from tests.unit.test_private_chat_query_prepare_application import private_runner

pytestmark = [
    pytest.mark.integration,
    pytest.mark.parametrize("registered", [runtime_profile("CPU").space], indirect=True),
]


@pytest.fixture
def common_read(registered, guarded_engine, tmp_path, monkeypatch):
    current = make_owned_common_private_source(registered, guarded_engine, monkeypatch)
    return make_common_private_similarity_read_case(current, tmp_path, monkeypatch)


def test_postgres_common_completed_read_replays_without_reencoding_or_new_jobs(common_read):
    with common_read.native.publisher.sessions() as session:
        before = session.scalar(select(func.count()).select_from(JobRecord))
    first = read(common_read)
    assert read(common_read) == first
    assert common_read.native.encodes == len(common_read.native.runs) == 1
    with common_read.native.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == before


def test_postgres_common_parallel_completed_read_keeps_one_original(common_read):
    with ThreadPoolExecutor(max_workers=2) as pool:
        left, right = tuple(pool.map(lambda _: read(common_read), range(2)))
    assert left == right and common_read.native.encodes == 1


def test_postgres_common_application_read_composes_all_three_sources_without_offer(common_read):
    value = common_read
    owner = CatalogPrivateChatQueryOwnerAdmission(value.source.owner)
    executor = Mock(spec=PrivateChatQueryNativeExecutor)
    runner = private_runner(value.source, owner, executor)
    driver = NativeQueryPrepareDriver()
    driver.offer_private_chat_query = Mock(
        side_effect=AssertionError("completed read cannot offer work")
    )
    app = NativePrivateChatQueryPreparation(
        owner=owner, executor=executor, runner=runner, driver=driver
    )
    preparation = initial_selection(SimpleNamespace(source=value.source, owner=owner))
    first = app.read(value.source.projection.origin, preparation)
    assert first == app.read(value.source.projection.origin, preparation)
    assert first.status == "READY" and first.context.status == "READY"
    assert len(first.context.candidates) == 3 and value.native.encodes == 1
    assert executor.mock_calls == []
    driver.offer_private_chat_query.assert_not_called()
    assert not workflow_definition_is_admitted("local-embedding-private-chat-query", "2.0.0")


@pytest.mark.parametrize("member", ("intent.json", "result.json", "shard.json", "vectors.f32"))
def test_postgres_common_corrupted_original_cannot_be_used_as_completed(common_read, member):
    assert_corrupt_output(common_read, member)


def test_postgres_common_private_claim_revocation_blocks_old_result(common_read):
    common_read.source.fault.value = "claim"
    with pytest.raises(SimilarityContextReadError):
        read(common_read)
    assert common_read.native.encodes == 1
