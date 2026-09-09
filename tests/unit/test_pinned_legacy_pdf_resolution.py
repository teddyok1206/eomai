from __future__ import annotations

import os
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts import LegacyRootAlias, LegacySourceInventoryEntry
from eom_catalog_service.legacy_source_inventory import LegacySourceRootConfiguration
from eom_catalog_service.pinned_legacy_pdf_resolution import (
    PinnedLegacyPdfResolutionError,
    resolve_pinned_legacy_pdf_sources,
)
from eom_identifiers import sha256_bytes


def _root_configuration(
    root: Path,
    *,
    alias: LegacyRootAlias = LegacyRootAlias.EOMIS_LEGACY_SOURCE,
    revision_marker: str = "4",
) -> LegacySourceRootConfiguration:
    return LegacySourceRootConfiguration.model_validate(
        {
            "schema_version": "legacy-source-root-configuration/1.0",
            "configuration_revision_id": "legacyrootconfigrev_" + revision_marker * 32,
            "roots": [
                {
                    "root_alias": alias.value,
                    "configuration_identity": "legacyroot_" + "5" * 32,
                    "absolute_path": str(root),
                }
            ],
        }
    )


def _entry(ordinal: int, relative_path: str, payload: bytes) -> LegacySourceInventoryEntry:
    return LegacySourceInventoryEntry.model_validate(
        {
            "entry_key": "legacyentry_" + f"{ordinal:032x}",
            "relative_path": relative_path,
            "file_observation": "REGULAR",
            "size_bytes": len(payload),
            "media_type": "application/pdf",
            "content_sha256": sha256_bytes(payload),
            "preliminary_class": "ORIGINAL_SOURCE_CANDIDATE",
            "source_family": "ITEM",
            "canonicality": "ORIGINAL",
            "rights_state": "UNREVIEWED",
            "relation_group_key": None,
            "exclusion_reasons": [],
        }
    )


def _fixture(
    tmp_path: Path,
) -> tuple[Path, LegacySourceRootConfiguration, tuple[LegacySourceInventoryEntry, ...]]:
    root = tmp_path / "legacy"
    pdf_directory = root / "pdfs"
    pdf_directory.mkdir(parents=True)
    entries = []
    for ordinal in range(50):
        payload = f"%PDF-1.7\nfixture-{ordinal:02d}\n%%EOF\n".encode()
        relative_path = f"pdfs/{ordinal:02d}.pdf"
        (root / relative_path).write_bytes(payload)
        entries.append(_entry(ordinal, relative_path, payload))
    return root, _root_configuration(root), tuple(entries)


def _arguments(
    roots: LegacySourceRootConfiguration,
    entries: tuple[LegacySourceInventoryEntry, ...],
) -> dict[str, Any]:
    alias = LegacyRootAlias.EOMIS_LEGACY_SOURCE
    return {
        "roots": roots,
        "inventory_root_alias": alias,
        "inventory_root_configuration_sha256": roots.identity_sha256(alias),
        "entries": entries,
    }


def test_resolves_exact_50_pdfs_to_frozen_metadata_only(tmp_path: Path) -> None:
    _, roots, entries = _fixture(tmp_path)

    resolved = resolve_pinned_legacy_pdf_sources(**_arguments(roots, entries))

    assert len(resolved) == 50
    assert resolved[0].entry_key == entries[0].entry_key
    assert resolved[0].relative_path == entries[0].relative_path
    assert resolved[0].byte_size == entries[0].size_bytes
    assert resolved[0].content_sha256 == entries[0].content_sha256
    assert not hasattr(resolved[0], "payload")
    with pytest.raises(FrozenInstanceError):
        resolved[0].byte_size = 0  # type: ignore[misc]


def test_requires_exactly_50_inventory_entries(tmp_path: Path) -> None:
    _, roots, entries = _fixture(tmp_path)

    with pytest.raises(PinnedLegacyPdfResolutionError, match="inventory is invalid"):
        resolve_pinned_legacy_pdf_sources(**_arguments(roots, entries[:-1]))


def test_missing_source_fails(tmp_path: Path) -> None:
    root, roots, entries = _fixture(tmp_path)
    (root / entries[0].relative_path).unlink()

    with pytest.raises(PinnedLegacyPdfResolutionError, match="source bytes do not resolve"):
        resolve_pinned_legacy_pdf_sources(**_arguments(roots, entries))


def test_inventory_alias_drift_fails(tmp_path: Path) -> None:
    _, roots, entries = _fixture(tmp_path)
    arguments = _arguments(roots, entries)
    arguments["inventory_root_alias"] = LegacyRootAlias.EOM_AI_SERVER_LEGACY_SOURCE

    with pytest.raises(PinnedLegacyPdfResolutionError, match="configuration does not resolve"):
        resolve_pinned_legacy_pdf_sources(**arguments)


def test_inventory_root_configuration_drift_fails(tmp_path: Path) -> None:
    root, roots, entries = _fixture(tmp_path)
    drifted = _root_configuration(root, revision_marker="6")
    arguments = _arguments(drifted, entries)
    arguments["inventory_root_configuration_sha256"] = roots.identity_sha256(
        LegacyRootAlias.EOMIS_LEGACY_SOURCE
    )

    with pytest.raises(PinnedLegacyPdfResolutionError, match="configuration does not resolve"):
        resolve_pinned_legacy_pdf_sources(**arguments)


@pytest.mark.parametrize("defect", ["entry_key", "relative_path"])
def test_duplicate_inventory_identity_fails(tmp_path: Path, defect: str) -> None:
    _, roots, entries = _fixture(tmp_path)
    update = {defect: getattr(entries[0], defect)}
    duplicate = entries[1].model_copy(update=update)
    changed = (entries[0], duplicate, *entries[2:])

    with pytest.raises(PinnedLegacyPdfResolutionError, match="inventory is invalid"):
        resolve_pinned_legacy_pdf_sources(**_arguments(roots, changed))


def test_noncanonical_inventory_order_fails(tmp_path: Path) -> None:
    _, roots, entries = _fixture(tmp_path)
    changed = (entries[1], entries[0], *entries[2:])

    with pytest.raises(PinnedLegacyPdfResolutionError, match="inventory is invalid"):
        resolve_pinned_legacy_pdf_sources(**_arguments(roots, changed))


@pytest.mark.parametrize(
    "relative_path",
    ["/absolute.pdf", "./dot.pdf", "pdfs/../escape.pdf", "pdfs\\escape.pdf", "bad\x00.pdf"],
)
def test_unsafe_relative_path_fails(tmp_path: Path, relative_path: str) -> None:
    _, roots, entries = _fixture(tmp_path)
    changed = (entries[0].model_copy(update={"relative_path": relative_path}), *entries[1:])

    with pytest.raises(PinnedLegacyPdfResolutionError, match="inventory is invalid"):
        resolve_pinned_legacy_pdf_sources(**_arguments(roots, changed))


def test_intermediate_symlink_fails(tmp_path: Path) -> None:
    root, roots, entries = _fixture(tmp_path)
    outside = tmp_path / "outside"
    (root / "pdfs").rename(outside)
    (root / "pdfs").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PinnedLegacyPdfResolutionError, match="source bytes do not resolve"):
        resolve_pinned_legacy_pdf_sources(**_arguments(roots, entries))


def test_final_symlink_fails(tmp_path: Path) -> None:
    root, roots, entries = _fixture(tmp_path)
    target = root / entries[0].relative_path
    outside = tmp_path / "outside.pdf"
    target.rename(outside)
    target.symlink_to(outside)

    with pytest.raises(PinnedLegacyPdfResolutionError, match="source bytes do not resolve"):
        resolve_pinned_legacy_pdf_sources(**_arguments(roots, entries))


def test_hardlinked_source_fails(tmp_path: Path) -> None:
    root, roots, entries = _fixture(tmp_path)
    os.link(root / entries[0].relative_path, root / "second-link.pdf")

    with pytest.raises(PinnedLegacyPdfResolutionError, match="source bytes do not resolve"):
        resolve_pinned_legacy_pdf_sources(**_arguments(roots, entries))


def test_non_regular_source_fails_without_blocking(tmp_path: Path) -> None:
    root, roots, entries = _fixture(tmp_path)
    target = root / entries[0].relative_path
    target.unlink()
    os.mkfifo(target)

    with pytest.raises(PinnedLegacyPdfResolutionError, match="source bytes do not resolve"):
        resolve_pinned_legacy_pdf_sources(**_arguments(roots, entries))


@pytest.mark.parametrize("defect", ["size", "hash"])
def test_size_or_hash_drift_fails(tmp_path: Path, defect: str) -> None:
    _, roots, entries = _fixture(tmp_path)
    update: dict[str, object]
    if defect == "size":
        update = {"size_bytes": entries[0].size_bytes + 1}
    else:
        update = {"content_sha256": "sha256:" + "f" * 64}
    changed = (entries[0].model_copy(update=update), *entries[1:])

    with pytest.raises(PinnedLegacyPdfResolutionError, match="source bytes do not resolve"):
        resolve_pinned_legacy_pdf_sources(**_arguments(roots, changed))


def test_mid_read_ctime_change_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, roots, entries = _fixture(tmp_path)
    target = root / entries[0].relative_path
    original_mode = target.stat().st_mode & 0o777
    real_read = os.read
    changed = False

    def mutate_after_read(descriptor: int, count: int) -> bytes:
        nonlocal changed
        chunk = real_read(descriptor, count)
        if chunk and not changed:
            changed = True
            target.chmod(0o600)
            target.chmod(original_mode)
        return chunk

    monkeypatch.setattr(
        "eom_catalog_service.pinned_legacy_pdf_resolution.os.read", mutate_after_read
    )

    with pytest.raises(PinnedLegacyPdfResolutionError, match="source bytes do not resolve"):
        resolve_pinned_legacy_pdf_sources(**_arguments(roots, entries))
    assert changed


def test_wrong_inventory_media_type_fails(tmp_path: Path) -> None:
    _, roots, entries = _fixture(tmp_path)
    changed = (
        entries[0].model_copy(update={"media_type": "application/octet-stream"}),
        *entries[1:],
    )

    with pytest.raises(PinnedLegacyPdfResolutionError, match="inventory is invalid"):
        resolve_pinned_legacy_pdf_sources(**_arguments(roots, changed))
