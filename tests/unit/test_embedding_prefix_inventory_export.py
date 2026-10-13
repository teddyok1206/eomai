"""Candidate metadata/export tests only; no actual root or native execution admission."""

from __future__ import annotations

import os
import runpy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.embedding_native_installation_evidence import (
    parse_rootlocal_prefix_inventory_candidate,
    rootlocal_prefix_inventory_candidate_bytes,
)
from eom_catalog_service.embedding_runtime_prefix_closure import (
    PrefixRuntimeByteAudit,
    PrefixRuntimeInventory,
    PrefixRuntimeInventoryEntry,
)
from eom_identifiers import canonical_json_bytes

from tests.unit.test_embedding_native_installation_evidence import INVENTORY_DRAFT, inventory_body

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def leaf() -> dict[str, Any]:
    return runpy.run_path(str(ROOT / "scripts/embedding/admit_index_runtime.py"))[
        "_inventory_candidate_bytes"
    ].__globals__


def synthetic_audit() -> PrefixRuntimeByteAudit:
    """Declared metadata values, not a mocked successful protected audit."""
    value = inventory_body()
    prefix = Path("/opt/eom/conda/envs/eom-embedding-index-cpu")
    inventory = PrefixRuntimeInventory(
        prefix,
        0,
        tuple(value["prefix_root_epoch"]),
        tuple(
            zip(reversed(prefix.parents), map(tuple, value["fixed_ancestor_epochs"]), strict=True)
        ),
        tuple(
            PrefixRuntimeInventoryEntry(
                entry["relative_member"],
                tuple(entry["epoch"]),
                entry["sha256"],
                entry["symlink_target"],
            )
            for entry in value["entries"]
        ),
    )
    return PrefixRuntimeByteAudit(profile="CPU_INDEX_FP32", inventory=inventory, **value["audit"])


def serialize(leaf: dict[str, Any], audit: PrefixRuntimeByteAudit) -> bytes:
    value = inventory_body()
    return leaf["_inventory_candidate_bytes"](
        audit,
        owner_input_raw_sha256=value["owner_input_raw_sha256"],
        host_seed_sha256=value["host_seed_sha256"],
        boot_id=value["boot_id"],
    )


def test_export_matches_existing_schema_pydantic_and_canonical_bytes(
    leaf: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    audit = synthetic_audit()
    with monkeypatch.context() as blocked:
        blocked.setattr(Path, "lstat", lambda *_: pytest.fail("serializer must not rescan files"))
        raw = serialize(leaf, audit)
    assert raw == canonical_json_bytes(inventory_body())
    parsed = parse_rootlocal_prefix_inventory_candidate(
        raw, schema_raw=INVENTORY_DRAFT.read_bytes()
    )
    assert parsed.evidence_state == "CANDIDATE_NOT_ADMITTED"
    assert rootlocal_prefix_inventory_candidate_bytes(parsed) == raw
    assert serialize(leaf, audit) == raw


@pytest.mark.parametrize(
    "field,value",
    [
        ("regular_members", True),
        ("regular_members", 2),
        ("link_members", 0),
        ("size_bytes", 2),
        ("elf_members", 0),
        ("elf_members", 2),
        ("source_closure_sha256", "sha256:wrong"),
        ("profile", "UNKNOWN"),
    ],
)
def test_invalid_audit_metadata_cannot_be_exported(
    leaf: dict[str, Any], field: str, value: object
) -> None:
    with pytest.raises(ValueError):
        serialize(leaf, replace(synthetic_audit(), **{field: value}))


def test_export_is_bounded_including_added_semantic_hash(
    leaf: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    audit = synthetic_audit()
    raw = serialize(leaf, audit)
    monkeypatch.setitem(leaf, "_INVENTORY_MAX_BYTES", len(raw))
    assert serialize(leaf, audit) == raw
    monkeypatch.setitem(leaf, "_INVENTORY_MAX_BYTES", len(raw) - 1)
    with pytest.raises(ValueError, match="bound"):
        serialize(leaf, audit)


@pytest.fixture
def evidence_fd(leaf: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    path = tmp_path / "prefix-inventory.candidate.json"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    monkeypatch.setitem(leaf, "_INVENTORY_DESCRIPTOR", descriptor)
    # Synthetic owner substitution; main()'s actual root/interpreter guard remains unchanged.
    monkeypatch.setitem(leaf, "_INVENTORY_OWNER_UID", os.geteuid())
    try:
        yield path, descriptor
    finally:
        os.close(descriptor)


def test_candidate_fd_is_write_once_exact_readback_and_not_a_final_receipt(
    leaf: dict[str, Any], evidence_fd: tuple[Path, int]
) -> None:
    path, _ = evidence_fd
    found, identity = leaf["_inventory_descriptor"](path.parent)
    raw = serialize(leaf, synthetic_audit())
    leaf["_write_inventory_candidate"](raw, found, identity)
    assert path.read_bytes() == raw and path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        leaf["_write_inventory_candidate"](raw, found, identity)
    assert path.read_bytes() == raw


@pytest.mark.parametrize("fault", ["offset", "nonempty", "mode", "alias", "replaced", "hardlink"])
def test_changed_or_reused_candidate_fd_is_denied_before_writing(
    leaf: dict[str, Any], evidence_fd: tuple[Path, int], fault: str
) -> None:
    path, descriptor = evidence_fd
    found, identity = leaf["_inventory_descriptor"](path.parent)
    if fault == "offset":
        os.lseek(descriptor, 1, os.SEEK_SET)
    elif fault == "nonempty":
        os.write(descriptor, b"retained partial failure")
    elif fault == "mode":
        path.chmod(0o644)
    elif fault in {"alias", "replaced"}:
        retained = path.with_suffix(".retained")
        path.rename(retained)
        if fault == "alias":
            path.symlink_to(retained)
        else:
            path.write_bytes(b"other output")
    else:
        os.link(path, path.with_suffix(".second"))
    initial = os.pread(descriptor, 1024, 0)
    with pytest.raises(ValueError):
        leaf["_write_inventory_candidate"](b"new candidate", found, identity)
    assert os.pread(descriptor, 1024, 0) == initial


def test_short_writes_are_completed(
    leaf: dict[str, Any], evidence_fd: tuple[Path, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _ = evidence_fd
    _, identity = leaf["_inventory_descriptor"](path.parent)
    actual = os.write
    with monkeypatch.context() as patched:
        patched.setattr(os, "write", lambda fd, raw: actual(fd, raw[:3]))
        leaf["_write_inventory_candidate"](b"abcdefg", path, identity)
    assert path.read_bytes() == b"abcdefg"


def test_zero_write_preserves_partial_failure(
    leaf: dict[str, Any], evidence_fd: tuple[Path, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    path, descriptor = evidence_fd
    _, identity = leaf["_inventory_descriptor"](path.parent)
    actual = os.write
    calls = 0

    def partial(fd: int, raw: bytes) -> int:
        nonlocal calls
        calls += 1
        return actual(fd, raw[:3]) if calls == 1 else 0

    with monkeypatch.context() as patched:
        patched.setattr(os, "write", partial)
        with pytest.raises(ValueError, match="write failed"):
            leaf["_write_inventory_candidate"](b"abcdef", path, identity)
    assert os.pread(descriptor, 1024, 0) == b"abc"


@pytest.mark.parametrize("fault", ["readback", "file_sync", "directory_sync"])
def test_failed_durability_or_readback_preserves_candidate_without_success(
    leaf: dict[str, Any], evidence_fd: tuple[Path, int], monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    path, descriptor = evidence_fd
    _, identity = leaf["_inventory_descriptor"](path.parent)
    actual_sync = os.fsync

    def sync(fd: int) -> None:
        if (fd == descriptor) == (fault == "file_sync"):
            raise OSError("synthetic synchronization failure")
        actual_sync(fd)

    with monkeypatch.context() as patched:
        if fault == "readback":
            patched.setattr(os, "pread", lambda *_: b"corrupt")
        else:
            patched.setattr(os, "fsync", sync)
        with pytest.raises((ValueError, OSError)):
            leaf["_write_inventory_candidate"](b"abcdefg", path, identity)
    assert path.read_bytes() == b"abcdefg"
    with pytest.raises(ValueError):
        leaf["_write_inventory_candidate"](b"abcdefg", path, identity)
