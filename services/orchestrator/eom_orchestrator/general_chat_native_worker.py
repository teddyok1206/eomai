"""Admitted isolated Codex adapter behind the private worker application.

Construction runs only under the existing fixed-identity/read-only-config guard.
No credential enrollment/copy, provider/model fallback, DB or NAS access exists.
"""

from __future__ import annotations

from contextlib import suppress
from threading import Event
from typing import Literal, cast

from eom_identifiers import sha256_bytes
from eom_protocol.general_chat_grounding import AgentChatTurnInput
from eom_protocol.general_chat_rag_tools import ChatNativeToolPort, ChatRagToolPort
from eom_protocol.general_chat_rag_turn import RagChatTurnInput
from eom_protocol.general_chat_tools import ChatToolPort
from eom_protocol.general_chat_turn_contracts import ChatInputContract as ChatTurnInput
from eom_protocol.general_chat_turn_contracts import ChatResultContract as ChatTurnResult
from eom_protocol.general_chat_worker_messages import (
    ChatWorkerError,
    ChatWorkerFault,
    ChatWorkerPolicy,
    read_chat_worker_policy,
)

from eom_orchestrator.general_chat_agent_native import AGENT_CHAT_INSTRUCTIONS
from eom_orchestrator.general_chat_grounded_prompt import GROUNDED_CHAT_INSTRUCTIONS
from eom_orchestrator.general_chat_native import (
    CHAT_INSTRUCTIONS,
    NATIVE_PROFILE,
    CodexChatSession,
)
from eom_orchestrator.general_chat_rag_native import RAG_CHAT_INSTRUCTIONS
from eom_orchestrator.general_chat_stdio import (
    CHAT_WORKSPACE,
    CodexChatStdio,
    require_native_chat_identity,
)


def source_chat_worker_policy(*, model: str, protocol: Literal[3, 4] = 3) -> ChatWorkerPolicy:
    value = {
        "schema_version": f"general-chat-worker-policy/{protocol}.0",
        "agent_prompt_sha256": sha256_bytes(AGENT_CHAT_INSTRUCTIONS.encode("utf-8")),
        "grounded_prompt_sha256": sha256_bytes(GROUNDED_CHAT_INSTRUCTIONS.encode("utf-8")),
        "model": model,
        "native_profile": NATIVE_PROFILE,
        "prompt_revision": "general-chat/1.0.0",
        "prompt_sha256": sha256_bytes(CHAT_INSTRUCTIONS.encode("utf-8")),
    }
    if protocol == 4:
        value["rag_prompt_sha256"] = sha256_bytes(RAG_CHAT_INSTRUCTIONS.encode("utf-8"))
    return read_chat_worker_policy(value)


class IsolatedCodexChatWorker:
    def __init__(self, *, policy: ChatWorkerPolicy) -> None:
        self.policy = read_chat_worker_policy(policy.model_dump(mode="json"))
        if self.policy != source_chat_worker_policy(
            model=self.policy.model,
            protocol=4 if self.policy.schema_version.endswith("/4.0") else 3,
        ):
            raise ChatWorkerFault(ChatWorkerError.NOT_READY)
        # Stdio.start checks fixed UID/private home, effective CLI capabilities,
        # pinned root-owned config mounted read-only and a cleared environment.
        channel: CodexChatStdio | None = None
        try:
            channel = CodexChatStdio.start(model=self.policy.model)
            session = CodexChatSession(channel, model=self.policy.model, cwd=str(CHAT_WORKSPACE))
            session.initialize()
        except Exception:
            if channel is not None:
                with suppress(Exception):
                    channel.close()
            raise ChatWorkerFault(ChatWorkerError.NOT_READY) from None
        self.channel = channel
        self.session = session
        self.retirement_requested = Event()

    def require_admission(self, policy: ChatWorkerPolicy) -> None:
        if (
            policy != self.policy
            or not self.session.ready
            or self.channel.closed
            or self.channel.process.poll() is not None
        ):
            raise ChatWorkerFault(ChatWorkerError.NOT_READY)
        try:
            # Safe during an answer: OS/config/liveness only, no native RPC on the
            # shared stdio channel, generation, login or token refresh here.
            require_native_chat_identity()
        except Exception:
            raise ChatWorkerFault(ChatWorkerError.NOT_READY) from None

    def answer(
        self, request: ChatTurnInput, *, tools: ChatNativeToolPort | None = None
    ) -> ChatTurnResult:
        self.require_admission(self.policy)
        try:
            if isinstance(request, RagChatTurnInput):
                if tools is None:
                    raise ChatWorkerFault(ChatWorkerError.INVALID)
                return self.session.answer(request, tools=cast(ChatRagToolPort, tools))
            if isinstance(request, AgentChatTurnInput):
                if tools is None:
                    raise ChatWorkerFault(ChatWorkerError.INVALID)
                return self.session.answer(request, tools=cast(ChatToolPort, tools))
            return self.session.answer(request)
        except Exception:
            # Poisoned/unknown native state cannot be reused. The worker server
            # drains this handler and preserves its local pending/result evidence
            # before the service exits; this never retries the question.
            self.retirement_requested.set()
            with suppress(Exception):
                self.close()
            raise
        finally:
            if not self.session.ready or self.channel.closed:
                self.retirement_requested.set()

    def close(self) -> None:
        self.session.close()
