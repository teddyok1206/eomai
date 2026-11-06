"""Uploaded-question lineage; no invented legacy archive or exam identity."""

import hashlib
import json

from scripts.contracts.generate_material_learning_schemas import (
    BASE,
    ROOT,
    SHA,
    enum,
    identifier,
    integer,
    record,
    reference,
    sequence,
    text,
    version,
)


def schema():
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": BASE + "item-lineage/1.0",
        "title": "EOM uploaded material Item source-fidelity lineage",
        **record(
            schema_version=version("material-learning-item-lineage/1.0"),
            material_id=identifier("material"),
            material_revision_id=identifier("materialrev"),
            task_id=identifier("materialtask"),
            unit_key=text(1, 128),
            selection={"$ref": BASE + "authorization-request/1.0"},
            work_input=reference("artifactMember"),
            role_result={
                "$ref": "eom://schemas/external-item/creative-source-lineage/1.0#/$defs/member"
            },
            input_sha256=SHA,
            result_sha256=SHA,
            proposed_content_sha256=SHA,
            registered_content_sha256=SHA,
            source_answer_mode=enum(
                "EDITORIAL_SOURCE", "MODEL_PROPOSAL_UNVERIFIED", "NOT_APPLICABLE"
            ),
            warning_codes=sequence(text(1, 128), 0, 64),
            registration_policy=version("PRESERVE_SOURCE_WITH_REVIEW_WARNINGS_V1"),
            requested_by=identifier("operator"),
            created_at={"type": "string", "format": "date-time", "pattern": "Z$"},
            lineage_sha256=SHA,
        ),
    }


def main():
    for name, value in (
        ("item-lineage-v1", schema()),
        ("visual-set-v1", visual_schema()),
        ("item-metadata-v1", metadata_schema()),
        ("db-entry-v1", db_entry_schema()),
    ):
        data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
        for directory in (
            ROOT / "schemas/material-learning",
            ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/material-learning",
        ):
            (directory / (name + ".schema.json")).write_bytes(data)
        print("material-learning-" + name + " sha256:" + hashlib.sha256(data).hexdigest())


def metadata_schema():
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": BASE + "item-metadata/1.0",
        **record(
            item_type_key=version("uploaded-material-item"),
            source_kind=version("EXTERNAL"),
            material_id=identifier("material"),
            material_revision_id=identifier("materialrev"),
            unit_key=text(1, 128),
            title=text(1, 512),
            source_filename=text(1, 255),
            printed_label={"anyOf": [text(1, 100), {"type": "null"}]},
            section_path=sequence(text(1, 200), 0, 12),
            physical_pages={**sequence(integer(1, 2000), 1, 32), "uniqueItems": True},
            lineage_sha256=SHA,
            approval_basis=version("SOURCE_IMPORT_AUTOMATION_NOT_SCIENTIFIC_VERIFICATION"),
        ),
    }


def db_entry_schema():
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": BASE + "db-entry/1.0",
        **record(
            schema_version=version("material-item-db-entry/1.0"),
            metadata={"$ref": BASE + "item-metadata/1.0"},
            material_title=text(1, 200),
            registration={
                **record(
                    item_id=identifier("item"),
                    item_revision_id=identifier("itemrev"),
                    item_manifest_sha256=SHA,
                    approval_state=enum(
                        "DRAFT", "IN_REVIEW", "APPROVED", "REJECTED", "SUPERSEDED", "RETIRED"
                    ),
                    difficulty_band={"anyOf": [text(1, 64), {"type": "null"}]},
                    item_type_key=text(1, 128),
                ),
            },
        ),
    }


def visual_schema():
    crop = record(
        source_region_id=identifier("extregion"),
        input_index=integer(1, 32),
        source_role=enum("MAIN", "SOLUTIONS"),
        physical_page=integer(1, 2000),
        source_page=reference("artifactMember"),
        pdf=reference("artifactMember"),
        render_dpi=integer(120, 400),
        pixel_box=sequence(integer(0, 10000), 4, 4),
        member_path={**text(1, 100), "pattern": r"^images/extregion_[0-9a-f]{32}\.png$"},
        sha256=SHA,
        width_px=integer(1, 10000),
        height_px=integer(1, 10000),
        bytes=integer(1, 16 * 1024 * 1024),
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": BASE + "visual-set/1.0",
        "title": "EOM exact PDF material visual derivation; Hancom uses native pictures",
        **record(
            schema_version=version("material-learning-visual-set/1.0"),
            input_sha256=SHA,
            result_sha256=SHA,
            role_result={
                "$ref": "eom://schemas/external-item/creative-source-lineage/1.0#/$defs/member"
            },
            pdftoppm_sha256=SHA,
            crops=sequence(crop, 1, 64),
            manifest_sha256=SHA,
        ),
    }


if __name__ == "__main__":
    main()
