"""Synthetic process identity/descriptor gates; no installed unit or ML execution."""

from __future__ import annotations

import ast
import errno
import fcntl
import grp
import os
import platform
import pwd
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn

import pytest
from eom_catalog_service import embedding_native_entrypoint as entry
from eom_catalog_service.embedding_runtime_files import fixed_native_embedding_profile


@pytest.mark.parametrize("profile", ("CPU_INDEX_FP32", "CUDA_INDEX_FP32"))
def test_fixed_identity_uses_exact_profile_groups_isolation_and_zero_caps(
    monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    with monkeypatch.context() as patch:
        _identity(patch, profile)
        entry.require_native_embedding_identity(profile)


def _identity(patch: pytest.MonkeyPatch, profile: str = "CPU_INDEX_FP32") -> None:
    fixed = fixed_native_embedding_profile(profile)
    patch.setattr(pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=1234, pw_gid=1234))
    patch.setattr(
        grp,
        "getgrnam",
        lambda name: SimpleNamespace(gr_gid=4321 if name == "eom-gpu-lease" else 1234),
    )
    patch.setattr(os, "getresuid", lambda: (1234,) * 3)
    patch.setattr(os, "getresgid", lambda: (1234,) * 3)
    patch.setattr(os, "getgroups", lambda: [1234, 4321] if profile == "CUDA_INDEX_FP32" else [])
    patch.setattr(sys, "prefix", str(fixed.prefix))
    patch.setattr(sys, "executable", str(fixed.prefix / "bin/python3.12"))
    patch.setattr(sys, "version_info", (3, 12, 13))
    patch.setattr(sys, "dont_write_bytecode", True)
    patch.setattr(sys, "flags", SimpleNamespace(isolated=1, ignore_environment=1, no_user_site=1))
    patch.setattr(platform, "python_implementation", lambda: "CPython")
    patch.setattr(platform, "machine", lambda: "x86_64")
    patch.setattr(
        entry,
        "read_live_runtime_os_file",
        lambda *_args, **_kwargs: (
            b"NoNewPrivs:\t1\nCapInh:\t0000000000000000\nCapPrm:\t0000000000000000\n"
            b"CapEff:\t0000000000000000\nCapBnd:\t0000000000000000\nCapAmb:\t0000000000000000\n"
        ),
    )


@pytest.mark.parametrize(
    "fault",
    (
        "uid",
        "saved_uid",
        "gid",
        "groups",
        "prefix",
        "interpreter",
        "version",
        "isolated",
        "environment",
        "usersite",
        "bytecode",
        "platform",
        "nnp",
        "capability",
        "duplicate",
        "malformed",
        "missing",
        "cuda_group",
    ),
)
def test_identity_and_caps_drift_denies_before_any_native_leaf(
    fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = "CUDA_INDEX_FP32" if fault == "cuda_group" else "CPU_INDEX_FP32"
    with monkeypatch.context() as patch:
        _identity(patch, profile)
        if fault in {"uid", "saved_uid"}:
            patch.setattr(os, "getresuid", lambda: (0, 1234, 0))
        elif fault == "gid":
            patch.setattr(os, "getresgid", lambda: (0,) * 3)
        elif fault in {"groups", "cuda_group"}:
            patch.setattr(os, "getgroups", lambda: [0])
        elif fault == "prefix":
            patch.setattr(sys, "prefix", "/tmp/worker")
        elif fault == "interpreter":
            patch.setattr(sys, "executable", "/usr/bin/python3")
        elif fault == "version":
            patch.setattr(sys, "version_info", (3, 12, 12))
        elif fault in {"isolated", "environment", "usersite"}:
            values = dict(isolated=1, ignore_environment=1, no_user_site=1)
            values[
                {
                    "isolated": "isolated",
                    "environment": "ignore_environment",
                    "usersite": "no_user_site",
                }[fault]
            ] = 0
            patch.setattr(sys, "flags", SimpleNamespace(**values))
        elif fault == "bytecode":
            patch.setattr(sys, "dont_write_bytecode", False)
        elif fault == "platform":
            patch.setattr(platform, "machine", lambda: "aarch64")
        else:
            statuses = {
                "nnp": b"NoNewPrivs: 0\n",
                "capability": b"NoNewPrivs: 1\nCapEff: 0000000000000001\n",
                "duplicate": b"NoNewPrivs: 1\nNoNewPrivs: 1\n",
                "malformed": b"malformed\n",
                "missing": b"",
            }
            patch.setattr(
                entry, "read_live_runtime_os_file", lambda *_args, **_kwargs: statuses[fault]
            )
        with pytest.raises(ValueError):
            entry.require_native_embedding_identity(profile)


@pytest.mark.parametrize("operation", ["INDEX", "QUERY", "PRIVATE_CHAT_QUERY"])
def test_saved_binary_and_result_fds_receive_only_explicit_leaf_writes_and_are_closed(
    tmp_path: Path,
    operation: str,
) -> None:
    result, vectors = tmp_path / "result", tmp_path / "vectors"
    result.write_bytes(b"")
    vectors.write_bytes(b"")
    script = """
import errno, os, sys
from eom_catalog_service import embedding_native_entrypoint as entry
from eom_catalog_service import embedding_native_stdio as leaf
r=os.open(sys.argv[1],os.O_WRONLY); v=os.open(sys.argv[2],os.O_WRONLY)
os.dup2(r,1); os.dup2(v,2); os.close(r); os.close(v)
saved=[]
def identity(profile):
    os.write(1,b'identity diagnostic'); os.write(2,b'identity error')
def run(descriptors,scope):
    saved.extend([descriptors.result,descriptors.vectors])
    assert descriptors.input==0 and not os.get_inheritable(descriptors.result)
    assert not os.get_inheritable(descriptors.vectors)
    assert os.readlink('/proc/self/fd/1')=='/dev/null'
    assert os.readlink('/proc/self/fd/2')=='/dev/null'
    os.write(1,b'library diagnostic'); os.write(2,b'library error')
    os.write(descriptors.vectors,b'binary'); os.write(descriptors.result,b'{}')
entry.require_native_embedding_identity=identity
if sys.argv[3]=='QUERY':
    leaf.run_native_reference_query_descriptors=run
    entry.run_native_embedding_reference_query(profile='CPU_INDEX_FP32',backend_scope=lambda:None)
elif sys.argv[3]=='PRIVATE_CHAT_QUERY':
    leaf.run_native_private_chat_query_descriptors=run
    entry.run_native_embedding_private_chat_query(profile='CPU_INDEX_FP32',backend_scope=lambda:None)
else:
    leaf.run_native_embedding_descriptors=run
    entry.run_native_embedding_index(profile='CPU_INDEX_FP32',backend_scope=lambda:None)
for fd in saved:
    try: os.fstat(fd)
    except OSError as exc: assert exc.errno==errno.EBADF
    else: raise AssertionError('saved FD leaked')
os.write(1,b'after diagnostic'); os.write(2,b'after error')
"""
    completed = subprocess.run(
        [
            "/srv/eom/conda/envs/eom-api/bin/python",
            "-c",
            script,
            str(result),
            str(vectors),
            operation,
        ],
        check=False,
        timeout=30,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert completed.returncode == 0
    assert result.read_bytes() == b"{}" and vectors.read_bytes() == b"binary"


@pytest.mark.parametrize("operation", ["INDEX", "QUERY", "PRIVATE_CHAT_QUERY"])
def test_duplicate_partial_failure_closes_only_owned_fds(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    closed: list[int] = []
    calls = 0

    def duplicate(*_args: object) -> int:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(errno.EBADF, "synthetic FD denial")
        return 12345

    with monkeypatch.context() as patch:
        patch.setattr(fcntl, "fcntl", duplicate)
        patch.setattr(os, "close", closed.append)
        with pytest.raises(entry.NativeEmbeddingEntrypointError):
            run = {
                "QUERY": entry.run_native_embedding_reference_query,
                "INDEX": entry.run_native_embedding_index,
                "PRIVATE_CHAT_QUERY": entry.run_native_embedding_private_chat_query,
            }[operation]
            run(profile="CPU_INDEX_FP32", backend_scope=lambda: pytest.fail("no scope"))
    assert closed == [12345]


@pytest.mark.parametrize("operation", ["INDEX", "QUERY", "PRIVATE_CHAT_QUERY"])
def test_identity_failure_precedes_imported_leaf_and_scope(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    from collections.abc import Iterator
    from contextlib import contextmanager

    @contextmanager
    def quiet() -> Iterator[tuple[int, int]]:
        yield 31, 32

    def denied(_profile: str) -> None:
        raise ValueError("source-only identity denial")

    def patch_scope() -> NoReturn:
        pytest.fail("identity must precede scope")

    monkeypatch.setattr(entry, "_quiet_channels", quiet)
    monkeypatch.setattr(entry, "require_native_embedding_identity", denied)
    with pytest.raises(entry.NativeEmbeddingEntrypointError):
        run = {
            "QUERY": entry.run_native_embedding_reference_query,
            "INDEX": entry.run_native_embedding_index,
            "PRIVATE_CHAT_QUERY": entry.run_native_embedding_private_chat_query,
        }[operation]
        run(profile="CPU_INDEX_FP32", backend_scope=patch_scope)


def test_fresh_entrypoint_import_is_stdlib_only_and_no_cli_default() -> None:
    completed = subprocess.run(
        [
            "/srv/eom/conda/envs/eom-api/bin/python",
            "-c",
            "import sys; import eom_catalog_service.embedding_native_entrypoint; "
            "assert not any(n in sys.modules for n in "
            "('pydantic','torch','transformers','eom_gpu_lease'))",
        ],
        check=False,
        timeout=30,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert completed.returncode == 0
    source = (
        Path(__file__).resolve().parents[2]
        / "services/catalog_service/eom_catalog_service/embedding_native_entrypoint.py"
    )
    tree = ast.parse(source.read_text())
    assert not any(isinstance(node, ast.FunctionDef) and node.name == "main" for node in tree.body)


@pytest.mark.parametrize("field", ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"))
def test_every_process_capability_set_must_be_zero(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as patch:
        _identity(patch)
        raw = b"NoNewPrivs: 1\n" + b"".join(
            f"{name}: {'0000000000000001' if name == field else '0000000000000000'}\n".encode()
            for name in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
        )
        patch.setattr(entry, "read_live_runtime_os_file", lambda *_args, **_kwargs: raw)
        with pytest.raises(entry.NativeEmbeddingEntrypointError, match="CAPABILITIES_INVALID"):
            entry.require_native_embedding_identity("CPU_INDEX_FP32")
