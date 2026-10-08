from __future__ import annotations

import json

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from scripts.chat import prepare_test_role


def test_nonroot_preparation_stops_before_private_files_or_postgres(monkeypatch, capsys):
    monkeypatch.setattr(prepare_test_role.os, "geteuid", lambda: 999)
    monkeypatch.setattr(
        prepare_test_role.sys, "argv", ["prepare", "/tmp/eom-api-testdb-synthetic", "a" * 40]
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("must reject before side effects")

    monkeypatch.setattr(prepare_test_role, "read_chat_environment", forbidden)
    monkeypatch.setattr(prepare_test_role.psycopg, "connect", forbidden)
    assert prepare_test_role.main() == 1
    assert capsys.readouterr().err == "GENERAL_CHAT_TEST_ROLE_REQUIRES_ROOT\n"


def test_source_mismatch_is_rejected_before_secret_read(monkeypatch, capsys):
    monkeypatch.setattr(prepare_test_role.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        prepare_test_role.sys, "argv", ["prepare", "/tmp/eom-api-testdb-synthetic", "b" * 40]
    )
    monkeypatch.setattr(
        prepare_test_role.subprocess, "check_output", lambda *_args, **_kwargs: "a" * 40
    )
    assert prepare_test_role.main() == 1
    assert capsys.readouterr().err == "GENERAL_CHAT_TEST_SOURCE_MISMATCH\n"


def test_guarded_manifest_parser_reuses_the_same_strict_identity_and_field_checks(tmp_path):
    manifest = DisposableManifest.create("20261008000000_abcdef12")
    target = tmp_path / "manifest.json"
    target.write_text(manifest.to_json(), encoding="ascii")
    assert DisposableManifest.from_json(manifest.to_json()) == DisposableManifest.load(target)
    values = json.loads(manifest.to_json())
    values["database"] = "eom"
    import pytest

    from scripts.api.testdb_guard import TestDatabaseGuardError

    with pytest.raises(TestDatabaseGuardError):
        DisposableManifest.from_json(json.dumps(values))
