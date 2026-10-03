#!/usr/bin/env python3
"""Thin operator CLI; execute in the explicit image trainer Conda environment."""

from __future__ import annotations

import argparse
from pathlib import Path

from eom_image_provider.informative_lineart_acquisition import acquire_informative_lineart_model
from eom_image_provider.informative_lineart_download import fetch_informative_lineart_member
from eom_image_provider.provider import ProviderError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--created-by", required=True)
    args = parser.parse_args()
    try:
        result = acquire_informative_lineart_model(
            args.staging_root, created_by=args.created_by, fetch=fetch_informative_lineart_member
        )
    except ProviderError as exc:
        print(f"ACQUISITION=FAILED code={exc.code}")
        return 1
    print("ACQUISITION=PASS activation=FORBIDDEN")
    print(f"EXTRACTOR_ID={result.manifest.extractor_id}")
    print(f"EXTRACTOR_REVISION_ID={result.manifest.extractor_revision_id}")
    print(f"MANIFEST_SEMANTIC_SHA256={result.manifest.manifest_sha256}")
    print(f"TENSOR_COUNT={result.tensor_count} PARAMETER_COUNT={result.parameter_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
