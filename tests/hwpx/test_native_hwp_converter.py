from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_hwpx_builder import native_hwp_converter as adapter
from eom_hwpx_builder.errors import HwpxError
from eom_hwpx_builder.util import canonical_json_bytes, sha256_bytes, sha256_file
from eom_hwpx_contracts.curated_document import CuratedHwpConverterSnapshot
from eom_hwpx_contracts.native_conversion import NativeHwpConverterBundle

from tests.hwpx.test_native_hwp_preservation import candidate


def bundle(tmp_path, monkeypatch):
    parent = tmp_path / "vendor"
    parent.mkdir()
    java = tmp_path / "java"
    java.write_bytes(b"fixed Java binary")
    files = [
        {"filename": name, "sha256": sha256_bytes(name.encode()), "size_bytes": len(name)}
        for name in ("converter.jar", "hwplib-1.1.10.jar", "hwpxlib-1.0.9.jar")
    ]
    value = {
        "schema_version": "native-hwp-converter-bundle/1.0",
        "source_commit": "62d95b980a4e3a6766877dd3fb6f7f45f4afcf3d",
        "java_sha256": sha256_file(java),
        "files": files,
    }
    value["bundle_sha256"] = sha256_bytes(canonical_json_bytes(value))
    snapshot = CuratedHwpConverterSnapshot(
        profile="HWP2HWPX_NATIVE_V1",
        source_commit=value["source_commit"],
        bundle_sha256=value["bundle_sha256"],
    )
    root = parent / value["bundle_sha256"].split(":")[1]
    root.mkdir()
    for row in files:
        (root / row["filename"]).write_bytes(row["filename"].encode())
    (root / "manifest.json").write_bytes(canonical_json_bytes(value))
    monkeypatch.setattr(adapter, "_TOOL_ROOT", parent)
    monkeypatch.setattr(adapter, "_JAVA", java)
    # Simulate a protected system installation. Permissions/ownership have their
    # own tests below and are also checked in the real sandbox integration.
    monkeypatch.setattr(adapter, "_protected_path", lambda *args, **kwargs: None)
    return root, java, value, snapshot


def test_converter_pins_bundle_files_java_and_uses_no_ambient_options(tmp_path, monkeypatch):
    root, java, value, snapshot = bundle(tmp_path, monkeypatch)
    observed = adapter.NativeHwpConverter(snapshot)
    assert observed._classpath == os.pathsep.join(
        str(root / row["filename"]) for row in value["files"]
    )
    for member in (root / "converter.jar", java):
        original = member.read_bytes()
        member.write_bytes(b"changed")
        with pytest.raises(HwpxError, match="differs"):
            adapter.NativeHwpConverter(snapshot)
        member.write_bytes(original)
    value["java_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="bundle hash differs"):
        NativeHwpConverterBundle.model_validate(value)


def test_protected_install_rejects_symlinks_write_permissions_and_other_owner(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(adapter, "_INSTALL_OWNER_UID", os.geteuid())
    file = tmp_path / "tool"
    file.write_bytes(b"fixed")
    file.chmod(0o644)
    adapter._protected_path(file)
    file.chmod(0o664)
    with pytest.raises(HwpxError, match="not protected"):
        adapter._protected_path(file)
    file.chmod(0o644)
    link = tmp_path / "link"
    link.symlink_to(file)
    with pytest.raises(HwpxError, match="not protected"):
        adapter._protected_path(link)
    monkeypatch.setattr(adapter, "_INSTALL_OWNER_UID", os.geteuid() + 1)
    with pytest.raises(HwpxError, match="not protected"):
        adapter._protected_path(file)


def test_native_adapter_uses_fixed_command_and_checks_result_before_normalization(
    tmp_path, monkeypatch
):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    raw, evidence = candidate(fixture)
    source = tmp_path / "source.hwp"
    source.write_bytes(b"native HWP input")
    source_hash = sha256_file(source)
    evidence["source_sha256"] = source_hash
    converter = adapter.NativeHwpConverter.__new__(adapter.NativeHwpConverter)
    converter._classpath = "fixed-installed-jars"
    output = tmp_path / "converted.hwpx"
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        Path(command[-2]).write_bytes(raw.read_bytes())
        Path(command[-1]).write_bytes(canonical_json_bytes(evidence))
        return SimpleNamespace(returncode=0)

    def normalize(candidate_path, target):
        target.write_bytes(candidate_path.read_bytes())
        return "validated conversion"

    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "untrusted ambient option")
    monkeypatch.setattr(adapter.subprocess, "run", run)
    monkeypatch.setattr(adapter, "normalize_hwp_conversion_package", normalize)
    assert converter.convert(source, output, source_sha256=source_hash) == "validated conversion"
    command, kwargs = calls[0]
    assert command[0] == str(adapter._JAVA)
    assert command[5] == "eom.hwpx.NativeHwpConverter"
    assert "JAVA_TOOL_OPTIONS" not in kwargs["env"]
    assert kwargs["stdin"] == subprocess.DEVNULL and kwargs["timeout"] == 90
    assert source.read_bytes() == b"native HWP input"
    with pytest.raises(HwpxError):
        converter.convert(source, output, source_sha256=source_hash)
    assert len(calls) == 1


def test_failed_converter_never_normalizes_or_produces_deliverable(tmp_path, monkeypatch):
    source, output = tmp_path / "source.hwp", tmp_path / "output.hwpx"
    source.write_bytes(b"native")
    converter = adapter.NativeHwpConverter.__new__(adapter.NativeHwpConverter)
    converter._classpath = "fixed"
    monkeypatch.setattr(
        adapter.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1)
    )
    with pytest.raises(HwpxError, match="converter failed"):
        converter.convert(source, output, source_sha256=sha256_file(source))
    assert not output.exists()
