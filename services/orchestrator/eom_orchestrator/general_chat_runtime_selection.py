"""Explicit nonsecret CLI pins shared by owner and isolated worker composition."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from eom_protocol.general_chat_rag_knowledge import ChatRagPolicy
from eom_protocol.general_chat_worker_messages import CodexCliIdentity

RUNTIME_ENVIRONMENT_KEYS = MappingProxyType(
    {
        "cli_version": "EOM_GENERAL_CHAT_CODEX_VERSION",
        "cli_launcher_sha256": "EOM_GENERAL_CHAT_CODEX_LAUNCHER_SHA256",
        "cli_binary_sha256": "EOM_GENERAL_CHAT_CODEX_BINARY_SHA256",
    }
)


def native_runtime_from_environment(values: Mapping[str, str]) -> CodexCliIdentity | None:
    present = set(RUNTIME_ENVIRONMENT_KEYS.values()) & values.keys()
    if not present:
        return None
    if len(present) != len(RUNTIME_ENVIRONMENT_KEYS):
        raise ValueError("incomplete selected chat CLI identity")
    if values.get("EOM_GENERAL_CHAT_PROTOCOL_VERSION") != "4":
        raise ValueError("selected chat runtime requires existing protocol-4 RAG configuration")
    if not values.get("EOM_GENERAL_CHAT_RAG_POLICY_REVISION_ID") or not values.get(
        "EOM_GENERAL_CHAT_RAG_POLICY_SHA256"
    ):
        raise ValueError("selected chat runtime requires existing RAG policy pins")
    ChatRagPolicy.model_validate(
        {
            "access_policy_revision_id": values["EOM_GENERAL_CHAT_RAG_POLICY_REVISION_ID"],
            "sha256": values["EOM_GENERAL_CHAT_RAG_POLICY_SHA256"],
        }
    )
    return CodexCliIdentity.model_validate(
        {field: values[key] for field, key in RUNTIME_ENVIRONMENT_KEYS.items()}
    )
