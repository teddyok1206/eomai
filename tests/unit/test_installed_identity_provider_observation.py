"""Real temporary FD/bytes with explicit synthetic process/ownership/unit seams.

Never root, installed provider, authentication, DB or model acceptance evidence.
"""

from __future__ import annotations

import os
import subprocess
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml
from eom_identity_service import installed_owner_session_provider as module
from eom_identity_service.owner_session_transport import (
    FixedIdentityProviderPin,
    OwnerSessionTransportError,
)

_ORIGINAL_UNIT_READER = module._unit


@pytest.fixture
def observation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    profile = getattr(request, "param", 0o644)
    fresh_seconds = profile.get("fresh_auth_seconds", 900) if isinstance(profile, dict) else 900
    configuration = tmp_path / "config/api.yaml"
    secret = tmp_path / "keys/api.env"
    code_root = tmp_path / "code"
    monkeypatch.setattr(module, "_CONFIG", configuration)
    monkeypatch.setattr(module, "_SECRET", secret)
    monkeypatch.setattr(module, "_API_PREFIX", code_root)
    monkeypatch.setattr(module.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=1000, pw_gid=1000))
    paths = (configuration, secret, *(code_root / name for name in sorted(module._CODE_MEMBERS)))
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.parent.chmod(0o755)
        path.write_bytes(b"synthetic configuration/code" if path != secret else b"NOT-A-REAL-KEY")
        if path == configuration:
            path.write_bytes(
                yaml.safe_dump(
                    {"schema_version": 1, "auth": {"fresh_auth_seconds": fresh_seconds}}
                ).encode()
            )
        path.chmod(0o644 if path != secret else 0o600)
    configuration.chmod(profile.get("mode", 0o644) if isinstance(profile, dict) else profile)
    process_path = tmp_path / "process.stat"
    process_path.write_text("12345 (python) S " + " ".join(["0"] * 18 + ["9876"]) + "\n")
    descriptor = os.open(process_path, os.O_RDONLY)
    descriptors = [descriptor]
    original_fstat = os.fstat
    original_lstat = Path.lstat
    original_readlink = os.readlink

    def metadata(value, *, root: bool):
        return SimpleNamespace(
            **{
                name: 0 if name == "st_uid" and root else getattr(value, name)
                for name in (
                    "st_dev",
                    "st_ino",
                    "st_mode",
                    "st_uid",
                    "st_gid",
                    "st_nlink",
                    "st_size",
                    "st_mtime_ns",
                    "st_ctime_ns",
                )
            }
        )

    special = {configuration, secret, configuration.parent, secret.parent}

    def fstat(fd):
        raw = original_fstat(fd)
        path = original_readlink(f"/proc/self/fd/{fd}")
        return metadata(raw, root=Path(path) in special)

    def lstat(path, *args, **kwargs):
        return metadata(original_lstat(path, *args, **kwargs), root=path in special)

    def readlink(path):
        if str(path) == f"/proc/self/fd/{descriptor}":
            return "/proc/12345/stat"
        return original_readlink(path)

    monkeypatch.setattr(module.os, "fstat", fstat)
    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(module.os, "readlink", readlink)

    def held(path: Path):
        fd = os.open(path, os.O_PATH if path == secret else os.O_RDONLY)
        parent = os.open(path.parent, os.O_PATH | os.O_DIRECTORY)
        descriptors.extend((fd, parent))
        return module.HeldIdentityProviderFile(
            path,
            fd,
            parent,
            module._epoch(fstat(fd)),
            module._epoch(fstat(parent)),
            None if path == secret else "sha256:" + sha256(path.read_bytes()).hexdigest(),
        )

    config, key, *code = tuple(held(path) for path in paths)
    pin = FixedIdentityProviderPin("a" * 40, "sha256:" + "b" * 64, config.sha256)
    value = module.InstalledIdentityProviderObservation(
        pin, 12345, 9876, "c" * 32, descriptor, config, key, tuple(code)
    )
    started = datetime.now(UTC) + timedelta(seconds=10)
    properties = {
        "MainPID": "12345",
        "InvocationID": "c" * 32,
        "User": "eom-api",
        "ActiveState": "active",
        "FragmentPath": "/etc/systemd/system/eom-api.service",
        "DropInPaths": "",
        "ExecMainStartTimestamp": started.strftime("%a %Y-%m-%d %H:%M:%S UTC"),
    }
    monkeypatch.setattr(module, "_unit", lambda: dict(properties))
    yield value, properties, descriptors, original_fstat
    for fd in set(descriptors):
        with suppress(OSError):
            os.close(fd)


def assert_current(value):
    module.ProtectedInstalledIdentityProviderAdmission(value).assert_current(
        source_commit=value.pin.source_commit,
        wheel_sha256=value.pin.wheel_sha256,
        configuration_sha256=value.pin.configuration_sha256,
    )


def test_provider_unit_timeout_retries_only_observation_and_does_not_cache(monkeypatch):
    output = "\n".join(name + "=synthetic" for name in sorted(module._UNIT_PROPERTIES)).encode()
    response = SimpleNamespace(returncode=0, stdout=output, stderr=b"")
    run = Mock(side_effect=[subprocess.TimeoutExpired("systemctl", 2), response, response])
    monkeypatch.setattr(module.subprocess, "run", run)
    assert set(module._unit()) == module._UNIT_PROPERTIES
    assert [call.kwargs["timeout"] for call in run.call_args_list] == [2, 3]
    assert run.call_args_list[0].args == run.call_args_list[1].args
    assert run.call_args.args[0][:4] == (
        "/usr/bin/systemctl",
        "--no-pager",
        "show",
        "eom-api.service",
    )
    assert run.call_args.kwargs["env"] == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC"}
    assert set(module._unit()) == module._UNIT_PROPERTIES
    assert run.call_count == 3 and run.call_args.kwargs["timeout"] == 2


def test_persistent_provider_unit_timeout_is_bounded_and_redacted(monkeypatch):
    run = Mock(side_effect=subprocess.TimeoutExpired("systemctl", 2, output=b"private detail"))
    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(OwnerSessionTransportError, match=r"^OWNER_SESSION_PROVIDER_UNAVAILABLE$"):
        module._unit()
    assert [call.kwargs["timeout"] for call in run.call_args_list] == [2, 3]


@pytest.mark.parametrize("fault", ("exit", "stderr", "partial", "duplicate", "os_error"))
def test_provider_observation_retry_never_accepts_invalid_reply(monkeypatch, fault):
    output = "\n".join(name + "=synthetic" for name in sorted(module._UNIT_PROPERTIES)).encode()
    response = SimpleNamespace(returncode=0, stdout=output, stderr=b"")
    if fault == "exit":
        response.returncode = 1
    elif fault == "stderr":
        response.stderr = b"denied"
    elif fault == "partial":
        response.stdout = b"MainPID=123"
    elif fault == "duplicate":
        response.stdout += b"\nUser=duplicate"
    run = Mock(
        side_effect=[
            subprocess.TimeoutExpired("systemctl", 2),
            OSError("denied") if fault == "os_error" else response,
        ]
    )
    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises((OwnerSessionTransportError, OSError)):
        module._unit()
    assert run.call_count == 2


@pytest.mark.parametrize("changed", (False, True))
def test_provider_identity_is_still_checked_after_observation_retry(
    observation, monkeypatch, changed
):
    value, properties, *_ = observation
    # Keep the fixture's FD/ownership seams and exercise the real subprocess reader.
    if changed:
        properties["InvocationID"] = "d" * 32
    response = SimpleNamespace(
        returncode=0,
        stderr=b"",
        stdout="\n".join(f"{key}={item}" for key, item in properties.items()).encode(),
    )
    run = Mock(side_effect=[subprocess.TimeoutExpired("systemctl", 2), response, response])
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module, "_unit", _ORIGINAL_UNIT_READER)
    if changed:
        with pytest.raises(OwnerSessionTransportError):
            assert_current(value)
    else:
        assert_current(value)
    assert run.call_count == (2 if changed else 3)


def test_fresh_auth_policy_uses_only_current_pinned_configuration(observation):
    value, *_ = observation
    admission = module.ProtectedInstalledIdentityProviderAdmission(value)
    assert admission.fresh_auth_seconds() == 900
    value.configuration.path.write_text("auth:\n  fresh_auth_seconds: 2700\n")
    with pytest.raises(OwnerSessionTransportError):
        admission.fresh_auth_seconds()


@pytest.mark.parametrize("seconds", (60, 900, 2700, 3600, True, "2700", 0, 3601))
def test_fresh_auth_policy_value_and_identity_bounds(observation, monkeypatch, seconds):
    value, *_ = observation
    admission = module.ProtectedInstalledIdentityProviderAdmission(value)
    checked = []
    monkeypatch.setattr(type(admission), "assert_current", lambda _self, **kw: checked.append(kw))
    monkeypatch.setattr(
        module,
        "_raw",
        lambda fd, size: (
            yaml.safe_dump({"auth": {"fresh_auth_seconds": seconds}}).encode()
            if fd == value.configuration.descriptor
            else pytest.fail("secret or non-config read")
        ),
    )
    if type(seconds) is int and 60 <= seconds <= 3600:
        assert admission.fresh_auth_seconds() == seconds
        assert len(checked) == 2
    else:
        with pytest.raises(OwnerSessionTransportError):
            admission.fresh_auth_seconds()


def test_staged_configuration_does_not_require_traversing_private_api_directory(
    observation, monkeypatch
):
    value, *_ = observation
    original = Path.lstat

    def private_configuration(path, *args, **kwargs):
        if path == value.configuration.path:
            raise PermissionError("dropped owner cannot traverse API private directory")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", private_configuration)
    assert_current(value)


@pytest.mark.parametrize("observation", (0o640, 0o644), indirect=True)
def test_real_readonly_and_metadata_only_descriptors_match_synthetic_unit(observation):
    value, *_ = observation
    assert_current(value)
    with pytest.raises(OSError):
        os.read(value.key_metadata.descriptor, 1)


@pytest.mark.parametrize("mode", (0o604, 0o664, 0o646))
def test_unapproved_configuration_modes_remain_denied(observation, mode):
    value, *_ = observation
    value.configuration.path.chmod(mode)
    configuration = replace(
        value.configuration, epoch=module._epoch(os.fstat(value.configuration.descriptor))
    )
    with pytest.raises(OwnerSessionTransportError, match=r"^OWNER_SESSION_PROVIDER_UNAVAILABLE$"):
        assert_current(replace(value, configuration=configuration))


@pytest.mark.parametrize("field", ("MainPID", "InvocationID", "User", "ActiveState", "DropInPaths"))
def test_process_unit_replacement_is_denied(observation, field):
    value, properties, *_ = observation
    properties[field] = "foreign"
    with pytest.raises(OwnerSessionTransportError, match=r"^OWNER_SESSION_PROVIDER_UNAVAILABLE$"):
        assert_current(value)


@pytest.mark.parametrize("kind", ("code", "configuration", "key_metadata"))
def test_in_place_file_changes_are_denied(observation, kind):
    value, *_ = observation
    member = value.code[0] if kind == "code" else getattr(value, kind)
    member.path.write_bytes(b"changed private bytes")
    with pytest.raises(OwnerSessionTransportError, match=r"^OWNER_SESSION_PROVIDER_UNAVAILABLE$"):
        assert_current(value)


@pytest.mark.parametrize("kind", ("code", "configuration", "key_metadata"))
def test_atomic_namespace_replacement_is_denied(observation, kind):
    value, *_ = observation
    member = value.code[0] if kind == "code" else getattr(value, kind)
    candidate = member.path.with_name("replacement")
    candidate.write_bytes(member.path.read_bytes())
    candidate.chmod(member.path.stat().st_mode & 0o777)
    candidate.replace(member.path)
    with pytest.raises(OwnerSessionTransportError, match=r"^OWNER_SESSION_PROVIDER_UNAVAILABLE$"):
        assert_current(value)


def test_readable_key_handle_is_denied_without_reading_key(observation):
    value, _properties, descriptors, *_ = observation
    descriptor = os.open(value.key_metadata.path, os.O_RDONLY)
    descriptors.append(descriptor)
    key = replace(value.key_metadata, descriptor=descriptor)
    with pytest.raises(OwnerSessionTransportError, match=r"^OWNER_SESSION_PROVIDER_UNAVAILABLE$"):
        assert_current(replace(value, key_metadata=key))


def test_foreign_release_pin_and_closed_fd_are_content_free(observation):
    value, *_ = observation
    adapter = module.ProtectedInstalledIdentityProviderAdmission(value)
    with pytest.raises(OwnerSessionTransportError) as failure:
        adapter.assert_current(
            source_commit="f" * 40,
            wheel_sha256=value.pin.wheel_sha256,
            configuration_sha256=value.pin.configuration_sha256,
        )
    assert str(failure.value) == "OWNER_SESSION_PROVIDER_UNAVAILABLE"
    os.close(value.configuration.descriptor)
    with pytest.raises(OwnerSessionTransportError, match=r"^OWNER_SESSION_PROVIDER_UNAVAILABLE$"):
        assert_current(value)


def test_files_newer_than_api_start_and_late_unit_denial_fail(observation, monkeypatch):
    value, properties, *_ = observation
    properties["ExecMainStartTimestamp"] = "Tue 2020-01-01 00:00:00 UTC"
    with pytest.raises(OwnerSessionTransportError):
        assert_current(value)
    properties["ExecMainStartTimestamp"] = (datetime.now(UTC) + timedelta(seconds=10)).strftime(
        "%a %Y-%m-%d %H:%M:%S UTC"
    )
    calls = []

    def unit():
        calls.append(None)
        return dict(properties) | ({"InvocationID": "d" * 32} if len(calls) > 1 else {})

    monkeypatch.setattr(module, "_unit", unit)
    with pytest.raises(OwnerSessionTransportError):
        assert_current(value)


def test_wrong_process_start_duplicate_files_and_extra_code_are_rejected(observation):
    value, *_ = observation
    with pytest.raises(OwnerSessionTransportError):
        assert_current(replace(value, start_ticks=8888))
    with pytest.raises(OwnerSessionTransportError):
        replace(value, code=(*value.code, value.code[0]))
    with pytest.raises(OwnerSessionTransportError):
        replace(value, process_descriptor=value.configuration.descriptor)


def test_root_capture_factory_never_opens_paths_for_nonroot(monkeypatch):
    monkeypatch.setattr(module.os, "geteuid", lambda: 1000)
    opened = []
    monkeypatch.setattr(module.os, "open", lambda *args, **kwargs: opened.append(args))
    pin = FixedIdentityProviderPin("a" * 40, "sha256:" + "b" * 64, "sha256:" + "c" * 64)
    with (
        pytest.raises(OwnerSessionTransportError),
        module.open_installed_identity_provider_observation(pin, code_sha256=()),
    ):
        pytest.fail("nonroot cannot create a root installed observation")
    assert not opened


@pytest.mark.parametrize("kind", ("code", "configuration", "key_metadata"))
def test_unrelated_sibling_change_does_not_invalidate_pinned_provider_file(observation, kind):
    value, *_ = observation
    member = value.code[0] if kind == "code" else getattr(value, kind)
    assert_current(value)
    sibling = member.path.parent / "unrelated-cache-metadata"
    sibling.write_bytes(b"not authentication material")
    assert_current(value)
    sibling.unlink()
    assert_current(value)


@pytest.mark.parametrize("kind", ("code", "configuration", "key_metadata"))
@pytest.mark.parametrize("mutation", ("mode", "replacement", "symlink"))
def test_named_parent_identity_and_permissions_remain_pinned(observation, kind, mutation):
    value, *_ = observation
    member = value.code[0] if kind == "code" else getattr(value, kind)
    assert_current(value)
    parent = member.path.parent
    if mutation == "mode":
        parent.chmod(0o777)
    else:
        backup = parent.with_name(parent.name + "-previous")
        parent.rename(backup)
        if mutation == "symlink":
            parent.symlink_to(backup, target_is_directory=True)
        else:
            parent.mkdir(mode=0o755)
    with pytest.raises(OwnerSessionTransportError, match=r"^OWNER_SESSION_PROVIDER_UNAVAILABLE$"):
        assert_current(value)


def test_fixed_code_inventory_contains_no_key_or_caller_selected_member():
    members = module.identity_provider_code_members()
    assert members == tuple(sorted(set(members)))
    assert set(members) == {
        "eom_api/dependencies.py",
        "eom_api/lifespan.py",
        "eom_api/request_context.py",
        "eom_api/services/reference_query_prepare_client.py",
        "eom_api/routers/owner_session_capture.py",
        "eom_api/settings.py",
        "eom_identity_service/auth_service.py",
        "eom_identity_service/authenticated_session_fence.py",
        "eom_identity_service/owner_session_transport.py",
        "eom_identity_service/tokens.py",
        "eom_operator_identity/owner_session_capture.py",
        "eom_operator_identity/owner_session_capture_v11.py",
    }
    assert all(
        name.endswith(".py") and ".." not in name and "secrets" not in name for name in members
    )
