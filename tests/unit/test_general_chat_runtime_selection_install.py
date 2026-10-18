"""Selected-runtime configuration and isolated installer CAS; no live OS/DB work."""

from __future__ import annotations

import os
import pwd
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_identifiers import sha256_bytes
from eom_orchestrator.general_chat_owner_runtime import ChatOwnerConfiguration
from eom_orchestrator.general_chat_protected_environment import (
    install_chat_environment,
    read_chat_preparation_file,
)
from eom_orchestrator.general_chat_runtime_selection import RUNTIME_ENVIRONMENT_KEYS
from eom_orchestrator.general_chat_state import ChatError
from eom_protocol.general_chat_rag_knowledge import ChatRagPolicy
from eom_protocol.general_chat_worker_messages import CodexCliIdentity

from scripts.chat import install_runtime as installation

COMMIT = "a" * 40
MODEL = "synthetic-model"
POLICY = ChatRagPolicy(
    access_policy_revision_id="accessrev_" + "2" * 32, sha256="sha256:" + "a" * 64
)
IDENTITY = CodexCliIdentity(
    cli_version="0.162.1",
    cli_launcher_sha256="sha256:" + "b" * 64,
    cli_binary_sha256="sha256:" + "c" * 64,
)
OWNER_VALUES = {
    "EOM_GENERAL_CHAT_DATABASE_URL": "postgresql+psycopg://eom_general_chat_runtime:synthetic@127.0.0.1:5432/eom_test",
    "EOM_RUNTIME_SOURCE_COMMIT": COMMIT,
    "EOM_GENERAL_CHAT_MODEL": MODEL,
}
RAG_VALUES = {
    "EOM_GENERAL_CHAT_PROTOCOL_VERSION": "4",
    "EOM_GENERAL_CHAT_RAG_POLICY_REVISION_ID": POLICY.access_policy_revision_id,
    "EOM_GENERAL_CHAT_RAG_POLICY_SHA256": POLICY.sha256,
}
NATIVE_VALUES = {
    key: IDENTITY.model_dump(mode="json")[field] for field, key in RUNTIME_ENVIRONMENT_KEYS.items()
}


def test_owner_configuration_preserves_optional_selected_runtime_and_existing_rag() -> None:
    old = ChatOwnerConfiguration.from_environment(OWNER_VALUES | RAG_VALUES)
    selected = ChatOwnerConfiguration.from_environment(OWNER_VALUES | RAG_VALUES | NATIVE_VALUES)
    assert old.native_runtime is None
    assert selected.native_runtime == IDENTITY
    assert selected.rag_policy == old.rag_policy == POLICY
    assert selected.model == old.model == MODEL
    with pytest.raises(AttributeError):
        selected.native_runtime = None  # type: ignore[misc]


@pytest.mark.parametrize("missing", tuple(NATIVE_VALUES))
def test_owner_configuration_rejects_partial_runtime_pins(missing: str) -> None:
    values = OWNER_VALUES | RAG_VALUES | NATIVE_VALUES
    del values[missing]
    with pytest.raises(ChatError, match="OWNER_CONFIGURATION_INVALID"):
        ChatOwnerConfiguration.from_environment(values)


@pytest.mark.parametrize(
    "invalid",
    [
        {"EOM_GENERAL_CHAT_PROTOCOL_VERSION": "3"},
        {"EOM_GENERAL_CHAT_PROTOCOL_VERSION": "5"},
        {"EOM_GENERAL_CHAT_CODEX_VERSION": "codex-cli 0.162.1"},
        {"EOM_GENERAL_CHAT_CODEX_VERSION": "latest"},
        {"EOM_GENERAL_CHAT_CODEX_LAUNCHER_SHA256": "b" * 64},
        {"EOM_GENERAL_CHAT_CODEX_BINARY_SHA256": "sha256:" + "C" * 64},
        {"EOM_GENERAL_CHAT_RAG_POLICY_SHA256": "bad"},
    ],
)
def test_owner_configuration_never_falls_back_from_invalid_native_or_rag_pins(
    invalid: dict[str, str],
) -> None:
    with pytest.raises(ChatError, match="OWNER_CONFIGURATION_INVALID"):
        ChatOwnerConfiguration.from_environment(OWNER_VALUES | RAG_VALUES | NATIVE_VALUES | invalid)


def test_native_selection_cannot_activate_rag_in_a_legacy_configuration() -> None:
    with pytest.raises(ChatError, match="OWNER_CONFIGURATION_INVALID"):
        ChatOwnerConfiguration.from_environment(OWNER_VALUES | NATIVE_VALUES)
    with pytest.raises(ChatError, match="OWNER_CONFIGURATION_INVALID"):
        installation.configuration_payloads(COMMIT, MODEL, native_runtime=IDENTITY)


def test_legacy_configuration_bytes_and_selected_runtime_configuration_are_distinct() -> None:
    legacy = installation.configuration_payloads(COMMIT, MODEL, rag_policy=POLICY)
    selected = installation.configuration_payloads(
        COMMIT, MODEL, rag_policy=POLICY, native_runtime=IDENTITY
    )
    target = installation.CONFIG_ROOT / "general-chat-model.env"
    assert selected[target] == legacy[target] + "".join(
        f"{key}={value}\n" for key, value in NATIVE_VALUES.items()
    ).encode("ascii")
    assert installation.configuration_payloads(COMMIT, MODEL)[target] == (
        f"EOM_GENERAL_CHAT_MODEL={MODEL}\n".encode("ascii")
    )
    assert set(selected) == set(legacy)
    assert (
        selected[installation.CONFIG_ROOT / "general-chat-release.env"]
        == (legacy[installation.CONFIG_ROOT / "general-chat-release.env"])
    )


def test_source_option_is_explicit_nonsecret_and_never_enables_without_rag() -> None:
    target = installation.CONFIG_ROOT / "general-chat-model.env"
    disabled = installation.configuration_payloads(COMMIT, MODEL, rag_policy=POLICY)
    enabled = installation.configuration_payloads(
        COMMIT, MODEL, rag_policy=POLICY, private_query_source=True
    )
    assert (
        enabled[target] == disabled[target] + b"EOM_GENERAL_CHAT_PRIVATE_QUERY_SOURCE=READ_ONLY\n"
    )
    assert set(enabled) == set(disabled)
    with pytest.raises(ChatError, match="CONFIGURATION_INVALID"):
        installation.configuration_payloads(COMMIT, MODEL, private_query_source=True)


@dataclass
class InstallationHarness:
    events: list[str]
    target: Path
    release: Path
    before: bytes
    desired: bytes
    guard: Any
    busy: bool = False


@pytest.fixture
def installed_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> InstallationHarness:
    configuration = tmp_path / "etc"
    units = tmp_path / "units"
    configuration.mkdir()
    units.mkdir()
    monkeypatch.setattr(installation, "CONFIG_ROOT", configuration)
    monkeypatch.setattr(installation, "UNIT_ROOT", units)
    target = configuration / "general-chat-model.env"
    release = configuration / "general-chat-release.env"
    before = installation.configuration_payloads(COMMIT, MODEL, rag_policy=POLICY)[target]
    desired = installation.configuration_payloads(
        COMMIT, MODEL, rag_policy=POLICY, native_runtime=IDENTITY
    )[target]
    target.write_bytes(before)
    target.chmod(0o600)
    release.write_bytes(f"EOM_RUNTIME_SOURCE_COMMIT={COMMIT}\n".encode())
    release.chmod(0o600)
    secret = configuration / "secret.env"
    secret.write_bytes(
        f"EOM_GENERAL_CHAT_DATABASE_URL={OWNER_VALUES['EOM_GENERAL_CHAT_DATABASE_URL']}\n".encode()
    )
    secret.chmod(0o600)
    monkeypatch.setattr(installation, "SECRET", secret)
    auth = tmp_path / "auth.json"
    auth.write_bytes(b"synthetic-auth-metadata-only")
    auth.chmod(0o600)
    monkeypatch.setattr(installation, "AUTH", auth)
    monkeypatch.setattr(
        pwd,
        "getpwnam",
        lambda _: SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid()),
    )
    payloads = {}
    for index, unit in enumerate(installation.UNITS):
        payload = f"synthetic-unit-{index}\n".encode()
        payloads[unit] = payload
        path = units / unit
        path.write_bytes(payload)
        path.chmod(0o644)
    harness = InstallationHarness([], target, release, before, desired, None)
    monkeypatch.setattr(
        installation, "require_source", lambda *_: harness.events.append("source-stopped")
    )
    monkeypatch.setattr(
        installation, "require_compatible_runtime", lambda *_: harness.events.append("installed")
    )
    monkeypatch.setattr(installation, "require_root_directory", lambda *_: None)
    monkeypatch.setattr(
        installation,
        "chat_owner_engine",
        lambda *_args, **_kw: SimpleNamespace(dispose=lambda: None),
    )
    monkeypatch.setattr(
        installation, "require_chat_owner_database", lambda _: harness.events.append("read-db")
    )

    def stopped() -> None:
        harness.events.append("recheck-stopped")
        if harness.busy:
            raise ChatError("GENERAL_CHAT_INSTALL_MUST_BE_STOPPED")

    monkeypatch.setattr(installation, "require_chat_services_stopped", stopped)
    original_read = read_chat_preparation_file
    original_install = install_chat_environment

    def read(path: Path, *, uid: int, gid: int, mode: int) -> bytes:
        return original_read(path, uid=os.getuid(), gid=os.getgid(), mode=mode)

    monkeypatch.setattr(installation, "read_chat_preparation_file", read)

    def read_environment(path: Path, **_kw: Any) -> dict[str, str]:
        return dict(
            line.split("=", 1)
            for line in read(path, uid=0, gid=0, mode=0o600).decode().splitlines()
        )

    monkeypatch.setattr(installation, "read_chat_environment", read_environment)

    def install(path: Path, payload: bytes, **_kw: Any) -> None:
        harness.events.append("write-config")
        original_install(path, payload, uid=os.getuid(), gid=os.getgid())

    monkeypatch.setattr(installation, "install_chat_environment", install)

    def check_output(command: list[str], **_kw: Any) -> bytes:
        assert command[:4] == ["git", "-C", str(installation.REPOSITORY), "show"]
        return payloads[command[-1].rsplit("/", 1)[-1]]

    monkeypatch.setattr(subprocess, "check_output", check_output)

    def run(command: list[str], **_kw: Any) -> None:
        assert command == ["systemctl", "daemon-reload"]
        harness.events.append("daemon-reload")

    monkeypatch.setattr(subprocess, "run", run)

    def unchanged() -> None:
        harness.events.append("recheck-cli")

    harness.guard = SimpleNamespace(identity=IDENTITY, assert_unchanged=unchanged)

    def capture(path: Path) -> Any:
        assert path == Path("/usr/local/bin/codex")
        harness.events.append("capture-cli")
        return harness.guard

    monkeypatch.setattr(installation, "capture_codex_cli_identity", capture)
    return harness


@pytest.mark.parametrize("previous_runtime", [None, COMMIT])
def test_pin_only_cas_preserves_model_rag_and_exact_release_without_source_advance(
    installed_runtime: InstallationHarness, previous_runtime: str | None
) -> None:
    value = installed_runtime
    release_before = value.release.read_bytes()
    installation.stage(
        COMMIT,
        MODEL,
        pin_codex_runtime=True,
        previous_runtime_commit=previous_runtime,
        previous_model_config_sha256=sha256_bytes(value.before),
    )
    assert value.target.read_bytes() == value.desired
    assert value.release.read_bytes() == release_before
    assert value.events.count("write-config") == 1
    first_write = value.events.index("write-config")
    assert "capture-cli" in value.events[:first_write]
    assert value.events[first_write - 2 : first_write] == ["recheck-cli", "recheck-stopped"]
    assert value.events[-1] == "daemon-reload"


@pytest.mark.parametrize("previous_runtime", [None, COMMIT, "d" * 40])
def test_exact_desired_replay_has_no_filesystem_or_service_mutation(
    installed_runtime: InstallationHarness, previous_runtime: str | None
) -> None:
    value = installed_runtime
    value.target.write_bytes(value.desired)
    before_stat = value.target.stat()
    installation.stage(
        COMMIT,
        MODEL,
        pin_codex_runtime=True,
        previous_runtime_commit=previous_runtime,
        previous_model_config_sha256=sha256_bytes(value.before),
    )
    assert value.target.read_bytes() == value.desired
    after_stat = value.target.stat()
    assert (after_stat.st_ino, after_stat.st_mtime_ns, after_stat.st_ctime_ns) == (
        before_stat.st_ino,
        before_stat.st_mtime_ns,
        before_stat.st_ctime_ns,
    )
    assert "write-config" not in value.events and "daemon-reload" not in value.events


@pytest.mark.parametrize("digest", [None, "sha256:" + "f" * 64, "bad"])
def test_changed_native_pins_require_the_exact_model_configuration_predecessor_before_writes(
    installed_runtime: InstallationHarness, digest: str | None
) -> None:
    value = installed_runtime
    with pytest.raises(ChatError, match="TARGET_CONFLICT"):
        installation.stage(
            COMMIT,
            MODEL,
            pin_codex_runtime=True,
            previous_model_config_sha256=digest,
        )
    assert value.target.read_bytes() == value.before
    assert "write-config" not in value.events and "daemon-reload" not in value.events


@pytest.mark.parametrize("change", ["version", "same-version-bytes"])
def test_future_runtime_repin_uses_current_model_digest_without_a_new_source_release(
    installed_runtime: InstallationHarness, change: str
) -> None:
    value = installed_runtime
    value.target.write_bytes(value.desired)
    old_selection = value.target.read_bytes()
    replacement = IDENTITY.model_copy(
        update={
            "cli_version": "0.163.0" if change == "version" else IDENTITY.cli_version,
            "cli_binary_sha256": "sha256:" + "e" * 64,
        }
    )
    value.guard.identity = replacement
    expected = installation.configuration_payloads(
        COMMIT, MODEL, rag_policy=POLICY, native_runtime=replacement
    )[value.target]
    installation.stage(
        COMMIT,
        MODEL,
        pin_codex_runtime=True,
        previous_model_config_sha256=sha256_bytes(old_selection),
    )
    assert value.target.read_bytes() == expected
    assert value.release.read_bytes() == f"EOM_RUNTIME_SOURCE_COMMIT={COMMIT}\n".encode()
    assert value.events.count("write-config") == 1


@pytest.mark.parametrize("similarity_search", [False, True])
def test_codex_repin_preserves_enabled_source_and_exact_replay_does_not_reprovision(
    installed_runtime: InstallationHarness, monkeypatch, tmp_path, similarity_search
) -> None:
    value = installed_runtime
    flag = b"EOM_GENERAL_CHAT_PRIVATE_QUERY_SOURCE=READ_ONLY\n"
    if similarity_search:
        flag += b"EOM_GENERAL_CHAT_SIMILARITY_SEARCH=NATIVE_TOPIC\n"
    value.target.write_bytes(value.desired + flag)
    existing = value.target.read_bytes()
    calls = []
    monkeypatch.setattr(
        installation, "source_endpoint_preflight", lambda _: (b"fixed-source-policy", True)
    )
    monkeypatch.setattr(
        installation, "source_endpoint", lambda: SimpleNamespace(path=tmp_path / "source.sock")
    )
    monkeypatch.setattr(
        installation, "stage_source_endpoint", lambda *_a, **_k: calls.append("mutation")
    )
    installation.stage(
        COMMIT,
        MODEL,
        pin_codex_runtime=True,
        previous_model_config_sha256=sha256_bytes(existing),
    )
    assert value.target.read_bytes() == existing and not calls
    assert "write-config" not in value.events and "daemon-reload" not in value.events
    value.guard.identity = IDENTITY.model_copy(update={"cli_version": "0.163.0"})
    installation.stage(
        COMMIT,
        MODEL,
        pin_codex_runtime=True,
        previous_model_config_sha256=sha256_bytes(existing),
    )
    assert value.target.read_bytes().endswith(flag) and not calls


def test_codex_only_repin_cannot_be_used_to_change_source_selection(
    installed_runtime: InstallationHarness,
) -> None:
    value = installed_runtime
    with pytest.raises(ChatError, match="TARGET_CONFLICT"):
        installation.stage(
            COMMIT,
            MODEL,
            pin_codex_runtime=True,
            private_query_source=True,
            previous_model_config_sha256=sha256_bytes(value.before),
        )
    assert value.target.read_bytes() == value.before
    assert "write-config" not in value.events and "capture-cli" not in value.events


def test_source_provisioning_conflict_precedes_model_release_and_unit_writes(
    installed_runtime: InstallationHarness, monkeypatch
) -> None:
    value = installed_runtime
    previous = "d" * 40
    value.release.write_bytes(f"EOM_RUNTIME_SOURCE_COMMIT={previous}\n".encode())

    def conflict(_):
        raise ChatError("GENERAL_CHAT_INSTALL_TARGET_CONFLICT")

    monkeypatch.setattr(installation, "source_endpoint_preflight", conflict)
    with pytest.raises(ChatError, match="TARGET_CONFLICT"):
        installation.stage(
            COMMIT,
            MODEL,
            previous_runtime_commit=previous,
            rag_policy=POLICY,
            previous_model_config_sha256=sha256_bytes(value.before),
            private_query_source=True,
        )
    assert value.target.read_bytes() == value.before
    assert value.release.read_bytes() == f"EOM_RUNTIME_SOURCE_COMMIT={previous}\n".encode()
    assert "write-config" not in value.events and "daemon-reload" not in value.events


def test_application_release_advance_remains_separate_from_native_selection_cas(
    installed_runtime: InstallationHarness,
) -> None:
    value = installed_runtime
    previous = "d" * 40
    value.release.write_bytes(f"EOM_RUNTIME_SOURCE_COMMIT={previous}\n".encode())
    installation.stage(
        COMMIT,
        MODEL,
        pin_codex_runtime=True,
        previous_runtime_commit=previous,
        previous_model_config_sha256=sha256_bytes(value.before),
    )
    assert value.target.read_bytes() == value.desired
    assert value.release.read_bytes() == f"EOM_RUNTIME_SOURCE_COMMIT={COMMIT}\n".encode()
    assert value.events.count("write-config") == 2


def test_unit_predecessor_is_independent_of_runtime_and_exact_unit_replay_is_accepted(
    installed_runtime: InstallationHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = installed_runtime
    previous_runtime, previous_unit = "d" * 40, "e" * 40
    value.release.write_bytes(f"EOM_RUNTIME_SOURCE_COMMIT={previous_runtime}\n".encode())
    previous_payloads = {
        unit: (installation.UNIT_ROOT / unit).read_bytes() for unit in installation.UNITS
    }
    desired_payloads = {
        unit: payload + b"new-unit\n" for unit, payload in previous_payloads.items()
    }
    reads = []

    def read_unit(command: list[str], **_kw: Any) -> bytes:
        revision, path = command[-1].split(":", 1)
        reads.append(revision)
        assert revision in {COMMIT, previous_unit}
        return (desired_payloads if revision == COMMIT else previous_payloads)[Path(path).name]

    monkeypatch.setattr(subprocess, "check_output", read_unit)
    installation.stage(
        COMMIT,
        MODEL,
        previous_runtime_commit=previous_runtime,
        previous_unit_commit=previous_unit,
        rag_policy=POLICY,
    )
    assert previous_unit in reads and previous_runtime not in reads
    assert value.release.read_bytes() == f"EOM_RUNTIME_SOURCE_COMMIT={COMMIT}\n".encode()
    first_epochs = {}
    for unit, payload in desired_payloads.items():
        path = installation.UNIT_ROOT / unit
        assert path.read_bytes() == payload and path.stat().st_mode & 0o777 == 0o644
        first_epochs[unit] = (path.stat().st_ino, path.stat().st_mtime_ns)
    # An already-installed desired unit is not rechecked against its old predecessor.
    installation.stage(COMMIT, MODEL, previous_unit_commit=previous_unit, rag_policy=POLICY)
    for unit, epoch in first_epochs.items():
        actual = (installation.UNIT_ROOT / unit).stat()
        assert (actual.st_ino, actual.st_mtime_ns) == epoch


@pytest.mark.parametrize("invalid", ["", "latest", "a" * 39, "A" * 40, "b" * 41])
def test_unit_predecessor_requires_an_exact_immutable_commit_before_any_writes(
    installed_runtime: InstallationHarness, invalid: str
) -> None:
    value = installed_runtime
    before = value.release.read_bytes()
    with pytest.raises(ChatError, match="TARGET_INVALID"):
        installation.stage(COMMIT, MODEL, previous_unit_commit=invalid)
    assert value.target.read_bytes() == value.before and value.release.read_bytes() == before
    assert "write-config" not in value.events and "daemon-reload" not in value.events


@pytest.mark.parametrize("conflict", ["unit", "runtime"])
def test_separate_unit_pin_does_not_bypass_unit_or_runtime_predecessor_conflicts(
    installed_runtime: InstallationHarness, monkeypatch: pytest.MonkeyPatch, conflict: str
) -> None:
    value = installed_runtime
    previous_runtime, previous_unit = "d" * 40, "e" * 40
    value.release.write_bytes(f"EOM_RUNTIME_SOURCE_COMMIT={previous_runtime}\n".encode())
    before_release = value.release.read_bytes()
    unit_before = {
        unit: (installation.UNIT_ROOT / unit).read_bytes() for unit in installation.UNITS
    }

    def read_unit(command: list[str], **_kw: Any) -> bytes:
        revision = command[-1].split(":", 1)[0]
        return b"desired-unit\n" if revision == COMMIT else b"not-installed-predecessor\n"

    monkeypatch.setattr(subprocess, "check_output", read_unit)
    with pytest.raises(ChatError, match="TARGET_CONFLICT"):
        installation.stage(
            COMMIT,
            MODEL,
            previous_runtime_commit=previous_runtime if conflict == "unit" else "f" * 40,
            previous_unit_commit=previous_unit,
            rag_policy=POLICY,
        )
    assert (
        value.release.read_bytes() == before_release and value.target.read_bytes() == value.before
    )
    assert all(
        (installation.UNIT_ROOT / unit).read_bytes() == payload
        for unit, payload in unit_before.items()
    )
    assert "write-config" not in value.events and "daemon-reload" not in value.events


@pytest.mark.parametrize("enable_source", [False, True])
def test_normal_release_update_preserves_native_identity_without_implicit_cli_capture(
    installed_runtime: InstallationHarness, monkeypatch, tmp_path, enable_source
) -> None:
    value = installed_runtime
    previous_runtime = "d" * 40
    value.target.write_bytes(value.desired)
    value.release.write_bytes(f"EOM_RUNTIME_SOURCE_COMMIT={previous_runtime}\n".encode())
    existing = value.target.read_bytes()
    monkeypatch.setattr(
        installation, "source_endpoint_preflight", lambda _: (b"fixed-source-policy", True)
    )
    monkeypatch.setattr(
        installation, "source_endpoint", lambda: SimpleNamespace(path=tmp_path / "source.sock")
    )
    installation.stage(
        COMMIT,
        MODEL,
        previous_runtime_commit=previous_runtime,
        previous_model_config_sha256=sha256_bytes(existing),
        rag_policy=POLICY,
        private_query_source=enable_source,
        similarity_search=enable_source,
    )
    expected = installation.configuration_payloads(
        COMMIT,
        MODEL,
        rag_policy=POLICY,
        native_runtime=IDENTITY,
        private_query_source=enable_source,
        similarity_search=enable_source,
    )[value.target]
    assert value.target.read_bytes() == expected
    assert value.release.read_bytes() == f"EOM_RUNTIME_SOURCE_COMMIT={COMMIT}\n".encode()
    assert "capture-cli" not in value.events


@pytest.mark.parametrize("enable_source", [False, True])
@pytest.mark.parametrize("supply_policy", [False, True])
@pytest.mark.parametrize("runtime_commit", [COMMIT, "d" * 40])
def test_same_release_configuration_cas_changes_only_explicit_source_selections(
    installed_runtime: InstallationHarness,
    monkeypatch,
    tmp_path,
    enable_source,
    supply_policy,
    runtime_commit,
) -> None:
    value = installed_runtime
    current = installation.configuration_payloads(
        COMMIT,
        MODEL,
        rag_policy=POLICY,
        native_runtime=IDENTITY,
        private_query_source=not enable_source,
        similarity_search=not enable_source,
    )[value.target]
    value.target.write_bytes(current)
    value.release.write_bytes(f"EOM_RUNTIME_SOURCE_COMMIT={runtime_commit}\n".encode())
    original_release = value.release.read_bytes()
    release_epoch = value.release.stat()
    original_units = {
        unit: (installation.UNIT_ROOT / unit).read_bytes() for unit in installation.UNITS
    }
    monkeypatch.setattr(
        installation, "source_endpoint_preflight", lambda _: (b"fixed-source-policy", True)
    )
    monkeypatch.setattr(
        installation, "source_endpoint", lambda: SimpleNamespace(path=tmp_path / "source.sock")
    )
    installation.stage(
        COMMIT,
        MODEL,
        runtime_commit=runtime_commit,
        previous_runtime_commit=runtime_commit,
        previous_model_config_sha256=sha256_bytes(current),
        rag_policy=POLICY if supply_policy else None,
        private_query_source=enable_source,
        similarity_search=enable_source,
    )
    assert (
        value.target.read_bytes()
        == installation.configuration_payloads(
            COMMIT,
            MODEL,
            rag_policy=POLICY,
            native_runtime=IDENTITY,
            private_query_source=enable_source,
            similarity_search=enable_source,
        )[value.target]
    )
    assert value.release.read_bytes() == original_release
    after = value.release.stat()
    assert (after.st_ino, after.st_mtime_ns, after.st_ctime_ns) == (
        release_epoch.st_ino,
        release_epoch.st_mtime_ns,
        release_epoch.st_ctime_ns,
    )
    assert all(
        (installation.UNIT_ROOT / unit).read_bytes() == payload
        for unit, payload in original_units.items()
    )
    assert value.events.count("write-config") == 1
    assert "installed" in value.events and "source-stopped" in value.events
    assert "capture-cli" not in value.events
    assert value.events[value.events.index("write-config") - 1] == "recheck-stopped"


@pytest.mark.parametrize(
    "fault",
    [
        "missing-cas",
        "wrong-cas",
        "model",
        "policy",
        "release-missing",
        "release-conflict",
        "release-mode",
        "unit-missing",
        "unit-conflict",
        "incompatible",
        "busy",
        "source-preflight",
    ],
)
def test_same_release_configuration_cas_never_bypasses_existing_boundaries(
    installed_runtime: InstallationHarness, monkeypatch, tmp_path, fault
) -> None:
    value = installed_runtime
    value.target.write_bytes(value.desired)
    model, policy, digest = MODEL, POLICY, sha256_bytes(value.desired)
    if fault == "missing-cas":
        digest = None
    elif fault == "wrong-cas":
        digest = "sha256:" + "f" * 64
    elif fault == "model":
        model = "different-model"
    elif fault == "policy":
        policy = POLICY.model_copy(update={"sha256": "sha256:" + "f" * 64})
    elif fault == "release-missing":
        value.release.unlink()
    elif fault == "release-conflict":
        value.release.write_bytes(f"EOM_RUNTIME_SOURCE_COMMIT={'d' * 40}\n".encode())
    elif fault == "release-mode":
        value.release.chmod(0o644)
    elif fault == "unit-missing":
        (installation.UNIT_ROOT / installation.UNITS[0]).unlink()
    elif fault == "unit-conflict":
        (installation.UNIT_ROOT / installation.UNITS[0]).write_bytes(b"foreign-unit\n")
    elif fault == "busy":
        value.busy = True

    def reject(*_a, **_k):
        raise ChatError("GENERAL_CHAT_INSTALL_TARGET_CONFLICT")

    if fault == "incompatible":
        monkeypatch.setattr(installation, "require_compatible_runtime", reject)
    monkeypatch.setattr(
        installation,
        "source_endpoint_preflight",
        reject if fault == "source-preflight" else lambda _: (b"fixed-source-policy", True),
    )
    monkeypatch.setattr(
        installation, "source_endpoint", lambda: SimpleNamespace(path=tmp_path / "source.sock")
    )
    before = {
        path: path.read_bytes()
        for path in (
            value.target,
            value.release,
            *(installation.UNIT_ROOT / u for u in installation.UNITS),
        )
        if path.exists()
    }
    with pytest.raises(ChatError):
        installation.stage(
            COMMIT,
            model,
            previous_runtime_commit=COMMIT,
            previous_model_config_sha256=digest,
            rag_policy=policy,
            private_query_source=True,
            similarity_search=True,
        )
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert "capture-cli" not in value.events and "write-config" not in value.events
    assert "daemon-reload" not in value.events


def test_same_release_pin_is_rechecked_after_source_preflight_before_config_cas(
    installed_runtime: InstallationHarness, monkeypatch, tmp_path
) -> None:
    value = installed_runtime
    value.target.write_bytes(value.desired)

    def substitute(_):
        value.release.write_bytes(f"EOM_RUNTIME_SOURCE_COMMIT={'d' * 40}\n".encode())
        return b"fixed-source-policy", True

    monkeypatch.setattr(installation, "source_endpoint_preflight", substitute)
    monkeypatch.setattr(
        installation, "source_endpoint", lambda: SimpleNamespace(path=tmp_path / "source.sock")
    )
    with pytest.raises(ChatError, match="TARGET_CONFLICT"):
        installation.stage(
            COMMIT,
            MODEL,
            previous_runtime_commit=COMMIT,
            previous_model_config_sha256=sha256_bytes(value.desired),
            private_query_source=True,
            similarity_search=True,
        )
    assert value.target.read_bytes() == value.desired
    assert value.release.read_bytes() == f"EOM_RUNTIME_SOURCE_COMMIT={'d' * 40}\n".encode()
    assert "write-config" not in value.events and "daemon-reload" not in value.events


def test_normal_update_preserves_existing_source_and_similarity_selection_when_unspecified(
    installed_runtime: InstallationHarness, monkeypatch, tmp_path
) -> None:
    value = installed_runtime
    previous_runtime = "d" * 40
    current = installation.configuration_payloads(
        previous_runtime,
        MODEL,
        rag_policy=POLICY,
        native_runtime=IDENTITY,
        private_query_source=True,
        similarity_search=True,
    )[value.target]
    value.target.write_bytes(current)
    value.release.write_bytes(f"EOM_RUNTIME_SOURCE_COMMIT={previous_runtime}\n".encode())
    monkeypatch.setattr(
        installation, "source_endpoint_preflight", lambda _: (b"fixed-source-policy", True)
    )
    monkeypatch.setattr(
        installation, "source_endpoint", lambda: SimpleNamespace(path=tmp_path / "source.sock")
    )
    installation.stage(
        COMMIT,
        MODEL,
        previous_runtime_commit=previous_runtime,
        previous_model_config_sha256=sha256_bytes(current),
        rag_policy=POLICY,
    )
    assert value.target.read_bytes() == current and "capture-cli" not in value.events


def test_normal_native_preservation_does_not_bypass_model_configuration_cas(
    installed_runtime: InstallationHarness,
) -> None:
    value = installed_runtime
    value.target.write_bytes(value.desired)
    original_release = value.release.read_bytes()
    with pytest.raises(ChatError, match="TARGET_CONFLICT"):
        installation.stage(
            COMMIT,
            MODEL,
            previous_runtime_commit=COMMIT,
            previous_model_config_sha256="sha256:" + "f" * 64,
            rag_policy=POLICY,
        )
    assert value.target.read_bytes() == value.desired
    assert value.release.read_bytes() == original_release
    assert "capture-cli" not in value.events and "write-config" not in value.events


@pytest.mark.parametrize("change", ["model", "rag", "legacy", "extra", "partial-native"])
def test_native_pin_capture_cannot_change_or_discard_existing_model_or_rag(
    installed_runtime: InstallationHarness, change: str
) -> None:
    value = installed_runtime
    model, supplied_rag = MODEL, None
    if change == "model":
        model = "other-model"
    elif change == "rag":
        supplied_rag = POLICY.model_copy(update={"sha256": "sha256:" + "d" * 64})
    elif change == "legacy":
        value.target.write_bytes(f"EOM_GENERAL_CHAT_MODEL={MODEL}\n".encode())
    elif change == "extra":
        value.target.write_bytes(value.before + b"EXTRA_CONFIG=unexpected\n")
    else:
        value.target.write_bytes(value.before + b"EOM_GENERAL_CHAT_CODEX_VERSION=0.162.1\n")
    unchanged = value.target.read_bytes()
    with pytest.raises(ChatError):
        installation.stage(
            COMMIT,
            model,
            rag_policy=supplied_rag,
            pin_codex_runtime=True,
            previous_model_config_sha256=sha256_bytes(unchanged),
        )
    assert value.target.read_bytes() == unchanged
    assert "capture-cli" not in value.events and "write-config" not in value.events


@pytest.mark.parametrize("changed", ["cli", "service"])
def test_changed_cli_epoch_or_restarted_service_refuses_native_config_replacement(
    installed_runtime: InstallationHarness, changed: str
) -> None:
    value = installed_runtime
    if changed == "cli":

        def reject() -> None:
            raise ValueError("synthetic protected epoch changed")

        value.guard.assert_unchanged = reject
    else:
        value.busy = True
    with pytest.raises((ChatError, ValueError)):
        installation.stage(
            COMMIT,
            MODEL,
            pin_codex_runtime=True,
            previous_model_config_sha256=sha256_bytes(value.before),
        )
    assert value.target.read_bytes() == value.before
    assert "write-config" not in value.events and "daemon-reload" not in value.events


def test_native_pin_flag_is_explicit_and_routed_to_the_installer_without_model_or_rag_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(sys, "argv", ["installer", "stage", COMMIT, MODEL, "--pin-codex-runtime"])
    monkeypatch.setattr(installation, "stage", lambda *args, **kw: calls.append((args, kw)))
    assert installation.main() == 0
    assert calls[0][0] == (COMMIT, MODEL)
    assert calls[0][1]["pin_codex_runtime"] is True
    assert calls[0][1]["rag_policy"] is None


def test_cli_routes_independent_unit_predecessor_without_replacing_runtime_predecessor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous_runtime, previous_unit = "d" * 40, "e" * 40
    calls = []
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "installer",
            "stage",
            COMMIT,
            MODEL,
            "--previous-runtime-commit",
            previous_runtime,
            "--previous-unit-commit",
            previous_unit,
        ],
    )
    monkeypatch.setattr(installation, "stage", lambda *args, **kw: calls.append((args, kw)))
    assert installation.main() == 0
    assert calls[0][0] == (COMMIT, MODEL)
    assert calls[0][1]["previous_runtime_commit"] == previous_runtime
    assert calls[0][1]["previous_unit_commit"] == previous_unit
