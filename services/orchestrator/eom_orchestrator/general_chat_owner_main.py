"""Installed Orchestrator-owner host: private history RPC plus one resident epoch."""

from __future__ import annotations

import grp
import os
import pwd
import signal
import sys
from collections.abc import Callable
from pathlib import Path
from threading import Event, Thread

from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.general_chat_artifacts import GeneralChatArtifactStore
from eom_orchestrator.general_chat_coordinator import run_chat_coordinator
from eom_orchestrator.general_chat_execution import GeneralChatExecutionService
from eom_orchestrator.general_chat_knowledge import CatalogChatKnowledgeClient
from eom_orchestrator.general_chat_native_worker import source_chat_worker_policy
from eom_orchestrator.general_chat_owner import GeneralChatConversationOwner
from eom_orchestrator.general_chat_owner_runtime import (
    ChatOwnerConfiguration,
    chat_owner_engine,
    require_chat_owner_database,
    require_chat_owner_identity,
)
from eom_orchestrator.general_chat_owner_server import (
    GeneralChatOwnerRpcServer,
    PrivateChatQueryRpcAccess,
)
from eom_orchestrator.general_chat_private_query_client import PRIVATE_CHAT_QUERY_SOURCE_SOCKET
from eom_orchestrator.general_chat_private_query_source import GeneralChatPrivateQuerySource
from eom_orchestrator.general_chat_repository import GeneralChatRepository
from eom_orchestrator.general_chat_similarity_consumer import ChatSimilarityPorts
from eom_orchestrator.general_chat_socket import OWNER_SOCKET, ChatSocketEndpoint
from eom_orchestrator.general_chat_state import ChatError, safe_chat_error_code
from eom_orchestrator.general_chat_worker_client import ChatWorkerClient
from eom_orchestrator.private_chat_query_prepare_client import PrivateChatQueryPrepareClient
from eom_orchestrator.settings import Settings


def main() -> int:
    engines = []
    stop = Event()
    coordinator: Thread | None = None
    server: GeneralChatOwnerRpcServer | None = None
    source_server: GeneralChatOwnerRpcServer | None = None
    source_thread: Thread | None = None
    source_failed = Event()
    result = 1
    try:
        require_chat_owner_identity()
        config = ChatOwnerConfiguration.from_environment(os.environ)
        owner, worker = pwd.getpwnam("eom-general-chat"), pwd.getpwnam("eom-cdx-chat")
        api, api_group = pwd.getpwnam("eom-api"), grp.getgrnam("eom-api")
        metadata = chat_owner_engine(config, pool_size=12)
        engines.append(metadata)
        require_chat_owner_database(metadata)
        publication = chat_owner_engine(config, pool_size=2)
        engines.append(publication)
        settings = Settings(
            staging_root=Path("/var/lib/eom-general-chat/staging"),
            nas_artifact_root=Path("/mnt/nas/eom/artifacts"),
            runtime_source_commit=config.source_commit,
        )
        evidence = GeneralChatArtifactStore(
            metadata,
            ControlArtifactPublisher(publication, settings),
            source_commit=config.source_commit,
        )
        repository = GeneralChatRepository(metadata)
        knowledge = CatalogChatKnowledgeClient()
        execution = GeneralChatExecutionService(
            repository,
            evidence,
            knowledge=knowledge,
            rag_knowledge=knowledge,
            rag_policy=config.rag_policy,
            similarity=(
                ChatSimilarityPorts(
                    knowledge, PrivateChatQueryPrepareClient.for_installed_owner(), evidence, stop
                )
                if config.similarity_search
                else None
            ),
        )
        policy = source_chat_worker_policy(
            model=config.model,
            protocol=4 if config.rag_policy is not None else 3,
            native_runtime=config.native_runtime,
        )
        endpoint = ChatSocketEndpoint(
            Path("/run/eom-general-chat-worker/worker.sock"),
            worker.pw_uid,
            worker.pw_gid,
        )
        server = GeneralChatOwnerRpcServer(
            GeneralChatConversationOwner(
                repository, evidence, knowledge=knowledge, rag_knowledge=knowledge
            ),
            endpoint=ChatSocketEndpoint(OWNER_SOCKET, owner.pw_uid, api_group.gr_gid),
            allowed_uids=frozenset({api.pw_uid}),
        )
        if config.private_query_source:
            source_server = GeneralChatOwnerRpcServer(
                None,
                endpoint=ChatSocketEndpoint(
                    PRIVATE_CHAT_QUERY_SOURCE_SOCKET, owner.pw_uid, grp.getgrnam("eom").gr_gid
                ),
                allowed_uids=frozenset(),
                private_queries=PrivateChatQueryRpcAccess(
                    GeneralChatPrivateQuerySource(execution),
                    pwd.getpwnam("eom-workflow-runner").pw_uid,
                ),
                maximum_requests=2,
            )

        def request_stop(*_: object) -> None:
            stop.set()
            assert server is not None
            server.stop()
            if source_server is not None:
                source_server.stop()

        def serve_source() -> None:
            assert source_server is not None
            try:
                source_server.serve()
            except Exception:
                # Thread tracebacks could disclose private adapter details.
                # The main host emits only the stable unavailable code below.
                source_failed.set()
            finally:
                if not stop.is_set():
                    source_failed.set()
                    request_stop()

        for number in (signal.SIGINT, signal.SIGTERM):
            signal.signal(number, request_stop)
        if source_server is not None:
            source_thread = Thread(target=serve_source, name="general-chat-query-source")
            source_thread.start()
        coordinator = Thread(
            target=run_chat_coordinator,
            args=(
                execution,
                lambda: ChatWorkerClient(
                    endpoint=endpoint, policy=policy, tools=execution.tool_broker
                ),
            ),
            kwargs={"stop": stop, "report_state": lambda code: sys.stderr.write(code + "\n")},
            name="general-chat-coordinator",
        )
        coordinator.start()
        # Native unavailability/recovery fences execution, not owner-scoped reads.
        server.serve()
        if source_failed.is_set():
            raise ChatError("GENERAL_CHAT_APPLICATION_UNAVAILABLE")
        result = 0
    except Exception as error:
        sys.stderr.write(safe_chat_error_code(error) + "\n")
    finally:
        stop.set()
        cleanup: list[Callable[[], None]] = []
        if source_server is not None:
            cleanup.append(source_server.stop)
        if source_thread is not None and source_thread.ident is not None:
            cleanup.append(source_thread.join)
        if source_server is not None:
            cleanup.append(source_server.close)
        if server is not None:
            cleanup.append(server.close)
        if coordinator is not None and coordinator.ident is not None:
            cleanup.append(coordinator.join)
        cleanup.extend(engine.dispose for engine in engines)
        cleanup_failed = False
        for close in cleanup:
            try:
                close()
            except Exception:
                # A changed socket must not prevent other resources from closing
                # or expose raw adapter errors through interpreter/thread output.
                cleanup_failed = True
        if cleanup_failed:
            sys.stderr.write("GENERAL_CHAT_RUNTIME_STOPPED\n")
            result = 1
    return result


if __name__ == "__main__":
    os.umask(0o007)
    raise SystemExit(main())
