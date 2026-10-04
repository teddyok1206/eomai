#!/usr/bin/env python3
"""Thin operator CLI: install a typed extractor pointer, never activate a production model."""

from __future__ import annotations

import argparse
import grp
import json
import pwd
from pathlib import Path

from eom_image_contracts import InformativeLineartPointer
from eom_image_provider.informative_lineart_installation import install_informative_lineart_revision


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--model-store-root", type=Path, required=True)
    parser.add_argument("--extractor-id", required=True)
    parser.add_argument("--extractor-revision-id", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    pointer = InformativeLineartPointer(
        extractor_id=args.extractor_id,
        extractor_revision_id=args.extractor_revision_id,
        manifest_sha256=args.manifest_sha256,
        provider_family="informative-drawings-style1",
        runtime_contract_version="eom-informative-lineart-extractor/1.0",
    )
    manifest = install_informative_lineart_revision(
        source=args.source,
        model_store_root=args.model_store_root,
        pointer=pointer,
        source_owner_uid=pwd.getpwnam("eom").pw_uid,
        worker_group_gid=grp.getgrnam("eom-image").gr_gid,
    )
    print(
        json.dumps(
            {
                "install": "READY",
                **pointer.model_dump(mode="json"),
                "state": manifest.state,
                "production_activation": "UNCHANGED",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
