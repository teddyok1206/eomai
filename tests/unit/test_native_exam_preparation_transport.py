from __future__ import annotations

import io
import json
import stat
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_hwpx_builder.util import canonical_json_bytes, sha256_bytes
from eom_hwpx_contracts.native_exam_preparation import NativeExamFilePreparationRequest
from eom_hwpx_contracts.validation import validate_contract
from eom_orchestrator import native_exam_preparation as adapter
from pydantic import ValidationError

from tests.hwpx.test_native_exam_preparation import prepared_payload


def repack(payload: bytes, *, changes=None, extra=None, remove=None, transform=None) -> bytes:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    parts.update(changes or {})
    parts.update(extra or {})
    for name in remove or ():
        parts.pop(name)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, raw in sorted(parts.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100600 << 16
            if transform:
                info = transform(info)
            archive.writestr(info, raw)
    return output.getvalue()


@pytest.mark.parametrize(
    "kind", ["hash", "missing", "extra", "traversal", "case", "symlink", "compressed", "duplicate"]
)
def test_untrusted_transport_fails_before_creating_workspace(tmp_path: Path, kind: str) -> None:
    _, request, _, payload = prepared_payload(tmp_path)
    if kind == "hash":
        payload = repack(payload, changes={"items/001.hwpx": b"PK\x03\x04changed"})
    elif kind == "missing":
        payload = repack(payload, remove=("items/002.hwpx",))
    elif kind == "extra":
        payload = repack(payload, extra={"unlisted.json": b"{}"})
    elif kind == "traversal":
        payload = repack(payload, extra={"../escape.hwpx": b"PK\x03\x04"})
    elif kind == "case":
        payload = repack(payload, extra={"ITEMS/001.hwpx": b"PK\x03\x04"})
    elif kind == "symlink":

        def special(info):
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            return info

        payload = repack(payload, transform=special)
    elif kind == "compressed":

        def compressed(info):
            info.compress_type = zipfile.ZIP_DEFLATED
            return info

        payload = repack(payload, transform=compressed)
    else:
        output = io.BytesIO(payload)
        with zipfile.ZipFile(output, "a") as archive, pytest.warns(UserWarning):
            archive.writestr("result.json", b"{}")
        payload = output.getvalue()
    with pytest.raises(ValueError):
        adapter.unpack_native_exam_file_preparation(
            payload, request=request, workspace=tmp_path / "out"
        )
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "escape.hwpx").exists()


@pytest.mark.parametrize(
    "field,new",
    [
        ("source_role", "SOLUTIONS"),
        ("original_source_sha256", "sha256:" + "a" * 64),
        ("request_sha256", "sha256:" + "b" * 64),
    ],
)
def test_result_cannot_switch_source_request_or_role(tmp_path: Path, field: str, new: str) -> None:
    _, request, result, payload = prepared_payload(tmp_path)
    value = result.model_dump(mode="json")
    value[field] = new
    altered = repack(payload, changes={"result.json": canonical_json_bytes(value)})
    with pytest.raises(ValueError):
        adapter.unpack_native_exam_file_preparation(
            altered, request=request, workspace=tmp_path / "out"
        )
    assert not (tmp_path / "out").exists()


def test_rehashed_split_is_still_bound_to_native_source_role_and_plan(tmp_path: Path) -> None:
    _, request, result, payload = prepared_payload(tmp_path)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        split = json.loads(archive.read("splits/001.json"))
    split["source_role"] = "SOLUTIONS"
    raw = canonical_json_bytes(split)
    value = result.model_dump(mode="json")
    value["items"][0]["split_evidence"].update({"bytes": len(raw), "sha256": sha256_bytes(raw)})
    value["materialized_bytes"] = sum(
        item[member]["bytes"]
        for item in value["items"]
        for member in ("document", "split_evidence")
    )
    altered = repack(
        payload, changes={"splits/001.json": raw, "result.json": canonical_json_bytes(value)}
    )
    with pytest.raises(ValueError, match="SPLIT_CLOSURE_INVALID"):
        adapter.unpack_native_exam_file_preparation(
            altered, request=request, workspace=tmp_path / "out"
        )
    assert not (tmp_path / "out").exists()


def test_port_uses_only_fixed_installed_module_with_existing_isolation_budget(
    tmp_path: Path, monkeypatch
) -> None:
    data, request, result, payload = prepared_payload(tmp_path)
    calls = []
    python = Path("/opt/eom/native-exam-tools/runtime/bin/python")
    monkeypatch.setattr(adapter, "_installed_python", lambda path: python)

    def run(executable, arguments, incoming, **kwargs):
        calls.append((executable, arguments, incoming, kwargs))
        return payload

    prepared = adapter.prepare_native_exam_file(
        data, request=request, workspace=tmp_path / "out", python=python, run=run
    )
    assert prepared.result == result and len(calls) == 1
    executable, arguments, incoming, limits = calls[0]
    assert executable == python and incoming == data
    assert arguments[:5] == (
        "-I",
        "-B",
        "-m",
        "eom_hwpx_builder.native_exam_tool",
        "--request-json",
    )
    assert json.loads(arguments[5]) == request.model_dump(mode="json")
    assert limits["timeout_seconds"] == 115.0
    assert limits["maximum_stdout"] == 512 * 1024 * 1024
    with pytest.raises(ValueError, match="INPUT_INVALID"):
        adapter.prepare_native_exam_file(
            data + b"changed", request=request, workspace=tmp_path / "other", python=python, run=run
        )
    assert len(calls) == 1


def test_request_rejects_unnecessary_or_missing_converter_and_arbitrary_paths(
    tmp_path: Path,
) -> None:
    _, request, _, _ = prepared_payload(tmp_path)
    value = request.model_dump(mode="json")
    value["executable"] = "/usr/bin/not-a-parser"
    with pytest.raises(ValidationError):
        NativeExamFilePreparationRequest.model_validate(value)
    value = request.model_dump(mode="json")
    value["source_format"] = "HWP"
    with pytest.raises(ValidationError, match="CONVERTER_MISMATCH"):
        NativeExamFilePreparationRequest.model_validate(value)
    value = request.model_dump(mode="json")
    value["expected_numbers"] = [2, 1]
    with pytest.raises(ValidationError, match="NUMBERS_INVALID"):
        NativeExamFilePreparationRequest.model_validate(value)
    validate_contract("native-exam-file-preparation", request.model_dump(mode="json"))


def test_existing_workspace_is_never_overwritten(tmp_path: Path) -> None:
    _, request, _, payload = prepared_payload(tmp_path)
    workspace = tmp_path / "out"
    prepared = adapter.unpack_native_exam_file_preparation(
        payload, request=request, workspace=workspace
    )
    before = (workspace / "items/001.hwpx").read_bytes()
    with pytest.raises(ValueError, match="OUTPUT_INVALID"):
        adapter.unpack_native_exam_file_preparation(payload, request=request, workspace=workspace)
    assert (workspace / "items/001.hwpx").read_bytes() == before
    assert prepared.workspace == workspace


@pytest.mark.parametrize(
    "change",
    [
        {"st_uid": 1000},
        {"st_gid": 1000},
        {"st_mode": stat.S_IFDIR | 0o775},
        {"st_mode": stat.S_IFLNK | 0o777},
    ],
)
def test_runtime_prefix_must_be_root_protected_not_just_the_executable(monkeypatch, change) -> None:
    python = Path("/opt/eom/native-exam/runtime/bin/python")
    prefix = python.parent.parent
    with monkeypatch.context() as scoped:
        scoped.setattr(adapter, "_trusted_executable", lambda path: path)

        def metadata(path):
            mode = stat.S_IFLNK | 0o777 if path == python else stat.S_IFDIR | 0o755
            values = {"st_uid": 0, "st_gid": 0, "st_mode": mode}
            if path == prefix:
                values.update(change)
            return SimpleNamespace(**values)

        scoped.setattr(Path, "lstat", metadata)
        with pytest.raises(ValueError, match="RUNTIME_UNTRUSTED"):
            adapter._installed_python(python)
    with pytest.raises(ValueError, match="RUNTIME_UNTRUSTED"):
        adapter._installed_python(Path("relative/bin/python"))


def test_valid_root_owned_runtime_configuration_is_kept(monkeypatch) -> None:
    python = Path("/opt/eom/native-exam/runtime/bin/python")
    with monkeypatch.context() as scoped:
        scoped.setattr(adapter, "_trusted_executable", lambda path: path)
        scoped.setattr(
            Path,
            "lstat",
            lambda path: SimpleNamespace(
                st_uid=0,
                st_gid=0,
                st_mode=stat.S_IFREG | 0o755 if path == python else stat.S_IFDIR | 0o755,
            ),
        )
        assert adapter._installed_python(python) == python


def test_venv_lexical_executable_is_kept_when_trusted_symlink_target_differs(
    tmp_path: Path, monkeypatch
) -> None:
    data, request, _, payload = prepared_payload(tmp_path)
    configured = Path("/opt/eom/native-exam/runtime/bin/python")
    base = Path("/opt/eom/conda/envs/eom-base/bin/python3.12")
    calls = []

    def run(executable, arguments, incoming, **kwargs):
        calls.append(executable)
        return payload

    with monkeypatch.context() as scoped:
        scoped.setattr(adapter, "_trusted_executable", lambda path: base)

        def metadata(path):
            mode = stat.S_IFLNK | 0o777 if path == configured else stat.S_IFDIR | 0o755
            return SimpleNamespace(st_uid=0, st_gid=0, st_mode=mode)

        scoped.setattr(Path, "lstat", metadata)
        assert adapter._installed_python(configured) == configured
        adapter.prepare_native_exam_file(
            data, request=request, workspace=tmp_path / "received", python=configured, run=run
        )
    assert calls == [configured]


def test_corrupt_zip_crc_is_a_stable_failure_without_candidates(tmp_path: Path) -> None:
    _, request, _, payload = prepared_payload(tmp_path)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        member = archive.getinfo("items/001.hwpx")
        start = member.header_offset + 30 + len(member.filename.encode()) + len(member.extra)
    changed = bytearray(payload)
    changed[start + 20] ^= 1
    with pytest.raises(ValueError, match="OUTPUT_INVALID"):
        adapter.unpack_native_exam_file_preparation(
            bytes(changed), request=request, workspace=tmp_path / "out"
        )
    assert not (tmp_path / "out").exists()
