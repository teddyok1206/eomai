"""Catalog authorization precedes file or Graph resolution, with no model usage."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from eom_catalog_service.chat_knowledge_resolution import (
    ChatKnowledgeResolutionError,
    ChatKnowledgeResolutionService,
)
from eom_protocol.general_chat_grounding import ChatKnowledgeCatalogRequest


@pytest.mark.parametrize(
    "actor",
    [
        None,
        SimpleNamespace(status="DISABLED", deleted_at=None, must_change_password=False),
        SimpleNamespace(status="ACTIVE", deleted_at=None, must_change_password=True),
        SimpleNamespace(status="ACTIVE", deleted_at=None, must_change_password=False),
    ],
)
def test_unauthorized_operator_never_resolves_sources(monkeypatch, actor):
    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def begin(self):
            return nullcontext()

        def connection(self, **kwargs):
            pass

        def execute(self, *args):
            pass

        def get(self, model, key):
            return actor

    service = object.__new__(ChatKnowledgeResolutionService)
    service.sessions = Session
    monkeypatch.setattr(
        "eom_catalog_service.chat_knowledge_resolution.effective_permissions",
        lambda *_: frozenset(),
    )
    request = ChatKnowledgeCatalogRequest(
        actor_id="operator_" + "1" * 32, purpose="AUTHORIZE", selection=None
    )
    with pytest.raises(ChatKnowledgeResolutionError, match="CHAT_KNOWLEDGE_FORBIDDEN"):
        service.resolve(request)
