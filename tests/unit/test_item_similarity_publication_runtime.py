"""Source composition and actual local directories; DB admission observations synthetic."""

from __future__ import annotations

import os
from dataclasses import replace

import pytest
from eom_catalog_service.item_similarity_publication_service import (
    CatalogItemSimilarityPublicationService,
)
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.similarity_read_runtime import (
    SimilarityReaderRuntimeError,
    build_catalog_item_similarity_publications,
    build_catalog_similarity_context_reads,
)
from eom_identifiers import sha256_bytes

from tests.unit.test_similarity_read_runtime import install_seams


def context_reads(tmp_path, monkeypatch):
    value = install_seams(monkeypatch)
    root = tmp_path / "owner-staging"
    root.mkdir(mode=0o700)
    return build_catalog_similarity_context_reads(
        value.engine,
        mode="ENABLED",
        configuration_raw_sha256=sha256_bytes(value.raw),
        settings=CatalogSettings(staging_root=root, nas_artifact_root=tmp_path / "artifacts"),
    )


def test_disabled_publication_has_no_file_db_or_owner_access():
    assert (
        build_catalog_item_similarity_publications(
            mode="DISABLED", context_reads=object(), source_commit="not-selected"
        )
        is None
    )


@pytest.mark.parametrize(
    "mode,source", (("AUTO", "a" * 40), ("ENABLED", None), ("ENABLED", "latest"))
)
def test_incomplete_enable_never_selects_a_default_owner_or_revision(mode, source):
    with pytest.raises(SimilarityReaderRuntimeError):
        build_catalog_item_similarity_publications(
            mode=mode, context_reads=None, source_commit=source
        )


def test_enabled_publication_reuses_verified_read_owner_and_private_local_paths(
    tmp_path, monkeypatch
):
    reads = context_reads(tmp_path, monkeypatch)
    result = build_catalog_item_similarity_publications(
        mode="ENABLED", context_reads=reads, source_commit="a" * 40
    )
    assert isinstance(result, CatalogItemSimilarityPublicationService)
    assert result.owner is reads.owner
    settings = result.publisher.settings
    assert settings.nas_artifact_root == reads.owner.settings.nas_artifact_root
    assert settings.runtime_source_commit == "a" * 40
    for path in (settings.workspace_root, settings.staging_root):
        assert path.is_relative_to(reads.owner.settings.staging_root)
        assert path.stat().st_uid == os.geteuid()
        assert path.stat().st_mode & 0o777 == 0o700
    assert (
        build_catalog_item_similarity_publications(
            mode="ENABLED", context_reads=reads, source_commit="a" * 40
        ).publisher.settings
        == settings
    )


@pytest.mark.parametrize(
    "fault",
    ("parent_symlink", "ancestor_symlink", "parent_writable", "child_symlink", "child_writable"),
)
def test_unsafe_publication_scratch_is_not_repaired_or_used(tmp_path, monkeypatch, fault):
    reads = context_reads(tmp_path, monkeypatch)
    parent = reads.owner.settings.staging_root
    if fault == "parent_symlink":
        renamed = parent.with_name("actual-parent")
        parent.rename(renamed)
        parent.symlink_to(renamed, target_is_directory=True)
    elif fault == "ancestor_symlink":
        alias = tmp_path / "ancestor-alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        reads.owner.settings = replace(reads.owner.settings, staging_root=alias / parent.name)
    elif fault == "parent_writable":
        parent.chmod(0o777)
    else:
        child = parent / "item-similarity-publication"
        if fault == "child_symlink":
            target = tmp_path / "not-publication"
            target.mkdir()
            child.symlink_to(target, target_is_directory=True)
        else:
            child.mkdir(mode=0o755)
    with pytest.raises(SimilarityReaderRuntimeError):
        build_catalog_item_similarity_publications(
            mode="ENABLED", context_reads=reads, source_commit="a" * 40
        )
