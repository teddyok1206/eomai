"""Installed Orchestrator-owner host: private history RPC plus one resident epoch."""

from __future__ import annotations

import grp
import os
import pwd
import signal
import sys
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
from eom_orchestrator.general_chat_owner_server import GeneralChatOwnerRpcServer
from eom_orchestrator.general_chat_repository import GeneralChatRepository
from eom_orchestrator.general_chat_socket import OWNER_SOCKET, ChatSocketEndpoint
from eom_orchestrator.general_chat_state import safe_chat_error_code
from eom_orchestrator.general_chat_worker_client import ChatWorkerClient
from eom_orchestrator.settings import Settings


def main() -> int:
    engines = []
    stop = Event()
    coordinator: Thread | None = None
    server: GeneralChatOwnerRpcServer | None = None
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
        )
        policy = source_chat_worker_policy(
            model=config.model, protocol=4 if config.rag_policy is not None else 3
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

        def request_stop(*_: object) -> None:
            stop.set()
            assert server is not None
            server.stop()

        for number in (signal.SIGINT, signal.SIGTERM):
            signal.signal(number, request_stop)
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
        return 0
    except Exception as error:
        sys.stderr.write(safe_chat_error_code(error) + "\n")
        return 1
    finally:
        stop.set()
        if server is not None:
            server.close()
        if coordinator is not None and coordinator.ident is not None:
            coordinator.join()
        for engine in engines:
            engine.dispose()


if __name__ == "__main__":
    os.umask(0o007)
    raise SystemExit(main())
