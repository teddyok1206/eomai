from __future__ import annotations

import copy
import subprocess
from collections import deque
from pathlib import Path
from time import monotonic

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator.general_chat_native import (
    DISABLED_CHAT_FEATURES,
    CodexChatSession,
    NativeChatError,
)
from eom_orchestrator.general_chat_stdio import (
    CHAT_WORKSPACE,
    CodexChatStdio,
    native_chat_command,
    native_chat_environment,
    require_native_chat_capability,
    require_native_chat_identity,
)
from eom_protocol.general_chat import read_chat_turn_input, read_chat_turn_result

PYTHON = "/srv/eom/conda/envs/eom-api/bin/python"
MODEL = "approved-test-model"
CWD = "/fixed/native/workspace"


def request(*, suffix="1", follow_up=False):
    messages = [{"role": "user", "text": "안녕하세요"}]
    if follow_up:
        messages += [
            {"role": "assistant", "text": "안녕하세요. 무엇을 도와드릴까요?"},
            {"role": "user", "text": "이전 질문도 고려해 줘"},
        ]
    return read_chat_turn_input(
        {
            "protocol_version": "general-chat-turn/1.0",
            "conversation_id": "chat_" + suffix * 32,
            "turn_id": "chatturn_" + suffix * 32,
            "claim_id": "chatclaim_" + suffix * 32,
            "prompt_revision": "general-chat/1.0.0",
            "context_sha256": content_sha256(messages),
            "messages": messages,
        }
    )


def answer_item(
    *, phase="final_answer", text="안녕하세요!", item_id="answer-1", kind="agentMessage"
):
    return {"id": item_id, "type": kind, "phase": phase, "text": text}


def event(method, *, thread_id="thread-1", turn_id="turn-1", **fields):
    return {"method": method, "params": {"threadId": thread_id, "turnId": turn_id, **fields}}


def final_event(*, status="completed", items=None, error=None):
    return event(
        "turn/completed",
        turn={
            "id": "turn-1",
            "status": status,
            "items": [] if items is None else items,
            "error": error,
        },
    )


class Channel:
    def __init__(self, events=None):
        self.sent = []
        self.queue = deque()
        self.events = (
            [event("item/completed", item=answer_item()), final_event()]
            if events is None
            else events
        )
        self.closed = False
        self.account_type = "chatgpt"
        self.config_patch = {}
        self.thread_patch = {}
        self.thread_number = 0
        self.early_events = False

    def send(self, document):
        self.sent.append(copy.deepcopy(document))
        method = document.get("method")
        if "id" not in document or method is None:
            return
        result = {}
        if method == "account/read":
            result = {"account": None if self.account_type is None else {"type": self.account_type}}
        elif method == "config/read":
            result = {
                "config": {
                    "forced_login_method": "chatgpt",
                    "model_provider": "openai",
                    "model": MODEL,
                    "sandbox_mode": "read-only",
                    "approval_policy": "never",
                    "web_search": "disabled",
                    **self.config_patch,
                }
            }
        elif method == "thread/start":
            self.thread_number += 1
            result = {
                "model": MODEL,
                "modelProvider": "openai",
                "approvalPolicy": "never",
                "cwd": CWD,
                "sandbox": {"type": "readOnly", "networkAccess": False},
                "thread": {"id": f"thread-{self.thread_number}", "turns": []},
                "runtimeWorkspaceRoots": [],
                **self.thread_patch,
            }
        elif method == "turn/start":
            result = {"turn": {"id": "turn-1", "status": "inProgress", "items": []}}
            if self.early_events:
                self.queue.extend(copy.deepcopy(self.events))
        self.queue.append({"id": document["id"], "result": result})
        if method == "turn/start" and not self.early_events:
            self.queue.extend(copy.deepcopy(self.events))

    def receive(self, *, deadline):
        assert deadline > monotonic()
        if not self.queue:
            raise TimeoutError("sensitive native timeout body must not escape")
        result = self.queue.popleft()
        if isinstance(result, Exception):
            raise result
        return result

    def close(self):
        self.closed = True


def session(channel=None):
    channel = channel or Channel()
    native = CodexChatSession(channel, model=MODEL, cwd=CWD)
    native.initialize()
    return native, channel


def test_success_is_pinned_final_answer_not_commentary_reasoning_or_deltas():
    events = [
        event("item/started", item=answer_item(phase="commentary", text="작업 중")),
        event("item/completed", item=answer_item(phase="commentary", text="작업 중")),
        event("item/reasoning/textDelta", delta="private reasoning not an answer"),
        event("item/agentMessage/delta", itemId="answer-2", delta="not the final full answer"),
        event("item/completed", item=answer_item(item_id="answer-2", text="완료된 답변")),
        final_event(items=[answer_item(item_id="answer-2", text="완료된 답변")]),
    ]
    native, channel = session(Channel(events))
    staged = request()
    result = native.answer(staged)
    assert result.status == "SUCCEEDED" and result.reply == "완료된 답변"
    assert read_chat_turn_result(result.model_dump(mode="json"), request=staged) == result
    assert native.ready and not channel.closed
    assert channel.sent[-1]["method"] == "thread/unsubscribe"


def test_followup_preserves_roles_and_injects_only_preceding_history():
    native, channel = session()
    staged = request(follow_up=True)
    assert native.answer(staged).status == "SUCCEEDED"
    injected = next(
        value["params"] for value in channel.sent if value.get("method") == "thread/inject_items"
    )
    assert [item["role"] for item in injected["items"]] == ["user", "assistant"]
    assert [item["content"][0]["type"] for item in injected["items"]] == [
        "input_text",
        "output_text",
    ]
    assert injected["items"][0]["content"][0]["text"] == staged.messages[0].text
    start = next(value["params"] for value in channel.sent if value.get("method") == "turn/start")
    assert start["input"][0]["text"] == staged.messages[-1].text
    assert start["sandboxPolicy"] == {"type": "readOnly", "networkAccess": False}
    assert start["environments"] == []


def test_actual_startup_metadata_is_not_mistaken_for_conversation_execution():
    channel = Channel()
    channel.queue.extend(
        [
            {"method": "configWarning", "params": {"summary": "recoverable startup warning"}},
            {"method": "remoteControl/status/changed", "params": {"status": "disabled"}},
            {"method": "account/updated", "params": {"authMode": "chatgpt"}},
        ]
    )
    native, _ = session(channel)
    assert native.ready and not native._pending
    result = native.answer(request())
    assert result.status == "SUCCEEDED" and result.reply == "안녕하세요!"


def test_metadata_between_turn_events_is_not_exported_or_used_as_an_answer():
    events = [
        {"method": "configWarning", "params": {"summary": "private diagnostic"}},
        {"method": "remoteControl/status/changed", "params": {"status": "disabled"}},
        event("item/completed", item=answer_item(text="실제 답변")),
        final_event(),
    ]
    native, _ = session(Channel(events))
    result = native.answer(request())
    assert result.status == "SUCCEEDED" and result.reply == "실제 답변"
    assert "private diagnostic" not in result.model_dump_json()


@pytest.mark.parametrize("method", ["item/completed", "turn/started", "unknown/admin/event"])
def test_other_startup_events_are_still_rejected(method):
    channel = Channel()
    channel.queue.append({"method": method, "params": {}})
    with pytest.raises(NativeChatError, match="CODEX_PROTOCOL_INVALID"):
        session(channel)
    assert channel.closed


def test_two_owners_use_distinct_ephemeral_threads_without_native_history_resume():
    native, channel = session()
    assert native.answer(request()).status == "SUCCEEDED"
    channel.events = [
        event("item/completed", thread_id="thread-2", item=answer_item()),
        event(
            "turn/completed",
            thread_id="thread-2",
            turn={"id": "turn-1", "status": "completed", "items": [], "error": None},
        ),
    ]
    assert native.answer(request(suffix="2")).status == "SUCCEEDED"
    starts = [value["params"] for value in channel.sent if value.get("method") == "thread/start"]
    assert len(starts) == 2 and all(value["ephemeral"] is True for value in starts)
    assert all(value["environments"] == [] and value["dynamicTools"] == [] for value in starts)
    assert all(value["allowProviderModelFallback"] is False for value in starts)
    assert not any(
        value.get("method") in {"thread/resume", "thread/fork", "thread/read"}
        for value in channel.sent
    )
    assert not any(value.get("method") == "thread/inject_items" for value in channel.sent)


def test_events_before_turn_start_response_are_checked_in_order():
    channel = Channel()
    channel.early_events = True
    native, _ = session(channel)
    assert native.answer(request()).status == "SUCCEEDED"


def test_late_retired_thread_housekeeping_does_not_break_another_owners_turn():
    native, channel = session()
    assert native.answer(request()).status == "SUCCEEDED"
    channel.events = [
        event("thread/closed", thread_id="thread-1"),
        event("thread/status/changed", thread_id="thread-1"),
        event("item/completed", thread_id="thread-2", item=answer_item()),
        event(
            "turn/completed",
            thread_id="thread-2",
            turn={"id": "turn-1", "status": "completed", "items": [], "error": None},
        ),
    ]
    assert native.answer(request(suffix="2")).status == "SUCCEEDED"


def test_late_retired_thread_content_is_never_accepted_as_another_owners_answer():
    native, channel = session()
    assert native.answer(request()).status == "SUCCEEDED"
    channel.events = [event("item/completed", thread_id="thread-1", item=answer_item())]
    result = native.answer(request(suffix="2"))
    assert result.status == "FAILED" and not result.reply and channel.closed


def test_native_handle_reuse_is_rejected_before_inference_for_another_owner():
    native, channel = session()
    assert native.answer(request()).status == "SUCCEEDED"
    channel.thread_patch = {"thread": {"id": "thread-1", "turns": []}}
    assert native.answer(request(suffix="2")).status == "FAILED"
    assert sum(value.get("method") == "turn/start" for value in channel.sent) == 1


@pytest.mark.parametrize("status", ["failed", "interrupted", "inProgress"])
def test_terminal_failure_never_promotes_partial_answer_or_retries(status):
    native, channel = session(
        Channel([event("item/completed", item=answer_item()), final_event(status=status)])
    )
    result = native.answer(request())
    assert (
        result.status == "FAILED"
        and result.failure_code == "CODEX_TURN_FAILED"
        and result.reply == ""
    )
    assert channel.closed and not native.ready
    assert sum(value.get("method") == "turn/start" for value in channel.sent) == 1
    with pytest.raises(NativeChatError, match="CODEX_UNAVAILABLE"):
        native.answer(request())


@pytest.mark.parametrize(
    "bad_event",
    [
        event("item/completed", thread_id="other-thread", item=answer_item()),
        event("item/completed", thread_id={}, item=answer_item()),
        event("item/completed", turn_id="other-turn", item=answer_item()),
        event("item/completed", item=answer_item(phase={})),
        event("item/completed", item=answer_item(kind={})),
        event("item/completed", item=answer_item(text="x" * 32001)),
        event("item/completed", item=answer_item(text="nul\x00text")),
        event("unexpected/native-method"),
        {"id": True, "result": {}},
        {"method": {}, "params": {}},
        {"method": "item/completed", "params": []},
        final_event(items=[]),
        final_event(items=[answer_item()], error={"message": "do not leak raw details"}),
    ],
)
def test_bad_identity_unknown_shape_empty_answer_and_errors_fail_closed(bad_event):
    native, channel = session(Channel([bad_event]))
    result = native.answer(request())
    assert result.status == "FAILED" and result.reply == "" and channel.closed
    assert "do not leak" not in result.model_dump_json()


@pytest.mark.parametrize("missing", [False, True])
def test_native_optional_phase_preserves_legacy_public_answer_only_after_completed_turn(missing):
    item = answer_item(phase=None, text="완료된 공개 답변")
    if missing:
        del item["phase"]
    native, _ = session(Channel([event("item/completed", item=item), final_event()]))
    assert native.answer(request()).reply == "완료된 공개 답변"
    native, channel = session(
        Channel([event("item/completed", item=item), final_event(status="failed")])
    )
    result = native.answer(request())
    assert result.status == "FAILED" and not result.reply and channel.closed


def test_native_failure_logs_only_bounded_protocol_metadata_not_model_contents(caplog):
    native, _ = session(
        Channel(
            [
                event(
                    "item/completed",
                    item=answer_item(phase="invalid", text="private answer should not leak"),
                )
            ]
        )
    )
    assert native.answer(request()).status == "FAILED"
    assert "method=item/completed code=CODEX_PROTOCOL_INVALID" in caplog.text
    assert "private answer" not in caplog.text


@pytest.mark.parametrize(
    "kind",
    [
        "commandExecution",
        "fileChange",
        "mcpToolCall",
        "webSearch",
        "imageGeneration",
        "collabAgentToolCall",
    ],
)
def test_unexpected_native_tools_are_rejected_even_if_turn_claims_success(kind):
    native, channel = session(
        Channel(
            [event("item/started", item=answer_item(kind=kind)), final_event(items=[answer_item()])]
        )
    )
    result = native.answer(request())
    assert (
        result.failure_code == "CHAT_ISOLATION_NOT_READY" and result.reply == "" and channel.closed
    )


def test_native_server_permission_request_is_denied_and_process_closed():
    native, channel = session(
        Channel(
            [{"id": "approval-1", "method": "item/commandExecution/requestApproval", "params": {}}]
        )
    )
    result = native.answer(request())
    assert result.status == "FAILED" and channel.closed
    assert channel.sent[-1] == {
        "id": "approval-1",
        "error": {"code": -32601, "message": "Not supported"},
    }


@pytest.mark.parametrize(
    "problem,expected",
    [
        (TimeoutError("private native details"), "CODEX_TIMEOUT"),
        (OSError("private native details"), "CODEX_UNAVAILABLE"),
    ],
)
def test_uncertain_native_outcome_is_failed_without_auto_generation_retry(problem, expected):
    native, channel = session(Channel([problem]))
    result = native.answer(request())
    assert result.failure_code == expected and not result.reply and channel.closed
    assert sum(value.get("method") == "turn/start" for value in channel.sent) == 1


@pytest.mark.parametrize("account_type", [None, "apiKey", "chatgptAuthTokens", "unknown"])
def test_only_separately_enrolled_chatgpt_auth_is_admitted(account_type):
    channel = Channel()
    channel.account_type = account_type
    with pytest.raises(NativeChatError, match="CODEX_AUTH_REQUIRED"):
        session(channel)
    assert channel.closed
    assert not any(value.get("method") == "turn/start" for value in channel.sent)


@pytest.mark.parametrize(
    "key,value",
    [
        ("forced_login_method", None),
        ("model_provider", "other"),
        ("model", "different"),
        ("sandbox_mode", "danger-full-access"),
        ("approval_policy", "on-request"),
        ("web_search", "live"),
    ],
)
def test_native_effective_configuration_mismatch_prevents_inference(key, value):
    channel = Channel()
    channel.config_patch[key] = value
    with pytest.raises(NativeChatError, match="CHAT_ISOLATION_NOT_READY"):
        session(channel)
    assert channel.closed and not any(value.get("method") == "turn/start" for value in channel.sent)


@pytest.mark.parametrize(
    "patch",
    [
        {"model": "other"},
        {"runtimeWorkspaceRoots": ["/home/eom/EOM"]},
        {"cwd": "/home/eom/EOM"},
        {"approvalPolicy": "on-request"},
        {"sandbox": {"type": "workspaceWrite"}},
        {"sandbox": {"type": "readOnly", "networkAccess": True}},
        {"thread": {"id": "thread-1", "turns": [{"id": "old-other-owner-turn"}]}},
    ],
)
def test_thread_policy_and_empty_native_history_verified_before_start(patch):
    channel = Channel()
    channel.thread_patch = patch
    native, _ = session(channel)
    assert native.answer(request()).status == "FAILED" and channel.closed
    assert not any(value.get("method") == "turn/start" for value in channel.sent)


def test_conflicting_completed_item_text_fails_instead_of_overwriting_history():
    native, channel = session(
        Channel(
            [
                event("item/completed", item=answer_item(text="first")),
                final_event(items=[answer_item(text="second")]),
            ]
        )
    )
    assert native.answer(request()).failure_code == "CODEX_PROTOCOL_INVALID" and channel.closed


def test_pinned_context_is_validated_before_native_call_even_for_constructed_model():
    native, channel = session()
    bad = request().model_copy(update={"context_sha256": "sha256:" + "0" * 64})
    with pytest.raises(ValueError):
        native.answer(bad)
    assert not any(value.get("method") == "turn/start" for value in channel.sent)


def test_native_launch_has_no_inherited_environment_credentials_shell_or_six_slot():
    command = native_chat_command(model=MODEL)
    environment = native_chat_environment()
    assert command[-3:] == ["app-server", "--strict-config", "--stdio"]
    for feature in DISABLED_CHAT_FEATURES:
        assert f"features.{feature}=false" in command
    assert set(environment) == {
        "HOME",
        "CODEX_HOME",
        "PATH",
        "LANG",
        "RUST_LOG",
        "NO_COLOR",
        "TMPDIR",
    }
    assert environment["HOME"].endswith("eom-cdx-chat") and "OPENAI_API_KEY" not in environment
    assert "eom-cdx-01" not in str(command + list(environment.values()))
    with pytest.raises(ValueError):
        native_chat_command(model="model;bad")


def test_current_operator_cannot_start_dedicated_native_runtime():
    with pytest.raises(NativeChatError, match="CHAT_ISOLATION_NOT_READY"):
        require_native_chat_identity()


def test_capability_probe_checks_actual_same_feature_config_without_model_run(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        output = (
            b"codex-cli 0.160.0\n"
            if command[-1] == "--version"
            else "\n".join(f"{feature} stable false" for feature in DISABLED_CHAT_FEATURES).encode()
        )
        return subprocess.CompletedProcess(command, 0, output)

    monkeypatch.setattr("eom_orchestrator.general_chat_stdio.subprocess.run", run)
    command = native_chat_command(model=MODEL)
    require_native_chat_capability(command=command, environment=native_chat_environment())
    assert calls[1][0] == [*command[:-3], "features", "list"]
    assert calls[1][1]["cwd"] == CHAT_WORKSPACE
    assert all("app-server" not in call[0] for call in calls)


@pytest.mark.parametrize("output", [b"codex-cli 0.161.0", b"codex-cli 0.160.0"])
def test_changed_cli_or_missing_enabled_feature_inventory_is_not_admitted(monkeypatch, output):
    def run(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 0, output if command[-1] == "--version" else b"shell_tool stable true\n"
        )

    monkeypatch.setattr("eom_orchestrator.general_chat_stdio.subprocess.run", run)
    with pytest.raises(NativeChatError, match="CHAT_ISOLATION_NOT_READY"):
        require_native_chat_capability(
            command=native_chat_command(model=MODEL), environment=native_chat_environment()
        )


def transport(script):
    process = subprocess.Popen(
        [PYTHON, "-I", "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        bufsize=0,
    )
    return CodexChatStdio(process)


def test_stdio_can_write_bounded_context_and_read_fragmented_json_without_native_model():
    channel = transport(
        "import sys,json; v=json.loads(sys.stdin.buffer.readline()); "
        "sys.stdout.write(json.dumps(v)+'\\n'); sys.stdout.flush()"
    )
    try:
        payload = {"unicode": "한국어", "large": "x" * 128000}
        channel.send(payload)
        assert channel.receive(deadline=monotonic() + 10) == payload
    finally:
        channel.close()
    assert channel.closed and channel.process.poll() is not None
    channel.close()


@pytest.mark.parametrize(
    "raw",
    [
        b'{"id":1,"id":2}\n',
        b'{"value":NaN}\n',
        b'{"value":1e999}\n',
        b"[]\n",
        b"bad json\n",
        b"\xff\n",
        b"\n" * 17,
        b"x" * (1048576 + 1) + b"\n",
    ],
    ids=lambda raw: f"frame-{len(raw)}" if len(raw) > 100 else repr(raw),
)
def test_stdio_rejects_duplicate_fields_nonfinite_invalid_and_oversized_frames(raw):
    expression = "b'x' * (1048576 + 1) + b'\\n'" if len(raw) > 1048576 else repr(raw)
    channel = transport(f"import sys; sys.stdout.buffer.write({expression}); sys.stdout.flush()")
    try:
        with pytest.raises(NativeChatError):
            channel.receive(deadline=monotonic() + 10)
    finally:
        channel.close()


def test_stdio_deadline_and_eof_are_explicit_without_busy_polling():
    channel = transport("import sys; sys.stdin.buffer.readline()")
    try:
        with pytest.raises(TimeoutError):
            channel.receive(deadline=monotonic())
    finally:
        channel.close()
    channel = transport("pass")
    try:
        with pytest.raises(OSError):
            channel.receive(deadline=monotonic() + 10)
    finally:
        channel.close()


def test_native_adapter_has_no_persistence_network_api_or_other_worker_dependencies():
    root = Path(__file__).resolve().parents[2] / "services/orchestrator/eom_orchestrator"
    source = (root / "general_chat_native.py").read_text()
    assert "sqlalchemy" not in source and "ControlArtifactPublisher" not in source
    assert "openai.OpenAI" not in source and "requests" not in source
    assert "eom-cdx-01" not in source and "database_url" not in source


def test_identity_preparation_is_pinned_and_does_not_activate_or_copy_auth():
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts/chat/provision_worker_identity.sh"
    source = script.read_text()
    assert "EXPECTED_COMMIT" in source and "status --porcelain=v1" in source
    assert "working tree is not clean" in source
    assert "existing chat home ownership differs" in source
    assert "do not overwrite it" in source
    assert "service_activation=NONE" in source and "db_migration=NONE" in source
    assert "usermod" not in source and "auth.json" not in source
    assert "systemctl" not in source and "eom-cdx-01" not in source
    assert (root / "infra/chat/codex-config.toml").read_bytes() == (
        b"# EOM dedicated text-only chat. Configuration is pinned by the launcher.\n"
    )
    assert subprocess.run(["bash", "-n", str(script)], capture_output=True).returncode == 0
    result = subprocess.run(["bash", str(script), "a" * 40], capture_output=True)
    assert result.returncode != 0 and b"requires root" in result.stderr


def test_enrollment_is_fixed_identity_interactive_and_never_replaces_or_borrows_auth():
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts/chat/enroll_worker_account.sh"
    source = script.read_text()
    assert "enrollment requires the operator's terminal" in source
    assert "working tree is not clean" in source and "source commit mismatch" in source
    assert "do not replace an enrolled account" in source
    assert "runuser -u" in source and "/usr/bin/env -i" in source
    assert 'forced_login_method="chatgpt"' in source and "login --device-auth" in source
    assert "15m" in source and "--kill-after=10s" in source
    assert "--with-api-key" not in source and "systemctl" not in source
    assert "eom-cdx-01" not in source and "cp " not in source
    assert subprocess.run(["bash", "-n", str(script)], capture_output=True).returncode == 0
    result = subprocess.run(["bash", str(script), "a" * 40], capture_output=True)
    assert result.returncode != 0 and b"requires root" in result.stderr
