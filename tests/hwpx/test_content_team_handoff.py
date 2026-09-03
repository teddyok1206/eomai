from __future__ import annotations

import hashlib
import warnings
import zipfile
from pathlib import Path

import pytest
from eom_hwpx_builder.content_team_handoff import (
    ContentTeamHandoffError,
    inspect_content_team_handoff,
)


def _profile_archive(path: Path, members: list[tuple[str, bytes]]) -> tuple[str, dict[str, str]]:
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members:
            archive.writestr(name, payload)
    archive_sha = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    member_hashes = {
        f"member-{index}": f"sha256:{hashlib.sha256(payload).hexdigest()}"
        for index, (_name, payload) in enumerate(members)
    }
    return archive_sha, member_hashes


def test_handoff_archive_attestation_finds_members_by_immutable_hash(tmp_path: Path) -> None:
    path = tmp_path / "handoff.zip"
    archive_sha, member_hashes = _profile_archive(
        path,
        [("handoff/templates/base.hwpx", b"base"), ("handoff/prototypes/table.hwpx", b"table")],
    )

    evidence = inspect_content_team_handoff(
        path,
        expected_archive_sha256=archive_sha,
        expected_member_hashes=member_hashes,
    )

    assert evidence.entry_count == 2
    assert evidence.uncompressed_bytes == 9
    assert tuple(member.purpose for member in evidence.members) == ("member-0", "member-1")
    assert tuple(member.archive_member for member in evidence.members) == (
        "handoff/templates/base.hwpx",
        "handoff/prototypes/table.hwpx",
    )


def test_handoff_archive_rejects_hash_drift_and_missing_profile_member(tmp_path: Path) -> None:
    path = tmp_path / "handoff.zip"
    archive_sha, member_hashes = _profile_archive(path, [("base.hwpx", b"base")])

    with pytest.raises(ContentTeamHandoffError, match="unsafe"):
        inspect_content_team_handoff(
            path,
            expected_archive_sha256="sha256:" + "0" * 64,
            expected_member_hashes=member_hashes,
        )
    with pytest.raises(ContentTeamHandoffError, match="missing or ambiguous"):
        inspect_content_team_handoff(
            path,
            expected_archive_sha256=archive_sha,
            expected_member_hashes={"missing": "sha256:" + "1" * 64},
        )


def test_handoff_archive_rejects_traversal_and_case_collision(tmp_path: Path) -> None:
    traversal = tmp_path / "traversal.zip"
    traversal_sha, traversal_members = _profile_archive(traversal, [("../base.hwpx", b"base")])
    with pytest.raises(ContentTeamHandoffError, match="path is unsafe"):
        inspect_content_team_handoff(
            traversal,
            expected_archive_sha256=traversal_sha,
            expected_member_hashes=traversal_members,
        )

    collision = tmp_path / "collision.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        collision_sha, collision_members = _profile_archive(
            collision,
            [("base.hwpx", b"base"), ("BASE.HWPX", b"other")],
        )
    with pytest.raises(ContentTeamHandoffError, match="duplicate member"):
        inspect_content_team_handoff(
            collision,
            expected_archive_sha256=collision_sha,
            expected_member_hashes=collision_members,
        )


def test_handoff_archive_rejects_excessive_compression_ratio(tmp_path: Path) -> None:
    path = tmp_path / "compressed.zip"
    payload = b"0" * 100_000
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("base.hwpx", payload)
    archive_sha = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    member_hashes = {"base": f"sha256:{hashlib.sha256(payload).hexdigest()}"}

    with pytest.raises(ContentTeamHandoffError, match="unsafe compression"):
        inspect_content_team_handoff(
            path,
            expected_archive_sha256=archive_sha,
            expected_member_hashes=member_hashes,
        )
