"""Installed source composition contracts, not live OS/auth/DB-role acceptance."""

from __future__ import annotations

import ast
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_orchestrator import general_chat_owner_main as owner_main
from eom_orchestrator import general_chat_owner_runtime as runtime
from eom_orchestrator import general_chat_worker_main as worker_main
from eom_orchestrator.general_chat_native import NativeChatError
from eom_orchestrator.general_chat_state import ChatError

ROOT = Path(__file__).resolve().parents[2]
VALUES = {
    "EOM_GENERAL_CHAT_DATABASE_URL": "postgresql+psycopg://eom_general_chat_runtime:synthetic@127.0.0.1:5432/eom_test",
    "EOM_RUNTIME_SOURCE_COMMIT": "a" * 40,
    "EOM_GENERAL_CHAT_MODEL": "synthetic-model",
}


def test_owner_configuration_is_explicit_frozen_and_does_not_render_password():
    config = runtime.ChatOwnerConfiguration.from_environment(VALUES)
    assert (
        config.model == "synthetic-model"
        and config.database_url.username == runtime.OWNER_DATABASE_ROLE
    )
    assert "synthetic@" not in repr(config)
    with pytest.raises(AttributeError):
        config.model = "other"


def test_rag_configuration_requires_explicit_protocol_and_both_immutable_policy_pins():
    from tests.unit.general_chat_rag_fixtures import scope

    pins = {
        "EOM_GENERAL_CHAT_PROTOCOL_VERSION": "4",
        "EOM_GENERAL_CHAT_RAG_POLICY_REVISION_ID": scope().policy.access_policy_revision_id,
        "EOM_GENERAL_CHAT_RAG_POLICY_SHA256": scope().policy.sha256,
    }
    assert (
        runtime.ChatOwnerConfiguration.from_environment(VALUES | pins).rag_policy == scope().policy
    )
    assert runtime.ChatOwnerConfiguration.from_environment(VALUES).rag_policy is None
    for key in pins:
        missing = dict(pins)
        del missing[key]
        with pytest.raises(ChatError, match="CONFIGURATION_INVALID"):
            runtime.ChatOwnerConfiguration.from_environment(VALUES | missing)
    for invalid in (
        {"EOM_GENERAL_CHAT_PROTOCOL_VERSION": "5"},
        {"EOM_GENERAL_CHAT_PROTOCOL_VERSION": "3"},
        {"EOM_GENERAL_CHAT_RAG_POLICY_REVISION_ID": "latest"},
        {"EOM_GENERAL_CHAT_RAG_POLICY_SHA256": "bad"},
    ):
        with pytest.raises(ChatError, match="CONFIGURATION_INVALID"):
            runtime.ChatOwnerConfiguration.from_environment(VALUES | pins | invalid)


@pytest.mark.parametrize(
    "key,value",
    [
        ("EOM_GENERAL_CHAT_DATABASE_URL", "postgresql+psycopg://postgres:s@127.0.0.1:5432/eom"),
        (
            "EOM_GENERAL_CHAT_DATABASE_URL",
            "postgresql+psycopg://eom_general_chat_runtime:s@external:5432/eom",
        ),
        (
            "EOM_GENERAL_CHAT_DATABASE_URL",
            VALUES["EOM_GENERAL_CHAT_DATABASE_URL"] + "?options=admin",
        ),
        ("EOM_GENERAL_CHAT_DATABASE_URL", "sqlite:///test.db"),
        ("EOM_RUNTIME_SOURCE_COMMIT", "main"),
        ("EOM_GENERAL_CHAT_MODEL", "model --unsafe"),
    ],
)
def test_owner_configuration_rejects_fallbacks_and_unpinned_inputs(key, value):
    with pytest.raises(ChatError, match="GENERAL_CHAT_OWNER_CONFIGURATION_INVALID"):
        runtime.ChatOwnerConfiguration.from_environment(VALUES | {key: value})


@pytest.mark.parametrize("missing", VALUES)
def test_missing_specific_environment_is_not_filled_by_global_credentials(missing):
    values = VALUES | {"EOM_DATABASE_URL": VALUES["EOM_GENERAL_CHAT_DATABASE_URL"]}
    del values[missing]
    with pytest.raises(ChatError, match="CONFIGURATION_INVALID"):
        runtime.ChatOwnerConfiguration.from_environment(values)


def test_owner_requires_exact_service_uid_before_configuration_or_connections(monkeypatch, capsys):
    monkeypatch.setattr(runtime.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=os.getuid() + 1))
    monkeypatch.setattr(
        owner_main, "chat_owner_engine", lambda *_args, **_kwargs: pytest.fail("no DB")
    )
    assert owner_main.main() == 1
    assert capsys.readouterr().err == "GENERAL_CHAT_OWNER_NOT_READY\n"


def test_worker_rejects_identity_before_private_handoff_or_native_start(monkeypatch, capsys):
    monkeypatch.setattr(worker_main.sys, "argv", ["worker", "--model", "synthetic-model"])

    def reject():
        raise NativeChatError("PRIVATE_IDENTITY_DETAIL")

    monkeypatch.setattr(worker_main, "require_native_chat_identity", reject)
    monkeypatch.setattr(
        worker_main, "IsolatedCodexChatWorker", lambda **_: pytest.fail("no native")
    )
    monkeypatch.setattr(
        worker_main, "ChatLocalHandoff", lambda *_args, **_kwargs: pytest.fail("no read")
    )
    assert worker_main.main() == 1
    assert capsys.readouterr().err == "GENERAL_CHAT_WORKER_NOT_READY\n"


@pytest.mark.parametrize("change", ["role", "superuser", "migration", "forbidden", "none"])
def test_read_only_owner_database_admission_checks_exact_role_and_privilege_boundary(
    change, monkeypatch
):
    statements = []
    rows = [
        [runtime.OWNER_DATABASE_ROLE, False, False, False, False, False],
        runtime.CURRENT_MIGRATION_REVISION,
    ]
    if change == "role":
        rows[0][0] = "postgres"
    elif change == "superuser":
        rows[0][1] = True
    elif change == "migration":
        rows[1] = "20261007_0048"
    monkeypatch.setattr(runtime, "chat_role_boundary_ready", lambda *_args, **_kw: True)
    monkeypatch.setattr(
        runtime, "chat_privileges_ready", lambda *_args, **_kw: change != "forbidden"
    )

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def execute(self, sql):
            statements.append(str(sql))
            value = rows[len(statements) - 1]
            return SimpleNamespace(one=lambda: value, scalar_one=lambda: value)

    engine = SimpleNamespace(connect=Connection)
    if change == "none":
        runtime.require_chat_owner_database(engine)
    else:
        with pytest.raises(ChatError, match="GENERAL_CHAT_OWNER_DATABASE_NOT_READY"):
            runtime.require_chat_owner_database(engine)
    assert all(value.startswith("SELECT ") for value in statements)
    assert "alembic_version" in statements[-1]


def test_worker_entrypoint_never_imports_owner_storage_or_database_adapters():
    forbidden = {
        "sqlalchemy",
        "eom_orchestrator.database",
        "eom_orchestrator.models",
        "eom_orchestrator.control_artifacts",
        "eom_orchestrator.general_chat_owner",
    }
    for leaf in ("general_chat_worker_main.py", "general_chat_worker_lifecycle.py"):
        tree = ast.parse((ROOT / "services/orchestrator/eom_orchestrator" / leaf).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in forbidden


def test_systemd_units_keep_separate_capacity_durable_handoff_and_graceful_drain():
    worker = (ROOT / "infra/systemd/eom-general-chat-worker.service").read_text()
    owner = (ROOT / "infra/systemd/eom-general-chat.service").read_text()
    assert "User=eom-cdx-chat\nGroup=eom-cdx-chat\n" in worker
    assert "SupplementaryGroups=" not in worker and "InaccessiblePaths=/mnt/nas" in worker
    assert "StateDirectory=eom-general-chat-worker\nStateDirectoryMode=0700" in worker
    assert "ReadOnlyPaths=/srv/eom/worker-homes/eom-cdx-chat/.codex/config.toml" in worker
    assert "User=eom-general-chat\nGroup=eom-api\n" in owner
    assert "SupplementaryGroups=eom eom-cdx-chat" in owner
    assert "Wants=eom-general-chat-worker.service" in owner
    assert "Requires=eom-general-chat-worker.service" not in owner
    assert "InaccessiblePaths=/home/eom/EOM /home/eom/EOMIS /srv/eom/worker-homes" in owner
    for value in (worker, owner):
        assert "KillMode=mixed\nTimeoutStopSec=1300" in value
        assert "Restart=on-failure" in value and "StartLimitBurst=5" in value
        assert "python -I -m eom_orchestrator.general_chat_" in value
        assert "PYTHONPATH=" not in value and "codex auth" not in value


def test_chat_owner_retains_its_own_group_for_fixed_private_query_socket():
    # A service Group override omits the account's primary GID from initgroups.
    # The private QUERY parent/socket use that named group, not eom-api.
    owner = (ROOT / "infra/systemd/eom-general-chat.service").read_text()
    fields = dict(
        line.split("=", 1)
        for line in owner.splitlines()
        if line.startswith(("User=", "Group=", "SupplementaryGroups="))
    )
    assert fields["User"] == "eom-general-chat" and fields["Group"] == "eom-api"
    assert set(fields["SupplementaryGroups"].split()) == {
        "eom",
        "eom-cdx-chat",
        "eom-general-chat",
    }
    worker = (ROOT / "infra/systemd/eom-general-chat-worker.service").read_text()
    assert "SupplementaryGroups=" not in worker
    assert "User=eom-cdx-chat\nGroup=eom-cdx-chat\n" in worker
