"""Actual owner main/thread composition with explicit fake DB/native adapters."""

from __future__ import annotations

import signal
from dataclasses import dataclass, field
from threading import Event
from types import SimpleNamespace

import pytest
from eom_orchestrator import general_chat_owner_main as host
from eom_orchestrator.general_chat_owner_runtime import ChatOwnerConfiguration
from eom_orchestrator.general_chat_private_query_client import PRIVATE_CHAT_QUERY_SOURCE_SOCKET
from eom_orchestrator.general_chat_socket import OWNER_SOCKET
from eom_orchestrator.general_chat_state import ChatError

from tests.unit.general_chat_rag_fixtures import scope
from tests.unit.test_general_chat_service_composition import VALUES

RAG = {
    "EOM_GENERAL_CHAT_PROTOCOL_VERSION": "4",
    "EOM_GENERAL_CHAT_RAG_POLICY_REVISION_ID": scope().policy.access_policy_revision_id,
    "EOM_GENERAL_CHAT_RAG_POLICY_SHA256": scope().policy.sha256,
}
MODE = "EOM_GENERAL_CHAT_PRIVATE_QUERY_SOURCE"


def test_source_mode_is_default_off_and_requires_current_rag_configuration():
    assert not ChatOwnerConfiguration.from_environment(VALUES).private_query_source
    assert not ChatOwnerConfiguration.from_environment(VALUES | RAG).private_query_source
    assert not ChatOwnerConfiguration.from_environment(
        VALUES | {MODE: "DISABLED"}
    ).private_query_source
    assert ChatOwnerConfiguration.from_environment(
        VALUES | RAG | {MODE: "READ_ONLY"}
    ).private_query_source
    with pytest.raises(ChatError, match="CONFIGURATION_INVALID"):
        ChatOwnerConfiguration.from_environment(VALUES | {MODE: "READ_ONLY"})


@pytest.mark.parametrize("value", ["", "true", "read_only", "ADMIN", "READ_ONLY "])
def test_source_mode_never_guesses_or_coerces_an_enable_flag(value):
    with pytest.raises(ChatError, match="CONFIGURATION_INVALID"):
        ChatOwnerConfiguration.from_environment(VALUES | RAG | {MODE: value})


@dataclass
class HostCase:
    enabled: bool = True
    failure: str | None = None
    events: list[str] = field(default_factory=list)
    servers: list[object] = field(default_factory=list)
    source_started: Event = field(default_factory=Event)
    coordinator_stopped: Event = field(default_factory=Event)


@pytest.fixture
def composed(monkeypatch):
    case = HostCase()
    stop_handler = {}
    users = {
        "eom-general-chat": SimpleNamespace(pw_uid=901, pw_gid=901),
        "eom-cdx-chat": SimpleNamespace(pw_uid=902, pw_gid=902),
        "eom-api": SimpleNamespace(pw_uid=903, pw_gid=903),
        "eom-workflow-runner": SimpleNamespace(pw_uid=904, pw_gid=905),
    }
    monkeypatch.setattr(host, "require_chat_owner_identity", lambda: None)
    monkeypatch.setattr(host.pwd, "getpwnam", users.__getitem__)
    monkeypatch.setattr(
        host.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=903 if name == "eom-api" else 905)
    )
    monkeypatch.setattr(host.os, "environ", VALUES | RAG | {MODE: "READ_ONLY"})
    monkeypatch.setattr(
        host.signal, "signal", lambda number, handler: stop_handler.__setitem__(number, handler)
    )

    class Engine:
        def dispose(self):
            case.events.append("dispose")

    monkeypatch.setattr(host, "chat_owner_engine", lambda *_args, **_kwargs: Engine())
    monkeypatch.setattr(host, "require_chat_owner_database", lambda _: None)
    monkeypatch.setattr(host, "ControlArtifactPublisher", lambda *_: object())
    monkeypatch.setattr(host, "GeneralChatArtifactStore", lambda *_a, **_k: object())
    monkeypatch.setattr(host, "GeneralChatRepository", lambda _: object())
    monkeypatch.setattr(host, "CatalogChatKnowledgeClient", object)
    execution = object()
    monkeypatch.setattr(host, "GeneralChatExecutionService", lambda *_a, **_k: execution)
    monkeypatch.setattr(host, "GeneralChatConversationOwner", lambda *_a, **_k: object())
    monkeypatch.setattr(host, "source_chat_worker_policy", lambda **_: object())

    class Server:
        def __init__(self, owner, **kwargs):
            self.owner, self.options = owner, kwargs
            self.kind = "source" if owner is None else "api"
            self.stopped = Event()
            if self.kind == "source" and case.failure == "bind":
                raise RuntimeError("private details must not reach stderr")
            case.servers.append(self)

        def serve(self):
            if self.kind == "source":
                case.source_started.set()
                if case.failure == "serve":
                    raise RuntimeError("private details must not reach stderr")
                assert self.stopped.wait(5)
            elif case.failure == "serve":
                assert self.stopped.wait(5)
            else:
                if case.enabled:
                    assert case.source_started.wait(5)
                if case.failure == "api":
                    raise RuntimeError("private details must not reach stderr")
                stop_handler[signal.SIGTERM]()

        def stop(self):
            self.stopped.set()

        def close(self):
            self.stop()
            case.events.append(self.kind + "-closed")
            if self.kind == "source" and case.failure == "close":
                raise RuntimeError("private cleanup details must not reach stderr")

    monkeypatch.setattr(host, "GeneralChatOwnerRpcServer", Server)

    def coordinator(current, worker_factory, *, stop, report_state):
        assert current is execution
        assert stop.wait(5)
        case.events.append("coordinator-stopped")
        case.coordinator_stopped.set()

    monkeypatch.setattr(host, "run_chat_coordinator", coordinator)
    return case


def test_enabled_host_composes_exact_peer_separate_profile_and_stops_every_owner(composed, capsys):
    assert host.main() == 0
    api, source = composed.servers
    assert api.owner is not None and api.options["endpoint"].path == OWNER_SOCKET
    assert api.options["allowed_uids"] == frozenset({903})
    assert "private_queries" not in api.options
    assert source.owner is None and not source.options["allowed_uids"]
    assert source.options["endpoint"].path == PRIVATE_CHAT_QUERY_SOURCE_SOCKET
    assert (source.options["endpoint"].owner_uid, source.options["endpoint"].group_gid) == (
        901,
        905,
    )
    assert source.options["private_queries"].peer_uid == 904
    assert source.options["maximum_requests"] == 2
    assert composed.coordinator_stopped.is_set()
    assert composed.events.count("dispose") == 2
    assert composed.events.index("source-closed") < composed.events.index("dispose")
    assert composed.events.index("api-closed") < composed.events.index("dispose")
    assert capsys.readouterr().err == ""


def test_default_disabled_host_keeps_the_original_single_listener(composed, monkeypatch):
    composed.enabled = False
    monkeypatch.setattr(host.os, "environ", VALUES | RAG)
    assert host.main() == 0
    assert len(composed.servers) == 1 and composed.servers[0].owner is not None


def test_failed_optional_socket_cleanup_still_closes_api_and_sql(composed, capsys):
    composed.failure = "close"
    assert host.main() == 1
    assert capsys.readouterr().err == "GENERAL_CHAT_RUNTIME_STOPPED\n"
    assert "api-closed" in composed.events and composed.coordinator_stopped.is_set()
    assert composed.events.count("dispose") == 2


@pytest.mark.parametrize("phase", ["bind", "serve", "api"])
def test_partial_construction_or_listener_failure_cleans_up_without_raw_thread_error(
    composed, capsys, phase
):
    composed.failure = phase
    assert host.main() == 1
    expected = (
        "GENERAL_CHAT_APPLICATION_UNAVAILABLE"
        if phase == "serve"
        else "GENERAL_CHAT_RUNTIME_STOPPED"
    )
    assert capsys.readouterr().err == expected + "\n"
    assert "api-closed" in composed.events
    if phase != "bind":
        assert "source-closed" in composed.events
        assert composed.coordinator_stopped.is_set()
    assert composed.events.count("dispose") == 2
