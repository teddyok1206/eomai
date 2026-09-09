from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import stat
import warnings
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

import pytest

from scripts.api import verify_release_wheel_records as wheel_records
from scripts.api.verify_release_wheel_records import (
    WheelRecordError,
    main,
    verify_wheel_record,
)


def _digest(value: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(value).digest()).rstrip(b"=")
    return "sha256=" + encoded.decode("ascii")


def _row(name: str, value: bytes) -> tuple[str, str, str]:
    return name, _digest(value), str(len(value))


def _write_member(archive: zipfile.ZipFile, name: str, value: bytes) -> None:
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    archive.writestr(info, value, compress_type=zipfile.ZIP_DEFLATED)


def _wheel(
    tmp_path: Path,
    *,
    distribution: str = "eom_platform",
    record_mutation: Callable[[list[list[str]], str], None] | None = None,
    record_root: str | None = None,
    duplicate_member: bool = False,
    directory_member: bool = False,
    raw_record: bytes | None = None,
    package_payload: bytes = b'VERSION = "0.1.0"\n',
) -> Path:
    path = tmp_path / f"{distribution}-0.1.0-py3-none-any.whl"
    dist_info = record_root or f"{distribution}-0.1.0.dist-info"
    members = {
        f"{distribution}/__init__.py": package_payload,
        f"{dist_info}/METADATA": b"Metadata-Version: 2.1\nName: test\nVersion: 0.1.0\n",
        f"{dist_info}/WHEEL": b"Wheel-Version: 1.0\nTag: py3-none-any\n",
    }
    record_name = f"{dist_info}/RECORD"
    rows = [list(_row(name, value)) for name, value in members.items()]
    rows.append([record_name, "", ""])
    if record_mutation is not None:
        record_mutation(rows, record_name)
    record_buffer = io.StringIO(newline="")
    csv.writer(record_buffer, lineterminator="\n").writerows(rows)

    with zipfile.ZipFile(path, "w") as archive:
        for name, value in members.items():
            _write_member(archive, name, value)
        if duplicate_member:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                first_name, first_value = next(iter(members.items()))
                _write_member(archive, first_name, first_value)
        if directory_member:
            archive.writestr(f"{distribution}/directory/", b"")
        _write_member(
            archive,
            record_name,
            record_buffer.getvalue().encode("utf-8") if raw_record is None else raw_record,
        )
    path.chmod(0o600)
    return path


def test_release_wheel_record_verifier_accepts_exact_member_set_hashes_and_sizes(
    tmp_path: Path,
) -> None:
    verify_wheel_record(_wheel(tmp_path))


@pytest.mark.parametrize(
    "mutation",
    (
        lambda rows, _record: rows[0].__setitem__(1, "sha256=" + "A" * 43),
        lambda rows, _record: rows[0].__setitem__(2, "999"),
        lambda rows, _record: rows[0].__setitem__(1, "sha512=" + "A" * 43),
        lambda rows, _record: rows[0].__setitem__(1, rows[0][1] + "="),
        lambda rows, _record: rows[0].__setitem__(2, "01"),
        lambda rows, _record: rows[0].__setitem__(1, ""),
        lambda rows, _record: rows.pop(0),
        lambda rows, _record: rows.append(["extra.py", "sha256=" + "A" * 43, "1"]),
        lambda rows, _record: rows.append(list(rows[0])),
        lambda rows, _record: rows.append(["../escape.py", "sha256=" + "A" * 43, "1"]),
        lambda rows, _record: rows.append(["/absolute.py", "sha256=" + "A" * 43, "1"]),
        lambda rows, _record: rows.append(["bad\\path.py", "sha256=" + "A" * 43, "1"]),
        lambda rows, _record: rows.append(["bad\x00path.py", "sha256=" + "A" * 43, "1"]),
        lambda rows, record: rows[-1].__setitem__(1, "sha256=" + "A" * 43),
        lambda rows, record: rows[-1].__setitem__(2, "1"),
    ),
    ids=(
        "hash-mismatch",
        "size-mismatch",
        "algorithm",
        "digest-padding",
        "noncanonical-size",
        "blank-member-hash",
        "missing-row",
        "extra-row",
        "duplicate-row",
        "unsafe-row-path",
        "absolute-row-path",
        "backslash-row-path",
        "nul-row-path",
        "record-self-hash",
        "record-self-size",
    ),
)
def test_release_wheel_record_verifier_rejects_invalid_record_bindings(
    tmp_path: Path,
    mutation: Callable[[list[list[str]], str], None],
) -> None:
    with pytest.raises(WheelRecordError):
        verify_wheel_record(_wheel(tmp_path, record_mutation=mutation))


def test_release_wheel_record_verifier_rejects_wrong_dist_info_identity(tmp_path: Path) -> None:
    with pytest.raises(WheelRecordError, match="WHEEL_RECORD_IDENTITY"):
        verify_wheel_record(_wheel(tmp_path, record_root="other-0.1.0.dist-info"))


def test_release_wheel_record_verifier_rejects_duplicate_zip_member(tmp_path: Path) -> None:
    with pytest.raises(WheelRecordError, match="WHEEL_RECORD_MEMBER_DUPLICATE"):
        verify_wheel_record(_wheel(tmp_path, duplicate_member=True))


def test_release_wheel_record_verifier_rejects_directory_member_or_malformed_csv(
    tmp_path: Path,
) -> None:
    with pytest.raises(WheelRecordError, match="WHEEL_RECORD_MEMBER_TYPE"):
        verify_wheel_record(_wheel(tmp_path, directory_member=True))
    with pytest.raises(WheelRecordError, match="WHEEL_RECORD_PARSE_FAILED"):
        verify_wheel_record(_wheel(tmp_path, raw_record=b'"unterminated\n'))


def test_release_wheel_record_verifier_requires_private_single_link_regular_file(
    tmp_path: Path,
) -> None:
    wheel = _wheel(tmp_path)
    wheel.chmod(0o644)
    with pytest.raises(WheelRecordError, match="WHEEL_RECORD_FILE_IDENTITY"):
        verify_wheel_record(wheel)

    wheel.chmod(0o600)
    hardlink = tmp_path / "hardlink.whl"
    os.link(wheel, hardlink)
    with pytest.raises(WheelRecordError, match="WHEEL_RECORD_FILE_IDENTITY"):
        verify_wheel_record(wheel)


def test_release_wheel_record_verifier_rejects_symlink(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path)
    symlink = tmp_path / "eom_platform-0.1.0-py3-none-any-link.whl"
    symlink.symlink_to(wheel)
    with pytest.raises(WheelRecordError, match="WHEEL_RECORD_READ_FAILED"):
        verify_wheel_record(symlink)


def test_release_wheel_record_verifier_rejects_bad_or_oversized_archive(tmp_path: Path) -> None:
    invalid = tmp_path / "eom_platform-0.1.0-py3-none-any.whl"
    invalid.write_bytes(b"not a wheel")
    invalid.chmod(0o600)
    with pytest.raises(WheelRecordError, match="WHEEL_RECORD_READ_FAILED"):
        verify_wheel_record(invalid)

    with invalid.open("wb") as stream:
        stream.truncate(256 * 1024 * 1024 + 1)
    with pytest.raises(WheelRecordError, match="WHEEL_RECORD_FILE_IDENTITY"):
        verify_wheel_record(invalid)


def test_release_wheel_record_verifier_rejects_file_changed_during_scan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wheel = _wheel(tmp_path)
    original = wheel_records._verify_open_wheel

    def verify_then_change(stream: BinaryIO, *, expected_distribution: str) -> None:
        original(stream, expected_distribution=expected_distribution)
        with wheel.open("ab") as target:
            target.write(b"x")

    monkeypatch.setattr(wheel_records, "_verify_open_wheel", verify_then_change)
    with pytest.raises(WheelRecordError, match="WHEEL_RECORD_FILE_CHANGED"):
        verify_wheel_record(wheel)


def test_release_wheel_record_cli_requires_exact_three_distribution_set(tmp_path: Path) -> None:
    wheels = tuple(
        _wheel(tmp_path, distribution=distribution)
        for distribution in ("eom_api_contracts", "eom_application_api", "eom_platform")
    )
    assert main(tuple(str(path) for path in wheels)) == 0
    assert main(tuple(str(path) for path in wheels[:2])) == 2


def test_release_wheel_identity_output_is_canonical_and_ordered(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    wheels = tuple(
        _wheel(tmp_path, distribution=distribution)
        for distribution in ("eom_platform", "eom_application_api", "eom_api_contracts")
    )

    assert main(("--emit-identity", *(str(path) for path in wheels))) == 0

    line = capsys.readouterr().out.strip()
    prefix = "release_wheel_inspection_identity="
    assert line.startswith(prefix)
    payload = json.loads(line.removeprefix(prefix))
    assert payload["schema_version"] == "release-wheel-inspection-identity/1.0"
    assert [wheel["filename"] for wheel in payload["wheels"]] == sorted(
        path.name for path in wheels
    )
    assert all(wheel["sha256"].startswith("sha256:") for wheel in payload["wheels"])
    assert json.dumps(payload, sort_keys=True, separators=(",", ":")) == line.removeprefix(prefix)


def test_release_wheel_identity_detects_atomic_valid_record_substitution(tmp_path: Path) -> None:
    inspected_dir = tmp_path / "inspected"
    replacement_dir = tmp_path / "replacement"
    inspected_dir.mkdir()
    replacement_dir.mkdir()
    wheel = _wheel(inspected_dir)
    replacement = _wheel(replacement_dir, package_payload=b'VERSION = "0.1.1"\n')
    inspected_identity = verify_wheel_record(wheel)

    os.replace(replacement, wheel)
    replacement_identity = verify_wheel_record(wheel)

    assert replacement_identity.filename == inspected_identity.filename
    assert replacement_identity.sha256 != inspected_identity.sha256
    assert replacement_identity.inode != inspected_identity.inode
