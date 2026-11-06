#!/usr/bin/env python3
"""Bounded page resources and generic document pointers, before parsing/runtime code."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from scripts.contracts.generate_material_learning_schemas import (
    BASE,
    ROOT,
    SHA,
    enum,
    identifier,
    integer,
    nullable,
    record,
    reference,
    sequence,
    text,
    version,
)

_DEFS = BASE + "preparation-types/1.0#/$defs/"
_COMMIT = {"type": "string", "pattern": "^[0-9a-f]{40}$"}
_TIME = {"type": "string", "format": "date-time"}


def ref(name: str) -> dict[str, Any]:
    return {"$ref": _DEFS + name}


def schemas() -> dict[str, dict[str, Any]]:
    member = record(
        member_path={
            **text(1, 240),
            "pattern": "^analysis/(?:pages|images)/page-[0-9]{6}\\.(?:md|png)$",
        },
        schema_ref={"type": "string", "pattern": "^eom://schemas/[A-Za-z0-9._/-]{1,220}$"},
        media_type=enum("text/markdown", "image/png"),
        sha256=SHA,
        bytes=integer(1, 64 * 1024 * 1024),
    )
    page = record(
        physical_page=integer(1, 2000),
        text=ref("pageMember"),
        image=ref("pageMember"),
        width_pixels=integer(1, 10000),
        height_pixels=integer(1, 10000),
        render_dpi=integer(120, 400),
    )
    extractor = record(
        implementation=text(1, 128),
        version=text(1, 128),
        implementation_sha256=SHA,
        options_sha256=SHA,
    )
    profile = record(
        schema_version=version("material-learning-preparation-profile/1.0"),
        source_commit=_COMMIT,
        extractor=ref("extractor"),
        office_tool_source_commit=nullable(_COMMIT),
        libreoffice_sha256=nullable(SHA),
        h2orestart_sha256=nullable(SHA),
        maximum_pages=integer(1, 2000),
        maximum_rendered_bytes=integer(1, 4 * 1024 * 1024 * 1024),
        chunk_page_limit=integer(1, 256),
        chunk_soft_bytes=integer(64 * 1024 * 1024, 512 * 1024 * 1024),
        profile_sha256=SHA,
    )
    conversion = record(
        conversion_kind=enum("IDENTITY_PDF", "LIBREOFFICE_H2ORESTART_PDF"),
        review_pdf_sha256=SHA,
        libreoffice_version=nullable(text(1, 128)),
        libreoffice_sha256=nullable(SHA),
        h2orestart_sha256=nullable(SHA),
    )
    chunk = record(
        schema_version=version("material-learning-page-chunk/1.0"),
        document_id=identifier("edudoc"),
        document_revision_id=identifier("edudocrev"),
        source_role=enum("MAIN", "SOLUTIONS"),
        pdf_sha256=SHA,
        profile_sha256=SHA,
        first_physical_page=integer(1, 2000),
        last_physical_page=integer(1, 2000),
        pages=sequence(ref("page"), 1, 256),
    )
    chunk_reference = record(
        manifest=reference("artifactMember"),
        first_physical_page=integer(1, 2000),
        last_physical_page=integer(1, 2000),
        content_bytes=integer(1, 1024 * 1024 * 1024),
    )
    bundle = record(
        schema_version=version("material-learning-page-bundle/1.0"),
        document_id=identifier("edudoc"),
        document_revision_id=identifier("edudocrev"),
        source_role=enum("MAIN", "SOLUTIONS"),
        original=reference("artifactMember"),
        pdf=reference("artifactMember"),
        conversion=ref("conversion"),
        profile=ref("profile"),
        page_count=integer(1, 2000),
        chunks=sequence(ref("chunkReference"), 1, 2000),
        office_catalog=nullable(reference("artifactMember")),
    )
    document = record(
        schema_version=version("material-learning-document-revision/1.0"),
        document_id=identifier("edudoc"),
        document_revision_id=identifier("edudocrev"),
        document_key={**text(3, 128), "pattern": "^[a-z][a-z0-9-]{2,127}$"},
        revision_number={"const": 1},
        previous_revision_id={"type": "null"},
        material_id=identifier("material"),
        material_revision_id=identifier("materialrev"),
        source_role=enum("MAIN", "SOLUTIONS"),
        document_kind=enum("TEXTBOOK", "REFERENCE_BOOK", "GUIDANCE"),
        source_class=enum("TEXTBOOK", "INTERNAL_GUIDE"),
        title=text(1, 200),
        source_description=text(1, 2000),
        publisher_key={"type": "null"},
        curriculum_volume={"type": "null"},
        edition_label={"type": "null"},
        original=reference("artifactMember"),
        source=reference("artifactMember"),
        source_page_count=integer(1, 2000),
        analysis_bundle_manifest=reference("artifactMember"),
        rights_attestation=reference("artifactMember"),
        registered_by=identifier("operator"),
        registered_at=_TIME,
        registration_request_sha256=SHA,
        document_revision_sha256=SHA,
    )
    prepared = record(
        schema_version=version("material-learning-prepared/1.0"),
        material_id=identifier("material"),
        material_revision_id=identifier("materialrev"),
        intake_manifest=reference("artifactMember"),
        profile_sha256=SHA,
        sources=sequence(reference("preparedSource"), 1, 2),
        prepared_sha256=SHA,
    )
    preparation_input = record(
        schema_version=version("material-learning-preparation-input/1.0"),
        task_id=identifier("materialtask"),
        material_id=identifier("material"),
        material_revision_id=identifier("materialrev"),
        intake_manifest=reference("artifactMember"),
        profile=ref("profile"),
        input_sha256=SHA,
    )
    values = {
        "preparation-types": {
            "$defs": {
                "pageMember": member,
                "page": page,
                "extractor": extractor,
                "profile": profile,
                "conversion": conversion,
                "chunkReference": chunk_reference,
            }
        },
        "preparation-input": preparation_input,
        "pdf-projection": record(
            schema_version=version("material-learning-pdf-projection/1.0"),
            source_sha256=SHA,
            profile_sha256=SHA,
            conversion=ref("conversion"),
            pdf_bytes=integer(8, 256 * 1024 * 1024),
            office_catalog=reference("artifactMember"),
        ),
        "page-chunk": chunk,
        "page-bundle": bundle,
        "document-revision": document,
        "document-receipt": record(
            schema_version=version("material-learning-document-receipt/1.0"),
            document_id=identifier("edudoc"),
            document_revision_id=identifier("edudocrev"),
            revision_number={"const": 1},
            registration_request_sha256=SHA,
            revision_manifest=reference("artifactMember"),
            original=reference("artifactMember"),
            source=reference("artifactMember"),
            analysis_bundle_manifest=reference("artifactMember"),
            rights_attestation=reference("artifactMember"),
        ),
        "prepared": prepared,
        "office-command": record(
            schema_version=version("material-learning-office-command/1.0"),
            operation=enum("CREATE", "CONVERT", "READ"),
            instance_id={**text(43, 43), "pattern": "^officeconv_[0-9a-f]{32}$"},
            source_format=enum("HWP", "HWPX"),
            source_sha256=nullable(SHA),
        ),
        "office-reply": record(
            schema_version=version("material-learning-office-reply/1.0"),
            operation=enum("CREATE", "CONVERT", "READ"),
            instance_id={**text(43, 43), "pattern": "^officeconv_[0-9a-f]{32}$"},
            source_sha256=nullable(SHA),
            conversion=nullable(ref("conversion")),
        ),
    }
    return {
        name: {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": BASE + name + "/1.0",
            "title": f"EOM material learning {name} 1.0",
            **value,
        }
        for name, value in values.items()
    }


def main() -> None:
    for name, document in schemas().items():
        payload = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode()
        filename = f"material-learning-{name}-v1.schema.json"
        for directory in (
            ROOT / "schemas/material-learning",
            ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/material-learning",
        ):
            (directory / filename).write_bytes(payload)
        print(f"material-learning-{name}-v1 sha256:{hashlib.sha256(payload).hexdigest()}")


if __name__ == "__main__":
    main()
