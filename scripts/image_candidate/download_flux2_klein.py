#!/usr/bin/env python3
"""Download only the Diffusers component tree for the pinned FLUX.2 candidate."""

from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path

from huggingface_hub import snapshot_download  # type: ignore[import-not-found]

REPO_ID = "black-forest-labs/FLUX.2-klein-base-4B"
REVISION = "a3b4f4849157f664bdbc776fd7453c2783562f4d"
ALLOWED_PREFIXES = ("scheduler/", "text_encoder/", "tokenizer/", "transformer/", "vae/")
ALLOW_PATTERNS = ("model_index.json", *(prefix + "*" for prefix in ALLOWED_PREFIXES))


def _validate_destination(path: Path) -> None:
    if (
        not path.is_absolute()
        or path.parent != Path("/tmp")
        or not path.name.startswith("eom-flux2-klein-base-4b.")
        or path.exists()
        or path.is_symlink()
    ):
        raise SystemExit("FLUX2_DOWNLOAD_DESTINATION_INVALID")


def _validate_tree(path: Path) -> None:
    files: set[str] = set()
    for candidate in path.rglob("*"):
        metadata = candidate.lstat()
        relative = candidate.relative_to(path).as_posix()
        if stat.S_ISLNK(metadata.st_mode):
            raise SystemExit("FLUX2_DOWNLOAD_TREE_INVALID")
        if stat.S_ISREG(metadata.st_mode):
            if relative == "model_index.json" or relative.startswith(ALLOWED_PREFIXES):
                files.add(relative)
            else:
                raise SystemExit("FLUX2_DOWNLOAD_TREE_INVALID")
        elif not stat.S_ISDIR(metadata.st_mode):
            raise SystemExit("FLUX2_DOWNLOAD_TREE_INVALID")
    required = {
        "model_index.json",
        "scheduler/scheduler_config.json",
        "text_encoder/config.json",
        "text_encoder/model.safetensors.index.json",
        "tokenizer/tokenizer.json",
        "tokenizer/tokenizer_config.json",
        "transformer/config.json",
        "transformer/diffusion_pytorch_model.safetensors",
        "vae/config.json",
        "vae/diffusion_pytorch_model.safetensors",
    }
    if not required.issubset(files) or not any(
        value.startswith("text_encoder/model-") and value.endswith(".safetensors")
        for value in files
    ):
        raise SystemExit("FLUX2_DOWNLOAD_TREE_INCOMPLETE")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    destination = args.destination
    _validate_destination(destination)
    os.mkdir(destination, mode=0o700)
    snapshot_download(
        repo_id=REPO_ID,
        revision=REVISION,
        local_dir=destination,
        allow_patterns=list(ALLOW_PATTERNS),
    )
    cache = destination / ".cache"
    if cache.exists():
        if cache.is_symlink() or cache.parent != destination:
            raise SystemExit("FLUX2_DOWNLOAD_CACHE_INVALID")
        import shutil

        shutil.rmtree(cache)
    _validate_tree(destination)
    print(f"FLUX2_DOWNLOAD_ROOT={destination}")
    print(f"FLUX2_UPSTREAM_REVISION={REVISION}")


if __name__ == "__main__":
    main()
