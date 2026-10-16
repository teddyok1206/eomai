"""Synthetic captured readelf/kernel ports, never root/native/CUDA execution evidence."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_cuda_host_extension import parse_cuda_host_extension_bytes
from eom_catalog_service import embedding_cuda_host_closure as cuda
from eom_catalog_service import embedding_host_configuration_capture as capture
from eom_catalog_service import embedding_runtime_host_closure as host
from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
)
from eom_identifiers import sha256_bytes

from tests.unit.test_embedding_cuda_host_capture import fixture
from tests.unit.test_embedding_cuda_host_extension import rehash
from tests.unit.test_embedding_host_configuration_files import _mount_ports, _write
from tests.unit.test_embedding_runtime_prefix_closure import _elf_text


@dataclass
class FakeBase:
    reports: dict[int, bytes]
    closed: bool = False
    descriptors: list[int] = field(default_factory=list)

    def assert_current(self):
        assert not self.closed

    def close(self):
        self.closed = True

    def inspect_elf(self, fd, *, deadline):
        self.assert_current()
        self.descriptors.append(fd)
        return self.reports[os.fstat(fd).st_ino]

    def fixed_soname_versions(self, name):
        if name != "libc.so.6":
            raise InstalledRuntimeProofError("INSTALLED_RUNTIME_HOST_SONAME_UNAVAILABLE")
        return frozenset({"GLIBC_2.38"})

    def fixed_loader_path(self):
        return Path("/lib64/ld-linux-x86-64.so.2")

    def assert_absent_search_route(self, route):
        if route != "/usr/local/cuda/lib64":
            raise InstalledRuntimeProofError("INSTALLED_RUNTIME_HOST_ROUTE_INVALID")

    def assert_mapped_file(self, path, *, device, inode):
        raise InstalledRuntimeProofError("INSTALLED_RUNTIME_HOST_MAPPED_FILE_UNAVAILABLE")


def ports(tmp_path, monkeypatch):
    value = fixture(tmp_path, monkeypatch)
    document = parse_cuda_host_extension_bytes(value.manifest.read_bytes()).model_dump(mode="json")
    reports = {}
    for path, row in zip(value.libraries, document["libraries"], strict=True):
        raw = b"\x7fELF:synthetic-not-executable:" + path.name.encode()
        _write(path, raw)
        row.update(byte_count=len(raw), sha256=sha256_bytes(raw))
        report = _elf_text(
            needed=("libc.so.6",),
            soname=path.name,
            definition="EXAM_LIBRARY_1.0",
            required=("libc.so.6", "GLIBC_2.38"),
        )
        reports[path.stat().st_ino] = report.replace(
            b"ELF Header:\n", b"ELF Header:\n  Type: DYN (Shared object file)\n"
        )
    value.repin(rehash(document))
    selected = value.resolve().captured
    _mount_ports(monkeypatch, value)
    witness = capture.require_host_configuration_snapshot_mount(selected)
    base = FakeBase(reports)
    observed = []

    def create(**kwargs):
        assert kwargs["expected_seed_sha256"] == selected.host_seed_sha256
        assert kwargs["fixed_files"] == host._files_with_loader_cache(
            cache_byte_count=selected.cache_byte_count, cache_sha256=selected.cache_sha256
        )
        observed.append(True)
        kwargs["assert_mount_current"]()
        return base

    monkeypatch.setattr(host, "_capture_embedding_host", create)
    return value, selected, witness, base, observed


def compose(selected, witness):
    return cuda.capture_cuda_embedding_host(
        expected_seed_sha256=selected.host_seed_sha256,
        files=NumericalRuntimeFileSnapshots(os.geteuid()),
        snapshot_mount=witness,
    )


def test_six_exact_fd_providers_compose_with_base_and_close_all_descriptors(tmp_path, monkeypatch):
    value, selected, witness, base, observed = ports(tmp_path, monkeypatch)
    with compose(selected, witness) as combined:
        assert observed == [True] and len(base.descriptors) == 6
        assert combined.seed_sha256 == selected.host_seed_sha256
        assert combined.fixed_soname_versions("libcuda.so.1") == frozenset({"EXAM_LIBRARY_1.0"})
        assert combined.fixed_soname_versions("libc.so.6") == frozenset({"GLIBC_2.38"})
        assert combined.fixed_loader_path() == base.fixed_loader_path()
        combined.assert_absent_search_route("/usr/local/cuda/lib64")
        path = value.libraries[0]
        epoch = path.stat()
        combined.assert_mapped_file(path, device=epoch.st_dev, inode=epoch.st_ino)
        with pytest.raises(InstalledRuntimeProofError, match="MAPPED_FILE_UNAVAILABLE"):
            combined.assert_mapped_file(path, device=epoch.st_dev, inode=epoch.st_ino + 1)
        with pytest.raises(InstalledRuntimeProofError, match="SONAME_UNAVAILABLE"):
            combined.fixed_soname_versions("undeclared.so.1")
    assert base.closed
    for fd in base.descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)
    combined.close()
    with pytest.raises(InstalledRuntimeProofError, match="CUDA_HOST_CLOSED"):
        combined.assert_current()


@pytest.mark.parametrize(
    "fault",
    ("soname", "rpath", "runpath", "executable", "interpreter", "unknown_dependency", "version"),
)
def test_wrong_library_routes_dependencies_or_versions_fail_and_cleanup(
    tmp_path, monkeypatch, fault
):
    value, selected, witness, base, _ = ports(tmp_path, monkeypatch)
    inode = value.libraries[0].stat().st_ino
    raw = base.reports[inode]
    if fault == "soname":
        raw = raw.replace(b"Library soname: [libcuda.so.1]", b"Library soname: [libc.so.6]")
    elif fault in {"rpath", "runpath"}:
        raw += f" 0xf ({fault.upper()}) Library {fault}: [/tmp/untrusted]\n".encode()
    elif fault == "executable":
        raw = raw.replace(b"Type: DYN", b"Type: EXEC")
    elif fault == "interpreter":
        raw += b" [Requesting program interpreter: /lib64/ld-linux-x86-64.so.2]\n"
    elif fault == "unknown_dependency":
        raw += b" 0x1 (NEEDED) Shared library: [unregistered.so.1]\n"
    else:
        raw = raw.replace(b"GLIBC_2.38", b"GLIBC_999.0")
    base.reports[inode] = raw
    with pytest.raises(InstalledRuntimeProofError):
        compose(selected, witness)
    assert base.closed
    for fd in base.descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_mismatched_seed_fails_before_tool_capture(tmp_path, monkeypatch):
    _value, _selected, witness, base, observed = ports(tmp_path, monkeypatch)
    with pytest.raises(InstalledRuntimeProofError, match="SEED_INVALID"):
        cuda.capture_cuda_embedding_host(
            expected_seed_sha256="sha256:" + "9" * 64,
            files=NumericalRuntimeFileSnapshots(os.geteuid()),
            snapshot_mount=witness,
        )
    assert observed == [] and not base.closed and base.descriptors == []


def test_fd_substitution_is_rejected_even_when_original_files_are_unchanged(tmp_path, monkeypatch):
    value, selected, witness, base, _ = ports(tmp_path, monkeypatch)
    combined = compose(selected, witness)
    with value.libraries[1].open("rb") as alternate:
        os.dup2(alternate.fileno(), base.descriptors[0])
        with pytest.raises(InstalledRuntimeProofError, match="FD_CHANGED"):
            combined.assert_current()
        with pytest.raises(InstalledRuntimeProofError):
            combined.close()
    assert base.closed


def test_base_cache_mount_is_not_a_cuda_cache_witness(tmp_path, monkeypatch):
    _value, selected, witness, _base, observed = ports(tmp_path, monkeypatch)
    monkeypatch.setattr(capture, "_CACHE", selected.base_configuration.cache_path)
    with pytest.raises(capture.HostConfigurationSnapshotError, match="MOUNT_INVALID"):
        compose(selected, witness)
    assert observed == []


def test_unversioned_driver_is_not_confused_with_an_unregistered_provider(tmp_path, monkeypatch):
    value, selected, witness, base, _ = ports(tmp_path, monkeypatch)
    base.reports[value.libraries[0].stat().st_ino] = _elf_text(
        needed=("libc.so.6",), soname="libcuda.so.1", required=("libc.so.6", "GLIBC_2.38")
    ).replace(b"ELF Header:\n", b"ELF Header:\n  Type: DYN (Shared object file)\n")
    with compose(selected, witness) as combined:
        assert combined.fixed_soname_versions("libcuda.so.1") == frozenset()


@pytest.mark.parametrize("valid", (True, False))
def test_cuda_library_to_library_required_versions_are_checked(tmp_path, monkeypatch, valid):
    value, selected, witness, base, _ = ports(tmp_path, monkeypatch)
    provider, consumer = value.libraries[2:4]
    base.reports[consumer.stat().st_ino] = _elf_text(
        needed=(provider.name,),
        soname=consumer.name,
        required=(provider.name, "EXAM_LIBRARY_1.0" if valid else "MISSING_999.0"),
    ).replace(b"ELF Header:\n", b"ELF Header:\n  Type: DYN (Shared object file)\n")
    if valid:
        with compose(selected, witness) as combined:
            assert combined.fixed_soname_versions(provider.name) == frozenset({"EXAM_LIBRARY_1.0"})
    else:
        with pytest.raises(InstalledRuntimeProofError, match="VERSION_UNAVAILABLE"):
            compose(selected, witness)
    assert base.closed


def test_shared_metadata_parser_is_bounded_on_maximum_blank_line_input():
    root = Path(cuda.__file__).parent.parent
    program = """
import sys
sys.path.insert(0,sys.argv[1])
from eom_catalog_service.embedding_runtime_host_closure import (
    parse_embedding_elf_metadata, MAX_READELF_OUTPUT_BYTES)
from pathlib import Path
raw=b"Class: ELF64\\nData: 2's complement, little endian\\n"
raw+=b"Machine: Advanced Micro Devices X86-64\\n"
raw+=b"\\n"*(MAX_READELF_OUTPUT_BYTES-len(raw))
result=parse_embedding_elf_metadata(Path('/synthetic'),raw)
assert result.object_kind is None
print('BOUNDED_METADATA_PARSE=PASS')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", program, str(root)],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "BOUNDED_METADATA_PARSE=PASS"
