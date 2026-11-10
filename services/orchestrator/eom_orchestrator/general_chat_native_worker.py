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
    CodexCliIdentity,
    chat_worker_protocol_version,
    read_chat_worker_policy,
)

from eom_orchestrator.general_chat_agent_native import AGENT_CHAT_INSTRUCTIONS
from eom_orchestrator.general_chat_grounded_prompt import GROUNDED_CHAT_INSTRUCTIONS
from eom_orchestrator.general_chat_native import (
    CHAT_INSTRUCTIONS,
    NATIVE_PROFILE,
    SELECTED_NATIVE_PROFILE,
    CodexChatSession,
)
from eom_orchestrator.general_chat_rag_native import RAG_CHAT_INSTRUCTIONS
from eom_orchestrator.general_chat_stdio import (
    CHAT_WORKSPACE,
    CodexChatStdio,
    native_chat_command,
    native_chat_environment,
    require_native_chat_capability,
    require_native_chat_identity,
)


def source_chat_worker_policy(
    *, model: str, protocol: Literal[3, 4] = 3, native_runtime: CodexCliIdentity | None = None
) -> ChatWorkerPolicy:
    if native_runtime is not None and protocol != 4:
        raise ValueError("selected chat CLI requires existing RAG-capable transport")
    value: dict[str, object] = {
        "schema_version": f"general-chat-worker-policy/{5 if native_runtime else protocol}.0",
        "agent_prompt_sha256": sha256_bytes(AGENT_CHAT_INSTRUCTIONS.encode("utf-8")),
        "grounded_prompt_sha256": sha256_bytes(GROUNDED_CHAT_INSTRUCTIONS.encode("utf-8")),
        "model": model,
        "native_profile": SELECTED_NATIVE_PROFILE if native_runtime else NATIVE_PROFILE,
        "prompt_revision": "general-chat/1.0.0",
        "prompt_sha256": sha256_bytes(CHAT_INSTRUCTIONS.encode("utf-8")),
    }
    if protocol == 4:
        value["rag_prompt_sha256"] = sha256_bytes(RAG_CHAT_INSTRUCTIONS.encode("utf-8"))
    if native_runtime is not None:
        value["native_runtime"] = native_runtime.model_dump(mode="json")
    return read_chat_worker_policy(value)


class IsolatedCodexChatWorker:
    def __init__(self, *, policy: ChatWorkerPolicy) -> None:
        self.policy = read_chat_worker_policy(policy.model_dump(mode="json"))
        if self.policy != source_chat_worker_policy(
            model=self.policy.model,
            protocol=4 if chat_worker_protocol_version(self.policy) == 4 else 3,
            native_runtime=self.policy.native_runtime,
        ):
            raise ChatWorkerFault(ChatWorkerError.NOT_READY)
        self.channel: CodexChatStdio | None = None
        self.session: CodexChatSession | None = None
        self.retirement_requested = Event()
        self.closed = Event()
        try:
            require_native_chat_identity()
            # Inspection does not create a login-bearing native session. The
            # reserved slot may change account while the chat worker is idle.
            self.runtime_guard = require_native_chat_capability(
                command=native_chat_command(model=self.policy.model),
                environment=native_chat_environment(),
                native_runtime=self.policy.native_runtime,
            )
        except Exception:
            raise ChatWorkerFault(ChatWorkerError.NOT_READY) from None

    def require_admission(self, policy: ChatWorkerPolicy) -> None:
        if policy != self.policy or self.closed.is_set() or self.retirement_requested.is_set():
            raise ChatWorkerFault(ChatWorkerError.NOT_READY)
        try:
            # Safe during an answer: OS/config/liveness only, no native RPC on the
            # shared stdio channel, generation, login or token refresh here.
            require_native_chat_identity()
            if self.runtime_guard is not None:
                self.runtime_guard.assert_unchanged()
        except Exception:
            raise ChatWorkerFault(ChatWorkerError.NOT_READY) from None

    def answer(
        self, request: ChatTurnInput, *, tools: ChatNativeToolPort | None = None
    ) -> ChatTurnResult:
        self.require_admission(self.policy)
        try:
            if isinstance(request, (RagChatTurnInput, AgentChatTurnInput)) and tools is None:
                raise ChatWorkerFault(ChatWorkerError.INVALID)
            self._start_turn()
            assert self.session is not None
            result: ChatTurnResult
            if isinstance(request, RagChatTurnInput):
                result = self.session.answer(request, tools=cast(ChatRagToolPort, tools))
            elif isinstance(request, AgentChatTurnInput):
                result = self.session.answer(request, tools=cast(ChatToolPort, tools))
            else:
                result = self.session.answer(request)
            if not self.session.ready:
                self.retirement_requested.set()
            # Account-bearing process termination precedes result publication.
            self._close_turn()
            return result
        except Exception:
            # Poisoned/unknown native state cannot be reused. The worker server
            # drains this handler and preserves its local pending/result evidence
            # before the service exits; this never retries the question.
            self.retirement_requested.set()
            with suppress(Exception):
                self._close_turn()
            raise

    def _start_turn(self) -> None:
        try:
            if self.policy.native_runtime is None:
                self.channel = CodexChatStdio.start(model=self.policy.model)
            else:
                self.channel = CodexChatStdio.start(
                    model=self.policy.model, native_runtime=self.policy.native_runtime
                )
            self.session = CodexChatSession(
                self.channel, model=self.policy.model, cwd=str(CHAT_WORKSPACE)
            )
            self.session.initialize()
        except Exception:
            with suppress(Exception):
                self._close_turn()
            raise ChatWorkerFault(ChatWorkerError.NOT_READY) from None

    def _close_turn(self) -> None:
        channel = self.channel
        session = self.session
        try:
            if session is not None:
                session.close()
        finally:
            if channel is not None:
                channel.close()
                if channel.process.poll() is None:
                    raise ChatWorkerFault(ChatWorkerError.RECOVERY)
            self.session = None
            self.channel = None

    def close(self) -> None:
        self.closed.set()
        self._close_turn()
