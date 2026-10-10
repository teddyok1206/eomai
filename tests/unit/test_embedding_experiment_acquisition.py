from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from scripts.embedding import acquire_e5_small_probe as acquisition


@pytest.fixture
def pinned_runtime_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    versions = {
        "safetensors": "0.6.2",
        "tokenizers": "0.22.2",
        "torch": "2.7.1+cpu",
        "transformers": "4.56.2",
    }
    monkeypatch.setattr(acquisition.importlib.metadata, "version", versions.__getitem__)


def test_official_probe_recipe_has_exact_safe_byte_inventory(pinned_runtime_versions: None) -> None:
    spec = acquisition.experiment_spec()
    assert spec.upstream_revision == "614241f622f53c4eeff9890bdc4f31cfecc418b3"
    assert sum(value.size_bytes for value in spec.files) == 492_794_846
    assert spec.document_prefix == spec.query_prefix == "query: "
    assert spec.pooling == "MEAN" and spec.dimension == 384
    assert spec.truncation == "REJECT_OVERFLOW"
    assert all(not member.member_path.endswith(".bin") for member in spec.files)


def test_relative_or_symlink_store_is_rejected_before_acquisition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_network(*_args: object, **_kwargs: object) -> None:
        pytest.fail("invalid model store must not start a download")

    monkeypatch.setattr(acquisition, "urlopen", forbidden_network)
    with pytest.raises(ValueError, match="absolute nonsymlink"):
        acquisition.acquire(Path("relative"))
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="absolute nonsymlink"):
        acquisition.acquire(link)
    actual = tmp_path / "actual"
    actual.mkdir()
    with pytest.raises(ValueError, match="absolute nonsymlink"):
        acquisition.acquire(link / "actual")


def test_group_writable_store_is_rejected_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o770)

    def forbidden_network(*_args: object, **_kwargs: object) -> None:
        pytest.fail("unsafe model store must not start a download")

    monkeypatch.setattr(acquisition, "urlopen", forbidden_network)
    with pytest.raises(ValueError, match="nonwritable-by-others"):
        acquisition.acquire(tmp_path)


def test_fake_acquisition_hashes_every_byte_and_never_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pinned_runtime_versions: None
) -> None:
    # Tiny fake files test acquisition; no model, corpus or network is consumed.
    payload = b"synthetic-safe-file"
    files = tuple(
        (name, len(payload), hashlib.sha256(payload).hexdigest())
        for name, _size, _digest in acquisition.FILES
    )
    monkeypatch.setattr(acquisition, "FILES", files)
    monkeypatch.setattr(acquisition, "urlopen", lambda *_args, **_kwargs: io.BytesIO(payload))
    spec = acquisition.acquire(tmp_path)
    snapshot = tmp_path / spec.model_id / spec.model_revision_id
    assert (snapshot / "manifest.json").stat().st_mode & 0o777 == 0o400
    for name, _size, _digest in files:
        assert (snapshot / name).read_bytes() == payload
        assert (snapshot / name).stat().st_mode & 0o777 == 0o400
    with pytest.raises(FileExistsError):
        acquisition.acquire(tmp_path)


def test_fake_acquisition_hash_mismatch_never_publishes_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pinned_runtime_versions: None
) -> None:
    payload = b"wrong"
    files = tuple(
        (name, len(payload), hashlib.sha256(b"right").hexdigest())
        for name, _size, _digest in acquisition.FILES
    )
    monkeypatch.setattr(acquisition, "FILES", files)
    monkeypatch.setattr(acquisition, "urlopen", lambda *_args, **_kwargs: io.BytesIO(payload))
    with pytest.raises(ValueError, match="differs from pinned"):
        acquisition.acquire(tmp_path)
    assert not tuple(tmp_path.rglob("manifest.json"))
