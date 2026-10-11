"""Source-only tiny fixtures: no root identity, model, network or installed-state mutation."""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import importlib.util
import io
import os
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from eom_catalog_contracts.item_inference_transfer import LocalEmbeddingModelSpec
from eom_identifiers import canonical_json_bytes

from scripts.embedding import _install_experiment_snapshot as reviewed
from scripts.embedding import acquire_bge_m3_probe as acquisition
from scripts.embedding.model_snapshot_acquisition import build_experiment_spec


def helper_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("synthetic_model_only_helper", reviewed.__file__)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pinned_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    versions = dict(reviewed.BGE_RUNTIME_VERSIONS)
    monkeypatch.setattr(importlib.metadata, "version", versions.__getitem__)


def test_reviewed_bge_safe_candidate_has_exact_recipe_and_independent_manifest(
    pinned_versions: None,
) -> None:
    spec = acquisition.experiment_spec()
    assert spec.model_dump(mode="json") == reviewed.reviewed_bge_model_spec()
    assert spec.upstream_repo == "BAAI/bge-m3"
    assert spec.upstream_revision == "9a0624b896d81da7492a910ffa53731274b6cf3d"
    assert spec.dimension == 1024 and spec.maximum_tokens == 2048 and spec.pooling == "CLS"
    assert spec.query_prefix == spec.document_prefix == ""
    assert spec.dtype == "float32" and spec.truncation == "REJECT_OVERFLOW"
    assert len(spec.files) == 7
    assert sum(member.size_bytes for member in spec.files) == 2_293_233_901
    assert all(not member.member_path.endswith(".bin") for member in spec.files)
    raw = canonical_json_bytes(spec.model_dump(mode="json"))
    assert raw == reviewed.BGE_MANIFEST_BYTES
    assert hashlib.sha256(raw).hexdigest() == reviewed.BGE_MANIFEST_RAW_SHA256
    assert reviewed.BGE_MEMBERS["manifest.json"] == (len(raw), reviewed.BGE_MANIFEST_RAW_SHA256)


def test_wrong_runtime_fails_before_network_or_new_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "unreviewed")
    monkeypatch.setattr(acquisition, "urlopen", lambda *_a, **_k: pytest.fail("no network"))
    with pytest.raises(ValueError, match="exact CPU runtime"):
        acquisition.acquire(tmp_path)
    assert not tuple(tmp_path.iterdir())


def test_untrusted_recipe_is_not_admitted_by_acquisition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pinned_versions: None
) -> None:
    monkeypatch.setattr(acquisition, "reviewed_bge_model_spec", lambda: {"untrusted": "recipe"})
    monkeypatch.setattr(acquisition, "urlopen", lambda *_a, **_k: pytest.fail("no network"))
    with pytest.raises(ValueError, match="independent admission pins"):
        acquisition.acquire(tmp_path)
    assert not tuple(tmp_path.iterdir())


def tiny_spec(payload: bytes) -> LocalEmbeddingModelSpec:
    return build_experiment_spec(
        repository="BAAI/bge-m3",
        revision=reviewed.BGE_UPSTREAM_REVISION,
        files=tuple(
            (name, len(payload), hashlib.sha256(payload).hexdigest())
            for name, _size, _hash in reviewed.BGE_FILES
        ),
        dimension=1024,
        maximum_tokens=2048,
        pooling="CLS",
        prefix="",
        runtime_versions=reviewed.BGE_RUNTIME_VERSIONS,
    )


def test_fake_bge_acquisition_verifies_bytes_no_clobber_and_no_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = b"synthetic BGE bytes, not a model"
    spec = tiny_spec(payload)
    requested: list[str] = []

    def response(request: Any, *, timeout: int) -> io.BytesIO:
        assert timeout == 60
        requested.append(request.full_url)
        return io.BytesIO(payload)

    monkeypatch.setattr(acquisition, "experiment_spec", lambda: spec)
    monkeypatch.setattr(acquisition, "urlopen", response)
    assert acquisition.acquire(tmp_path) == spec
    snapshot = tmp_path / spec.model_id / spec.model_revision_id
    assert (snapshot / "manifest.json").read_bytes() == canonical_json_bytes(
        spec.model_dump(mode="json")
    )
    assert len(requested) == 7
    assert all(reviewed.BGE_UPSTREAM_REVISION in url for url in requested)
    assert "PRODUCTION_ACTIVATION=NOT_PERFORMED" in capsys.readouterr().out
    with pytest.raises(FileExistsError):
        acquisition.acquire(tmp_path)
    assert len(requested) == 7


def bge_source(tmp_path: Path, helper: ModuleType) -> tuple[Path, Path, dict[str, tuple[int, str]]]:
    store = tmp_path / "source"
    source = store / helper.BGE_MODEL_ID / helper.BGE_MODEL_REVISION
    source.mkdir(parents=True, mode=0o700)
    for directory in (store, source.parent, source):
        directory.chmod(0o700)
    (source / "1_Pooling").mkdir(mode=0o700)
    payloads = {"manifest.json": b"TEST_ONLY", "1_Pooling/config.json": b"{}"}
    members = {name: (len(raw), hashlib.sha256(raw).hexdigest()) for name, raw in payloads.items()}
    for name, raw in payloads.items():
        (source / name).write_bytes(raw)
        (source / name).chmod(0o400)
    target_parent = tmp_path / "target"
    target_parent.mkdir(mode=0o700)
    return source, target_parent / helper.BGE_MODEL_REVISION, members


def copy_bge(
    helper: ModuleType, source: Path, target: Path, members: dict[str, tuple[int, str]]
) -> None:
    helper.copy_reviewed_model_snapshot(
        source,
        target,
        model_id=helper.BGE_MODEL_ID,
        model_revision=helper.BGE_MODEL_REVISION,
        members=members,
        source_uid=os.geteuid(),
        cpu_gid=os.getegid(),
    )


def test_model_only_shared_fd_copy_uses_fresh_inode_and_preserves_old_history_fake_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = helper_module()
    source, target, members = bge_source(tmp_path, helper)
    old = tmp_path / "retained-e5-history"
    old.write_bytes(b"immutable terminal evidence")
    monkeypatch.setattr(helper, "require_root_path", lambda *_a, **_k: None)
    monkeypatch.setattr(helper.os, "chown", lambda *_a, **_k: None)
    copy_bge(helper, source, target, members)
    assert (target / "manifest.json").stat().st_ino != (source / "manifest.json").stat().st_ino
    assert (target / "manifest.json").stat().st_mode & 0o777 == 0o440
    assert target.stat().st_mode & 0o777 == 0o750
    with pytest.raises(ValueError, match="TARGET_EXISTS"):
        copy_bge(helper, source, target, members)
    assert old.read_bytes() == b"immutable terminal evidence"


def test_model_only_copy_rejects_source_manifest_runtime_rewrite_against_independent_raw_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = helper_module()
    source, target, members = bge_source(tmp_path, helper)
    raw = reviewed.BGE_MANIFEST_BYTES
    rewritten = raw.replace(b'"version":"4.56.2"', b'"version":"4.56.3"')
    assert rewritten != raw and len(rewritten) == len(raw)
    member = source / "manifest.json"
    member.chmod(0o600)
    member.write_bytes(rewritten)
    independent = {**members, "manifest.json": (len(raw), hashlib.sha256(raw).hexdigest())}
    monkeypatch.setattr(helper, "require_root_path", lambda *_a, **_k: None)
    monkeypatch.setattr(helper.os, "chown", lambda *_a, **_k: pytest.fail("no exposure"))
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        copy_bge(helper, source, target, independent)
    assert target.stat().st_mode & 0o777 == 0o700


def test_model_only_copy_rejects_existing_target_symlink_without_touching_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = helper_module()
    source, target, members = bge_source(tmp_path, helper)
    destination = tmp_path / "untouched"
    destination.mkdir()
    target.symlink_to(destination, target_is_directory=True)
    monkeypatch.setattr(helper, "require_root_path", lambda *_a, **_k: None)
    with pytest.raises(ValueError, match="TARGET_EXISTS"):
        copy_bge(helper, source, target, members)
    assert not tuple(destination.iterdir())


@pytest.mark.parametrize(
    "mutation", ["manifest", "size", "symlink", "hardlink", "fifo", "extra", "owner", "mode"]
)
def test_model_only_shared_copy_rejects_untrusted_source_without_exposure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    helper = helper_module()
    source, target, members = bge_source(tmp_path, helper)
    monkeypatch.setattr(helper, "require_root_path", lambda *_a, **_k: None)
    monkeypatch.setattr(helper.os, "chown", lambda *_a, **_k: pytest.fail("no exposure"))
    member = source / "manifest.json"
    if mutation == "manifest":
        member.chmod(0o600)
        member.write_bytes(b"WRONG_RAW")
    elif mutation == "size":
        member.chmod(0o600)
        member.write_bytes(b"short")
    elif mutation == "symlink":
        member.unlink()
        member.symlink_to(source / "1_Pooling/config.json")
    elif mutation == "hardlink":
        os.link(member, tmp_path / "hardlink")
    elif mutation == "fifo":
        member.unlink()
        os.mkfifo(member, 0o400)
    elif mutation == "extra":
        (source / "unreviewed.bin").write_bytes(b"unsafe")
    elif mutation == "owner":
        original_fstat = helper.os.fstat

        def different_owner(fd: int) -> object:
            value = original_fstat(fd)
            if value.st_ino == member.lstat().st_ino:
                return SimpleNamespace(
                    **{
                        name: getattr(value, name)
                        for name in (
                            "st_dev",
                            "st_ino",
                            "st_mode",
                            "st_gid",
                            "st_nlink",
                            "st_size",
                            "st_mtime_ns",
                            "st_ctime_ns",
                        )
                    },
                    st_uid=value.st_uid + 1,
                )
            return value

        monkeypatch.setattr(helper.os, "fstat", different_owner)
    else:
        source.chmod(0o750)
    with pytest.raises((ValueError, OSError)):
        copy_bge(helper, source, target, members)
    if target.exists():
        assert target.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("field", ["model_id", "model_revision", "member", "digest"])
def test_copy_rejects_invalid_independent_pin_shape_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    helper = helper_module()
    source, target, members = bge_source(tmp_path, helper)
    args = dict(
        model_id=helper.BGE_MODEL_ID,
        model_revision=helper.BGE_MODEL_REVISION,
        members=members,
        source_uid=os.geteuid(),
        cpu_gid=os.getegid(),
    )
    if field in ("model_id", "model_revision"):
        args[field] = "../escape"
    elif field == "member":
        args["members"] = {**members, "../escape": (1, "0" * 64)}
    else:
        args["members"] = {**members, "manifest.json": (9, "not-a-hash")}
    monkeypatch.setattr(helper, "require_root_path", lambda *_a, **_k: pytest.fail("no path use"))
    with pytest.raises(ValueError, match="SOURCE_INVALID"):
        helper.copy_reviewed_model_snapshot(source, target, **args)
    assert not target.exists()


def model_only_context(
    tmp_path: Path, helper: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> list[str]:
    events: list[str] = []
    prefix = tmp_path / "runtime"
    executable = prefix / "bin/python3.12"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"fake interpreter never executed")
    store = tmp_path / "models"
    store.mkdir(mode=0o750)
    store.chmod(0o750)
    monkeypatch.setattr(helper, "PREFIX", prefix)
    monkeypatch.setattr(helper, "MODEL_STORE", store)
    monkeypatch.setattr(helper.sys, "executable", str(executable))
    monkeypatch.setattr(helper.sys, "flags", SimpleNamespace(isolated=1, no_site=1))
    monkeypatch.setattr(helper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(helper, "require_root_path", lambda *_a, **_k: None)
    monkeypatch.setattr(helper.grp, "getgrnam", lambda _name: SimpleNamespace(gr_gid=os.getegid()))
    monkeypatch.setattr(helper.pwd, "getpwnam", lambda _name: SimpleNamespace(pw_uid=1000))

    def parent(model_id: str, cpu_gid: int) -> Path:
        assert model_id == helper.BGE_MODEL_ID and cpu_gid == os.getegid()
        events.append("new-BGE-parent")
        return store / model_id

    def copy(_source: Path, target: Path, **kwargs: object) -> None:
        assert target == store / helper.BGE_MODEL_ID / helper.BGE_MODEL_REVISION
        assert kwargs["members"] is helper.BGE_MEMBERS
        assert kwargs["source_uid"] == 1000 and kwargs["cpu_gid"] == os.getegid()
        events.append("new-BGE-copy")

    monkeypatch.setattr(helper, "prepare_model_snapshot_parent", parent)
    monkeypatch.setattr(helper, "copy_reviewed_model_snapshot", copy)
    for name in (
        "validate_runtime_tree",
        "verify_platform_wheel",
        "copy_reviewed_model",
        "ensure_owner_workspace",
    ):
        monkeypatch.setattr(
            helper, name, lambda *_a, **_k: pytest.fail("old runtime/history unchanged")
        )
    monkeypatch.setattr(
        helper.sys,
        "argv",
        [
            "helper",
            "--model-source",
            "/source",
            "--manifest-raw-sha256",
            helper.BGE_MANIFEST_RAW_SHA256,
        ],
    )
    return events


def test_model_only_entry_admits_only_new_snapshot_fake_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    helper = helper_module()
    events = model_only_context(tmp_path, helper, monkeypatch)
    assert helper.model_only_main() == 0
    assert events == ["new-BGE-parent", "new-BGE-copy"]
    assert (
        capsys.readouterr().out
        == "EMBEDDING_MODEL_ONLY_ADMISSION=PASS\nRUNTIME_AND_HISTORY=UNCHANGED\n"
    )


@pytest.mark.parametrize(
    "mutation", ["uid", "isolated", "no_site", "executable", "manifest", "store_group"]
)
def test_model_only_entry_context_failure_has_zero_copy_and_safe_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mutation: str,
) -> None:
    helper = helper_module()
    events = model_only_context(tmp_path, helper, monkeypatch)
    if mutation == "uid":
        monkeypatch.setattr(helper.os, "geteuid", lambda: 1000)
    elif mutation in ("isolated", "no_site"):
        monkeypatch.setattr(
            helper.sys, "flags", SimpleNamespace(**{"isolated": 1, "no_site": 1, mutation: 0})
        )
    elif mutation == "executable":
        monkeypatch.setattr(helper.sys, "executable", "/untrusted/python")
    elif mutation == "manifest":
        monkeypatch.setattr(
            helper.sys,
            "argv",
            ["helper", "--model-source", "/source", "--manifest-raw-sha256", "0" * 64],
        )
    else:
        monkeypatch.setattr(
            helper.grp, "getgrnam", lambda _name: SimpleNamespace(gr_gid=os.getegid() + 1)
        )
    assert helper.model_only_main() == 1
    assert events == []
    output = capsys.readouterr()
    assert output.out == "" and output.err == "EMBEDDING_MODEL_ONLY_ADMISSION_REJECTED\n"


def test_root_helper_remains_stdlib_only_and_no_unsafe_model_or_execution() -> None:
    tree = ast.parse(Path(reviewed.__file__).read_bytes())
    imports = {
        node.module.split(".", 1)[0]
        if isinstance(node, ast.ImportFrom) and node.module
        else alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imports <= {
        "__future__",
        "argparse",
        "base64",
        "csv",
        "grp",
        "hashlib",
        "io",
        "json",
        "os",
        "pwd",
        "re",
        "stat",
        "sys",
        "zipfile",
        "pathlib",
        "typing",
    }
    calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert not calls & {"eval", "exec", "os.system", "os.execv", "os.execve", "os.spawnv"}
