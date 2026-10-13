"""Complete synthetic read-only prefix composition; no root/model/GPU/service admission."""

from __future__ import annotations

import hashlib
import io
import json
import os
import runpy
import stat
import subprocess
import sys
import tarfile
import time
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, NoReturn, cast

import pytest
from eom_catalog_service import embedding_conda_runtime_closure as conda
from eom_catalog_service import embedding_runtime_host_closure as host
from eom_catalog_service import embedding_runtime_prefix_closure as prefix
from eom_catalog_service.embedding_runtime_files import (
    FixedNativeEmbeddingProfile,
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
)
from eom_catalog_service.embedding_runtime_wheel_closure import (
    RuntimeWheelArchivePin,
    RuntimeWheelMemberPin,
)

from tests.unit.embedding_installed_runtime_fixtures import synthetic_record, synthetic_wheel
from tests.unit.test_embedding_conda_runtime_admission import _fixture as conda_fixture


def _hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _put(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(raw)
    path.chmod(0o600)


def _tar(members: dict[str, bytes], commit: str, *, wrapped: bool = True) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        comment = f"52 comment={commit}\n".encode()
        global_header = tarfile.TarInfo("pax_global_header")
        global_header.type = tarfile.XGLTYPE
        global_header.size = len(comment)
        archive.addfile(global_header, io.BytesIO(comment))
        if wrapped:
            root = tarfile.TarInfo(commit)
            root.type = tarfile.DIRTYPE
            archive.addfile(root)
        for name, raw in members.items():
            item = tarfile.TarInfo(commit + "/" + name if wrapped else name)
            item.size = len(raw)
            archive.addfile(item, io.BytesIO(raw))
    return stream.getvalue()


def _project() -> bytes:
    where = json.dumps(sorted(prefix._ROOTS))
    return (
        "[project]\nname='eom-platform'\nversion='0.1.0'\n"
        "[tool.setuptools.packages.find]\nwhere=" + where + "\n"
        "[tool.setuptools.package-data]\neom_catalog_service=['resources/*.json']\n"
    ).encode()


def _fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    profile: Literal["CPU_INDEX_FP32", "CUDA_INDEX_FP32"] = "CPU_INDEX_FP32",
    literal_resource: bool = False,
) -> tuple[prefix.PrefixRuntimeAuditPlan, Any, host.ProtectedEmbeddingHostClosure, Path, Path]:
    actual_popen = subprocess.Popen
    staged = conda_fixture(tmp_path, monkeypatch, profile)
    monkeypatch.setattr(prefix, "_COUNTS", {"CPU_INDEX_FP32": 4, "CUDA_INDEX_FP32": 4})
    monkeypatch.setattr(
        prefix,
        "fixed_native_embedding_profile",
        lambda _profile: FixedNativeEmbeddingProfile(profile, staged.prefix, "synthetic", None),
    )
    commit = "b" * 40
    rows = {
        pin.wheel_filename.split("-", 1)[0]: (
            pin.wheel_filename.split("-")[1],
            pin.wheel_filename,
            pin.sha256[7:],
        )
        for pin in staged.plan.overlay_archives
    }
    helper = ("def index_runtime_locks(directory, profile):\n return " + repr(rows) + "\n").encode()
    lock_directory = tmp_path / "owner/locks"
    source = {
        "pyproject.toml": _project(),
        "scripts/embedding/_install_experiment_snapshot.py": helper,
        "services/catalog_service/eom_catalog_service/__init__.py": b"",
        "services/catalog_service/eom_catalog_service/native.py": b"# source never executed\n",
        "services/catalog_service/eom_catalog_service/resources/config.json": b"{}\n",
        "packages/gpu_lease/pyproject.toml": (
            b"[project]\nname='eom-gpu-lease'\nversion='0.1.0'\n"
            b"[tool.setuptools.packages.find]\nwhere=['.']\ninclude=['eom_gpu_lease*']\n"
        ),
        "packages/gpu_lease/eom_gpu_lease/__init__.py": b"# synthetic\n",
        "packages/gpu_lease/eom_gpu_lease/lease.py": b"# synthetic\n",
    }
    if literal_resource:
        source["pyproject.toml"] += (
            b"eom_operator_identity=['resources/operator-owner-session-capture-v1.schema.json']\n"
        )
        source["packages/operator_identity/eom_operator_identity/__init__.py"] = b"# synthetic\n"
        source[
            "packages/operator_identity/eom_operator_identity/resources/operator-owner-session-capture-v1.schema.json"
        ] = b'{"synthetic_schema":true}\n'
    for parent, name in prefix._LOCKS:
        source[parent + "/" + name] = b"# pinned synthetic lock\n"
        _put(lock_directory / name, source[parent + "/" + name])
    tar = _tar(source, commit)
    source_pin = prefix.PrefixSourceArchivePin(_hash(tar), len(tar))
    _put(staged.archive_root / source_pin.sha256[7:] / f"source-{commit}.tar", tar)
    helper_path = tmp_path / "owner/install.py"
    _put(helper_path, helper)
    private = []
    for name in (
        ("eom-platform",) if profile == "CPU_INDEX_FP32" else ("eom-platform", "eom-gpu-lease")
    ):
        payload = {
            path.removeprefix("services/catalog_service/"): raw
            for path, raw in source.items()
            if path.startswith("services/catalog_service/")
        }
        if literal_resource:
            payload.update(
                {
                    path.removeprefix("packages/operator_identity/"): raw
                    for path, raw in source.items()
                    if path.startswith("packages/operator_identity/")
                }
            )
        if name == "eom-gpu-lease":
            payload = {
                path.removeprefix("packages/gpu_lease/"): raw
                for path, raw in source.items()
                if path.startswith("packages/gpu_lease/eom_gpu_lease/")
            }
        dist = name.replace("-", "_") + "-0.1.0.dist-info"
        payload[dist + "/METADATA"] = (
            f"Metadata-Version: 2.1\nName: {name}\nVersion: 0.1.0\n\n".encode()
        )
        payload[dist + "/WHEEL"] = (
            b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n"
        )
        record = dist + "/RECORD"
        wheel = synthetic_wheel(payload | {record: synthetic_record(payload, record)})
        archive = RuntimeWheelArchivePin(
            name.replace("-", "_") + "-0.1.0-py3-none-any.whl", _hash(wheel), len(wheel)
        )
        _put(staged.archive_root / archive.sha256[7:] / archive.wheel_filename, wheel)
        installed = payload | {dist + "/INSTALLER": b"pip\n"}
        installed[record] = synthetic_record(installed, record)
        for path, raw in installed.items():
            _put(staged.prefix / "lib/python3.12/site-packages" / path, raw)
        private.append(prefix.PrefixSourceWheelPin(name, archive, commit, source_pin))
    extras = []
    for name in ("created_at", "history"):
        raw = ("synthetic " + name + "\n").encode()
        _put(staged.prefix / "conda-meta" / name, raw)
        extras.append(RuntimeWheelMemberPin(_hash(raw), len(raw)))
    plan = prefix.PrefixRuntimeAuditPlan(
        staged.plan,
        tuple(sorted(staged.plan.overlay_archives, key=lambda pin: pin.wheel_filename)),
        tuple(private),
        extras[0],
        extras[1],
        RuntimeWheelMemberPin(_hash(helper), len(helper)),
    )
    tool = conda._ZSTD_PATH
    loader = tmp_path / "synthetic-loader"
    _put(loader, b"synthetic loader not executed")
    monkeypatch.setattr(host, "_ZSTD", tool)
    monkeypatch.setattr(host, "_LOADER", loader)
    stack = ExitStack()
    descriptors = {path: os.open(path, os.O_RDONLY | os.O_CLOEXEC) for path in (tool, loader)}
    for fd in descriptors.values():
        stack.callback(os.close, fd)
    owned = host.ProtectedEmbeddingHostClosure(
        NumericalRuntimeFileSnapshots(os.geteuid()),
        host._HostRoutes(os.geteuid()),
        stack,
        descriptors,
        {path: host._identity(os.fstat(fd)) for path, fd in descriptors.items()},
        _hash(b"synthetic"),
    )

    def child(command: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
        assert command == ["/usr/bin/zstd", "-q", "-d", "-c"]
        kwargs.pop("executable")
        return actual_popen(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                "-c",
                "import sys\nwhile b:=sys.stdin.buffer.read(65536):\n"
                " sys.stdout.buffer.write(b)\n sys.stdout.buffer.flush()",
            ],
            **kwargs,
        )

    monkeypatch.setattr(subprocess, "Popen", child)
    for directory in tmp_path.rglob("*"):
        if directory.is_dir() and not directory.is_symlink():
            directory.chmod(0o700)
    return plan, staged, owned, helper_path, lock_directory


def _audit(
    plan: prefix.PrefixRuntimeAuditPlan,
    staged: Any,
    owned: host.ProtectedEmbeddingHostClosure,
    helper_path: Path,
    locks: Path,
) -> prefix.PrefixRuntimeByteAudit:
    return prefix.audit_installed_embedding_prefix(
        plan,
        prefix=staged.prefix,
        archive_root=staged.archive_root,
        helper_path=helper_path,
        lock_directory=locks,
        files=NumericalRuntimeFileSnapshots(os.geteuid()),
        host=owned,
    )


@pytest.mark.parametrize("profile", ["CPU_INDEX_FP32", "CUDA_INDEX_FP32"])
def test_complete_source_conda_overlay_private_tree_closure_has_no_new_instruction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: Literal["CPU_INDEX_FP32", "CUDA_INDEX_FP32"],
) -> None:
    plan, staged, owned, helper, locks = _fixture(tmp_path, monkeypatch, profile=profile)
    marker = tmp_path / "NEW_EXECUTED"
    observed_trees: list[dict[Path, tuple[int, ...]]] = []
    actual_tree = prefix._tree

    def tree(
        root: Path, expected: set[Path], links: dict[Path, str], owner_uid: int
    ) -> tuple[dict[Path, tuple[int, ...]], int, int]:
        result = actual_tree(root, expected, links, owner_uid)
        observed_trees.append(result[0])
        return result

    monkeypatch.setattr(prefix, "_tree", tree)
    with owned:
        first = _audit(plan, staged, owned, helper, locks)
        second = _audit(plan, staged, owned, helper, locks)
    assert first == second and first.profile == profile
    assert first.regular_members > 31 and first.link_members == 4 and first.elf_members == 0
    inventory = first.inventory
    assert len(observed_trees) == 2
    assert inventory.root_epoch is observed_trees[0][staged.prefix]
    assert inventory.owner_uid == os.geteuid() == staged.prefix.lstat().st_uid
    assert inventory.ancestor_epochs == tuple(
        (path, prefix._ancestor_identity(path.lstat())) for path in reversed(staged.prefix.parents)
    )
    names = [entry.relative_member for entry in inventory.entries]
    assert names == sorted(set(names))
    regular = links = size = 0
    for entry in inventory.entries:
        path = staged.prefix / entry.relative_member
        assert entry.epoch is observed_trees[0][path]
        assert entry.epoch == prefix._identity(path.lstat())
        if stat.S_ISREG(entry.epoch[4]):
            assert entry.sha256 == _hash(path.read_bytes()) and entry.symlink_target is None
            regular += 1
            size += entry.epoch[6]
        elif stat.S_ISLNK(entry.epoch[4]):
            assert entry.symlink_target == os.readlink(path) and entry.sha256 is None
            links += 1
        else:
            assert stat.S_ISDIR(entry.epoch[4]) and entry.sha256 is entry.symlink_target is None
    assert (regular, links, size) == (first.regular_members, first.link_members, first.size_bytes)
    assert {staged.prefix, *(staged.prefix / name for name in names)} == set(observed_trees[0])
    inventory.assert_unchanged()
    assert not marker.exists()


def _local_inventory(tmp_path: Path) -> prefix.PrefixRuntimeInventory:
    """Actual eom-owned metadata values only, not a complete byte audit or root admission."""
    root = tmp_path / "prefix"
    root.mkdir(mode=0o700)
    target = root / "bin/a"
    _put(target, b"synthetic local bytes")
    link = root / "bin/alias"
    link.symlink_to("a")
    epochs, _size, _regular = prefix._tree(root, {target, link}, {link: "a"}, os.geteuid())
    return prefix.PrefixRuntimeInventory(
        root,
        os.geteuid(),
        epochs[root],
        tuple((path, prefix._ancestor_identity(path.lstat())) for path in reversed(root.parents)),
        tuple(
            prefix.PrefixRuntimeInventoryEntry(
                str(path.relative_to(root)),
                epoch,
                _hash(b"synthetic local bytes") if path == target else None,
                "a" if path == link else None,
            )
            for path, epoch in sorted(epochs.items())
            if path != root
        ),
    )


def test_inventory_is_frozen_and_unchanged_check_never_walks_opens_or_rehashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inventory = _local_inventory(tmp_path)
    with pytest.raises(FrozenInstanceError):
        inventory.__setattr__("owner_uid", 0)
    with pytest.raises(FrozenInstanceError):
        inventory.entries[0].__setattr__("relative_member", "changed")
    assert isinstance(inventory.entries, tuple) and isinstance(inventory.root_epoch, tuple)

    def deny(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("metadata-only inventory must not read bytes or rescan")

    for module, name in (
        (os, "walk"),
        (os, "open"),
        (os, "read"),
        (os, "pread"),
        (hashlib, "sha256"),
    ):
        monkeypatch.setattr(module, name, deny)
    inventory.assert_unchanged()


@pytest.mark.parametrize(
    "fault", ["missing", "added", "same_bytes_replaced", "mode", "directory", "link", "ancestor"]
)
def test_retained_inventory_denies_missing_added_replaced_link_or_metadata_drift(
    tmp_path: Path, fault: str
) -> None:
    inventory = _local_inventory(tmp_path)
    target = inventory.prefix / "bin/a"
    if fault == "missing":
        target.unlink()
    elif fault == "added":
        _put(inventory.prefix / "bin/extra", b"unregistered")
        # Namespace timestamps can share a filesystem tick; this tests a real changed epoch,
        # not an unsupported continuous-directory-membership claim from metadata alone.
        directory_epoch = inventory.entries[0].epoch
        os.utime(target.parent, ns=(directory_epoch[7] + 1, directory_epoch[7] + 1))
    elif fault == "same_bytes_replaced":
        replacement = inventory.prefix / "bin/replacement"
        _put(replacement, target.read_bytes())
        replacement.replace(target)
    elif fault == "mode":
        target.chmod(0o640)
    elif fault == "directory":
        target.parent.chmod(0o750)
    elif fault == "link":
        link = target.parent / "alias"
        link.unlink()
        link.symlink_to("different")
    else:
        tmp_path.chmod(0o750)
    with pytest.raises(InstalledRuntimeProofError, match="INVENTORY_CHANGED"):
        inventory.assert_unchanged()


@pytest.mark.parametrize(
    "fault",
    [
        "root_bool",
        "owner_bool",
        "nested_bool",
        "path",
        "hash",
        "link",
        "order",
        "duplicate",
        "empty",
        "missing_directory",
        "ancestor",
        "list",
        "count",
        "bytes",
    ],
)
def test_forged_or_changed_inventory_values_revalidate_before_metadata_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    inventory = _local_inventory(tmp_path)
    forged = replace(inventory)
    if fault == "root_bool":
        object.__setattr__(forged, "root_epoch", (True, *inventory.root_epoch[1:]))
    elif fault == "owner_bool":
        object.__setattr__(forged, "owner_uid", True)
    elif fault in {"nested_bool", "path", "hash", "link"}:
        index = 1 if fault != "link" else 2
        entry = replace(inventory.entries[index])
        field, value = (
            ("epoch", (True, *entry.epoch[1:]))
            if fault == "nested_bool"
            else ("relative_member", "../outside")
            if fault == "path"
            else ("sha256", _hash(b"x") + "\n")
            if fault == "hash"
            else ("symlink_target", None)
        )
        object.__setattr__(entry, field, value)
        object.__setattr__(
            forged, "entries", (*inventory.entries[:index], entry, *inventory.entries[index + 1 :])
        )
    elif fault == "order":
        object.__setattr__(forged, "entries", tuple(reversed(inventory.entries)))
    elif fault == "duplicate":
        object.__setattr__(forged, "entries", (*inventory.entries, inventory.entries[-1]))
    elif fault == "empty":
        object.__setattr__(forged, "entries", ())
    elif fault == "missing_directory":
        object.__setattr__(forged, "entries", inventory.entries[1:])
    elif fault == "ancestor":
        object.__setattr__(forged, "ancestor_epochs", inventory.ancestor_epochs[:-1])
    elif fault == "list":
        object.__setattr__(forged, "entries", list(inventory.entries))
    elif fault == "count":
        monkeypatch.setattr(prefix, "_MAX_MEMBERS", len(inventory.entries) - 1)
    else:
        monkeypatch.setattr(prefix, "_MAX_BYTES", 1)

    def deny(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("malformed local values deny before metadata IO")

    monkeypatch.setattr(Path, "lstat", deny)
    with pytest.raises(InstalledRuntimeProofError, match=r"INVENTORY|PATH_INVALID"):
        forged.assert_unchanged()


def test_same_audit_export_uses_existing_tree_epochs_hashes_and_no_additional_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, staged, owned, helper, locks = _fixture(tmp_path, monkeypatch)
    actual_tree = prefix._tree
    actual_inventory = prefix.PrefixRuntimeInventory
    observed: list[dict[Path, tuple[int, ...]]] = []

    def tree(
        root: Path, expected: set[Path], links: dict[Path, str], owner_uid: int
    ) -> tuple[dict[Path, tuple[int, ...]], int, int]:
        result = actual_tree(root, expected, links, owner_uid)
        observed.append(result[0])
        return result

    def deny(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("export must reuse current metadata and verified hashes")

    def export(*args: Any, **kwargs: Any) -> prefix.PrefixRuntimeInventory:
        with monkeypatch.context() as blocked:
            for module, name in (
                (os, "open"),
                (os, "walk"),
                (os, "pread"),
                (hashlib, "sha256"),
                (prefix, "_tree"),
                (Path, "lstat"),
            ):
                blocked.setattr(module, name, deny)
            return actual_inventory(*args, **kwargs)

    monkeypatch.setattr(prefix, "_tree", tree)
    monkeypatch.setattr(prefix, "PrefixRuntimeInventory", export)
    with owned:
        audit = _audit(plan, staged, owned, helper, locks)
    assert len(observed) == 1 and audit.inventory.root_epoch is observed[0][staged.prefix]


def test_additive_inventory_preserves_existing_bounded_cli_receipt_literal() -> None:
    leaf = Path(__file__).resolve().parents[2] / "scripts/embedding/admit_index_runtime.py"
    assert (
        b'print("EMBEDDING_PREFIX_BYTES_AUDIT_PASS_NOT_ADMITTED", audit.byte_closure_sha256)'
        in leaf.read_bytes()
    )
    receipt = b"EMBEDDING_PREFIX_BYTES_AUDIT_PASS_NOT_ADMITTED " + _hash(b"x").encode() + b"\n"
    assert len(receipt) <= 128 and b"inventory" not in receipt and b"{" not in receipt


@pytest.mark.parametrize("fault", ["added", "removed", "directory", "link", "host"])
def test_terminal_audit_drift_returns_no_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    plan, staged, owned, helper, locks = _fixture(tmp_path, monkeypatch)
    actual_elf = prefix._elf_closure

    def late(*args: Any, **kwargs: Any) -> tuple[str, int]:
        result = actual_elf(*args, **kwargs)
        target = staged.prefix / "lib/python3.12/site-packages/eom_catalog_service/native.py"
        if fault == "added":
            _put(target.parent / "unexpected.py", b"unregistered")
        elif fault == "removed":
            target.unlink()
        elif fault == "directory":
            target.parent.chmod(0o750)
        elif fault == "link":
            path = next(path for path in staged.prefix.rglob("*") if path.is_symlink())
            path.unlink()
            path.symlink_to("unexpected")
        else:

            def changed(_self: object) -> NoReturn:
                raise InstalledRuntimeProofError("INSTALLED_RUNTIME_HOST_FILE_CHANGED")

            monkeypatch.setattr(host.ProtectedEmbeddingHostClosure, "assert_current", changed)
        return result

    monkeypatch.setattr(prefix, "_elf_closure", late)
    with pytest.raises(InstalledRuntimeProofError), owned:
        _audit(plan, staged, owned, helper, locks)


@pytest.mark.parametrize(
    "fault",
    [
        "extra",
        "extra_empty_directory",
        "hidden_pyc",
        "source_module",
        "source_resource",
        "metadata",
        "helper",
        "lock",
        "writable",
        "hardlink",
    ],
)
def test_whole_prefix_fails_closed_without_new_marker_or_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    plan, staged, owned, helper, locks = _fixture(tmp_path, monkeypatch)
    site = staged.prefix / "lib/python3.12/site-packages"
    if fault in {"extra", "hidden_pyc"}:
        _put(
            site
            / (
                "unknown.py"
                if fault == "extra"
                else "eom_catalog_service/__pycache__/native.cpython-312.pyc"
            ),
            b"unowned",
        )
    elif fault == "extra_empty_directory":
        (site / "unowned").mkdir()
    elif fault in {"source_module", "source_resource"}:
        (
            site
            / "eom_catalog_service"
            / ("native.py" if fault == "source_module" else "resources/config.json")
        ).write_bytes(b"changed")
    elif fault == "metadata":
        (staged.prefix / "conda-meta/history").write_bytes(b"changed")
    elif fault == "helper":
        helper.write_bytes(b"raise RuntimeError('untrusted body')")
    elif fault == "lock":
        next(locks.iterdir()).write_bytes(b"changed")
    elif fault == "writable":
        (site / "eom_catalog_service/native.py").chmod(0o666)
    else:
        os.link(site / "eom_catalog_service/native.py", tmp_path / "other")
    with owned, pytest.raises(InstalledRuntimeProofError):
        _audit(plan, staged, owned, helper, locks)
    assert not (tmp_path / "NEW_EXECUTED").exists()


@pytest.mark.parametrize("wrapped", [True, False])
def test_fixed_git_tar_commit_layout_and_all_private_resource_mapping(
    tmp_path: Path, wrapped: bool
) -> None:
    commit = "a" * 40
    members = {
        "pyproject.toml": _project(),
        "services/catalog_service/eom_catalog_service/__init__.py": b"",
        "services/catalog_service/eom_catalog_service/resources/config.json": b"{}",
    }
    raw = _tar(members, commit, wrapped=wrapped)
    path = tmp_path / "source.tar"
    _put(path, raw)
    fd = os.open(path, os.O_RDONLY)
    try:
        source = prefix._git_source(fd, len(raw), commit)
        assert prefix._source_payload(source, "eom-platform") == {
            name.removeprefix("services/catalog_service/"): (_hash(value), len(value))
            for name, value in members.items()
            if name.startswith("services/")
        }
        with pytest.raises(InstalledRuntimeProofError, match="SOURCE_COMMIT"):
            prefix._git_source(fd, len(raw), "b" * 40)
    finally:
        os.close(fd)


@pytest.mark.parametrize("fault", [None, "missing", "changed", "extra"])
def test_literal_json_resource_is_source_exact_and_part_of_whole_prefix_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    plan, staged, owned, helper, locks = _fixture(tmp_path, monkeypatch, literal_resource=True)
    root = staged.prefix / "lib/python3.12/site-packages/eom_operator_identity/resources"
    literal = root / "operator-owner-session-capture-v1.schema.json"
    if fault == "missing":
        literal.unlink()
    elif fault == "changed":
        literal.write_bytes(b'{"wrong_schema":true}\n')
    elif fault == "extra":
        _put(root / "unselected.schema.json", b"{}\n")
    with owned:
        if fault is None:
            result = _audit(plan, staged, owned, helper, locks)
            assert result.regular_members > 0 and literal.exists()
        else:
            with pytest.raises(InstalledRuntimeProofError):
                _audit(plan, staged, owned, helper, locks)
    assert not (tmp_path / "NEW_EXECUTED").exists()


@pytest.mark.parametrize(
    "selector",
    [
        "/resources/name.json",
        "resources/../name.json",
        "../resources/name.json",
        "resources\\name.json",
        "resources/**.json",
        "resources/**/*.json",
        "resources/name?.json",
        "resources/[a].json",
        "resources//name.json",
        "resources/./name.json",
        "resources/name.txt",
    ],
)
def test_literal_resource_never_expands_general_globs_or_unsafe_paths(selector: str) -> None:
    project = _project() + ("eom_operator_identity=[" + json.dumps(selector) + "]\n").encode()
    source = prefix._Source(
        {"services/catalog_service/eom_catalog_service/__init__.py": (_hash(b""), 0)},
        {"pyproject.toml": project},
    )
    with pytest.raises(InstalledRuntimeProofError, match="SOURCE_PROJECT_INVALID"):
        prefix._source_payload(source, "eom-platform")


def test_missing_declared_literal_original_source_is_not_silently_omitted() -> None:
    project = (
        _project()
        + b"eom_operator_identity=['resources/operator-owner-session-capture-v1.schema.json']\n"
    )
    source = prefix._Source(
        {"services/catalog_service/eom_catalog_service/__init__.py": (_hash(b""), 0)},
        {"pyproject.toml": project},
    )
    with pytest.raises(InstalledRuntimeProofError, match="SOURCE_LITERAL_RESOURCE_MISSING"):
        prefix._source_payload(source, "eom-platform")


def _input(plan: prefix.PrefixRuntimeAuditPlan) -> dict[str, Any]:
    def archive(pin: RuntimeWheelArchivePin) -> dict[str, Any]:
        return {"filename": pin.wheel_filename, "sha256": pin.sha256, "size_bytes": pin.size_bytes}

    def member(pin: Any) -> dict[str, Any]:
        return {"sha256": pin.sha256, "size_bytes": pin.size_bytes}

    return {
        "schema_version": "embedding-prefix-audit-input/1.0",
        "profile": plan.conda.profile,
        "host_seed_sha256": _hash(b"synthetic"),
        "conda_source": {
            "sha256": plan.conda.source_list_sha256,
            "size_bytes": plan.conda.source_list_size_bytes,
        },
        "conda_archives": [
            {"filename": pin.filename, "sha256": pin.sha256, "size_bytes": pin.size_bytes}
            for pin in plan.conda.archives
        ],
        "public_archives": [archive(pin) for pin in plan.public_archives],
        "private_archives": [
            {
                "name": pin.name,
                "archive": archive(pin.archive),
                "source_commit": pin.source_commit,
                "source_archive": member(pin.source_archive),
            }
            for pin in plan.private_archives
        ],
        "created_at": member(plan.created_at),
        "history": member(plan.history),
        "helper": member(plan.helper),
        "bootstrap": [
            {"filename": name, "sha256": _hash(b"x"), "size_bytes": 1}
            for name in sorted(prefix._BOOTSTRAP)
        ],
    }


@pytest.mark.parametrize(
    "fault",
    [
        "unknown",
        "duplicate",
        "float",
        "bool",
        "source_bool",
        "commit",
        "bootstrap",
        "count",
        "too_large",
    ],
)
def test_owner_input_is_closed_bounded_integer_only_and_never_a_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    plan, _staged, owned, _helper, _locks = _fixture(tmp_path, monkeypatch)
    with owned:
        value = _input(plan)
        if fault == "unknown":
            value["approved"] = True
        elif fault == "float":
            value["history"]["size_bytes"] = 1.0
        elif fault == "bool":
            value["history"]["size_bytes"] = True
        elif fault == "source_bool":
            value["private_archives"][0]["source_archive"]["size_bytes"] = True
        elif fault == "commit":
            value["private_archives"][0]["source_commit"] = "latest"
        elif fault == "bootstrap":
            value["bootstrap"][0]["filename"] = "untrusted.py"
        elif fault == "count":
            value["public_archives"].append(value["public_archives"][0])
        raw = json.dumps(value).encode()
        if fault == "duplicate":
            raw = raw[:-1] + b',"profile":"CPU_INDEX_FP32"}'
        elif fault == "too_large":
            raw += b" " * (128 * 1024)
        with pytest.raises(InstalledRuntimeProofError):
            prefix.parse_embedding_prefix_audit_input(raw)


def test_owner_input_roundtrips_exact_source_plan_not_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _staged, owned, _helper, _locks = _fixture(tmp_path, monkeypatch)
    with owned:
        actual, host_sha, bootstrap = prefix.parse_embedding_prefix_audit_input(
            json.dumps(_input(plan)).encode()
        )
        assert actual == plan and host_sha == _hash(b"synthetic") and len(bootstrap) == 6


def test_constructed_nested_source_size_bool_denies_before_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, staged, owned, helper, locks = _fixture(tmp_path, monkeypatch)
    broken = prefix.PrefixSourceArchivePin(_hash(b"x"), 1)
    object.__setattr__(broken, "size_bytes", True)
    private = replace(plan.private_archives[0])
    object.__setattr__(private, "source_archive", broken)
    forged = replace(plan)
    object.__setattr__(forged, "private_archives", (private,))

    def deny(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("no IO")

    with owned:
        monkeypatch.setattr(os, "open", deny)
        with pytest.raises(InstalledRuntimeProofError):
            _audit(forged, staged, owned, helper, locks)


def _elf_text(
    *,
    needed: tuple[str, ...] = (),
    soname: str | None = None,
    rpath: str | None = None,
    runpath: str | None = None,
    definition: str | None = None,
    required: tuple[str, str] | None = None,
) -> bytes:
    text = (
        "ELF Header:\n  Class: ELF64\n  Data: 2's complement, little endian\n"
        "  Machine: Advanced Micro Devices X86-64\n"
    )
    for name in needed:
        text += f" 0x1 (NEEDED) Shared library: [{name}]\n"
    if soname:
        text += f" 0xe (SONAME) Library soname: [{soname}]\n"
    if rpath is not None:
        text += f" 0xf (RPATH) Library rpath: [{rpath}]\n"
    if runpath is not None:
        text += f" 0x1d (RUNPATH) Library runpath: [{runpath}]\n"
    if definition:
        text += (
            "Version definition section '.gnu.version_d' contains 1 entry:\n"
            f" 0x1 Rev: 1 Flags: none Index: 2 Cnt: 1 Name: {definition}\n"
        )
    if required:
        text += (
            "Version needs section '.gnu.version_r' contains 1 entry:\n"
            f" 0x1 Version: 1 File: {required[0]} Cnt: 1\n"
            f" 0x2 Name: {required[1]} Flags: none Version: 2\n"
        )
    return text.encode()


@pytest.mark.parametrize(
    "fault", ["machine", "class", "endian", "needed_path", "loader", "audit", "too_large"]
)
def test_prefix_readelf_bounded_fixed_native_metadata_denies_foreign_and_injected_routes(
    fault: str,
) -> None:
    raw = _elf_text(needed=("libc.so.6",), required=("libc.so.6", "GLIBC_2.38"))
    if fault == "machine":
        raw = raw.replace(b"Advanced Micro Devices X86-64", b"AArch64")
    elif fault == "class":
        raw = raw.replace(b"ELF64", b"ELF32")
    elif fault == "endian":
        raw = raw.replace(b"little endian", b"big endian")
    elif fault == "needed_path":
        raw = raw.replace(b"[libc.so.6]", b"[/tmp/libc.so.6]")
    elif fault == "loader":
        raw += b" [Requesting program interpreter: /tmp/loader]\n"
    elif fault == "audit":
        raw += b" 0x1 (AUDIT) untrusted\n"
    else:
        raw += b"x" * (1024**2)
    with pytest.raises(InstalledRuntimeProofError):
        prefix._readelf(Path("/prefix/lib/a.so"), raw)


def test_prefix_readelf_retains_complete_version_and_separate_search_recipe() -> None:
    parsed = prefix._readelf(
        Path("/prefix/lib/a.so"),
        _elf_text(
            needed=("libc.so.6",),
            soname="a.so",
            rpath="$ORIGIN/..",
            runpath="$ORIGIN",
            definition="EXAMPLE_1",
            required=("libc.so.6", "GLIBC_2.38"),
        ),
    )
    assert parsed.needed == ("libc.so.6",) and parsed.rpath == ("$ORIGIN/..",)
    assert parsed.runpath == ("$ORIGIN",) and parsed.definitions == frozenset({"EXAMPLE_1"})
    assert parsed.requirements == (("libc.so.6", frozenset({"GLIBC_2.38"})),)


@pytest.mark.parametrize(
    "fault",
    ["needed_format", "soname", "flags", "flags_1", "definition_count", "need_count", "file_count"],
)
def test_prefix_readelf_never_drops_loader_flags_or_declared_version_entries(fault: str) -> None:
    raw = _elf_text(
        needed=("libc.so.6",), definition="EXAMPLE_1", required=("libc.so.6", "GLIBC_2.38")
    )
    if fault == "needed_format":
        raw = raw.replace(b"Shared library: [libc.so.6]", b"unparsed library")
    elif fault == "soname":
        raw += b" 0xe (SONAME) Library soname: [/tmp/injected.so]\n"
    elif fault == "flags":
        raw += b" 0x1e (FLAGS) Flags: TEXTREL\n"
    elif fault == "flags_1":
        raw += b" 0x6ffffffb (FLAGS_1) Flags: NODEFLIB\n"
    elif fault == "definition_count":
        raw = raw.replace(
            b"definition section '.gnu.version_d' contains 1",
            b"definition section '.gnu.version_d' contains 2",
        )
    elif fault == "need_count":
        raw = raw.replace(
            b"needs section '.gnu.version_r' contains 1",
            b"needs section '.gnu.version_r' contains 2",
        )
    else:
        raw = raw.replace(b"File: libc.so.6 Cnt: 1", b"File: libc.so.6 Cnt: 2")
    with pytest.raises(InstalledRuntimeProofError):
        prefix._readelf(Path("/prefix/lib/a.so"), raw)


def _graph(
    tmp_path: Path,
    metadata: dict[str, bytes],
    *,
    links: dict[str, str] | None = None,
    host_versions: dict[str, frozenset[str]] | None = None,
) -> tuple[str, int]:
    """Synthetic metadata fence only; no readelf, root, GPU or loader execution."""
    installed = tmp_path / "prefix"
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    inventory: set[Path] = set()
    for relative in metadata:
        path = installed / relative
        _put(path, b"\x7fELF" + relative.encode())
        inventory.add(path)
    for directory in [tmp_path, *tmp_path.rglob("*")]:
        if directory.is_dir():
            directory.chmod(0o700)
    for path in inventory:
        raw = path.read_bytes()
        files.verify(path, sha256=_hash(raw), size=len(raw), maximum=1024)
    link_values = {installed / path: target for path, target in (links or {}).items()}
    inventory.update(link_values)
    versions = {} if host_versions is None else host_versions

    def inspect(descriptor: int, *, deadline: float) -> bytes:
        assert deadline > time.monotonic()
        path = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
        return metadata[str(path.relative_to(installed))]

    def version(name: str) -> frozenset[str]:
        if name not in versions:
            raise InstalledRuntimeProofError("INSTALLED_RUNTIME_HOST_SONAME_UNAVAILABLE")
        return versions[name]

    captured = cast(
        host.ProtectedEmbeddingHostClosure,
        SimpleNamespace(
            inspect_elf=inspect,
            fixed_soname_versions=version,
            fixed_loader_path=lambda: Path("/synthetic/fixed/loader"),
        ),
    )
    return prefix._elf_closure(
        installed, inventory, link_values, files, captured, time.monotonic() + 10
    )


def test_elf_search_uses_first_origin_candidate_not_union_or_prefix_lib_default(
    tmp_path: Path,
) -> None:
    metadata = {
        "bin/python3.12": _elf_text(
            needed=("a.so",), rpath="$ORIGIN/../first:$ORIGIN/../second", required=("a.so", "V1")
        ),
        "first/a.so": _elf_text(soname="a.so", definition="V1"),
        "second/a.so": _elf_text(soname="a.so", definition="V2"),
    }
    assert _graph(tmp_path / "ordered", metadata)[1] == 3
    metadata["first/a.so"] = _elf_text(soname="a.so", definition="V2")
    with pytest.raises(InstalledRuntimeProofError, match="ELF_VERSION_UNAVAILABLE"):
        _graph(tmp_path / "wrong_first", metadata)
    with pytest.raises(InstalledRuntimeProofError, match="HOST_SONAME_UNAVAILABLE"):
        _graph(
            tmp_path / "no_default",
            {"bin/python3.12": _elf_text(needed=("a.so",)), "lib/a.so": _elf_text(soname="a.so")},
        )


def test_elf_rpath_is_transitive_but_runpath_is_direct_only(tmp_path: Path) -> None:
    metadata = {
        "bin/python3.12": _elf_text(needed=("a.so",), rpath="$ORIGIN/../lib"),
        "lib/a.so": _elf_text(soname="a.so", needed=("b.so",)),
        "lib/b.so": _elf_text(soname="b.so"),
    }
    assert _graph(tmp_path / "transitive", metadata)[1] == 3
    metadata["bin/python3.12"] = _elf_text(needed=("a.so",), runpath="$ORIGIN/../lib")
    with pytest.raises(InstalledRuntimeProofError, match="HOST_SONAME_UNAVAILABLE"):
        _graph(tmp_path / "direct_only", metadata)
    metadata["lib/a.so"] = _elf_text(soname="a.so", needed=("b.so",), runpath="$ORIGIN")
    assert _graph(tmp_path / "explicit_child", metadata)[1] == 3


@pytest.mark.parametrize("fault", ["cycle", "escape", "soname", "version", "host_version"])
def test_elf_alias_and_version_resolution_fails_closed(tmp_path: Path, fault: str) -> None:
    metadata = {
        "bin/python3.12": _elf_text(
            needed=("a.so",), rpath="$ORIGIN/../alias", required=("a.so", "V1")
        ),
        "lib/a.so": _elf_text(soname="a.so", definition="V1"),
    }
    links = {"alias": "lib"}
    if fault == "cycle":
        links = {"alias": "again", "again": "alias"}
    elif fault == "escape":
        links = {"alias": "../../outside"}
    elif fault == "soname":
        metadata["lib/a.so"] = _elf_text(soname="different.so", definition="V1")
    elif fault == "version":
        metadata["lib/a.so"] = _elf_text(soname="a.so", definition="V2")
    else:
        metadata["bin/python3.12"] = _elf_text(needed=("libc.so.6",), required=("libc.so.6", "NEW"))
    with pytest.raises(InstalledRuntimeProofError):
        _graph(
            tmp_path / fault, metadata, links=links, host_versions={"libc.so.6": frozenset({"OLD"})}
        )


def test_elf_resolves_source_known_directory_alias(tmp_path: Path) -> None:
    assert (
        _graph(
            tmp_path,
            {
                "bin/python3.12": _elf_text(needed=("a.so",), rpath="$ORIGIN/../alias"),
                "lib/a.so": _elf_text(soname="a.so"),
            },
            links={"alias": "lib"},
        )[1]
        == 2
    )


@pytest.mark.parametrize(
    "route", ["", ".", "/tmp/lib", "$ORIGIN/../../outside", "$LIB", "$PLATFORM", "$ORIGIN/$LIB"]
)
def test_exact_inside_prefix_origin_routes_never_accept_developer_or_shell_paths(
    route: str,
) -> None:
    parsed = prefix._readelf(Path("/prefix/lib/a.so"), _elf_text(rpath=route))
    with pytest.raises(InstalledRuntimeProofError):
        prefix._routes(parsed, Path("/prefix"), {Path("/prefix"), Path("/prefix/lib")})


def test_source_archive_bound_preserves_member_bound_and_rejects_bool() -> None:
    assert prefix.PrefixSourceArchivePin(_hash(b"x"), 54272000).size_bytes == 54272000
    with pytest.raises(InstalledRuntimeProofError):
        prefix.PrefixSourceArchivePin(_hash(b"x"), True)
    with pytest.raises(InstalledRuntimeProofError):
        RuntimeWheelMemberPin(_hash(b"x"), 54272000)


@pytest.mark.parametrize("mode", ["prefix-bytes", "conda31-bytes"])
def test_cli_is_owner_only_and_cannot_execute_successor(
    mode: str, capsys: pytest.CaptureFixture[str]
) -> None:
    leaf = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/embedding/admit_index_runtime.py")
    )
    result = leaf["main"](
        [
            mode,
            "--profile",
            "CPU_INDEX_FP32",
            "--owner-input",
            "/opt/eom/.embedding-index-install-Abcd1234/prefix-audit-input.json",
            "--owner-input-sha256",
            _hash(b"x"),
        ]
    )
    assert result == 1 and "OWNER_UNAVAILABLE" in capsys.readouterr().err


@pytest.mark.parametrize(
    "fault", ["extra", "duplicate", "float", "bootstrap_bool", "bootstrap_name", "raw_pin", "epoch"]
)
def test_owner_leaf_denies_before_source_import_or_new_instruction(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    leaf = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/embedding/admit_index_runtime.py")
    )
    function = leaf["main"]
    namespace = function.__globals__
    owner_path = Path("/opt/eom/.embedding-index-install-Abcd1234/prefix-audit-input.json")
    value: dict[str, Any] = {
        name: None
        for name in (
            "schema_version",
            "profile",
            "host_seed_sha256",
            "conda_source",
            "conda_archives",
            "public_archives",
            "private_archives",
            "created_at",
            "history",
            "helper",
            "bootstrap",
        )
    }
    value["bootstrap"] = [
        {"filename": name, "sha256": _hash(b""), "size_bytes": 0}
        for name in sorted(namespace["_BOOTSTRAP"])
    ]
    if fault == "extra":
        value["approved"] = True
    elif fault == "bootstrap_bool":
        value["bootstrap"][0]["size_bytes"] = False
    elif fault == "bootstrap_name":
        value["bootstrap"][0]["filename"] = "unapproved.py"
    raw = json.dumps(value).encode()
    if fault == "duplicate":
        raw = raw[:-1] + b',"bootstrap":[]}'
    elif fault == "float":
        raw = raw.replace(b'"profile": null', b'"profile": 1.0')
    stdout, stderr = io.StringIO(), io.StringIO()
    mocked_sys = SimpleNamespace(
        prefix="/opt/eom/conda/envs/eom-embedding-experiment",
        version_info=(3, 12, 13),
        flags=SimpleNamespace(isolated=True, no_site=True),
        dont_write_bytecode=True,
        modules={},
        path=["UNCHANGED"],
        stdout=stdout,
        stderr=stderr,
    )
    calls: list[Path] = []

    def root_bytes(
        path: Path, _sha: str, _maximum: int
    ) -> tuple[bytes, dict[Path, tuple[int, ...]]]:
        calls.append(path)
        if path == owner_path:
            return raw, {}
        if fault == "raw_pin":
            raise ValueError("synthetic independently supplied raw pin mismatch")
        return b"", {}

    def current(_epochs: object) -> NoReturn:
        raise ValueError("synthetic owner snapshot epoch drift")

    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setitem(namespace, "sys", mocked_sys)
    monkeypatch.setitem(namespace, "__file__", str(owner_path.parent / "admit.py"))
    monkeypatch.setitem(namespace, "_root_bytes", root_bytes)
    monkeypatch.setitem(namespace, "_current", current)
    assert (
        function(
            [
                "prefix-bytes",
                "--profile",
                "CPU_INDEX_FP32",
                "--owner-input",
                str(owner_path),
                "--owner-input-sha256",
                _hash(raw),
            ]
        )
        == 1
    )
    assert "AUDIT_INVALID" in stderr.getvalue() and stdout.getvalue() == ""
    assert mocked_sys.path == ["UNCHANGED"] and mocked_sys.modules == {}
    assert len(calls) == (2 if fault == "raw_pin" else 7 if fault == "epoch" else 1)


def test_actual_prefix_module_import_is_stdlib_only_no_site() -> None:
    root = Path(prefix.__file__).parent.parent
    code = """
import sys
assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
sys.path.insert(0,sys.argv[1])
import eom_catalog_service.embedding_runtime_prefix_closure
for forbidden in ('pydantic','jsonschema','eom_catalog_contracts','eom_identifiers',
                  'torch','transformers','numpy'):
 assert not any(n==forbidden or n.startswith(forbidden+'.') for n in sys.modules)
print('STDLIB_PREFIX_IMPORT_PASS')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", code, str(root)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "STDLIB_PREFIX_IMPORT_PASS"
