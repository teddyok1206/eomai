"""Real private local files, never a browser, database, NAS or account."""

import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_kakao_archive_contracts.capture import CsvMember
from eom_kakao_archive_contracts.render import LocalMember, sha256
from eom_orchestrator import kakao_runtime_os as runtime_os
from eom_orchestrator.kakao_capture_inputs import KakaoCaptureInputError, KakaoCaptureOutputReader


@pytest.fixture
def staged():
    with tempfile.TemporaryDirectory(
        prefix="kakao-c1-input-", dir=Path.home() / ".cache"
    ) as folder:
        root = Path(folder)
        root.chmod(0o2750)
        reader = KakaoCaptureOutputReader(
            root, "kakaoattempt_" + "a" * 32, os.getuid(), os.getgid()
        )
        attempt = root / reader.attempt_id
        output = attempt / "outputs"
        nested = output / "photos"
        for path in (attempt, output, nested):
            path.mkdir(mode=0o750)
            path.chmod(0o750)
        payload = b"synthetic local capture payload"
        path = nested / "image.png"
        path.write_bytes(payload)
        path.chmod(0o640)
        member = LocalMember(
            relative_path="outputs/photos/image.png",
            size_bytes=len(payload),
            media_type="image/png",
            sha256=sha256(payload),
        )
        yield SimpleNamespace(
            reader=reader,
            root=root,
            attempt=attempt,
            output=output,
            nested=nested,
            path=path,
            member=member,
            payload=payload,
        )


def test_exact_member_read_is_read_only_and_private(staged):
    before = {
        p: (p.read_bytes(), p.stat().st_mtime_ns) for p in staged.root.rglob("*") if p.is_file()
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert tuple(pool.map(staged.reader, (staged.member, staged.member))) == (
            staged.payload,
            staged.payload,
        )
    assert before == {
        p: (p.read_bytes(), p.stat().st_mtime_ns) for p in staged.root.rglob("*") if p.is_file()
    }
    assert str(staged.root) not in repr(staged.reader)
    assert staged.payload.decode() not in repr(staged.reader)


def test_csv_and_json_are_read_without_interpreting_their_content(staged):
    for name, media, cls in (
        ("source.csv", "text/csv", CsvMember),
        ("normalization.json", "application/json", LocalMember),
    ):
        path = staged.output / name
        path.write_bytes(staged.payload)
        path.chmod(0o640)
        member = cls(
            relative_path="outputs/" + name,
            media_type=media,
            size_bytes=len(staged.payload),
            sha256=sha256(staged.payload),
        )
        assert staged.reader(member) == staged.payload


@pytest.mark.parametrize("size", [1, 32768])
def test_fixed_result_reader_is_bounded_but_does_not_interpret_worker_json(staged, size):
    path = staged.output / "result.json"
    path.write_bytes(b"x" * size)
    path.chmod(0o640)
    assert staged.reader.read_result() == b"x" * size


@pytest.mark.parametrize("size", [0, 32769])
def test_result_proposal_cannot_exceed_the_fixed_budget(staged, size):
    path = staged.output / "result.json"
    path.write_bytes(b"x" * size)
    path.chmod(0o640)
    with pytest.raises(KakaoCaptureInputError, match="STAGING_UNSAFE"):
        staged.reader.read_result()


@pytest.mark.parametrize("value", ["../outside", "kakaoattempt_" + "a" * 32 + "/other", None])
def test_untrusted_attempt_cannot_select_a_path(staged, value):
    with pytest.raises(KakaoCaptureInputError, match="INPUT_INVALID"):
        replace(staged.reader, attempt_id=value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("root", Path("relative")),
        ("root", Path("/tmp/../etc")),
        ("worker_uid", True),
        ("worker_uid", 0),
        ("worker_uid", -1),
        ("control_gid", -1),
    ],
)
def test_invalid_configuration_fails_before_io(staged, field, value):
    with pytest.raises(KakaoCaptureInputError, match="INPUT_INVALID"):
        replace(staged.reader, **{field: value})


@pytest.mark.parametrize(
    "change",
    [
        {"relative_path": "inputs/auth.json"},
        {"relative_path": "outputs/../../private"},
        {"relative_path": "/outputs/image.png"},
        {"relative_path": "outputs\\image.png"},
        {"size_bytes": 0},
        {"size_bytes": 1024 * 1024 * 1024},
        {"media_type": "application/pdf"},
    ],
)
def test_model_copy_is_not_validation_or_permission(staged, change):
    with pytest.raises(KakaoCaptureInputError, match="MEMBER_INVALID"):
        staged.reader(staged.member.model_copy(update=change))


@pytest.mark.parametrize("which", ["root", "attempt", "output", "nested", "path"])
def test_symlink_at_any_materialization_boundary_is_rejected(staged, which):
    path = getattr(staged, which)
    moved = path.with_name(path.name + "-original")
    path.rename(moved)
    path.symlink_to(moved, target_is_directory=moved.is_dir())
    try:
        with pytest.raises(KakaoCaptureInputError, match="STAGING_UNSAFE"):
            staged.reader(staged.member)
    finally:
        path.unlink()
        moved.rename(path)


@pytest.mark.parametrize(
    "which,mode",
    [
        ("root", 0o750),
        ("attempt", 0o770),
        ("output", 0o755),
        ("nested", 0o777),
        ("path", 0o644),
        ("path", 0o600),
    ],
)
def test_installed_permissions_are_exact(staged, which, mode):
    getattr(staged, which).chmod(mode)
    with pytest.raises(KakaoCaptureInputError, match="STAGING_UNSAFE"):
        staged.reader(staged.member)


def test_wrong_uid_or_control_group_is_rejected(staged):
    for key in ("worker_uid", "control_gid"):
        with pytest.raises(KakaoCaptureInputError, match="STAGING_UNSAFE"):
            replace(staged.reader, **{key: getattr(staged.reader, key) + 1})(staged.member)


def test_missing_other_attempt_does_not_fallback_to_existing_output(staged):
    with pytest.raises(KakaoCaptureInputError, match="INPUT_MISSING") as error:
        replace(staged.reader, attempt_id="kakaoattempt_" + "b" * 32)(staged.member)
    assert str(staged.root) not in str(error.value)


def test_missing_payload_is_not_a_request_to_redownload(staged):
    staged.path.unlink()
    with pytest.raises(KakaoCaptureInputError, match="INPUT_MISSING"):
        staged.reader(staged.member)


def test_hash_tamper_hardlink_and_fifo_are_rejected(staged):
    staged.path.write_bytes(b"x" * len(staged.payload))
    with pytest.raises(KakaoCaptureInputError, match="HASH_MISMATCH"):
        staged.reader(staged.member)
    duplicate = staged.path.with_name("hardlink.png")
    os.link(staged.path, duplicate)
    with pytest.raises(KakaoCaptureInputError, match="STAGING_UNSAFE"):
        staged.reader(staged.member)
    duplicate.unlink()
    staged.path.unlink()
    os.mkfifo(staged.path, mode=0o640)
    with pytest.raises(KakaoCaptureInputError, match="STAGING_UNSAFE"):
        staged.reader(staged.member)


def test_mutation_during_fd_read_is_rejected(staged, monkeypatch):
    inode, calls = staged.path.stat().st_ino, 0
    original = runtime_os.os.fstat

    def fstat(fd):
        nonlocal calls
        info = original(fd)
        if info.st_ino == inode:
            calls += 1
            if calls == 2:
                with staged.path.open("ab") as stream:
                    stream.write(b"changed")
                info = original(fd)
        return info

    monkeypatch.setattr(runtime_os.os, "fstat", fstat)
    with pytest.raises(KakaoCaptureInputError, match="STAGING_UNSAFE"):
        staged.reader(staged.member)
