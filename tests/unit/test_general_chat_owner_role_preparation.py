"""Fixed production preparation guards; no real roles, files or secrets used."""

from __future__ import annotations

import stat
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from eom_orchestrator.general_chat_state import ChatError
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from sqlalchemy.engine import make_url

from scripts.chat import prepare_owner_role as preparation

COMMIT = "a" * 40


def test_nonroot_guard_precedes_subprocess_and_private_reads(monkeypatch):
    monkeypatch.setattr(preparation.os, "geteuid", lambda: 123)

    def forbidden(*args, **kwargs):
        raise AssertionError("no protected work before root admission")

    monkeypatch.setattr(preparation.subprocess, "check_output", forbidden)
    with pytest.raises(ChatError, match="GENERAL_CHAT_ROLE_REQUIRES_ROOT"):
        preparation.require_preparation_boundary(COMMIT)


@pytest.mark.parametrize(
    ("head", "dirty", "state", "code"),
    [
        ("b" * 40, "", "inactive", "GENERAL_CHAT_ROLE_SOURCE_MISMATCH"),
        (COMMIT, " M changed", "inactive", "GENERAL_CHAT_ROLE_SOURCE_MISMATCH"),
        (COMMIT, "", "active", "GENERAL_CHAT_OWNER_MUST_BE_STOPPED"),
        (COMMIT, "", "activating", "GENERAL_CHAT_OWNER_MUST_BE_STOPPED"),
        (COMMIT, "", "failed", "GENERAL_CHAT_OWNER_MUST_BE_STOPPED"),
    ],
)
def test_source_and_stopped_service_are_checked_before_protected_state(
    monkeypatch, head, dirty, state, code
):
    monkeypatch.setattr(preparation.os, "geteuid", lambda: 0)
    replies = iter([head, dirty, state])
    monkeypatch.setattr(preparation.subprocess, "check_output", lambda *_a, **_k: next(replies))
    with pytest.raises(ChatError, match=code):
        preparation.require_preparation_boundary(COMMIT)


@pytest.mark.parametrize(
    ("mode", "uid", "gid", "ready"),
    [
        (stat.S_IFDIR | 0o750, 0, 123, True),
        (stat.S_IFLNK | 0o750, 0, 123, False),
        (stat.S_IFDIR | 0o777, 0, 123, False),
        (stat.S_IFDIR | 0o750, 456, 123, False),
        (stat.S_IFDIR | 0o750, 0, 456, False),
    ],
)
def test_protected_parent_is_fixed_root_owned_directory(monkeypatch, mode, uid, gid, ready):
    monkeypatch.setattr(preparation.os, "geteuid", lambda: 0)
    replies = iter([COMMIT, "", "inactive"])
    monkeypatch.setattr(preparation.subprocess, "check_output", lambda *_a, **_k: next(replies))
    monkeypatch.setattr(preparation.grp, "getgrnam", lambda group: SimpleNamespace(gr_gid=123))
    metadata = SimpleNamespace(st_mode=mode, st_uid=uid, st_gid=gid)
    monkeypatch.setattr(
        preparation, "TARGET", SimpleNamespace(parent=SimpleNamespace(lstat=lambda: metadata))
    )
    if ready:
        preparation.require_preparation_boundary(COMMIT)
    else:
        with pytest.raises(ChatError, match="GENERAL_CHAT_PROTECTED_ENVIRONMENT_INVALID"):
            preparation.require_preparation_boundary(COMMIT)


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"EOM_DATABASE_URL": "postgresql+psycopg://broad:synthetic@127.0.0.1:5432/eom"},
        {"EOM_GENERAL_CHAT_DATABASE_URL": "not-a-url"},
        {"EOM_GENERAL_CHAT_DATABASE_URL": "postgresql+psycopg://broad:x@127.0.0.1:5432/eom"},
        {
            "EOM_GENERAL_CHAT_DATABASE_URL": "postgresql+psycopg://eom_general_chat_runtime:x@127.0.0.1:5432/other"
        },
        {
            "EOM_GENERAL_CHAT_DATABASE_URL": "postgresql+psycopg://eom_general_chat_runtime:x@127.0.0.1:5432/eom?sslmode=disable"
        },
    ],
)
def test_replay_rejects_wrong_keys_url_identity_and_options(monkeypatch, tmp_path, value):
    target = tmp_path / "existing"
    target.touch()
    monkeypatch.setattr(preparation, "TARGET", target)
    monkeypatch.setattr(preparation, "read_chat_environment", lambda *_a, **_k: value)
    with pytest.raises(ChatError, match="GENERAL_CHAT_ROLE_IDENTITY_CONFLICT"):
        preparation.retained_password("eom")


def test_replay_retains_only_the_exact_dedicated_credential(monkeypatch, tmp_path):
    target = tmp_path / "existing"
    target.touch()
    monkeypatch.setattr(preparation, "TARGET", target)
    monkeypatch.setattr(
        preparation,
        "read_chat_environment",
        lambda *_a, **_k: {
            "EOM_GENERAL_CHAT_DATABASE_URL": "postgresql+psycopg://eom_general_chat_runtime:retained@127.0.0.1:5432/eom"
        },
    )
    assert preparation.retained_password("eom") == "retained"


@pytest.fixture
def staged(monkeypatch):
    calls = []
    rows = SimpleNamespace(head=[("eom", CURRENT_MIGRATION_REVISION)], session=None)

    class Cursor:
        def execute(self, query, values=None):
            calls.append((query, values))

        def fetchall(self):
            return rows.head

        def fetchone(self):
            return rows.session

    monkeypatch.setattr(preparation.sys, "argv", ["prepare", COMMIT])
    monkeypatch.setattr(preparation, "require_preparation_boundary", lambda commit: None)
    monkeypatch.setattr(preparation.grp, "getgrnam", lambda group: SimpleNamespace(gr_gid=123))
    monkeypatch.setattr(
        preparation,
        "read_chat_environment",
        lambda *_a, **_k: {
            "POSTGRES_DB": "eom",
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "synthetic-admin-not-for-runtime",
        },
    )
    monkeypatch.setattr(preparation, "retained_password", lambda database: None)
    monkeypatch.setattr(preparation.secrets, "token_urlsafe", lambda size: "synthetic-dedicated")
    monkeypatch.setattr(
        preparation.psycopg,
        "connect",
        lambda **kwargs: nullcontext(SimpleNamespace(cursor=lambda: nullcontext(Cursor()))),
    )
    monkeypatch.setattr(preparation, "require_chat_role_replay", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        preparation,
        "install_chat_environment",
        lambda path, payload, **kwargs: calls.append(("install", payload, kwargs)),
    )
    monkeypatch.setattr(
        preparation,
        "prepare_chat_role",
        lambda cursor, spec, **kwargs: calls.append(("role", spec, kwargs)),
    )
    return calls, rows


def test_first_preparation_uses_shared_profile_after_durable_distinct_secret(staged, capsys):
    calls, _ = staged
    assert preparation.main() == 0
    install, role = calls[-2:]
    assert install[0] == "install" and role[0] == "role"
    url = make_url(install[1].decode().split("=", 1)[1].strip())
    assert url.username == preparation.OWNER_DATABASE_ROLE
    assert url.password == "synthetic-dedicated"
    assert install[2] == {"uid": 0, "gid": 0}
    assert role[1].role == preparation.OWNER_DATABASE_ROLE and role[1].database == "eom"
    assert role[2] == {"password": "synthetic-dedicated", "exists": False}
    output = capsys.readouterr()
    assert "STAGED" in output.out and "service_activation=NONE" in output.out
    assert "synthetic" not in output.out + output.err


@pytest.mark.parametrize("failure", ["revision", "database", "sessions"])
def test_database_revision_or_active_role_prevents_both_secret_and_grants(staged, capsys, failure):
    calls, rows = staged
    if failure == "revision":
        rows.head = [("eom", "outdated")]
    elif failure == "database":
        rows.head = [("other", CURRENT_MIGRATION_REVISION)]
    else:
        rows.session = (1,)
    assert preparation.main() == 1
    assert not any(call[0] in {"install", "role"} for call in calls)
    assert "GENERAL_CHAT_" in capsys.readouterr().err


def test_exact_replay_does_not_install_or_rotate_any_credential(staged, monkeypatch):
    calls, _ = staged
    monkeypatch.setattr(preparation, "retained_password", lambda database: "retained")
    monkeypatch.setattr(preparation, "require_chat_role_replay", lambda *args, **kwargs: True)

    def forbidden(*args, **kwargs):
        raise AssertionError("replay must not generate another credential")

    monkeypatch.setattr(preparation.secrets, "token_urlsafe", forbidden)
    assert preparation.main() == 0
    assert not any(call[0] == "install" for call in calls)
    assert calls[-1][2] == {"password": "retained", "exists": True}


def test_unknown_private_exception_is_not_exposed(staged, monkeypatch, capsys):
    calls, _ = staged

    def failure(*args, **kwargs):
        raise RuntimeError("do-not-expose-synthetic-password")

    monkeypatch.setattr(preparation, "require_chat_role_replay", failure)
    assert preparation.main() == 1
    assert not any(call[0] in {"install", "role"} for call in calls)
    assert capsys.readouterr().err == "GENERAL_CHAT_RUNTIME_STOPPED\n"
