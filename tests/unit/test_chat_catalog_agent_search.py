"""Read-only search authorization and query projection without a model or DB."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from eom_catalog_service.chat_knowledge_discovery import ChatKnowledgeQueryAdapter
from eom_catalog_service.chat_knowledge_search import ChatKnowledgeSearchService, chat_search_query
from eom_operator_identity import PermissionKey
from eom_protocol.general_chat_tools import ChatSearchCatalogRequest

from tests.unit.test_general_chat_agent_search import arguments


@pytest.mark.parametrize(
    "actor",
    [
        None,
        SimpleNamespace(status="DISABLED", deleted_at=None, must_change_password=False),
        SimpleNamespace(status="ACTIVE", deleted_at=object(), must_change_password=False),
        SimpleNamespace(status="ACTIVE", deleted_at=None, must_change_password=True),
        SimpleNamespace(status="ACTIVE", deleted_at=None, must_change_password=False),
    ],
)
@pytest.mark.parametrize("permissions", [frozenset(), frozenset({PermissionKey.ITEM_READ})])
def test_search_denies_before_any_discovery_or_title_projection(monkeypatch, actor, permissions):
    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def begin(self):
            return nullcontext()

        def connection(self, **kwargs):
            assert kwargs["execution_options"]["isolation_level"] == "REPEATABLE READ"

        def execute(self, statement):
            assert str(statement) == "SET TRANSACTION READ ONLY"

        def get(self, model, key):
            return actor

    service = object.__new__(ChatKnowledgeSearchService)
    service.reader = object.__new__(ChatKnowledgeQueryAdapter)
    service.reader.sessions = Session
    monkeypatch.setattr(
        "eom_catalog_service.chat_knowledge_discovery.effective_permissions",
        lambda *_: permissions,
    )
    answer = service.search(
        ChatSearchCatalogRequest(
            actor_id="operator_" + "1" * 32, arguments=arguments(), snapshot=None
        )
    )
    assert answer.outcome.status == "FAILED"
    assert answer.outcome.error_code == "CHAT_KNOWLEDGE_FORBIDDEN"
    assert answer.outcome.cards == () and answer.outcome.context is None


@pytest.mark.parametrize("kind", ["RECENT", "TOPIC", "EXAM"])
def test_agent_projection_uses_existing_typed_query_and_exact_snapshot(kind):
    from eom_protocol.general_chat_grounding import ChatKnowledgeSnapshot

    options = {}
    if kind == "TOPIC":
        options = {"terms": ["전자기"], "source": "PAST_EXAM"}
    elif kind == "EXAM":
        options = dict(
            administration_year=2025,
            administration_month=6,
            target_school_level="HIGH_SCHOOL",
            target_grade=1,
            subject_key="integrated-science",
            item_number=17,
        )
    snapshot = ChatKnowledgeSnapshot(
        graph_snapshot_revision_id="graphrev_" + "1" * 32, sha256="sha256:" + "1" * 64
    )
    query = chat_search_query(
        ChatSearchCatalogRequest(
            actor_id="operator_" + "1" * 32,
            arguments=arguments(kind, **options),
            snapshot=snapshot,
        )
    )
    assert query.query.kind == kind and query.limit == 6
    assert query.snapshot.graph_snapshot_revision_id == snapshot.graph_snapshot_revision_id
    assert query.snapshot.snapshot_sha256 == snapshot.sha256
