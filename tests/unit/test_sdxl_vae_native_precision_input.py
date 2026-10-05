"""Exercise the real descriptor-bound diagnostic read without loading Torch/CUDA."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
from eom_image_provider.provider import ProviderError

from tests.integration.test_sdxl_vae_native_precision import _read_real_target


def test_diagnostic_reader_uses_verified_descriptor_and_exact_hash(tmp_path: Path) -> None:
    raw = b"bounded input-read fixture, not a model or image"
    path = tmp_path / "fan.png"
    path.write_bytes(raw)
    path.chmod(0o400)
    assert _read_real_target(tmp_path, "fan", hashlib.sha256(raw).hexdigest()) == raw
    assert "torch" not in sys.modules


def test_diagnostic_reader_rejects_hash_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "fan.png"
    path.write_bytes(b"untrusted fixture")
    path.chmod(0o400)
    with pytest.raises(ProviderError, match="HASH_MISMATCH"):
        _read_real_target(tmp_path, "fan", "0" * 64)


def test_diagnostic_reader_rejects_symlink_and_traversal(tmp_path: Path) -> None:
    target = tmp_path / "real.png"
    target.write_bytes(b"untrusted fixture")
    target.chmod(0o400)
    (tmp_path / "fan.png").symlink_to(target)
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(ProviderError, match="INPUT_INVALID"):
        _read_real_target(tmp_path, "fan", sha)
    with pytest.raises(ProviderError, match="INPUT_INVALID"):
        _read_real_target(tmp_path, "../real", sha)
