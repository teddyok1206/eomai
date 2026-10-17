"""Synthetic root/entry ports and real temporary config bytes; no service/privileged effect."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from eom_catalog_service import image_gpu_unit_guardian as guardian
from eom_catalog_service.image_gpu_unit_identity import image_gpu_unit_templates
from eom_identifiers import canonical_json_bytes
from jsonschema import ValidationError as SchemaValidationError
from pydantic import TypeAdapter

from scripts.image_provider import gpu_guard_entry as entry
from tests.unit.test_embedding_cuda_installation_evidence import metadata

UNIT = "eom-image-provider@imgreq_" + "a" * 32 + ".service"


@pytest.fixture
def configured(monkeypatch, tmp_path):
    installation = guardian.ImageGpuInstallationPins(
        tuple((name, "sha256:" + "a" * 64) for name in image_gpu_unit_templates()),
        "sha256:" + "b" * 64,
        metadata()["receipt"].device_capture,
    )
    config = {
        "schema_version": "image-gpu-guardian-config/1.0",
        "owner_release_commit": entry.OWNER_RELEASE,
        "guardian_template_sha256": "sha256:" + "c" * 64,
        "installation": TypeAdapter(guardian.ImageGpuInstallationPins).dump_python(
            installation, mode="json"
        ),
    }
    path = tmp_path / "installation.json"
    path.write_bytes(canonical_json_bytes(config))
    calls, reads = [], []
    state = SimpleNamespace(
        flags=SimpleNamespace(isolated=1),
        dont_write_bytecode=True,
        platform="linux",
        argv=["start_gpu_guard.py", UNIT],
        path=[],
    )

    def read(selected, maximum):
        reads.append(selected)
        return (
            path.read_bytes() if selected == path else b"synthetic root code",
            entry._epoch(path.lstat()),
        )

    monkeypatch.setattr(entry, "ENTRY_ROOT", tmp_path)
    monkeypatch.setattr(entry, "__file__", str(tmp_path / "start_gpu_guard.py"))
    monkeypatch.setattr(entry, "sys", state)
    monkeypatch.setattr(entry.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(entry, "_directory", lambda _: None)
    monkeypatch.setattr(entry, "_read", read)
    monkeypatch.setattr(
        guardian,
        "start_image_gpu_unit_guardian",
        lambda *args, **kwargs: calls.append(("START", args, kwargs)),
    )
    monkeypatch.setattr(
        guardian,
        "manage_image_gpu_unit_lifetime",
        lambda *args, **kwargs: calls.append(("WATCH", args, kwargs)),
    )
    return config, installation, path, calls, reads, state


@pytest.mark.parametrize("mode", ("start_gpu_guard.py", "watch_gpu_guard.py"))
def test_fixed_entry_validates_schema_and_frozen_pins_before_one_supported_call(
    configured,
    monkeypatch,
    mode,
):
    config, installation, path, calls, reads, state = configured
    monkeypatch.setattr(entry, "__file__", str(path.parent / mode))
    state.argv[0] = mode
    entry.main()
    assert state.path == [str(entry.OWNER_SITE)]
    expected = (
        ("START", (UNIT,), {"guardian_template_sha256": config["guardian_template_sha256"]})
        if mode == "start_gpu_guard.py"
        else ("WATCH", (UNIT,), {"installation": installation})
    )
    assert calls == [expected]
    assert len(reads) == 3 and path in reads


@pytest.mark.parametrize(
    "fault", ("owner", "authority", "nested_authority", "version", "sha", "names", "device")
)
def test_bad_config_cannot_choose_authority_owner_latest_or_other_gpu_units(configured, fault):
    config, _, path, calls, _, _ = configured
    if fault == "owner":
        config["owner_release_commit"] = "e" * 40
    elif fault == "authority":
        config["role"] = "ADMIN"
    elif fault == "nested_authority":
        config["installation"]["role"] = "ADMIN"
    elif fault == "version":
        config["schema_version"] = "latest"
    elif fault == "sha":
        config["guardian_template_sha256"] = "missing"
    elif fault == "names":
        config["installation"]["templates"][-1][0] = "not-eom@.service"
    else:
        config["installation"]["device"]["gpu_uuid"] = "invented"
    path.write_bytes(canonical_json_bytes(config))
    with pytest.raises((ValueError, SchemaValidationError)):
        entry.main()
    assert calls == []


def test_duplicate_json_key_is_not_silently_reinterpreted(configured):
    _, _, path, calls, _, _ = configured
    path.write_bytes(b'{"owner_release_commit":"old","owner_release_commit":"new"}')
    with pytest.raises(ValueError, match="ENTRY_INVALID"):
        entry.main()
    assert calls == []


def test_changed_config_after_submission_is_not_silently_rebound_or_replayed(
    configured, monkeypatch
):
    _, _, path, calls, _, _ = configured

    def submit(*args, **kwargs):
        calls.append("ONCE")
        path.write_bytes(b"changed after effect")

    monkeypatch.setattr(guardian, "start_image_gpu_unit_guardian", submit)
    with pytest.raises(ValueError, match="ENTRY_INVALID"):
        entry.main()
    assert calls == ["ONCE"]


@pytest.mark.parametrize("fault", ("nonroot", "mode", "arguments", "isolation"))
def test_bad_process_or_entry_identity_stops_before_config_read(configured, monkeypatch, fault):
    _, _, path, calls, reads, state = configured
    if fault == "nonroot":
        monkeypatch.setattr(entry.os, "getresuid", lambda: (984, 984, 984))
    elif fault == "mode":
        monkeypatch.setattr(entry, "__file__", str(path.parent / "arbitrary.py"))
    elif fault == "arguments":
        state.argv.append("extra")
    else:
        state.flags.isolated = 0
    with pytest.raises(ValueError, match="ENTRY_INVALID"):
        entry.main()
    assert calls == [] and reads == []


def test_protected_reader_does_not_follow_a_symlink(tmp_path, monkeypatch):
    original = tmp_path / "original"
    original.write_bytes(b"unchanged synthetic fixture")
    alias = tmp_path / "alias"
    alias.symlink_to(original)
    monkeypatch.setattr(entry, "_directory", lambda _: None)
    with pytest.raises(OSError):
        entry._read(alias, 4096)
    assert original.read_bytes() == b"unchanged synthetic fixture"


def test_stable_diagnostic_codes_are_kept_without_dumping_validation_input():
    assert entry.diagnostic_code(ValueError("IMAGE_GPU_GUARDIAN_SUBMISSION_UNCERTAIN")) == (
        "IMAGE_GPU_GUARDIAN_SUBMISSION_UNCERTAIN"
    )
    assert entry.diagnostic_code(ValueError("synthetic private configuration value")) == (
        "IMAGE_GPU_GUARD_ENTRY_FAILED_VALUEERROR"
    )
