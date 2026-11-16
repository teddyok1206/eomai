"""Build and protect the exact offline Web wheel set; never install packages here."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import zipfile
from dataclasses import dataclass
from email.parser import BytesParser
from pathlib import Path

LOCAL_NAMES = frozenset({"eom-web-gui", "eom-kakao-archive-contracts"})
LOCK_NAME = "release.requirements.lock"
MAX_WHEEL_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
_PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([0-9][A-Za-z0-9_.+]*)")
_WHEEL = re.compile(
    r"[A-Za-z0-9_+.]+-[A-Za-z0-9_+.]+-[A-Za-z0-9_.]+-[A-Za-z0-9_.]+-[A-Za-z0-9_.]+\.whl"
)
_SHA = re.compile(r"[a-f0-9]{64}")


class ClosureError(ValueError):
    """Content-free failure before package execution."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ClosureError(code)


def _name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _read(path: Path, limit: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "UNSAFE_SOURCE_FILE")
        _require(0 < info.st_size <= limit, "SOURCE_SIZE_INVALID")
        value = source.read(limit + 1)
    _require(0 < len(value) <= limit, "SOURCE_SIZE_INVALID")
    return value


def read_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in _read(path, 64 * 1024).decode("ascii").splitlines():
        if not line or line.startswith("#"):
            continue
        match = _PIN.fullmatch(line)
        _require(match is not None, "EXACT_PIN_REQUIRED")
        assert match is not None
        name, version = _name(match[1]), match[2]
        _require(name not in pins, "DUPLICATE_PIN")
        pins[name] = version
    _require(pins.keys() >= LOCAL_NAMES and len(pins) <= 64, "WEB_CLOSURE_INVALID")
    return pins


@dataclass(frozen=True)
class Wheel:
    name: str
    version: str
    filename: str
    data: bytes
    sha256: str


def read_wheels(directory: Path, pins: dict[str, str]) -> dict[str, Wheel]:
    wheels: dict[str, Wheel] = {}
    total = 0
    for path in sorted(directory.iterdir()):
        if path.name == LOCK_NAME:
            continue
        _require(_WHEEL.fullmatch(path.name) is not None, "UNEXPECTED_WHEELHOUSE_ENTRY")
        data = _read(path, MAX_WHEEL_BYTES)
        total += len(data)
        _require(total <= MAX_TOTAL_BYTES, "CLOSURE_TOO_LARGE")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            metadata = [
                entry
                for entry in archive.infolist()
                if entry.filename.endswith(".dist-info/METADATA")
            ]
            _require(
                len(metadata) == 1 and metadata[0].file_size <= 2 * 1024 * 1024, "METADATA_INVALID"
            )
            message = BytesParser().parsebytes(archive.read(metadata[0]))
        names, versions = message.get_all("Name", []), message.get_all("Version", [])
        _require(len(names) == len(versions) == 1, "METADATA_IDENTITY_INVALID")
        name, version = _name(str(names[0])), str(versions[0])
        file_name, file_version = path.name.split("-", 2)[:2]
        _require((_name(file_name), file_version) == (name, version), "WHEEL_FILENAME_MISMATCH")
        _require(name not in wheels, "DUPLICATE_WHEEL")
        _require(pins.get(name) == version, "UNEXPECTED_WHEEL_VERSION")
        wheels[name] = Wheel(name, version, path.name, data, hashlib.sha256(data).hexdigest())
    _require(wheels.keys() == pins.keys(), "INCOMPLETE_WHEEL_CLOSURE")
    return wheels


def locked_bytes(wheels: dict[str, Wheel]) -> bytes:
    return "".join(
        f"{wheel.name}=={wheel.version} --hash=sha256:{wheel.sha256}\n"
        for _, wheel in sorted(wheels.items())
    ).encode("ascii")


def _write_new(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as destination:
        destination.write(data)


def stage_closure(
    directory: Path,
    destination: Path,
    pins: dict[str, str],
    *,
    expected_lock_sha256: str,
    expected_web_sha256: str,
    expected_commit: str,
) -> None:
    _require(_SHA.fullmatch(expected_lock_sha256) is not None, "LOCK_SHA_INVALID")
    _require(_SHA.fullmatch(expected_web_sha256) is not None, "WEB_SHA_INVALID")
    _require(re.fullmatch(r"[a-f0-9]{40}", expected_commit) is not None, "COMMIT_INVALID")
    info = destination.lstat()
    _require(
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o700
        and not any(destination.iterdir()),
        "PRIVATE_EMPTY_STAGING_REQUIRED",
    )
    lock = _read(directory / LOCK_NAME, 64 * 1024)
    _require(hashlib.sha256(lock).hexdigest() == expected_lock_sha256, "LOCK_SHA_MISMATCH")
    wheels = read_wheels(directory, pins)
    _require(locked_bytes(wheels) == lock, "WHEEL_HASH_CLOSURE_MISMATCH")
    web = wheels["eom-web-gui"]
    _require(web.sha256 == expected_web_sha256, "WEB_SHA_MISMATCH")
    with zipfile.ZipFile(io.BytesIO(web.data)) as archive:
        info_file = archive.getinfo("eom_web_gui/build-info.json")
        _require(info_file.file_size <= 4096, "BUILD_INFO_INVALID")
        build = json.loads(archive.read(info_file))
    _require(build.get("source_commit") == expected_commit, "SOURCE_COMMIT_MISMATCH")
    # All bytes have passed before any pip process is allowed to observe this directory.
    for wheel in wheels.values():
        _write_new(destination / wheel.filename, wheel.data)
    _write_new(destination / LOCK_NAME, lock)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("external", "create", "stage"))
    parser.add_argument("--pins", type=Path, required=True)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--lock-sha256")
    parser.add_argument("--web-sha256")
    parser.add_argument("--commit")
    args = parser.parse_args()
    pins = read_pins(args.pins)
    if args.action == "external":
        print(
            "\n".join(
                f"{name}=={version}"
                for name, version in sorted(pins.items())
                if name not in LOCAL_NAMES
            )
        )
    elif args.action == "create":
        if args.directory is None:
            parser.error("--directory is required")
        payload = locked_bytes(read_wheels(args.directory, pins))
        _write_new(args.directory / LOCK_NAME, payload)
        print(f"web_gui_closure_sha256={hashlib.sha256(payload).hexdigest()}")
    else:
        if any(
            value is None
            for value in (
                args.directory,
                args.destination,
                args.lock_sha256,
                args.web_sha256,
                args.commit,
            )
        ):
            parser.error("stage requires directory, destination, lock/web SHA-256 and commit")
        stage_closure(
            args.directory,
            args.destination,
            pins,
            expected_lock_sha256=args.lock_sha256,
            expected_web_sha256=args.web_sha256,
            expected_commit=args.commit,
        )
        print("web_gui_protected_offline_closure=PASS")


if __name__ == "__main__":
    main()
