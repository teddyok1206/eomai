"""Uploaded-question lineage; no invented legacy archive or exam identity."""

import hashlib
import json

from scripts.contracts.generate_material_learning_schemas import (
    BASE,
    ROOT,
    SHA,
    enum,
    identifier,
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
    value = schema()
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    for directory in (
        ROOT / "schemas/material-learning",
        ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/material-learning",
    ):
        (directory / "item-lineage-v1.schema.json").write_bytes(data)
    print("material-learning-item-lineage-v1 sha256:" + hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    main()
