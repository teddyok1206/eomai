#!/usr/bin/env python3
"""Source-role-aware page images; never reinterpret old contiguous-page manifests."""

import hashlib
import json

from scripts.contracts.generate_material_learning_schemas import (
    ROOT,
    SHA,
    enum,
    identifier,
    integer,
    record,
    sequence,
    text,
    version,
)


def main() -> None:
    image = record(
        input_index=integer(1, 32),
        source_role=enum("MAIN", "SOLUTIONS"),
        physical_page=integer(1, 2000),
        relative_path={
            **text(1, 80),
            "pattern": "^source/material/(?:main|solutions)/page-[0-9]{6}\\.png$",
        },
        media_type=version("image/png"),
        sha256=SHA,
        bytes=integer(24, 16 * 1024 * 1024),
        width_pixels=integer(1, 10000),
        height_pixels=integer(1, 10000),
    )
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "eom://schemas/workflow/codex-image-input-manifest/5.0",
        "title": "EOM material source page image input manifest V5",
        **record(
            schema_version=version("codex-image-input-manifest/5.0"),
            plan_id=identifier("execplan"),
            images=sequence(image, 1, 32),
            manifest_sha256=SHA,
        ),
    }
    payload = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode()
    for directory in (
        ROOT / "schemas/workflow/control-plane",
        ROOT / "packages/workflow/eom_workflow/resources/control-plane",
    ):
        (directory / "codex-image-input-manifest-v5.schema.json").write_bytes(payload)
    print("codex-image-input-manifest-v5 sha256:" + hashlib.sha256(payload).hexdigest())


if __name__ == "__main__":
    main()
