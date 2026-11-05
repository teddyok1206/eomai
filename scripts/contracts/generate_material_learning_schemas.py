#!/usr/bin/env python3
"""Publish the reviewed mixed-material wire contracts, independently of worker code.

The small schema vocabulary is authoritative. Pydantic and runtime consumers
must validate these installed resources; this script does not infer a protocol
from a worker implementation. No dependencies beyond the standard library.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BASE = "eom://schemas/material-learning/"
TYPES = BASE + "types/1.0#/$defs/"
SHA = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}


def text(minimum: int = 1, maximum: int = 2000) -> dict[str, Any]:
    return {"type": "string", "minLength": minimum, "maxLength": maximum}


def identifier(prefix: str) -> dict[str, Any]:
    return {"type": "string", "pattern": f"^{prefix}_[0-9a-f]{{32}}$"}


def integer(minimum: int, maximum: int) -> dict[str, Any]:
    return {"type": "integer", "minimum": minimum, "maximum": maximum}


def enum(*values: str) -> dict[str, Any]:
    return {"enum": list(values)}


def sequence(value: dict[str, Any], minimum: int, maximum: int) -> dict[str, Any]:
    return {"type": "array", "items": value, "minItems": minimum, "maxItems": maximum}


def nullable(value: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [value, {"type": "null"}]}


def record(**properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }


def reference(name: str) -> dict[str, Any]:
    return {"$ref": TYPES + name}


def version(value: str) -> dict[str, Any]:
    return {"const": value}


def schemas() -> dict[str, dict[str, Any]]:
    artifact = record(
        artifact_id=identifier("artifact"),
        artifact_revision_id=identifier("rev"),
        member_path={
            **text(1, 512),
            "pattern": r"^(?!/)(?!.*(?:^|/)\.{1,2}(?:/|$))(?!.*//)[A-Za-z0-9._()가-힣/-]+$",
        },
        schema_ref={"type": "string", "pattern": "^eom://schemas/[A-Za-z0-9._/-]{1,220}$"},
        media_type={"type": "string", "pattern": "^[a-z0-9.+-]+/[A-Za-z0-9.+-]+$"},
        sha256=SHA,
        bytes=integer(1, 2 * 1024 * 1024 * 1024),
    )
    address = record(source_role=enum("MAIN", "SOLUTIONS"), physical_page=integer(1, 2000))
    region = record(
        **address["properties"],
        bounding_box={
            "$ref": "eom://schemas/legacy-assessment/legacy-assessment-types/1.0#/$defs/normalizedBoundingBox"
        },
    )
    unit = record(
        local_key={**text(1, 96), "pattern": "^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,95}$"},
        kind=enum("EXPLANATION", "QUESTION", "SOLUTION", "ANSWER_KEY"),
        section_path=sequence(text(1, 160), 0, 12),
        printed_label=nullable(text(1, 100)),
        anchors=sequence(reference("region"), 1, 32),
        continuation=enum("COMPLETE", "FROM_PREVIOUS", "TO_NEXT", "BOTH"),
        related_item_labels=sequence(text(1, 100), 0, 64),
        summary=text(1, 2000),
        warnings=sequence(text(1, 2000), 0, 16),
    )
    source = record(
        source_role=enum("MAIN", "SOLUTIONS"),
        actual_format=enum("PDF", "HWP", "HWPX"),
        original_filename=text(1, 255),
        document_id=identifier("edudoc"),
        document_revision_id=identifier("edudocrev"),
        document_manifest_sha256=SHA,
        original=reference("artifactMember"),
        pdf=reference("artifactMember"),
        page_bundle=reference("artifactMember"),
        office_catalog=nullable(reference("artifactMember")),
        page_count=integer(1, 2000),
    )
    page = record(
        input_index=integer(1, 32),
        **address["properties"],
        image=reference("artifactMember"),
        text=nullable(reference("artifactMember")),
        width_pixels=integer(1, 16384),
        height_pixels=integer(1, 16384),
    )
    definitions = {
        "artifactMember": artifact,
        "pageAddress": address,
        "region": region,
        "discoveredUnit": unit,
        "preparedSource": source,
        "inputPage": page,
    }
    upload = record(
        schema_version=version("material-learning-upload/1.0"),
        title=text(1, 200),
        material_kind=enum("TEXTBOOK", "REFERENCE_BOOK", "WORKBOOK", "MOCK_EXAM", "OTHER"),
        source_description=text(1, 2000),
        additional_instructions=text(0, 8000),
        curriculum_unit_hints={**sequence(text(1, 160), 0, 16), "uniqueItems": True},
        rights_confirmed={"const": True},
    )
    rights = record(
        schema_version=version("material-learning-rights/1.0"),
        material_id=identifier("material"),
        material_revision_id=identifier("materialrev"),
        attested_by={**text(1, 128), "pattern": "^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"},
        attested_at={"type": "string", "format": "date-time"},
        basis=version("UPLOADER_ATTESTED_INTERNAL_PROCESSING"),
        source_hashes=sequence(SHA, 1, 2),
        permitted_uses={
            **sequence(
                enum(
                    "INTERNAL_ANALYSIS", "ITEM_REGISTRATION", "GRAPH_RETRIEVAL", "LOCAL_EMBEDDING"
                ),
                4,
                4,
            ),
            "uniqueItems": True,
        },
        public_redistribution_permitted={"const": False},
        withdrawal_policy=version("DENY_NEW_RESOLUTION_PRESERVE_PINNED_AUDIT"),
        attestation_sha256=SHA,
    )
    common = {
        "material_id": identifier("material"),
        "material_revision_id": identifier("materialrev"),
        "task_id": identifier("materialtask"),
        "sources": sequence(reference("preparedSource"), 1, 2),
        "rights_attestation": reference("artifactMember"),
        "pages": sequence(reference("inputPage"), 1, 32),
        "additional_instructions": text(0, 8000),
        "input_sha256": SHA,
    }
    discovery_work = record(
        schema_version=version("material-learning-discovery-work/1.0"),
        task_kind=version("DISCOVER"),
        **common,
        core_pages=sequence(reference("pageAddress"), 1, 8),
    )
    coverage = record(
        **address["properties"],
        roles=sequence(
            enum("EXPLANATION", "QUESTION", "SOLUTION", "ANSWER_KEY", "NON_CONTENT", "UNREADABLE"),
            1,
            6,
        ),
        note=text(0, 2000),
    )
    discovery_result = record(
        schema_version=version("material-learning-discovery-result/1.0"),
        input_sha256=SHA,
        coverage=sequence(coverage, 1, 32),
        units=sequence(reference("discoveredUnit"), 0, 128),
        warnings=sequence(text(1, 2000), 0, 32),
    )
    extraction_work = record(
        schema_version=version("material-learning-extraction-work/1.0"),
        task_kind=version("EXTRACT_ITEM"),
        **common,
        unit_key=identifier("materialunit"),
        question=reference("discoveredUnit"),
        solutions=sequence(reference("discoveredUnit"), 0, 8),
    )
    old = "eom://schemas/external-item/learning-result/2.0"
    extraction_result = record(
        schema_version=version("material-learning-extraction-result/1.0"),
        input_sha256=SHA,
        status=enum("PROPOSED", "NEEDS_DECISION"),
        regions=sequence(
            {"$ref": "eom://schemas/external-item/learning-result/1.0#/$defs/region"}, 1, 64
        ),
        proposal=nullable({"$ref": old + "#/$defs/proposal"}),
        solution_report={"$ref": old + "#/$defs/solutionReport"},
        conflicts=sequence(
            {"$ref": "eom://schemas/external-item/learning-result/1.0#/$defs/conflict"}, 0, 32
        ),
        office_bindings=nullable(
            {"$ref": "eom://schemas/external-item/office-visual-bindings/1.0"}
        ),
    )
    values = {
        "types": {"$defs": definitions},
        "upload": upload,
        "rights": rights,
        "discovery-work": discovery_work,
        "discovery-result": discovery_result,
        "extraction-work": extraction_work,
        "extraction-result": extraction_result,
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
            directory.mkdir(parents=True, exist_ok=True)
            (directory / filename).write_bytes(payload)
        print(f"material-learning-{name}-v1 sha256:{hashlib.sha256(payload).hexdigest()}")
    write_workflow_schemas()


def write_workflow_schemas() -> None:
    """Add a purpose-isolated support protocol, keeping predecessor bytes frozen."""
    selection = {
        "oneOf": [
            {"$ref": BASE + "discovery-work/1.0"},
            {"$ref": BASE + "extraction-work/1.0"},
        ]
    }
    artifacts: list[tuple[str, str, dict[str, Any]]] = []
    for kind in ("input", "result"):
        predecessor = ROOT / f"schemas/workflow/roles/external-item-learning-{kind}-v3.schema.json"
        document = json.loads(predecessor.read_bytes())
        stem = f"material-learning-{kind}-v1"
        document["$id"] = f"https://eom.local/schemas/workflow/roles/{stem}.schema.json"
        document["properties"]["protocol_version"] = version("workflow-role/1.37.0")
        if kind == "input":
            document["properties"]["request"] = record(
                request_name=version("MATERIAL_LEARNING_REQUEST"),
                work_input=deepcopy(selection),
            )
        else:
            document["properties"]["output"] = record(
                learning_result={
                    "oneOf": [
                        {"$ref": BASE + "discovery-result/1.0"},
                        {"$ref": BASE + "extraction-result/1.0"},
                    ]
                }
            )
        artifacts.append(("roles", stem, document))
    document = json.loads(
        (
            ROOT / "schemas/workflow/control-plane/resolved-execution-plan-v32.schema.json"
        ).read_bytes()
    )
    document.update(
        title="Mixed-material sequential learning resolved execution plan V33",
    )
    document["$id"] = "eom://schemas/workflow/resolved-execution-plan/33.0"
    document["properties"].update(
        schema_version=version("resolved-execution-plan/33.0"),
        workflow_definition_key=version("material-learning"),
        workflow_definition_version=version("1.0.0"),
        resolver_version=version("33.0.0"),
        work_input=deepcopy(selection),
    )
    document["properties"]["steps"]["items"]["properties"]["step_key"] = version("learn")
    artifacts.append(("control-plane", "resolved-execution-plan-v33", document))
    for directory, stem, document in artifacts:
        payload = (
            json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode()
        for parent in (
            ROOT / "schemas/workflow",
            ROOT / "packages/workflow/eom_workflow/resources",
        ):
            (parent / directory / (stem + ".schema.json")).write_bytes(payload)
        print(f"{stem} sha256:{hashlib.sha256(payload).hexdigest()}")


if __name__ == "__main__":
    main()
