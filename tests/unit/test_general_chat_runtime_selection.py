from __future__ import annotations

import pytest
from eom_orchestrator.general_chat_native_worker import source_chat_worker_policy
from eom_orchestrator.general_chat_runtime_selection import native_runtime_from_environment
from eom_protocol.general_chat_worker_messages import chat_worker_protocol_version


def selected_environment():
    return {
        "EOM_GENERAL_CHAT_PROTOCOL_VERSION": "4",
        "EOM_GENERAL_CHAT_RAG_POLICY_REVISION_ID": "accessrev_" + "a" * 32,
        "EOM_GENERAL_CHAT_RAG_POLICY_SHA256": "sha256:" + "b" * 64,
        "EOM_GENERAL_CHAT_CODEX_VERSION": "0.162.1",
        "EOM_GENERAL_CHAT_CODEX_LAUNCHER_SHA256": "sha256:" + "c" * 64,
        "EOM_GENERAL_CHAT_CODEX_BINARY_SHA256": "sha256:" + "d" * 64,
    }


def test_selected_policy_preserves_prompt_hashes_and_transport_without_version_constant():
    runtime = native_runtime_from_environment(selected_environment())
    previous = source_chat_worker_policy(model="synthetic-model", protocol=4)
    policy = source_chat_worker_policy(model="synthetic-model", protocol=4, native_runtime=runtime)
    assert policy.schema_version == "general-chat-worker-policy/5.0"
    assert policy.native_profile == "codex-app-server/environment-free/2.0"
    assert policy.native_runtime == runtime
    assert chat_worker_protocol_version(policy) == 4
    for field in (
        "prompt_sha256",
        "grounded_prompt_sha256",
        "agent_prompt_sha256",
        "rag_prompt_sha256",
    ):
        assert getattr(policy, field) == getattr(previous, field)
    assert "native_runtime" not in previous.model_dump(mode="json")


@pytest.mark.parametrize("version", ["0.162.1", "1.0.0", "9.99.123"])
def test_future_runtime_selection_does_not_edit_native_protocol_constant(version):
    values = selected_environment()
    values["EOM_GENERAL_CHAT_CODEX_VERSION"] = version
    runtime = native_runtime_from_environment(values)
    policy = source_chat_worker_policy(model="synthetic-model", protocol=4, native_runtime=runtime)
    assert policy.native_runtime is not None and policy.native_runtime.cli_version == version


def test_no_runtime_selection_keeps_legacy_configuration():
    assert native_runtime_from_environment({}) is None
    assert "native_runtime" not in source_chat_worker_policy(model="synthetic-model").model_dump(
        mode="json"
    )


@pytest.mark.parametrize("missing", list(selected_environment()))
def test_partial_pins_or_missing_existing_rag_never_enable_selected_runtime(missing):
    values = selected_environment()
    del values[missing]
    with pytest.raises(ValueError):
        native_runtime_from_environment(values)


def test_selected_runtime_never_implicitly_grants_protocol4():
    runtime = native_runtime_from_environment(selected_environment())
    with pytest.raises(ValueError):
        source_chat_worker_policy(model="synthetic-model", native_runtime=runtime)
