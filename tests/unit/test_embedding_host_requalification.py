"""Synthetic snapshot/ELF ports; not protected publication or native admission."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from eom_catalog_contracts.embedding_host_configuration import (
    host_configuration_snapshot_bytes,
    parse_host_configuration_snapshot,
)
from eom_catalog_service import embedding_cuda_host_closure as cuda
from eom_catalog_service import embedding_host_configuration_capture as capture
from eom_catalog_service import embedding_runtime_host_closure as host
from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots
from eom_identifiers import content_sha256

from tests.unit.test_embedding_cuda_host_closure import compose, ports
from tests.unit.test_embedding_host_configuration_contracts import snapshot_pointer
from tests.unit.test_embedding_host_configuration_files import (
    Fixture,
    _fixture,
    _mount_ports,
    _write,
)


def successor(
    original: Fixture,
    *,
    wrong_target: bool = False,
    baseline: str = host.UBUNTU_LIBLZMA_20261021_HOST_SEED_SHA256,
) -> Fixture:
    body = original.resolve().snapshot.model_dump(mode="json")
    body["configuration_revision_id"] = "embeddinghostconfigrev_" + "a" * 32
    body["baseline_host_seed_sha256"] = baseline
    if not wrong_target:
        body["host_seed_sha256"] = host.reviewed_embedding_host_configuration_seed(
            baseline_host_seed_sha256=body["baseline_host_seed_sha256"],
            cache_byte_count=body["loader_cache"]["byte_count"],
            cache_sha256=body["loader_cache"]["sha256"],
        )
    body["snapshot_sha256"] = content_sha256(
        {key: value for key, value in body.items() if key != "snapshot_sha256"}
    )
    parsed = parse_host_configuration_snapshot(body)
    directory = original.manifest.parent.parent / parsed.configuration_revision_id
    directory.mkdir(mode=0o700)
    manifest, cache = directory / "snapshot.json", directory / "ld.so.cache"
    _write(manifest, host_configuration_snapshot_bytes(parsed))
    _write(cache, original.cache.read_bytes())
    return Fixture(original.root, manifest, cache, snapshot_pointer(parsed))


def test_reviewed_snapshot_is_distinct_and_does_not_reinterpret_old_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _fixture(tmp_path, monkeypatch)
    old_raw = original.manifest.read_bytes()
    old_pointer = original.pointer
    updated = successor(original)
    new = updated.resolve()
    assert original.manifest.read_bytes() == old_raw and original.pointer == old_pointer
    old = original.resolve()
    assert old.snapshot.baseline_host_seed_sha256 == host.FIXED_EMBEDDING_HOST_SEED_SHA256
    assert new.snapshot.baseline_host_seed_sha256 == host.UBUNTU_LIBLZMA_20261021_HOST_SEED_SHA256
    assert old.snapshot.host_seed_sha256 != new.snapshot.host_seed_sha256
    assert old.pointer.snapshot_sha256 != new.pointer.snapshot_sha256
    assert old.pointer.configuration_id == new.pointer.configuration_id
    assert old.pointer.configuration_revision_id != new.pointer.configuration_revision_id


def test_new_baseline_cannot_reuse_old_target_even_with_valid_new_manifest_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    updated = successor(_fixture(tmp_path, monkeypatch), wrong_target=True)
    with pytest.raises(capture.HostConfigurationSnapshotError, match="SEED_PIN_INVALID"):
        updated.resolve()


@pytest.mark.parametrize(
    "baseline",
    [host.UBUNTU_LIBLZMA_20261021_HOST_SEED_SHA256, host.UBUNTU_GLIBC_20261114_HOST_SEED_SHA256],
)
def test_cpu_capture_passes_reviewed_files_to_existing_shared_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, baseline: str
) -> None:
    updated = successor(_fixture(tmp_path, monkeypatch), baseline=baseline)
    resolved = updated.resolve()
    _mount_ports(monkeypatch, updated)
    witness = capture.require_host_configuration_snapshot_mount(resolved)
    selected: list[Any] = []

    def shared(**kwargs: Any) -> object:
        kwargs["assert_mount_current"]()
        selected.append(kwargs)
        return sentinel

    sentinel = object()
    monkeypatch.setattr(host, "_capture_embedding_host", shared)
    result = capture.capture_snapshot_embedding_host(
        expected_seed_sha256=resolved.host_seed_sha256,
        files=NumericalRuntimeFileSnapshots(os.geteuid()),
        snapshot_mount=witness,
    )
    assert result is sentinel
    assert len(selected) == 1
    files = selected[0]["fixed_files"]
    assert files == host.reviewed_embedding_host_files(
        baseline_host_seed_sha256=resolved.baseline_host_seed_sha256,
        cache_byte_count=resolved.cache_byte_count,
        cache_sha256=resolved.cache_sha256,
    )
    assert next(row[2] for row in files if row[0].name == "liblzma.so.5.4.5") == (
        "26b37d25f7ca2a2d348de8ecabacda12e921cd933b21fa069a179760db77219d"
    )


@pytest.mark.parametrize(
    "baseline",
    [host.UBUNTU_LIBLZMA_20261021_HOST_SEED_SHA256, host.UBUNTU_GLIBC_20261114_HOST_SEED_SHA256],
)
def test_cuda_capture_selects_reviewed_base_without_changing_cuda_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, baseline: str
) -> None:
    _value, selected, witness, base, _observed = cast(Callable[..., Any], ports)(
        tmp_path, monkeypatch
    )
    changed_base = replace(
        selected.base_configuration,
        baseline_host_seed_sha256=baseline,
    )
    changed = replace(selected, base_configuration=changed_base)
    changed_witness = replace(witness, configuration=changed)
    observed: list[Any] = []

    def shared(**kwargs: Any) -> object:
        kwargs["assert_mount_current"]()
        observed.append(kwargs["fixed_files"])
        return base

    monkeypatch.setattr(host, "_capture_embedding_host", shared)
    with cast(Callable[..., Any], compose)(changed, changed_witness) as combined:
        assert type(combined) is cuda.ProtectedCudaEmbeddingHostClosure
        assert len(base.descriptors) == 6
    assert base.closed and len(observed) == 1
    assert observed[0] == host.reviewed_embedding_host_files(
        baseline_host_seed_sha256=baseline,
        cache_byte_count=changed.cache_byte_count,
        cache_sha256=changed.cache_sha256,
    )


def test_unknown_baseline_is_rejected_by_stdlib_reader_before_native_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    body = json.loads(fixture.manifest.read_bytes())
    body["baseline_host_seed_sha256"] = "sha256:" + "f" * 64
    body["snapshot_sha256"] = content_sha256(
        {key: value for key, value in body.items() if key != "snapshot_sha256"}
    )
    snapshot = parse_host_configuration_snapshot(body)
    _write(fixture.manifest, host_configuration_snapshot_bytes(snapshot))
    fixture.pointer = snapshot_pointer(snapshot)
    with pytest.raises(capture.HostConfigurationSnapshotError, match="SEED_PIN_INVALID"):
        fixture.resolve()


def test_glibc_successor_changes_only_the_eight_reviewed_package_members() -> None:
    cache = dict(
        cache_byte_count=45467,
        cache_sha256="sha256:bc2b95fdb167f457249c288055aa78a2fe3e67364b66d73a8f6d8dc745bcf3f3",
    )
    old = host.reviewed_embedding_host_files(
        baseline_host_seed_sha256=host.UBUNTU_LIBZ_20261023_HOST_SEED_SHA256, **cache
    )
    new = host.reviewed_embedding_host_files(
        baseline_host_seed_sha256=host.UBUNTU_GLIBC_20261114_HOST_SEED_SHA256, **cache
    )
    assert len(old) == len(new) == 23
    assert tuple(path for path, _, _ in old) == tuple(path for path, _, _ in new)
    old_by_path = {path: (size, sha) for path, size, sha in old}
    changed = {
        path.name: (size, sha) for path, size, sha in new if (size, sha) != old_by_path[path]
    }
    assert changed == {
        "ld-linux-x86-64.so.2": (
            236616,
            "5fc0940888e9d2e1a00e66d6b1a559c36364ee867683652e1074fa576952cc3f",
        ),
        "libc.so.6": (
            2129424,
            "755a371e86cc9f564ab54f66140747700fb0a103f698f659f2060f707897e09a",
        ),
        "libpthread.so.0": (
            14408,
            "cd34f895c9d2aa669d5d2654bed6b71210fc9003c3a1e96bb5311a40feb86039",
        ),
        "libdl.so.2": (
            14408,
            "4dbcca3c01ca84d092b5b7b2610f5835b55fc70a0288dd9d766b40ac9386e2d9",
        ),
        "libutil.so.1": (
            14408,
            "0cf9051e58789348d681a984d8e6d96334610093289b783539764a3d611921d3",
        ),
        "libm.so.6": (
            952616,
            "5dcc4d25466e29ca390ed6fabb371c69b65dff6fa4e91c34561057a020d6994a",
        ),
        "librt.so.1": (
            14624,
            "5a00236da5864e8d1123d74e616713110708d6e3e604188f4f256dab4c6941d4",
        ),
        "libresolv.so.2": (
            64008,
            "4dcb01645dbeea5d17f28fd96a730430a808d828b3b7d6a097cfbc311501f69f",
        ),
    }
    assert (
        len(
            {
                host.FIXED_EMBEDDING_HOST_SEED_SHA256,
                host.UBUNTU_LIBLZMA_20261021_HOST_SEED_SHA256,
                host.UBUNTU_LIBZ_20261023_HOST_SEED_SHA256,
                host.UBUNTU_GLIBC_20261114_HOST_SEED_SHA256,
            }
        )
        == 4
    )


def test_glibc_snapshot_requires_its_own_target_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _fixture(tmp_path, monkeypatch)
    before = original.manifest.read_bytes()
    updated = successor(original, baseline=host.UBUNTU_GLIBC_20261114_HOST_SEED_SHA256)
    assert updated.resolve().snapshot.baseline_host_seed_sha256 == (
        host.UBUNTU_GLIBC_20261114_HOST_SEED_SHA256
    )
    assert original.manifest.read_bytes() == before


def test_glibc_snapshot_cannot_rehash_an_old_host_seed_as_new_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    updated = successor(
        _fixture(tmp_path, monkeypatch),
        baseline=host.UBUNTU_GLIBC_20261114_HOST_SEED_SHA256,
        wrong_target=True,
    )
    with pytest.raises(capture.HostConfigurationSnapshotError, match="SEED_PIN_INVALID"):
        updated.resolve()
