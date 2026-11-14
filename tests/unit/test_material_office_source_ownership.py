"""Fixed converter workspace ownership survives root-to-Catalog replay handoff."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service import material_office_conversion as office
from eom_catalog_service.material_learning_source import (
    MaterialLearningSourceError,
    MaterialSourceFileFingerprint,
    validate_material_source_file,
)
from eom_identifiers import sha256_file

from tests.unit.test_office_document_converter import _write_minimal_hwpx


@pytest.fixture
def handoff(tmp_path, monkeypatch):
    catalog_uid, catalog_gid = os.geteuid(), os.getegid()
    root = tmp_path / "office-conversion"
    root.mkdir(mode=0o700)
    workspace = root / ("officeconv_" + "a" * 32)
    workspace.mkdir(mode=0o700)
    source = workspace / "original.hwpx"
    _write_minimal_hwpx(source)
    original = source.stat()
    owner = [0]
    actual_fstat, actual_lstat = os.fstat, Path.lstat

    def observed(metadata):
        if (metadata.st_dev, metadata.st_ino) != (original.st_dev, original.st_ino):
            return metadata
        # No privileged chown is performed: only UID observation is substituted.
        # Real FD bytes, mode, inode, link count, hashes and timestamps stay intact.
        fields = {key: getattr(metadata, key) for key in dir(metadata) if key.startswith("st_")}
        fields["st_uid"] = owner[0]
        return SimpleNamespace(**fields)

    monkeypatch.setattr(office, "_ROOT", root)
    monkeypatch.setattr(office.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        office.pwd,
        "getpwnam",
        lambda _name: SimpleNamespace(pw_uid=catalog_uid, pw_gid=catalog_gid),
    )
    monkeypatch.setattr(office.os, "fstat", lambda fd: observed(actual_fstat(fd)))
    monkeypatch.setattr(
        Path, "lstat", lambda path, **kwargs: observed(actual_lstat(path, **kwargs))
    )
    converter = office.CatalogOwnerMaterialOfficeConverter.__new__(
        office.CatalogOwnerMaterialOfficeConverter
    )
    fingerprint = MaterialSourceFileFingerprint("HWPX", source.stat().st_size, sha256_file(source))
    return SimpleNamespace(
        converter=converter,
        source=source,
        workspace=workspace,
        owner=owner,
        catalog_uid=catalog_uid,
        fingerprint=fingerprint,
    )


def test_first_root_copy_then_catalog_owned_replay_are_same_exact_source(handoff):
    handoff.converter.validate_source(handoff.workspace, fingerprint=handoff.fingerprint)
    handoff.owner[0] = handoff.catalog_uid
    handoff.converter.validate_source(handoff.workspace, fingerprint=handoff.fingerprint)
    assert sha256_file(handoff.source) == handoff.fingerprint.sha256


def test_upload_default_stays_strict_current_uid(handoff):
    handoff.owner[0] = handoff.catalog_uid
    with pytest.raises(MaterialLearningSourceError, match="SOURCE_FILE_INVALID"):
        validate_material_source_file(handoff.source, handoff.fingerprint)
    handoff.converter.validate_source(handoff.workspace, fingerprint=handoff.fingerprint)


@pytest.mark.parametrize(
    "fault", ["foreign_owner", "hash", "mode", "signature", "symlink", "hardlink"]
)
def test_fixed_workspace_never_admits_unsafe_or_changed_source(handoff, fault):
    fingerprint = handoff.fingerprint
    if fault == "foreign_owner":
        handoff.owner[0] = handoff.catalog_uid + 17
    elif fault == "hash":
        fingerprint = MaterialSourceFileFingerprint(
            "HWPX", fingerprint.content_length, "sha256:" + "0" * 64
        )
    elif fault == "mode":
        handoff.source.chmod(0o644)
    elif fault == "signature":
        handoff.source.write_bytes(b"not-a-zip" + handoff.source.read_bytes()[9:])
    elif fault == "hardlink":
        os.link(handoff.source, handoff.workspace / "second-link.hwpx")
    else:
        original = handoff.workspace / "saved.hwpx"
        handoff.source.rename(original)
        handoff.source.symlink_to(original)
    with pytest.raises((ValueError, OSError)):
        handoff.converter.validate_source(handoff.workspace, fingerprint=fingerprint)


@pytest.mark.parametrize("fault", ["other_workspace", "public_workspace"])
def test_only_fixed_private_catalog_workspace_is_accepted(handoff, tmp_path, fault):
    workspace = handoff.workspace
    if fault == "other_workspace":
        workspace = tmp_path
    else:
        workspace.chmod(0o755)
    with pytest.raises(ValueError, match="MATERIAL_OFFICE_"):
        handoff.converter.validate_source(workspace, fingerprint=handoff.fingerprint)
