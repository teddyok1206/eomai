"""Synthetic Conda byte-audit boundaries; no protected installation or tool execution."""

from __future__ import annotations

import hashlib
import io
import json
import os
import runpy
import selectors
import struct
import subprocess
import sys
import tarfile
import time
import zipfile
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn, cast

import pytest
from eom_catalog_service import embedding_conda_runtime_closure as conda
from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
    ObservedRuntimeMemberBytes,
)
from eom_catalog_service.embedding_runtime_wheel_closure import (
    RuntimeWheelArchivePin,
    RuntimeWheelInstallationPin,
    VerifiedRuntimeWheelMembers,
    verify_installed_runtime_wheel,
)


def _hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _member(tmp_path: Path, raw: bytes = b"bounded metadata", name: str = "member") -> Path:
    path = tmp_path / name
    path.write_bytes(raw)
    path.chmod(0o600)
    return path


def _deny(*_args: object, **_kwargs: object) -> NoReturn:
    raise AssertionError("invalid or retained input must not perform this operation")


def _plan() -> conda.CondaRuntimeAuditPlan:
    return conda.CondaRuntimeAuditPlan(
        "CPU_INDEX_FP32",
        conda._SOURCE_SHA,
        1,
        tuple(
            conda.CondaRuntimeArchivePin(f"package{index:02d}-1.0-build_0.conda", _hash(b"x"), 1)
            for index in range(31)
        ),
        tuple(
            RuntimeWheelArchivePin(f"{name}-{version}-py3-none-any.whl", "sha256:" + sha, 1)
            for name, version, sha in conda._OVERLAYS
        ),
    )


class _Fence:
    def __init__(self, result: object = None) -> None:
        self.result = result
        self.calls = 0

    def assert_current(self) -> None:
        self.calls += 1
        return cast(None, self.result)

    def open_zstd(self) -> subprocess.Popen[bytes]:
        # Synthetic-only factory; the production owner binds the accepted executable FD.
        return subprocess.Popen(
            [str(conda._ZSTD_PATH), "-q", "-d", "-c"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"},
            cwd="/",
            close_fds=True,
        )


def test_initial_empty_member_is_an_immutable_actual_observation(tmp_path: Path) -> None:
    path = _member(tmp_path, b"")
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    observed = files.observe_protected_member_bytes(path, maximum=1)
    assert observed == ObservedRuntimeMemberBytes(_hash(b""), 0, b"")
    with pytest.raises(FrozenInstanceError):
        observed.size_bytes = 1  # type: ignore[misc]
    assert files.read(path, sha256=observed.sha256, size=0, maximum=1) is observed.raw
    files.assert_unchanged()


def test_verified_borrow_retains_sha_and_fd_without_rehash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _member(tmp_path)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    digest, size = _hash(path.read_bytes()), path.stat().st_size
    files.verify(path, sha256=digest, size=size, maximum=1024)
    monkeypatch.setattr(hashlib, "sha256", _deny)
    with files.open_verified_member(path) as (descriptor, actual_sha):
        assert actual_sha == digest and os.pread(descriptor, 4, 0) == b"boun"
    with pytest.raises(OSError):
        os.fstat(descriptor)


@pytest.mark.parametrize("state", ["unknown", "identity_only", "stale", "substitute"])
def test_verified_borrow_rejects_unknown_identity_stale_and_substituted_fd(
    tmp_path: Path, state: str
) -> None:
    path = _member(tmp_path)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    if state == "identity_only":
        files.observe_protected_member_identity(path)
    elif state != "unknown":
        files.verify(path, sha256=_hash(path.read_bytes()), size=path.stat().st_size, maximum=1024)
    if state == "stale":
        path.write_bytes(b"changed")
    with (
        pytest.raises(InstalledRuntimeProofError),
        files.open_verified_member(path) as (descriptor, _sha),
    ):
        other = _member(tmp_path, b"other", "other")
        replacement = os.open(other, os.O_RDONLY)
        try:
            os.dup2(replacement, descriptor)
        finally:
            os.close(replacement)


@pytest.mark.parametrize("maximum", [True, False, -1, 0, 8 * 1024**2 + 1, 1.0, "1", None])
def test_initial_observation_rejects_invalid_exact_bound_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, maximum: object
) -> None:
    path = _member(tmp_path)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    monkeypatch.setattr(os, "open", _deny)
    with pytest.raises(InstalledRuntimeProofError, match="OBSERVATION_INVALID"):
        files.observe_protected_member_bytes(path, maximum=cast(int, maximum))


def test_initial_size_bound_precedes_pread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _member(tmp_path, b"xx")
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    monkeypatch.setattr(os, "pread", _deny)
    with pytest.raises(InstalledRuntimeProofError, match="FILE_SIZE_INVALID"):
        files.observe_protected_member_bytes(path, maximum=1)


def test_initial_aggregate_retained_budget_precedes_pread_and_releases_after_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = b"x" * (8 * 1024**2)
    first, second, excess = (
        _member(tmp_path, raw, "first"),
        _member(tmp_path, raw, "second"),
        _member(tmp_path, b"x", "excess"),
    )
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    observed = files.observe_protected_member_bytes(first, maximum=len(raw))
    files.observe_protected_member_bytes(second, maximum=len(raw))
    with monkeypatch.context() as blocked:
        blocked.setattr(os, "pread", _deny)
        with pytest.raises(InstalledRuntimeProofError, match="FILE_SIZE_INVALID"):
            files.observe_protected_member_bytes(excess, maximum=1)
        assert files.read(first, sha256=observed.sha256, size=len(raw), maximum=len(raw)) is (
            observed.raw
        )
    assert files.observe_protected_member_bytes(excess, maximum=1).raw == b"x"


def test_initial_observation_reuses_same_bytes_once_without_rehash_then_preserves_old_denial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _member(tmp_path)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    observed = files.observe_protected_member_bytes(path, maximum=1024)
    monkeypatch.setattr(os, "pread", _deny)
    files.verify(path, sha256=observed.sha256, size=observed.size_bytes, maximum=1024)
    assert files.read(path, sha256=observed.sha256, size=observed.size_bytes, maximum=1024) is (
        observed.raw
    )
    files.verify(path, sha256=observed.sha256, size=observed.size_bytes, maximum=1024)
    with pytest.raises(InstalledRuntimeProofError, match="REPEATED_BYTE_READ"):
        files.read(path, sha256=observed.sha256, maximum=1024)
    with pytest.raises(InstalledRuntimeProofError, match="REPEATED_BYTE_READ"):
        files.observe_protected_member_bytes(path, maximum=1024)


def test_expected_read_without_initial_observation_keeps_repeated_read_denial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = b"expected bytes"
    path = _member(tmp_path, raw)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    assert files.read(path, sha256=_hash(raw), maximum=1024) == raw
    monkeypatch.setattr(os, "pread", _deny)
    with pytest.raises(InstalledRuntimeProofError, match="REPEATED_BYTE_READ"):
        files.read(path, sha256=_hash(raw), maximum=1024)


@pytest.mark.parametrize("fault", ["hash", "size", "maximum"])
def test_initial_observation_expected_mismatch_never_rereads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    path = _member(tmp_path)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    observed = files.observe_protected_member_bytes(path, maximum=1024)
    monkeypatch.setattr(os, "pread", _deny)
    with pytest.raises(InstalledRuntimeProofError, match="DUPLICATE_REFERENCE_MISMATCH"):
        files.read(
            path,
            sha256=_hash(b"wrong") if fault == "hash" else observed.sha256,
            size=observed.size_bytes + 1 if fault == "size" else observed.size_bytes,
            maximum=observed.size_bytes - 1 if fault == "maximum" else 1024,
        )


def test_identity_only_epoch_can_upgrade_to_initial_actual_bytes(tmp_path: Path) -> None:
    path = _member(tmp_path)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    files.observe_protected_member_identity(path)
    observed = files.observe_protected_member_bytes(path, maximum=1024)
    assert observed.raw == b"bounded metadata"
    assert files.read(path, sha256=observed.sha256, maximum=1024) is observed.raw
    files.assert_unchanged()


@pytest.mark.parametrize("fault", ["rewrite", "replace", "missing", "mode", "ancestor"])
def test_identity_upgrade_rejects_drift_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    path = _member(tmp_path)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    files.observe_protected_member_identity(path)
    if fault == "rewrite":
        prior = path.stat()
        path.write_bytes(b"bounded metadata")
        os.utime(path, ns=(prior.st_atime_ns, prior.st_mtime_ns + 1_000_000_000))
    elif fault == "replace":
        _member(tmp_path, name="replacement").replace(path)
    elif fault == "missing":
        path.unlink()
    elif fault == "mode":
        path.chmod(0o640)
    else:
        tmp_path.chmod(0o750)
    monkeypatch.setattr(os, "pread", _deny)
    with pytest.raises(InstalledRuntimeProofError, match="CHANGED"):
        files.observe_protected_member_bytes(path, maximum=1024)


@pytest.mark.parametrize("fault", ["symlink", "ancestor_symlink", "hardlink", "writable", "setuid"])
def test_initial_observation_denies_unprotected_leaf_or_ancestor(
    tmp_path: Path, fault: str
) -> None:
    path = _member(tmp_path)
    if fault == "symlink":
        target = path.rename(tmp_path / "target")
        path.symlink_to(target)
    elif fault == "ancestor_symlink":
        directory = tmp_path / "directory"
        directory.mkdir(mode=0o700)
        path = _member(directory)
        alias = tmp_path / "alias"
        alias.symlink_to(directory, target_is_directory=True)
        path = alias / path.name
    elif fault == "hardlink":
        os.link(path, tmp_path / "alias")
    else:
        path.chmod(0o660 if fault == "writable" else 0o4600)
    with pytest.raises(InstalledRuntimeProofError):
        NumericalRuntimeFileSnapshots(os.geteuid()).observe_protected_member_bytes(
            path, maximum=1024
        )


def test_initial_observation_checks_fd_epoch_after_pread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _member(tmp_path)
    original = os.pread
    changed = False

    def mutate(descriptor: int, size: int, offset: int) -> bytes:
        nonlocal changed
        raw = original(descriptor, size, offset)
        if raw and not changed:
            changed = True
            path.chmod(0o640)
        return raw

    monkeypatch.setattr(os, "pread", mutate)
    with pytest.raises(InstalledRuntimeProofError, match="FILE_CHANGED"):
        NumericalRuntimeFileSnapshots(os.geteuid()).observe_protected_member_bytes(
            path, maximum=1024
        )


def test_initial_reuse_checks_held_fd_epoch_after_yield(tmp_path: Path) -> None:
    path = _member(tmp_path)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    observed = files.observe_protected_member_bytes(path, maximum=1024)
    with (
        pytest.raises(InstalledRuntimeProofError, match="FILE_CHANGED"),
        files.verified_open(path, sha256=observed.sha256, maximum=1024, retain_bytes=True),
    ):
        path.chmod(0o640)


@pytest.mark.parametrize(
    "filename",
    [
        "_libgcc_mutex-0.1-main.conda",
        "python-3.12.13-hc5f7cf0_3.conda",
        "xorg-libx11-1.8.12-h9b100fa_1.conda",
        "pip-26.1.2-pyhc872135_0.conda",
    ],
)
def test_conda_pin_accepts_real_fixed_source_filename_syntax(filename: str) -> None:
    assert conda.CondaRuntimeArchivePin(filename, _hash(b"archive"), 1).filename == filename


@pytest.mark.parametrize(
    "filename",
    ["../a.conda", "/a.conda", "a/b.conda", ".a.conda", "a.whl", "a.conda\n", "한.conda"],
)
def test_conda_pin_rejects_noncanonical_filename_syntax(filename: str) -> None:
    with pytest.raises(InstalledRuntimeProofError, match="CONDA_INVALID"):
        conda.CondaRuntimeArchivePin(filename, _hash(b"archive"), 1)


@pytest.mark.parametrize(
    "fault",
    [
        "conda_size_bool",
        "conda_sha_bool",
        "wheel_size_bool",
        "source_size_bool",
        "profile_bool",
        "archives_list",
        "overlays_list",
        "nested_wrong_type",
    ],
)
def test_public_audit_revalidates_forged_nested_values_before_io_or_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    plan = _plan()
    if fault == "conda_size_bool":
        object.__setattr__(plan.archives[0], "size_bytes", True)
    elif fault == "conda_sha_bool":
        object.__setattr__(plan.archives[0], "sha256", True)
    elif fault == "wheel_size_bool":
        object.__setattr__(plan.overlay_archives[0], "size_bytes", True)
    elif fault == "source_size_bool":
        object.__setattr__(plan, "source_list_size_bytes", True)
    elif fault == "profile_bool":
        object.__setattr__(plan, "profile", True)
    elif fault == "archives_list":
        object.__setattr__(plan, "archives", list(plan.archives))
    elif fault == "overlays_list":
        object.__setattr__(plan, "overlay_archives", list(plan.overlay_archives))
    else:
        object.__setattr__(plan, "archives", (object(), *plan.archives[1:]))
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    fence = _Fence()
    monkeypatch.setattr(os, "open", _deny)
    monkeypatch.setattr(NumericalRuntimeFileSnapshots, "read", _deny)
    with pytest.raises(InstalledRuntimeProofError, match="INVALID"):
        conda.audit_installed_conda31(
            plan, prefix=tmp_path, archive_root=tmp_path, files=files, tool_admission=fence
        )
    assert fence.calls == 0


@pytest.mark.parametrize(
    "tool", [None, object(), _Fence(True), _Fence(False), _Fence(0), _Fence("ok")]
)
def test_missing_tool_or_non_none_fence_result_cannot_start_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: object
) -> None:
    monkeypatch.setattr(os, "open", _deny)
    monkeypatch.setattr(NumericalRuntimeFileSnapshots, "read", _deny)
    monkeypatch.setattr(subprocess, "Popen", _deny)
    with pytest.raises(InstalledRuntimeProofError, match="CONDA_TOOL_UNAVAILABLE"):
        conda.audit_installed_conda31(
            _plan(),
            prefix=tmp_path,
            archive_root=tmp_path,
            files=NumericalRuntimeFileSnapshots(os.geteuid()),
            tool_admission=cast(conda.CondaArchiveToolAdmission, tool),
        )


def test_tool_fence_requires_the_owner_handle_none_return_only() -> None:
    fence = _Fence()
    conda._tool_fence(fence)
    assert fence.calls == 1


def test_legacy_assertion_only_handle_cannot_fall_back_to_named_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class AssertionOnly:
        def assert_current(self) -> None:
            return None

    monkeypatch.setattr(os, "open", _deny)
    monkeypatch.setattr(subprocess, "Popen", _deny)
    with pytest.raises(InstalledRuntimeProofError, match="CONDA_TOOL_UNAVAILABLE"):
        conda.audit_installed_conda31(
            _plan(),
            prefix=tmp_path,
            archive_root=tmp_path,
            files=NumericalRuntimeFileSnapshots(os.geteuid()),
            tool_admission=cast(conda.CondaArchiveToolAdmission, AssertionOnly()),
        )


def test_reader_delegates_one_spawn_to_required_fixed_tool_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    class FixedSyntheticTool:
        def assert_current(self) -> None:
            return None

        def open_zstd(self) -> subprocess.Popen[bytes]:
            child = actual(
                [sys.executable, "-I", "-S", "-B", "-c", "print('fixed synthetic decoder')"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            children.append(child)
            return child

    monkeypatch.setattr(subprocess, "Popen", _deny)
    reader = conda._ToolReader(io.BytesIO(b""), time.monotonic() + 2.0, tool=FixedSyntheticTool())
    try:
        chunks = []
        while raw := reader.read(65536):
            chunks.append(raw)
        assert b"".join(chunks) == b"fixed synthetic decoder\n"
    finally:
        reader.close(success=False)
    assert len(children) == 1 and children[0].poll() is not None


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"])
def test_text_relocation_matches_each_closed_encoding(encoding: str) -> None:
    old, prefix = "/canonical/build/placeholder", Path("/pfx")
    raw = (old + "/a:" + old + "/b\n").encode(encoding)
    assert conda._relocate(raw, old, "text", prefix) == ("/pfx/a:/pfx/b\n").encode(encoding)


def test_text_relocation_matches_mixed_closed_encodings_without_a_decoder() -> None:
    old, prefix = "/canonical/build/placeholder", Path("/pfx")
    encodings = ("utf-8", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be")
    raw = b"|".join(old.encode(encoding) for encoding in encodings)
    expected = b"|".join(str(prefix).encode(encoding) for encoding in encodings)
    assert conda._relocate(raw, old, "text", prefix) == expected


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"])
def test_binary_relocation_uses_encoded_nul_and_one_tail_pad_for_two_occurrences(
    encoding: str,
) -> None:
    old, prefix = "/canonical/build/placeholder", Path("/pfx")
    span = (old + "/a:" + old + "/b\0").encode(encoding)
    raw = b"before|" + span + b"after"
    transformed = span.replace(old.encode(encoding), str(prefix).encode(encoding))
    expected = b"before|" + transformed + bytes(len(span) - len(transformed)) + b"after"
    assert conda._relocate(raw, old, "binary", prefix) == expected
    assert len(expected) == len(raw)


@pytest.mark.parametrize("mode", ["text", "binary"])
def test_relocation_does_not_invent_a_change_when_placeholder_is_absent(mode: str) -> None:
    raw = b"unrelated\0data"
    assert conda._relocate(raw, "/canonical/build/placeholder", mode, Path("/pfx")) == raw


def test_binary_relocation_does_not_rewrite_an_unterminated_span() -> None:
    old = "/canonical/build/placeholder"
    raw = (old + "/unterminated").encode()
    assert conda._relocate(raw, old, "binary", Path("/pfx")) == raw


@pytest.mark.parametrize(
    "placeholder,mode,prefix",
    [
        ("/short", "binary", Path("/prefix/too/long")),
        ("/short", "text", Path("/prefix/too/long")),
        ("/canonical/placeholder", "text", Path("/space in prefix")),
        ("", "text", Path("/p")),
        ("/canonical/placeholder", "unknown", Path("/p")),
        (True, "text", Path("/p")),
    ],
)
def test_relocation_rejects_unmodeled_or_unsafe_recipe(
    placeholder: object, mode: str, prefix: Path
) -> None:
    with pytest.raises(InstalledRuntimeProofError, match="CONDA_INVALID"):
        conda._relocate(b"raw", cast(str, placeholder), mode, prefix)


class _TarReader:
    def __init__(self, raw: bytes) -> None:
        self.stream = io.BytesIO(raw)
        self.exact_sizes: list[int] = []

    def exact(self, size: int) -> bytes:
        self.exact_sizes.append(size)
        raw = self.stream.read(size)
        if len(raw) != size:
            raise AssertionError("hostile header requested unavailable payload")
        return raw

    def read(self, size: int) -> bytes:
        return self.stream.read(size)


def _header(size: int, kind: bytes = tarfile.REGTYPE, name: str = "member") -> bytes:
    member = tarfile.TarInfo(name)
    member.size = size
    member.type = kind
    return member.tobuf(format=tarfile.GNU_FORMAT)


def _pax_record(key: str, value: str) -> bytes:
    payload = f"{key}={value}\n".encode()
    length = len(payload) + 2
    while len(str(length)) + 1 + len(payload) != length:
        length = len(str(length)) + 1 + len(payload)
    return str(length).encode() + b" " + payload


@pytest.mark.parametrize(
    "size,kind",
    [
        (64 * 1024 + 1, tarfile.XHDTYPE),
        (2 * 1024**3 + 1, tarfile.REGTYPE),
        (-1, tarfile.REGTYPE),
        (0, tarfile.LNKTYPE),
        (0, tarfile.XGLTYPE),
        (0, tarfile.GNUTYPE_SPARSE),
        (0, tarfile.CHRTYPE),
        (1, tarfile.SYMTYPE),
    ],
)
def test_hostile_tar_header_size_or_type_is_rejected_before_payload_read(
    size: int, kind: bytes
) -> None:
    reader = _TarReader(_header(size, kind))
    with pytest.raises(InstalledRuntimeProofError, match="CONDA_TAR_INVALID"):
        next(conda._tar_members(cast(conda._ToolReader, reader), conda._Budget()))
    assert reader.exact_sizes == [512]


@pytest.mark.parametrize(
    "raw",
    [
        _pax_record("size", "999999999999999999"),
        _pax_record("GNU.sparse.size", "1"),
        _pax_record("path", "a") + _pax_record("path", "b"),
        b"999999 path=x\n",
        b"0 path=x\n",
    ],
)
def test_pax_rejects_size_overrides_sparse_keys_duplicates_and_false_lengths(raw: bytes) -> None:
    with pytest.raises(InstalledRuntimeProofError, match="CONDA_TAR_INVALID"):
        conda._pax(raw)


@pytest.mark.parametrize("name", ["/absolute", "../escape", "a/../../escape"])
def test_pax_path_override_cannot_escape_archive_root(name: str) -> None:
    pax = _pax_record("path", name)
    reader = _TarReader(
        _header(len(pax), tarfile.XHDTYPE) + pax + bytes((-len(pax)) % 512) + _header(0)
    )
    with pytest.raises(InstalledRuntimeProofError, match="CONDA_PATH_INVALID"):
        next(conda._tar_members(cast(conda._ToolReader, reader), conda._Budget()))


def test_bounded_pax_path_and_mtime_are_applied_without_loading_member_payload() -> None:
    pax = _pax_record("path", "bounded/member") + _pax_record("mtime", "1234.25")
    reader = _TarReader(
        _header(len(pax), tarfile.XHDTYPE)
        + pax
        + bytes((-len(pax)) % 512)
        + _header(3)
        + b"abc"
        + bytes(509)
        + bytes(1024)
    )
    members = conda._tar_members(cast(conda._ToolReader, reader), conda._Budget())
    member = next(members)
    assert (member.name, member.mtime, member.size) == ("bounded/member", 1234.25, 3)
    assert reader.exact_sizes == [512, len(pax), (-len(pax)) % 512, 512]
    assert reader.exact(member.size) == b"abc"
    assert list(members) == []


def _put(path: Path, raw: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


def _tar(entries: dict[str, tuple[bytes | str, int]]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, (content, mode) in entries.items():
            member = tarfile.TarInfo(name)
            member.mode, member.mtime = mode, 1700000000
            if isinstance(content, str):
                member.type, member.linkname = tarfile.SYMTYPE, content
                archive.addfile(member)
            else:
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
    return output.getvalue()


def _conda_zip(filename: str, info: bytes, payload: bytes, *, local64: bool = True) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("metadata.json", b'{"conda_pkg_format_version":2}')
        for kind, raw in (("info", info), ("pkg", payload)):
            entry = zipfile.ZipInfo(f"{kind}-{filename[:-6]}.tar.zst")
            if local64:
                with archive.open(entry, "w", force_zip64=True) as stream:
                    stream.write(raw)
            else:
                archive.writestr(entry, raw)
    return output.getvalue()


@dataclass(frozen=True)
class _SyntheticConda:
    plan: conda.CondaRuntimeAuditPlan
    prefix: Path
    archive_root: Path
    records: dict[str, Path]
    files: dict[str, Path]
    archive_paths: dict[str, Path]


def _fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str = "CPU_INDEX_FP32",
    *,
    duplicate_overlay_data: bool = False,
    corrupt_overlay_source_frame: bool = False,
) -> _SyntheticConda:
    from tests.unit.embedding_installed_runtime_fixtures import (
        synthetic_console_wrapper,
        synthetic_record,
        synthetic_wheel,
    )

    prefix, archive_root = tmp_path / "prefix", tmp_path / "archives"
    placeholder = "/canonical/build/" + "p" * 240
    current = b"# canonical source never executed\n"
    stale_name = "lib/python3.12/_sysconfigdata__linux_x86_64-linux-gnu.py"
    stale = ("PREFIX=" + placeholder + "\n").encode()

    def python_cache(raw: bytes) -> bytes:
        return (
            b"\xcb\x0d\x0d\x0a"
            + bytes(4)
            + struct.pack("<II", 1700000000, len(raw))
            + b"opaque canonical cache; never loaded"
        )

    ld = (placeholder + "/a:" + placeholder + "/b\0").encode()
    zlib = b"canonical target owned independently"
    empty_sha = _hash(b"").removeprefix("sha256:")
    entries: dict[str, dict[str, tuple[bytes | str, int]]] = {name: {} for name in conda._NAMES}
    entries["python"] = {
        "lib/python3.12/source.py": (current, 0o664),
        "lib/python3.12/__pycache__/source.cpython-312.pyc": (python_cache(current), 0o664),
        stale_name: (stale, 0o664),
        "lib/python3.12/__pycache__/_sysconfigdata__linux_x86_64-linux-gnu.cpython-312.pyc": (
            python_cache(stale),
            0o664,
        ),
        "compiler_compat/ld": ("../bin/x86_64-conda-linux-gnu-ld", 0o777),
        "lib/python3.1": ("python3.12", 0o777),
        "lib/python3.12/empty.py": (b"", 0o664),
    }
    entries["ld_impl_linux-64"] = {"bin/x86_64-conda-linux-gnu-ld": (ld, 0o775)}
    entries["libzlib"] = {"lib/libz.so.1.3.2": (zlib, 0o775)}
    entries["zlib"] = {"lib/libz.so": ("libz.so.1.3.2", 0o777)}
    entries["ncurses"] = {
        "lib/terminfo": ("../share/terminfo", 0o777),
        "share/terminfo/x/term": (b"bounded term data", 0o664),
    }
    for name, _version, _sha in conda._OVERLAYS:
        base = "site-packages/" if name == "pip" else "lib/python3.12/site-packages/"
        entries[name] = {
            base + name + "/__init__.py": (b"old overwritten package", 0o664),
            base + name + "/old.py": (b"obsolete source", 0o664),
        }
    entries["packaging"][
        "lib/python3.12/site-packages/packaging/__pycache__/old.cpython-312.pyc"
    ] = (python_cache(b"obsolete source"), 0o664)
    entries["pip"]["site-packages/pip-26.1.2.dist-info/INSTALLER"] = (b"conda\n", 0o664)
    entries["wheel"].update(
        {
            "bin/wheel": (b"old overwritten wheel script", 0o775),
            "share/eom-wheel-marker.txt": (b"old overwritten wheel data", 0o664),
            "bin/obsolete-wheel": (b"obsolete wheel script", 0o775),
            "share/obsolete-wheel.txt": (b"obsolete wheel data", 0o664),
        }
    )
    license_raw = b"bounded original licensing metadata"
    monkeypatch.setattr(
        conda, "_LICENSES", (("zlib", "LICENSE", len(license_raw), _hash(license_raw)[7:]),)
    )
    monkeypatch.setattr(
        conda,
        "_CROSS_LINKS",
        (
            (
                "python",
                "compiler_compat/ld",
                "ld_impl_linux-64",
                "bin/x86_64-conda-linux-gnu-ld",
                "f" * 64,
                len(ld),
            ),
            ("zlib", "lib/libz.so", "libzlib", "lib/libz.so.1.3.2", "e" * 64, len(zlib)),
        ),
    )
    monkeypatch.setattr(conda, "_TRANSFORMATION_COUNTS", (1, 1))
    monkeypatch.setattr(conda, "_CACHE_COUNTS", (3, 2, 2))
    monkeypatch.setattr(conda, "_STALE_SOURCES", frozenset({stale_name}))
    rows: list[str] = []
    archive_pins: list[conda.CondaRuntimeArchivePin] = []
    records: dict[str, Path] = {}
    paths: dict[str, Path] = {}
    archive_paths: dict[str, Path] = {}
    for name in sorted(conda._NAMES):
        version, build = "1.0", "build_0"
        filename = f"{name}-{version}-{build}.conda"
        subdir = "noarch" if name in {"pip", "tzdata"} else "linux-64"
        url = f"https://repo.anaconda.com/pkgs/main/{subdir}/{filename}"
        index = {"name": name, "version": version, "build": build, "build_number": 0, "depends": []}
        declared: list[dict[str, Any]] = []
        installed_rows: list[dict[str, Any]] = []
        for path, (content, mode) in entries[name].items():
            target = conda._mapped(path, "python" if name == "pip" else None)
            source_sha, source_size = (
                (_hash(content)[7:], len(content)) if isinstance(content, bytes) else (empty_sha, 0)
            )
            if path == "compiler_compat/ld":
                source_sha, source_size = "f" * 64, len(ld)
            if path == "lib/libz.so":
                source_sha, source_size = "e" * 64, len(zlib)
            row: dict[str, Any] = {
                "_path": path,
                "path_type": "hardlink" if isinstance(content, bytes) else "softlink",
                "sha256": source_sha,
                "size_in_bytes": source_size,
            }
            transformed = path in {stale_name, "bin/x86_64-conda-linux-gnu-ld"}
            if transformed:
                row |= {
                    "prefix_placeholder": placeholder,
                    "file_mode": "text" if path == stale_name else "binary",
                }
            declared.append(row)
            installed_rows.append(row | {"_path": target})
            if name in {name for name, _version, _sha in conda._OVERLAYS}:
                continue
            actual = prefix / target
            paths[target] = actual
            actual.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, str):
                actual.symlink_to(content)
            else:
                raw = (
                    conda._relocate(content, placeholder, row["file_mode"], prefix)
                    if transformed
                    else content
                )
                _put(actual, raw, mode & ~0o022)
                os.utime(
                    actual,
                    ns=(
                        1700000000000000000,
                        1700000001250000000 if path == stale_name else 1700000000250000000,
                    ),
                )
        if name == "pip":
            for row in list(installed_rows):
                if row["_path"].endswith(".py"):
                    p = PurePosixPath(row["_path"])
                    installed_rows.append(
                        {
                            "_path": str(p.parent / "__pycache__" / (p.stem + ".cpython-312.pyc")),
                            "path_type": "hardlink",
                        }
                    )
            installed_rows.extend(
                {"_path": "bin/" + script, "path_type": "unix_python_entry_point"}
                for script in ("pip", "pip3")
            )
        info_members: dict[str, tuple[bytes | str, int]] = {
            "info/index.json": (json.dumps(index).encode(), 0o664),
            "info/paths.json": (
                json.dumps({"paths_version": 1, "paths": declared}).encode(),
                0o664,
            ),
        }
        if name in {"pip", "tzdata"}:
            noarch: dict[str, Any] = {"type": "python" if name == "pip" else "generic"}
            if name == "pip":
                noarch["entry_points"] = [
                    "pip = pip._internal.cli.main:main",
                    "pip3 = pip._internal.cli.main:main",
                ]
            info_members["info/link.json"] = (
                json.dumps({"package_metadata_version": 1, "noarch": noarch}).encode(),
                0o664,
            )
        payload = dict(entries[name])
        if name == "wheel" and corrupt_overlay_source_frame:
            old_script, mode = payload["bin/wheel"]
            assert isinstance(old_script, bytes)
            payload["bin/wheel"] = (b"X" + old_script[1:], mode)
        if name == "zlib":
            payload["info/licenses/LICENSE"] = (license_raw, 0o664)
        archive_raw = _conda_zip(filename, _tar(info_members), _tar(payload))
        pin = conda.CondaRuntimeArchivePin(filename, _hash(archive_raw), len(archive_raw))
        archive_pins.append(pin)
        archive_path = archive_root / pin.sha256[7:] / filename
        archive_paths[name] = archive_path
        _put(archive_path, archive_raw)
        record = index | {
            "fn": filename,
            "url": url,
            "sha256": pin.sha256[7:],
            "size": len(archive_raw),
            "paths_data": {"paths_version": 1, "paths": installed_rows},
            "files": [row["_path"] for row in installed_rows],
        }
        record_path = prefix / "conda-meta" / f"{name}-{version}-{build}.json"
        records[name] = record_path
        _put(record_path, json.dumps(record).encode())
        rows.append(f"{pin.sha256[7:]}  {filename}  {url}")
    overlay_pins: list[RuntimeWheelArchivePin] = []
    overlays = []
    for name, version, _sha in conda._OVERLAYS:
        dist = f"{name}-{version}.dist-info"
        members = {
            name + "/__init__.py": b"# accepted overlay never imported\n",
            dist
            + "/METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n".encode(),
            dist + "/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n",
        }
        data_name = f"{name}-{version}.data/data/share/eom-wheel-marker.txt"
        if name == "wheel" or (name == "packaging" and duplicate_overlay_data):
            members[data_name] = b"# accepted overlay data never executed\n"
        scripts = ("pip", "pip3") if name == "pip" else (("wheel",) if name == "wheel" else ())
        if scripts:
            members[dist + "/entry_points.txt"] = (
                "[console_scripts]\n" + "".join(f"{script}={name}.cli:main\n" for script in scripts)
            ).encode()
        record_name = dist + "/RECORD"
        raw = synthetic_wheel(members | {record_name: synthetic_record(members, record_name)})
        overlay_pin = RuntimeWheelArchivePin(
            f"{name}-{version}-py3-none-any.whl", _hash(raw), len(raw)
        )
        _put(archive_root / overlay_pin.sha256[7:] / overlay_pin.wheel_filename, raw)
        overlay_pins.append(overlay_pin)
        overlays.append((name, version, overlay_pin.sha256[7:]))
        installed = members | {dist + "/INSTALLER": b"pip\n", dist + "/REQUESTED": b""}
        if data_name in installed:
            installed["../../../share/eom-wheel-marker.txt"] = installed.pop(data_name)
        for script in scripts:
            installed["../../../bin/" + script] = synthetic_console_wrapper(
                prefix, (name + ".cli", "main"), "removesuffix"
            )
        installed[record_name] = synthetic_record(installed, record_name)
        for path, content in installed.items():
            _put(Path(os.path.normpath(prefix / "lib/python3.12/site-packages" / path)), content)
    monkeypatch.setattr(conda, "_OVERLAYS", tuple(overlays))
    source = ("\n".join(rows) + "\n").encode()
    monkeypatch.setattr(conda, "_SOURCE_SHA", _hash(source))
    _put(archive_root / _hash(source)[7:] / "sources.lock", source)
    tool = tmp_path / "admitted-zstd-synthetic"
    _put(tool, b"synthetic tool identity; never executed", 0o755)
    monkeypatch.setattr(conda, "_ZSTD_PATH", tool)
    monkeypatch.setattr(conda, "_ZSTD_SHA", _hash(tool.read_bytes()))
    monkeypatch.setattr(conda, "_ZSTD_SIZE", tool.stat().st_size)
    actual_popen = subprocess.Popen

    def child(command: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
        assert command == [str(tool), "-q", "-d", "-c"]
        assert kwargs["env"] == {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}
        return actual_popen(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                "-c",
                "import sys\nwhile b := sys.stdin.buffer.read(65536):\n"
                " sys.stdout.buffer.write(b)\n sys.stdout.buffer.flush()\n",
            ],
            **kwargs,
        )

    monkeypatch.setattr(subprocess, "Popen", child)
    for directory in (tmp_path, *tmp_path.rglob("*")):
        if directory.is_dir() and not directory.is_symlink():
            directory.chmod(0o700)
    plan = conda.CondaRuntimeAuditPlan(
        profile, _hash(source), len(source), tuple(archive_pins), tuple(overlay_pins)
    )
    return _SyntheticConda(plan, prefix, archive_root, records, paths, archive_paths)


def _audit(fixture: _SyntheticConda, fence: _Fence | None = None) -> conda.CondaRuntimeByteAudit:
    return conda.audit_installed_conda31(
        fixture.plan,
        prefix=fixture.prefix,
        archive_root=fixture.archive_root,
        files=NumericalRuntimeFileSnapshots(os.geteuid()),
        tool_admission=fence or _Fence(),
    )


@pytest.mark.parametrize("profile", ["CPU_INDEX_FP32", "CUDA_INDEX_FP32"])
def test_public_audit_owns_verified_scripts_data_and_site_metadata_without_namespace_mixing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch, profile)
    first, second = _audit(fixture), _audit(fixture)
    assert first == second
    wheel = next(owner for owner in first.overlay_wheels if owner.name == "wheel")
    site = fixture.prefix / "lib/python3.12/site-packages"
    script, data = fixture.prefix / "bin/wheel", fixture.prefix / "share/eom-wheel-marker.txt"
    installer = site / f"wheel-{wheel.version}.dist-info/INSTALLER"
    assert {script, data, installer} <= wheel.all_installed_members <= first.installed_members
    assert data in wheel.archive_payload_members and script not in wheel.archive_payload_members
    assert installer in wheel.installed_members
    assert {script, data}.isdisjoint(wheel.installed_members)
    assert all(
        path.is_relative_to(site) for path in wheel.installed_members | wheel.namespace_roots
    )
    record = json.loads(fixture.records["wheel"].read_bytes())
    assert {"bin/wheel", "share/eom-wheel-marker.txt"} <= set(record["files"])
    for target in (script, data):
        source = next(
            row
            for row in record["paths_data"]["paths"]
            if row["_path"] == str(target.relative_to(fixture.prefix))
        )
        assert _hash(target.read_bytes())[7:] != source["sha256"]
    assert not (fixture.prefix / "bin/obsolete-wheel").exists()
    assert not (fixture.prefix / "share/obsolete-wheel.txt").exists()
    assert first.ledger_sha256 == second.ledger_sha256


def test_public_audit_rejects_two_verified_owners_of_the_same_outside_site_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch, duplicate_overlay_data=True)
    with pytest.raises(InstalledRuntimeProofError, match="CONDA_OWNERSHIP_CONFLICT"):
        _audit(fixture)


@pytest.mark.parametrize("member", ["bin/wheel", "share/eom-wheel-marker.txt"])
@pytest.mark.parametrize("fault", ["hash", "size", "symlink", "hardlink", "writable"])
def test_full_overlay_ownership_does_not_waive_actual_installed_bytes_or_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member: str, fault: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    target = fixture.prefix / member
    raw = target.read_bytes()
    if fault == "hash":
        target.write_bytes(b"X" + raw[1:])
    elif fault == "size":
        target.write_bytes(raw + b"X")
    elif fault == "symlink":
        target.rename(target.with_name(target.name + "-alias"))
        target.symlink_to(target.name + "-alias")
    elif fault == "hardlink":
        os.link(target, target.with_name(target.name + "-alias"))
    else:
        target.chmod(0o666)
    with pytest.raises(InstalledRuntimeProofError):
        _audit(fixture)


@pytest.mark.parametrize("fault", ["archive_hash", "source_frame", "source_metadata"])
def test_verified_overlay_replacements_do_not_waive_original_source_archive_and_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch, corrupt_overlay_source_frame=fault == "source_frame")
    if fault == "archive_hash":
        target = fixture.archive_paths["wheel"]
        raw = target.read_bytes()
        target.write_bytes(b"X" + raw[1:])
    elif fault == "source_metadata":
        target = fixture.records["wheel"]
        record = json.loads(target.read_bytes())
        next(row for row in record["paths_data"]["paths"] if row["_path"] == "bin/wheel")[
            "sha256"
        ] = "f" * 64
        target.write_bytes(json.dumps(record).encode())
    code = {
        "archive_hash": "FILE_HASH_MISMATCH",
        "source_frame": "CONDA_MEMBER_HASH_MISMATCH",
        "source_metadata": "CONDA_METADATA_INVALID",
    }[fault]
    with pytest.raises(InstalledRuntimeProofError, match=code):
        _audit(fixture)


@pytest.mark.parametrize("member", ["bin/obsolete-wheel", "share/obsolete-wheel.txt"])
def test_full_overlay_ownership_still_denies_unclaimed_original_survivors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    _put(fixture.prefix / member, b"unclaimed original source still present")
    with pytest.raises(InstalledRuntimeProofError, match="CONDA_OVERLAY_SURVIVOR"):
        _audit(fixture)


@pytest.mark.parametrize("member", ["bin/wheel", "share/eom-wheel-marker.txt"])
def test_full_overlay_members_remain_epoch_fenced_after_genuine_wheel_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    verify = verify_installed_runtime_wheel

    def verified_then_changed(
        library: RuntimeWheelInstallationPin,
        *,
        prefix: Path,
        archive_root: Path,
        files: NumericalRuntimeFileSnapshots,
    ) -> VerifiedRuntimeWheelMembers:
        observed = verify(library, prefix=prefix, archive_root=archive_root, files=files)
        if observed.name == "wheel":
            (fixture.prefix / member).chmod(0o640)
        return observed

    monkeypatch.setattr(conda, "verify_installed_runtime_wheel", verified_then_changed)
    with pytest.raises(InstalledRuntimeProofError, match="CHANGED"):
        _audit(fixture)


@pytest.mark.parametrize("profile", ["CPU_INDEX_FP32", "CUDA_INDEX_FP32"])
def test_complete_synthetic_archive_transform_overlay_cache_and_link_ledger_is_replayable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch, profile)
    fence = _Fence()
    first = _audit(fixture, fence)
    second = _audit(fixture)
    assert first == second
    assert (
        first.binary_relocations,
        first.text_relocations,
        first.archived_caches,
        first.retained_caches,
        first.absent_generated_caches,
        first.licensing_members,
    ) == (1, 1, 3, 2, 2, 1)
    assert first.link_members == 4 and fence.calls >= 125
    assert len(first.overlay_wheels) == 4
    assert len(first.installed_links) == 4
    assert set(first.installed_links) == {
        (path, os.readlink(path)) for path in first.installed_members if path.is_symlink()
    }
    assert all(path.exists() or path.is_symlink() for path in first.installed_members)


def _pip_source_metadata(fixture: _SyntheticConda) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(fixture.records["pip"].read_bytes())
    for row in body["paths_data"]["paths"]:
        if "sha256" in row and row["_path"].startswith("lib/python3.12/site-packages/"):
            row["_path"] = row["_path"].removeprefix("lib/python3.12/")
    return body


@pytest.mark.parametrize("representation", ("raw", "mapped", "raw_prefetch"))
@pytest.mark.parametrize("profile", ("CPU_INDEX_FP32", "CUDA_INDEX_FP32"))
def test_public_audit_retains_pip_raw_source_and_installed_files_as_distinct_representations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, representation: str, profile: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch, profile)
    original = _audit(fixture)
    if representation == "raw_prefetch":
        _set_installation_uris(fixture, "prefetch")
    path = fixture.records["pip"]
    body = (
        _pip_source_metadata(fixture)
        if representation != "mapped"
        else json.loads(path.read_bytes())
    )
    path.write_bytes(json.dumps(body).encode())
    assert _audit(fixture) == original
    assert path.stat().st_uid == os.geteuid()
    installer = "site-packages/pip-26.1.2.dist-info/INSTALLER"
    metadata_paths = {row["_path"] for row in body["paths_data"]["paths"]}
    assert (
        installer if representation != "mapped" else "lib/python3.12/" + installer
    ) in metadata_paths
    assert "lib/python3.12/" + installer in body["files"]
    assert any(
        name.startswith("lib/python3.12/site-packages/pip/__pycache__/") for name in metadata_paths
    )
    if representation == "raw_prefetch":
        assert body["url"] == (
            "file:///tmp/eom-embedding-conda-base-prefetch.KoqIDSXB/" + body["fn"]
        )


@pytest.mark.parametrize(
    "fault",
    (
        "duplicate_raw",
        "mapped_alias",
        "unknown_raw_cache",
        "unknown_raw_script",
        "unknown_raw_member",
        "other_owner",
        "nonpip",
        "traversal",
        "raw_files",
        "missing_files",
        "duplicate_files",
        "source_hash",
        "source_size",
        "source_size_bool",
        "path_type",
        "archive_bytes",
        "member_bytes",
    ),
)
def test_public_audit_pip_mapping_cannot_hide_alias_unknown_raw_or_identity_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    path = fixture.records["pip"]
    body = _pip_source_metadata(fixture)
    rows = body["paths_data"]["paths"]
    source = next(row for row in rows if row["_path"] == "site-packages/pip/__init__.py")
    if fault == "duplicate_raw":
        rows.append(dict(source))
    elif fault == "mapped_alias":
        rows.append(source | {"_path": "lib/python3.12/" + source["_path"]})
    elif fault == "unknown_raw_cache":
        cache = next(row for row in rows if row["_path"].endswith(".pyc"))
        cache["_path"] = cache["_path"].removeprefix("lib/python3.12/")
    elif fault == "unknown_raw_script":
        script = next(row for row in rows if row["_path"] == "bin/pip")
        script["_path"] = "python-scripts/pip"
    elif fault == "unknown_raw_member":
        source["_path"] = "site-packages/pip/unknown.py"
    elif fault == "other_owner":
        source["_path"] = "site-packages/packaging/old.py"
    elif fault == "nonpip":
        fixture.records["pip"].write_bytes(json.dumps(body).encode())
        path = fixture.records["packaging"]
        body = json.loads(path.read_bytes())
        body["paths_data"]["paths"][0]["_path"] = "site-packages/packaging/__init__.py"
    elif fault == "traversal":
        source["_path"] = "site-packages/pip/../pip/__init__.py"
    elif fault == "raw_files":
        body["files"] = [row["_path"] for row in rows]
    elif fault == "missing_files":
        body["files"].pop()
    elif fault == "duplicate_files":
        body["files"][1] = body["files"][0]
    elif fault == "source_hash":
        source["sha256"] = "f" * 64
    elif fault == "source_size":
        source["size_in_bytes"] += 1
    elif fault == "source_size_bool":
        source["size_in_bytes"] = True
    elif fault == "path_type":
        source["path_type"] = "softlink"
    elif fault == "archive_bytes":
        archive = fixture.archive_paths["pip"]
        archive_raw = bytearray(archive.read_bytes())
        archive_raw[0] ^= 1
        archive.write_bytes(archive_raw)
    else:
        member = fixture.files["lib/python3.12/source.py"]
        member_raw = member.read_bytes()
        member.write_bytes(b"!" + member_raw[1:])
    path.write_bytes(json.dumps(body).encode())
    code = (
        "FILE_HASH_MISMATCH"
        if fault in {"archive_bytes", "member_bytes"}
        else "CONDA_PATH_INVALID"
        if fault == "traversal"
        else "CONDA_METADATA_INVALID"
    )
    with pytest.raises(InstalledRuntimeProofError, match=code):
        _audit(fixture)


def _set_installation_uris(fixture: _SyntheticConda, representation: str) -> None:
    for name, path in fixture.records.items():
        record = json.loads(path.read_bytes())
        if representation == "canonical":
            record["url"] = fixture.archive_paths[name].as_uri()
        elif representation == "prefetch":
            record["url"] = "file:///tmp/eom-embedding-conda-base-prefetch.KoqIDSXB/" + record["fn"]
        path.write_bytes(json.dumps(record).encode())


@pytest.mark.parametrize("representation", ("upstream", "canonical", "prefetch"))
def test_public_conda_audit_accepts_only_reviewed_location_forms_with_same_byte_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, representation: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    original = _audit(fixture)
    _set_installation_uris(fixture, representation)
    assert _audit(fixture) == original
    assert all(path.stat().st_uid == os.geteuid() for path in fixture.records.values())


@pytest.mark.parametrize(
    "fault",
    (
        "foreign_file",
        "foreign_https",
        "foreign_canonical_hash",
        "wrong_filename",
        "short_suffix",
        "long_suffix",
        "unicode_suffix",
        "uppercase_scheme",
        "host",
        "userinfo",
        "traversal",
        "dot",
        "double_slash",
        "encoded_prefix",
        "encoded_filename",
        "encoded_separator",
        "query",
        "fragment",
        "newline",
        "oversized",
        "null",
        "boolean",
    ),
)
def test_public_conda_audit_rejects_unreviewed_url_without_normalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    path = fixture.records["_libgcc_mutex"]
    record = json.loads(path.read_bytes())
    filename = record["fn"]
    cache = "file:///tmp/eom-embedding-conda-base-prefetch.KoqIDSXB/"
    values: dict[str, object] = {
        "foreign_file": "file:///tmp/unreviewed/" + filename,
        "foreign_https": "https://example.invalid/" + filename,
        "foreign_canonical_hash": (fixture.archive_root / ("f" * 64) / filename).as_uri(),
        "wrong_filename": cache + "unregistered-1.0-build_0.conda",
        "short_suffix": cache.replace("KoqIDSXB", "Ab0Cd1E") + filename,
        "long_suffix": cache.replace("KoqIDSXB", "Ab0Cd1Ef2") + filename,
        "unicode_suffix": cache.replace("KoqIDSXB", "KoqIDSX한") + filename,
        "uppercase_scheme": "FILE" + cache[4:] + filename,
        "host": cache.replace("file:///", "file://localhost/") + filename,
        "userinfo": cache.replace("file:///", "file://synthetic@example.invalid/") + filename,
        "traversal": cache + "../" + filename,
        "dot": cache + "./" + filename,
        "double_slash": cache + "/" + filename,
        "encoded_prefix": cache.replace("eom-", "%65om-") + filename,
        "encoded_filename": cache + "%5f" + filename[1:],
        "encoded_separator": cache.rstrip("/") + "%2f" + filename,
        "query": cache + filename + "?synthetic=1",
        "fragment": cache + filename + "#synthetic",
        "newline": cache + filename + "\n",
        "oversized": cache + "x" * 513,
        "null": None,
        "boolean": True,
    }
    record["url"] = values[fault]
    path.write_bytes(json.dumps(record).encode())
    with pytest.raises(InstalledRuntimeProofError, match="CONDA_METADATA_INVALID"):
        _audit(fixture)


@pytest.mark.parametrize("representation", ("canonical", "prefetch"))
@pytest.mark.parametrize(
    "fault", ("name", "version", "build", "fn", "sha256", "size", "archive", "member")
)
def test_eligible_installation_uri_cannot_replace_identity_or_actual_byte_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, representation: str, fault: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    _set_installation_uris(fixture, representation)
    if fault == "archive":
        path = fixture.archive_paths["python"]
        raw = bytearray(path.read_bytes())
        raw[0] ^= 1
        path.write_bytes(raw)
    elif fault == "member":
        path = fixture.files["lib/python3.12/source.py"]
        member_raw = path.read_bytes()
        path.write_bytes(b"!" + member_raw[1:])
    else:
        path = fixture.records["python"]
        record = json.loads(path.read_bytes())
        if fault == "sha256":
            record[fault] = "f" * 64
        elif fault == "size":
            record[fault] += 1
        else:
            record[fault] = "wrong"
        path.write_bytes(json.dumps(record).encode())
    code = "FILE_HASH_MISMATCH" if fault in {"archive", "member"} else "CONDA_METADATA_INVALID"
    with pytest.raises(InstalledRuntimeProofError, match=code):
        _audit(fixture)


@pytest.mark.parametrize("value", (None, True, False, 1, b"uri", [], {}, "x" * 513))
def test_uri_raw_type_and_bound_reject_before_path_conversion(
    monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    monkeypatch.setattr(Path, "as_uri", _deny)
    assert not conda._installed_archive_uri_matches(
        value,
        "https://example.invalid/source.conda",
        Path("/canonical/source.conda"),
        "source.conda",
    )


def test_uri_predicate_has_no_io_decode_or_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filename = "python-3.12.13-hc5f7cf0_3.conda"
    source_uri = "https://repo.anaconda.com/pkgs/main/linux-64/" + filename
    archive = Path("/opt/eom/embedding-runtime-archives") / ("a" * 64) / filename
    accepted = (
        source_uri,
        archive.as_uri(),
        "file:///tmp/eom-embedding-conda-base-prefetch.Ab0Cd1Ef/" + filename,
    )
    monkeypatch.setattr(os, "open", _deny)
    monkeypatch.setattr(Path, "resolve", _deny)
    for value in accepted:
        assert conda._installed_archive_uri_matches(value, source_uri, archive, filename)


@pytest.mark.parametrize(
    "fault",
    [
        "source_bytes",
        "current_cache_mtime",
        "stale_cache_bytes",
        "overlay_bytes",
        "obsolete_survivor",
        "generated_cache",
        "alias_route",
        "directory_alias",
        "license_materialized",
        "missing_archive",
        "unknown_cache",
        "unknown_overlay_member",
    ],
)
def test_whole_synthetic_audit_denies_source_drift_and_ownership_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    if fault == "source_bytes":
        fixture.files["lib/python3.12/source.py"].write_bytes(b"wrong")
    elif fault == "current_cache_mtime":
        os.utime(fixture.files["lib/python3.12/source.py"], (1700000001, 1700000001))
    elif fault == "stale_cache_bytes":
        fixture.files[
            "lib/python3.12/__pycache__/_sysconfigdata__linux_x86_64-linux-gnu.cpython-312.pyc"
        ].write_bytes(b"wrong")
    elif fault == "overlay_bytes":
        (fixture.prefix / "lib/python3.12/site-packages/pip/__init__.py").write_bytes(b"wrong")
    elif fault == "obsolete_survivor":
        _put(fixture.prefix / "lib/python3.12/site-packages/pip/old.py", b"obsolete source")
    elif fault == "generated_cache":
        _put(
            fixture.prefix / "lib/python3.12/site-packages/pip/__pycache__/old.cpython-312.pyc",
            b"unregistered cache",
        )
    elif fault == "alias_route":
        path = fixture.files["compiler_compat/ld"]
        path.unlink()
        path.symlink_to("../../outside")
    elif fault == "directory_alias":
        path = fixture.files["lib/python3.1"]
        path.unlink()
        path.symlink_to("../conda-meta")
    elif fault == "license_materialized":
        _put(fixture.prefix / "info/licenses/LICENSE", b"bounded original licensing metadata")
    elif fault == "unknown_cache":
        _put(
            fixture.prefix / "lib/python3.12/__pycache__/source.cpython-312.opt-1.pyc",
            b"unknown cache",
        )
    elif fault == "unknown_overlay_member":
        _put(fixture.prefix / "lib/python3.12/site-packages/pip/unknown.py", b"unknown member")
    else:
        fixture.archive_paths["zlib"].unlink()
    with pytest.raises(InstalledRuntimeProofError):
        _audit(fixture)


@pytest.mark.parametrize(
    "field,value",
    [
        ("build_number", False),
        ("build_number", 0.0),
        ("paths_version", True),
        ("paths_version", 1.0),
        ("size", True),
        ("size_in_bytes", False),
        ("size_in_bytes", 0.0),
        ("sha256", "f" * 64),
    ],
)
def test_installed_metadata_cannot_self_attest_or_substitute_bool_float(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    path = fixture.records["python"]
    body = json.loads(path.read_bytes())
    if field == "paths_version":
        body["paths_data"][field] = value
    elif field == "size_in_bytes":
        next(row for row in body["paths_data"]["paths"] if row["_path"].endswith("empty.py"))[
            field
        ] = value
    else:
        body[field] = value
    path.write_bytes(json.dumps(body).encode())
    with pytest.raises(InstalledRuntimeProofError, match="METADATA_INVALID"):
        _audit(fixture)


@pytest.mark.parametrize("local64", [False, True])
def test_only_closed_local_zip_sizes_are_accepted(tmp_path: Path, local64: bool) -> None:
    filename = "python-3.12.13-hc5f7cf0_3.conda"
    raw = _conda_zip(filename, _tar({}), _tar({}), local64=local64)
    pin = conda.CondaRuntimeArchivePin(filename, _hash(raw), len(raw))
    path = _member(tmp_path, raw)
    with path.open("rb") as stream:
        archive = conda._zip(stream.fileno(), pin)
        try:
            assert len(archive.infolist()) == 3
        finally:
            assert archive.fp is not None
            archive.fp.close()
            archive.close()


@pytest.mark.parametrize(
    "fault",
    [
        "version",
        "extra_tag",
        "extra_size",
        "local_size",
        "name",
        "crc",
        "descriptor",
        "central_extra",
        "entries",
        "overlap",
    ],
)
def test_malformed_local_and_general_zip64_are_denied(tmp_path: Path, fault: str) -> None:
    filename = "python-3.12.13-hc5f7cf0_3.conda"
    raw = bytearray(_conda_zip(filename, _tar({}), _tar({})))
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entry = archive.infolist()[1]
    offset = entry.header_offset
    name_length = struct.unpack_from("<H", raw, offset + 26)[0]
    extra = offset + 30 + name_length
    if fault == "version":
        struct.pack_into("<H", raw, offset + 4, 46)
    elif fault == "extra_tag":
        struct.pack_into("<H", raw, extra, 2)
    elif fault == "extra_size":
        struct.pack_into("<Q", raw, extra + 4, entry.file_size + 1)
    elif fault == "local_size":
        struct.pack_into("<L", raw, offset + 18, entry.file_size)
    elif fault == "name":
        raw[offset + 30] = ord("x")
    elif fault == "crc":
        struct.pack_into("<L", raw, offset + 14, entry.CRC ^ 1)
    elif fault == "descriptor":
        struct.pack_into("<H", raw, offset + 6, 8)
    elif fault == "entries":
        struct.pack_into("<2H", raw, len(raw) - 22 + 8, 20000, 20000)
    else:
        central = struct.unpack_from("<L", raw, len(raw) - 22 + 16)[0]
        if fault == "central_extra":
            struct.pack_into("<H", raw, central + 30, 20)
        else:
            struct.pack_into("<L", raw, central + 42, offset)
    pin = conda.CondaRuntimeArchivePin(filename, _hash(bytes(raw)), len(raw))
    path = _member(tmp_path, bytes(raw))
    with path.open("rb") as stream, pytest.raises(InstalledRuntimeProofError):
        conda._zip(stream.fileno(), pin)


@pytest.mark.parametrize("fault", ["name", "package", "hash", "executable", "materialized"])
def test_licensing_ledger_is_closed_and_never_an_installed_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    raw = b"original bounded license"
    monkeypatch.setattr(conda, "_LICENSES", (("zlib", "LICENSE", len(raw), _hash(raw)[7:]),))
    name, package, content, mode = "info/licenses/LICENSE", "zlib", raw, 0o664
    if fault == "name":
        name = "info/execute.py"
    elif fault == "package":
        package = "python"
    elif fault == "hash":
        content = b"X" + raw[1:]
    elif fault == "executable":
        mode = 0o775
    else:
        _put(tmp_path / name, raw)
    metadata = {"info/paths.json": {"paths_version": 1, "paths": []}, "info/index.json": {}}
    reader = _TarReader(_tar({name: (content, mode)}))
    with pytest.raises(InstalledRuntimeProofError):
        conda._payload(
            cast(conda._ToolReader, reader), conda._Budget(), metadata, package, tmp_path, {}
        )


@pytest.mark.parametrize(
    "fault", ["constructor", "register_first", "register_second", "set_blocking"]
)
def test_tool_constructor_failure_always_reaps_child_and_closes_pipes(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    actual = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    class FailingSelector(selectors.EpollSelector):
        def register(self, fileobj: Any, events: int, data: Any = None) -> selectors.SelectorKey:
            if (fault == "register_first" and not self.get_map()) or (
                fault == "register_second" and self.get_map()
            ):
                raise OSError("synthetic selector failure")
            return super().register(fileobj, events, data)

    def child(_command: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
        result = actual(
            [sys.executable, "-I", "-S", "-B", "-c", "import time; time.sleep(30)"], **kwargs
        )
        children.append(result)
        return result

    monkeypatch.setattr(subprocess, "Popen", child)
    if fault == "constructor":
        monkeypatch.setattr(selectors, "DefaultSelector", _deny)
    else:
        monkeypatch.setattr(selectors, "DefaultSelector", FailingSelector)
    if fault == "set_blocking":

        def unavailable(_fd: int, _mode: bool) -> NoReturn:
            raise OSError("synthetic blocking failure")

        monkeypatch.setattr(os, "set_blocking", unavailable)
    with pytest.raises((OSError, AssertionError)):
        conda._ToolReader(io.BytesIO(b"x"), time.monotonic() + 10, tool=_Fence())
    assert not children if fault == "constructor" else len(children) == 1
    for process in children:
        assert process.poll() is not None
        assert process.stdin is not None and process.stdin.closed
        assert process.stdout is not None and process.stdout.closed


@pytest.mark.parametrize("phase", ["select", "read", "return"])
def test_tool_absolute_deadline_is_checked_after_select_io_and_before_return(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    actual = subprocess.Popen

    def child(_command: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
        return actual(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                "-c",
                "import sys; sys.stdout.buffer.write(b'x'); sys.stdout.buffer.flush()",
            ],
            **kwargs,
        )

    monkeypatch.setattr(subprocess, "Popen", child)
    reader = conda._ToolReader(io.BytesIO(b""), time.monotonic() + 10, tool=_Fence())
    clock = [0.0]
    reader.deadline = 1.0
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    if phase == "return":
        reader.buffer.extend(b"x")
        times = iter((0.0, 2.0))
        monkeypatch.setattr(time, "monotonic", lambda: next(times))
    elif phase == "select":
        select = reader.selector.select

        def late_select(timeout: float | None = None) -> list[tuple[selectors.SelectorKey, int]]:
            events = select(timeout)
            clock[0] = 2.0
            return events

        monkeypatch.setattr(reader.selector, "select", late_select)
    else:
        read = os.read

        def late_read(fd: int, size: int) -> bytes:
            raw = read(fd, size)
            clock[0] = 2.0
            return raw

        monkeypatch.setattr(os, "read", late_read)
    try:
        with pytest.raises(InstalledRuntimeProofError, match="TOOL_TIMEOUT"):
            reader.read(1)
    finally:
        reader.close(success=False)
    assert reader.process.poll() is not None


def test_current_real_stdlib_modules_import_under_isolated_no_site_no_bytecode() -> None:
    source_root = Path(conda.__file__).resolve().parent.parent
    code = """
import sys,pathlib
assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
sys.path.insert(0,sys.argv[1])
import eom_catalog_service.embedding_conda_runtime_closure as conda
import eom_catalog_service.embedding_runtime_files as files
import eom_catalog_service.embedding_runtime_wheel_closure as wheel
for forbidden in ('pydantic','jsonschema','eom_catalog_contracts','eom_identifiers',
                  'torch','transformers','numpy','safetensors','tokenizers'):
 assert not any(name==forbidden or name.startswith(forbidden+'.') for name in sys.modules)
assert hasattr(files.NumericalRuntimeFileSnapshots,'observe_protected_member_bytes')
assert len(conda._LICENSES)==21 and len(conda._CROSS_LINKS)==2
print('STDLIB_CONDA31_IMPORT_PASS')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", code, str(source_root)],
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC"},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "STDLIB_CONDA31_IMPORT_PASS"


@pytest.mark.parametrize("fault", ["timeout", "overflow"])
def test_owned_tool_stream_denies_bounded_timeout_overflow_and_reaps(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    actual = subprocess.Popen
    script = (
        "import time; time.sleep(30)"
        if fault == "timeout"
        else "import sys; sys.stdout.buffer.write(b'x'*65536); sys.stdout.buffer.flush()"
    )

    def child(_command: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
        return actual([sys.executable, "-I", "-S", "-B", "-c", script], **kwargs)

    monkeypatch.setattr(subprocess, "Popen", child)
    if fault == "overflow":
        monkeypatch.setattr(conda, "_MAX_EXPANDED", 16)
    started = time.monotonic()
    reader = conda._ToolReader(
        io.BytesIO(b""), started + (0.05 if fault == "timeout" else 10), tool=_Fence()
    )
    try:
        with pytest.raises(InstalledRuntimeProofError, match=r"TOOL_TIMEOUT|STREAM_OVERFLOW"):
            reader.read(1)
    finally:
        reader.close(success=False)
    assert reader.process.poll() is not None
    assert reader.process.stdin is not None and reader.process.stdin.closed
    assert reader.process.stdout is not None and reader.process.stdout.closed
    assert time.monotonic() - started < 2


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["wrong"],
        [
            "conda31-bytes",
            "--profile",
            "CPU_INDEX_FP32",
            "--owner-input",
            "/tmp/untrusted",
            "--owner-input-sha256",
            "sha256:" + "a" * 64,
        ],
        [
            "conda31-bytes",
            "--profile",
            "CPU_INDEX_FP32",
            "--profile",
            "CUDA_INDEX_FP32",
            "--owner-input-sha256",
            "sha256:" + "a" * 64,
        ],
    ],
)
def test_closed_cli_rejects_arbitrary_paths_and_duplicate_selectors_without_io(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    cli = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/embedding/admit_index_runtime.py")
    )
    monkeypatch.setattr(os, "open", _deny)
    monkeypatch.setattr(subprocess, "Popen", _deny)
    assert cli["main"](arguments) == 1
    assert "EMBEDDING_CONDA_ARGUMENTS_INVALID" in capsys.readouterr().err
