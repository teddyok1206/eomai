from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest
from eom_orchestrator import general_chat_stdio as stdio
from eom_orchestrator.general_chat_native import DISABLED_CHAT_FEATURES, NativeChatError
from eom_orchestrator.general_chat_native_worker import (
    IsolatedCodexChatWorker,
    source_chat_worker_policy,
)
from eom_orchestrator.general_chat_runtime_selection import native_runtime_from_environment
from eom_protocol.general_chat_worker_messages import ChatWorkerFault

from tests.unit.test_general_chat_native_worker import synthetic_native as synthetic_native
from tests.unit.test_general_chat_runtime_selection import selected_environment


@pytest.fixture
def capability(monkeypatch):
    selected = native_runtime_from_environment(selected_environment())
    observations = []

    def unchanged():
        observations.append("epoch")

    guard = SimpleNamespace(identity=selected, assert_unchanged=unchanged)
    monkeypatch.setattr(stdio, "capture_codex_cli_identity", lambda _: guard)

    def features(command, **_):
        observations.append("features")
        return subprocess.CompletedProcess(
            command,
            0,
            "\n".join(f"{feature} stable false" for feature in DISABLED_CHAT_FEATURES).encode(),
        )

    monkeypatch.setattr(stdio.subprocess, "run", features)
    return selected, guard, observations


def test_explicit_version_and_hash_guard_keeps_effective_feature_check(capability):
    selected, guard, observations = capability
    observed = stdio.require_native_chat_capability(
        command=stdio.native_chat_command(model="synthetic-model"),
        environment=stdio.native_chat_environment(),
        native_runtime=selected,
    )
    assert observed is guard and observations == ["features", "epoch"]


@pytest.mark.parametrize("field", ["cli_version", "cli_launcher_sha256", "cli_binary_sha256"])
def test_same_version_changed_binary_or_wrong_selected_version_rejected(capability, field):
    selected, _, observations = capability
    assert selected is not None
    changed = selected.model_copy(
        update={field: "9.0.0" if field == "cli_version" else "sha256:" + "e" * 64}
    )
    with pytest.raises(NativeChatError, match="CHAT_ISOLATION_NOT_READY"):
        stdio.require_native_chat_capability(
            command=stdio.native_chat_command(model="synthetic-model"),
            environment=stdio.native_chat_environment(),
            native_runtime=changed,
        )
    assert observations == []


def test_file_epoch_changed_during_feature_check_is_not_admitted(capability):
    selected, guard, _ = capability

    def changed():
        raise ValueError("installed binary changed")

    guard.assert_unchanged = changed
    with pytest.raises(NativeChatError, match="CHAT_ISOLATION_NOT_READY"):
        stdio.require_native_chat_capability(
            command=stdio.native_chat_command(model="synthetic-model"),
            environment=stdio.native_chat_environment(),
            native_runtime=selected,
        )


def test_new_selected_runtime_cannot_enable_forbidden_features(capability, monkeypatch):
    selected, _, _ = capability
    monkeypatch.setattr(
        stdio.subprocess,
        "run",
        lambda command, **_: subprocess.CompletedProcess(command, 0, b"shell_tool stable true\n"),
    )
    with pytest.raises(NativeChatError):
        stdio.require_native_chat_capability(
            command=stdio.native_chat_command(model="synthetic-model"),
            environment=stdio.native_chat_environment(),
            native_runtime=selected,
        )


def test_selected_worker_passes_pins_and_checks_epoch_on_each_admission(
    synthetic_native, monkeypatch
):
    events, channel = synthetic_native
    selected = native_runtime_from_environment(selected_environment())
    seen = []

    def start(*, model, native_runtime):
        seen.append((model, native_runtime))
        return channel

    def unchanged():
        seen.append("epoch")

    monkeypatch.setattr(stdio.CodexChatStdio, "start", start)
    channel.assert_runtime_unchanged = unchanged
    policy = source_chat_worker_policy(model="synthetic-model", protocol=4, native_runtime=selected)
    worker = IsolatedCodexChatWorker(policy=policy)
    worker.require_admission(policy)
    assert seen == [(policy.model, selected), "epoch"]
    assert not any(event[0] == "answer" for event in events)

    def changed():
        raise ValueError("same-version executable replaced")

    channel.assert_runtime_unchanged = changed
    with pytest.raises(ChatWorkerFault, match="GENERAL_CHAT_WORKER_NOT_READY"):
        worker.require_admission(policy)
    worker.close()
