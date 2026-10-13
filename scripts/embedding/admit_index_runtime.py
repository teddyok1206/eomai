"""Closed read-only protected-owner prefix audit; never execute NEW or grant admission."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from eom_catalog_service.embedding_runtime_prefix_closure import PrefixRuntimeByteAudit

_INVENTORY_MAX_BYTES = 8 * 1024**2
_INVENTORY_DESCRIPTOR = 3
_INVENTORY_OWNER_UID = 0

_BOOTSTRAP = {
    "__init__.py",
    "embedding_runtime_files.py",
    "embedding_runtime_wheel_closure.py",
    "embedding_runtime_host_closure.py",
    "embedding_conda_runtime_closure.py",
    "embedding_runtime_prefix_closure.py",
}


def _root_bytes(path: Path, sha: str, maximum: int) -> tuple[bytes, dict[Path, tuple[int, ...]]]:
    """Initial six-file bootstrap only; public snapshots own all subsequent audit IO."""
    descriptors: list[int] = []
    epochs: dict[Path, tuple[int, ...]] = {}

    def identity(value: os.stat_result) -> tuple[int, ...]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_uid,
            value.st_gid,
            value.st_mode,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    try:
        for component in path.parent.parts:
            parent = descriptors[-1] if descriptors else None
            fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent,
            )
            descriptors.append(fd)
            named = next(reversed(epochs)) / component if epochs else Path(component)
            value = os.fstat(fd)
            if value.st_uid != 0 or value.st_mode & 0o022:
                raise ValueError("unprotected bootstrap ancestor")
            epochs[named] = identity(value)
        fd = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=descriptors[-1],
        )
        descriptors.append(fd)
        value = os.fstat(fd)
        if (
            not stat.S_ISREG(value.st_mode)
            or value.st_uid != 0
            or value.st_nlink != 1
            or value.st_mode & 0o6022
            or not 0 <= value.st_size <= maximum
        ):
            raise ValueError("unprotected bootstrap member")
        raw = bytearray()
        while chunk := os.read(fd, min(65536, maximum + 1 - len(raw))):
            raw.extend(chunk)
            if len(raw) > value.st_size:
                raise ValueError("bootstrap size drift")
        epochs[path] = identity(value)
        if len(raw) != value.st_size or "sha256:" + hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError("bootstrap pin mismatch")
        if (
            any(identity(member.lstat()) != initial for member, initial in epochs.items())
            or identity(os.fstat(fd)) != epochs[path]
        ):
            raise ValueError("bootstrap epoch drift")
        return bytes(raw), epochs
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def _current(epochs: dict[Path, tuple[int, ...]]) -> None:
    for path, initial in epochs.items():
        value = path.lstat()
        current = (
            value.st_dev,
            value.st_ino,
            value.st_uid,
            value.st_gid,
            value.st_mode,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
        if current != initial:
            raise ValueError("bootstrap epoch drift")


def _inventory_descriptor(directory: Path) -> tuple[Path, tuple[int, ...]]:
    """The owner opens this fixed evidence file before the audit; never choose an output path."""
    path = directory / "prefix-inventory.candidate.json"
    descriptor = os.fstat(_INVENTORY_DESCRIPTOR)
    named = path.lstat()
    identity = descriptor.st_dev, descriptor.st_ino, descriptor.st_uid, descriptor.st_gid
    if (
        not stat.S_ISREG(descriptor.st_mode)
        or descriptor.st_uid != _INVENTORY_OWNER_UID
        or stat.S_IMODE(descriptor.st_mode) != 0o600
        or descriptor.st_nlink != 1
        or descriptor.st_size != 0
        or os.lseek(_INVENTORY_DESCRIPTOR, 0, os.SEEK_CUR) != 0
        or named != descriptor
        or path.is_symlink()
    ):
        raise ValueError("invalid inventory evidence descriptor")
    return path, identity


def _inventory_candidate_bytes(
    audit: PrefixRuntimeByteAudit,
    *,
    owner_input_raw_sha256: str,
    host_seed_sha256: str,
    boot_id: str,
) -> bytes:
    """Serialize this audit's small immutable metadata; parsing this candidate grants nothing."""
    from eom_catalog_service.embedding_runtime_files import fixed_native_embedding_profile
    from eom_catalog_service.embedding_runtime_prefix_closure import PrefixRuntimeByteAudit

    if type(audit) is not PrefixRuntimeByteAudit:
        raise ValueError("invalid inventory audit type")
    inventory = audit.inventory
    inventory.__post_init__()
    if (
        inventory.owner_uid != 0
        or inventory.prefix != fixed_native_embedding_profile(audit.profile).prefix
        or re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", boot_id) is None
    ):
        raise ValueError("invalid inventory evidence frame")
    regular = tuple(entry for entry in inventory.entries if stat.S_ISREG(entry.epoch[4]))
    if (
        any(
            type(value) is not int
            for value in (
                audit.regular_members,
                audit.link_members,
                audit.size_bytes,
                audit.elf_members,
            )
        )
        or audit.regular_members != len(regular)
        or audit.link_members != sum(stat.S_ISLNK(entry.epoch[4]) for entry in inventory.entries)
        or audit.size_bytes != sum(entry.epoch[6] for entry in regular)
        or not 0 < audit.elf_members <= audit.regular_members
    ):
        raise ValueError("invalid inventory audit counts")
    audit_values = {
        name: getattr(audit, name)
        for name in (
            "source_closure_sha256",
            "member_inventory_sha256",
            "byte_closure_sha256",
            "elf_closure_sha256",
            "regular_members",
            "link_members",
            "size_bytes",
            "elf_members",
        )
    }
    for value in (
        owner_input_raw_sha256,
        host_seed_sha256,
        *(audit_values[name] for name in audit_values if name.endswith("sha256")),
    ):
        if type(value) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
            raise ValueError("invalid inventory evidence hash")
    body: dict[str, Any] = {
        "schema_version": "embedding-native-prefix-inventory/1.0",
        "evidence_state": "CANDIDATE_NOT_ADMITTED",
        "profile": audit.profile,
        "owner_input_raw_sha256": owner_input_raw_sha256,
        "host_seed_sha256": host_seed_sha256,
        "boot_id": boot_id,
        "prefix_root_epoch": inventory.root_epoch,
        "fixed_ancestor_epochs": tuple(epoch for _path, epoch in inventory.ancestor_epochs),
        "audit": audit_values,
        "entries": tuple(
            {
                "relative_member": entry.relative_member,
                "kind": "REGULAR"
                if stat.S_ISREG(entry.epoch[4])
                else ("DIRECTORY" if stat.S_ISDIR(entry.epoch[4]) else "SYMLINK"),
                "epoch": entry.epoch,
                "sha256": entry.sha256,
                "symlink_target": entry.symlink_target,
            }
            for entry in inventory.entries
        ),
    }
    encoder = json.JSONEncoder(
        sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )

    def bounded(value: object) -> bytes:
        raw = bytearray()
        for chunk in encoder.iterencode(value):
            part = chunk.encode("utf-8")
            if len(raw) + len(part) > _INVENTORY_MAX_BYTES:
                raise ValueError("inventory evidence exceeds its bound")
            raw.extend(part)
        return bytes(raw)

    body["inventory_sha256"] = "sha256:" + hashlib.sha256(bounded(body)).hexdigest()
    return bounded(body)


def _write_inventory_candidate(raw: bytes, path: Path, identity: tuple[int, ...]) -> None:
    """Write only the pre-opened new candidate, preserving partial evidence on any failure."""
    if type(raw) is not bytes or not 0 < len(raw) <= _INVENTORY_MAX_BYTES:
        raise ValueError("invalid inventory evidence size")
    if _inventory_descriptor(path.parent) != (path, identity):
        raise ValueError("inventory evidence descriptor changed")
    remaining = memoryview(raw)
    while remaining:
        written = os.write(_INVENTORY_DESCRIPTOR, remaining)
        if written <= 0:
            raise ValueError("inventory evidence write failed")
        remaining = remaining[written:]
    os.fsync(_INVENTORY_DESCRIPTOR)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    for offset in range(0, len(raw), 65536):
        if (
            os.pread(_INVENTORY_DESCRIPTOR, min(65536, len(raw) - offset), offset)
            != raw[offset : offset + 65536]
        ):
            raise ValueError("inventory evidence readback failed")
    value = os.fstat(_INVENTORY_DESCRIPTOR)
    if (
        (value.st_dev, value.st_ino, value.st_uid, value.st_gid) != identity
        or value != path.lstat()
        or value.st_nlink != 1
        or stat.S_IMODE(value.st_mode) != 0o600
        or value.st_size != len(raw)
    ):
        raise ValueError("inventory evidence changed")


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    flags = {"--profile", "--owner-input", "--owner-input-sha256"}
    if (
        len(arguments) != 7
        or arguments[0] not in {"conda31-bytes", "prefix-bytes"}
        or set(arguments[1::2]) != flags
    ):
        print("EMBEDDING_CONDA_ARGUMENTS_INVALID", file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("conda31-bytes", "prefix-bytes"))
    parser.add_argument("--profile", choices=("CPU_INDEX_FP32", "CUDA_INDEX_FP32"), required=True)
    parser.add_argument("--owner-input", required=True)
    parser.add_argument("--owner-input-sha256", required=True)
    try:
        args = parser.parse_args(arguments)
    except SystemExit:
        print("EMBEDDING_CONDA_ARGUMENTS_INVALID", file=sys.stderr)
        return 1
    if (
        re.fullmatch(
            r"/opt/eom/\.embedding-index-install-[A-Za-z0-9]{8}/(?:conda31|prefix)-audit-input\.json",
            args.owner_input,
        )
        is None
        or re.fullmatch(r"sha256:[0-9a-f]{64}", args.owner_input_sha256) is None
    ):
        print("EMBEDDING_CONDA_ARGUMENTS_INVALID", file=sys.stderr)
        return 1
    if (
        os.geteuid() != 0
        or Path(sys.prefix) != Path("/opt/eom/conda/envs/eom-embedding-experiment")
        or sys.version_info[:3] != (3, 12, 13)
        or not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode)
    ):
        print("EMBEDDING_CONDA_OWNER_UNAVAILABLE", file=sys.stderr)
        return 1
    try:
        owner_input = Path(args.owner_input)
        if Path(__file__) != owner_input.parent / "admit.py":
            raise ValueError("not a protected admitted owner leaf")
        raw, epochs = _root_bytes(owner_input, args.owner_input_sha256, 128 * 1024)

        def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, member in pairs:
                if key in result:
                    raise ValueError("duplicate owner field")
                result[key] = member
            return result

        def reject(_value: str) -> Any:
            raise ValueError("noninteger owner value")

        value: Any = json.loads(
            raw, object_pairs_hook=unique, parse_float=reject, parse_constant=reject
        )
        if (
            type(value) is not dict
            or set(value)
            != {
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
            }
            or type(value.get("bootstrap")) is not list
            or len(value["bootstrap"]) != 6
        ):
            raise ValueError("invalid bootstrap values")
        pins = value["bootstrap"]
        if [pin.get("filename") for pin in pins if type(pin) is dict] != sorted(_BOOTSTRAP):
            raise ValueError("invalid bootstrap set")
        source = owner_input.parent / "source"
        for pin in pins:
            if (
                set(pin) != {"filename", "sha256", "size_bytes"}
                or type(pin["sha256"]) is not str
                or re.fullmatch(r"sha256:[0-9a-f]{64}", pin["sha256"]) is None
                or type(pin["size_bytes"]) is not int
                or not 0 <= pin["size_bytes"] <= 1024**2
            ):
                raise ValueError("invalid bootstrap pin")
            member, observed = _root_bytes(
                source / "eom_catalog_service" / pin["filename"], pin["sha256"], 1024**2
            )
            if len(member) != pin["size_bytes"]:
                raise ValueError("invalid bootstrap size")
            epochs.update(observed)
        _current(epochs)
        if any(
            name == "eom_catalog_service" or name.startswith("eom_catalog_service.")
            for name in sys.modules
        ):
            raise ValueError("not a fresh isolated owner process")
        sys.path.insert(0, str(source))
        from eom_catalog_service.embedding_runtime_files import (
            NumericalRuntimeFileSnapshots,
            fixed_native_embedding_profile,
            read_live_runtime_os_file,
        )
        from eom_catalog_service.embedding_runtime_host_closure import (
            capture_protected_embedding_host,
        )
        from eom_catalog_service.embedding_runtime_prefix_closure import (
            audit_installed_embedding_prefix,
            parse_embedding_prefix_audit_input,
        )

        plan, host_sha, bootstrap = parse_embedding_prefix_audit_input(raw)
        if plan.conda.profile != args.profile or bootstrap != tuple(
            (pin["filename"], pin["sha256"], pin["size_bytes"]) for pin in pins
        ):
            raise ValueError("owner input association mismatch")
        files = NumericalRuntimeFileSnapshots()
        _current(epochs)
        inventory_path, inventory_identity = _inventory_descriptor(owner_input.parent)
        boot_id = (
            read_live_runtime_os_file(
                Path("/proc/sys/kernel/random/boot_id"), maximum=64, owner_uid=0
            )
            .decode("ascii")
            .strip()
        )
        with capture_protected_embedding_host(expected_seed_sha256=host_sha, files=files) as host:
            audit = audit_installed_embedding_prefix(
                plan,
                prefix=fixed_native_embedding_profile(args.profile).prefix,
                archive_root=Path("/opt/eom/embedding-runtime-archives"),
                helper_path=owner_input.parent / "install.py",
                lock_directory=owner_input.parent / "locks",
                files=files,
                host=host,
            )
            _current(epochs)
            candidate = _inventory_candidate_bytes(
                audit,
                owner_input_raw_sha256=args.owner_input_sha256,
                host_seed_sha256=host_sha,
                boot_id=boot_id,
            )
            audit.inventory.assert_unchanged()
            files.assert_unchanged()
            host.assert_current()
            _write_inventory_candidate(candidate, inventory_path, inventory_identity)
            audit.inventory.assert_unchanged()
            files.assert_unchanged()
            host.assert_current()
            _current(epochs)
        print("EMBEDDING_PREFIX_BYTES_AUDIT_PASS_NOT_ADMITTED", audit.byte_closure_sha256)
        return 0
    except Exception as exc:
        code = getattr(exc, "code", "EMBEDDING_PREFIX_AUDIT_INVALID")
        print(
            code
            if type(code) is str and re.fullmatch(r"[A-Z_]+", code)
            else "EMBEDDING_PREFIX_AUDIT_INVALID",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
