#!/usr/bin/env python3
"""Generic uploaded document successors; old licensed textbook contracts stay closed."""

from __future__ import annotations

import copy
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

KNOWLEDGE = "eom://schemas/knowledge/"
SOURCE = KNOWLEDGE + "educational-document-source/5.0"


def old(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "schemas/knowledge" / (name + ".schema.json")).read_text())


def source_schema() -> dict[str, Any]:
    old_types = old("knowledge-analysis-types-v4")
    old_source = old_types["$defs"]["documentRevisionSource"]
    member = record(
        member_kind=enum("PAGE_TEXT", "PAGE_IMAGE"),
        physical_page=integer(1, 2000),
        artifact_id=identifier("artifact"),
        artifact_revision_id=identifier("rev"),
        member_path={
            **text(1, 80),
            "pattern": "^analysis/(?:pages/page-[0-9]{6}\\.md|images/page-[0-9]{6}\\.png)$",
        },
        materialized_path={
            **text(1, 80),
            "pattern": "^source/document/(?:pages/page-[0-9]{6}\\.md|images/page-[0-9]{6}\\.png)$",
        },
        sha256=SHA,
        bytes=integer(1, 16 * 1024 * 1024),
        schema_ref=enum(
            BASE + "page-text/1.0", "eom://schemas/educational-document/page-image/1.0"
        ),
        media_type=enum("text/markdown", "image/png"),
        logical_name={**text(1, 32), "pattern": "^page-[0-9]{6}\\.(?:md|png)$"},
        width_pixels=nullable(integer(1, 10000)),
        height_pixels=nullable(integer(1, 10000)),
    )
    source = record(
        source_kind=version("DOCUMENT_REVISION"),
        source_profile=version("UPLOADED_MATERIAL_V1"),
        source_class=enum("TEXTBOOK", "INTERNAL_GUIDE"),
        material_id=identifier("material"),
        material_revision_id=identifier("materialrev"),
        source_role=enum("MAIN", "SOLUTIONS"),
        document_id=identifier("edudoc"),
        document_revision_id=identifier("edudocrev"),
        lifecycle_state=version("APPROVED"),
        document_manifest=reference("artifactMember"),
        original_source=reference("artifactMember"),
        artifact_member=copy.deepcopy(old_source["properties"]["artifact_member"]),
        analysis_bundle_manifest=copy.deepcopy(
            old_source["properties"]["analysis_bundle_manifest"]
        ),
        rights_attestation=copy.deepcopy(old_source["properties"]["rights_attestation"]),
        first_physical_page=integer(1, 2000),
        last_physical_page=integer(1, 2000),
        selected_regions=sequence(reference("region"), 1, 128),
        curriculum_unit_keys=copy.deepcopy(old_source["properties"]["curriculum_unit_keys"]),
        chunk_manifests=sequence(reference("artifactMember"), 1, 32),
        materialization_members=sequence(member, 2, 64),
        materialization_bytes=integer(2, 128 * 1024 * 1024),
        page_image_count=integer(1, 32),
    )

    # Local old-source refs are defined by their own immutable old types document.
    def externalize(value):
        if isinstance(value, dict):
            return {
                key: (
                    old_types["$id"] + item
                    if key == "$ref" and isinstance(item, str) and item.startswith("#/")
                    else externalize(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [externalize(item) for item in value]
        return value

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SOURCE,
        "title": "EOM uploaded material EducationalDocument source V5",
        **externalize(source),
    }


def contracts() -> dict[str, tuple[str, dict[str, Any]]]:
    values = {"educational-document-knowledge-source-v5": ("knowledge", source_schema())}
    source_properties = source_schema()["properties"]
    selection = record(
        **{
            name: copy.deepcopy(source_properties[name])
            for name in (
                "source_kind",
                "source_class",
                "document_revision_id",
                "first_physical_page",
                "last_physical_page",
                "selected_regions",
                "curriculum_unit_keys",
            )
        }
    )
    values["create-material-knowledge-analysis-v1"] = (
        "knowledge",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": KNOWLEDGE + "create-material-knowledge-analysis/1.0",
            "title": "EOM create uploaded material document knowledge analysis",
            **record(
                operation=version("CREATE_MATERIAL_KNOWLEDGE_ANALYSIS"),
                source=selection,
                preset_key={**text(3, 64), "pattern": "^[a-z][a-z0-9-]{2,63}$"},
                general_knowledge_mode=version("DISABLED"),
                risk_policy_revision_id=identifier("analysisriskrev"),
                predecessor_analysis_run_id=nullable(identifier("analysisrun")),
                requested_by={**text(1, 128), "pattern": "^[a-zA-Z0-9_][a-zA-Z0-9_.:-]{0,127}$"},
                idempotency_key={**text(16, 128), "pattern": "^[\\x21-\\x7e]+$"},
            ),
        },
    )
    snapshot = old("knowledge-graph-snapshot-manifest-v9")
    snapshot["$id"] = KNOWLEDGE + "knowledge-graph-snapshot-manifest/10.0"
    snapshot["title"] = "Shared Graph snapshot with uploaded-material sources V10"
    snapshot["properties"]["schema_version"] = version("knowledge-graph-snapshot-manifest/10.0")
    snapshot["properties"]["source_revisions"] = sequence(
        {
            "anyOf": [
                {
                    "$ref": KNOWLEDGE
                    + "knowledge-graph-snapshot-manifest/4.0#/properties/source_revisions/items"
                },
                {"$ref": SOURCE},
            ]
        },
        1,
        10000,
    )
    values["knowledge-graph-snapshot-manifest-v10"] = ("knowledge", snapshot)
    for name, previous, number in (
        ("request", 8, 12),
        ("proposal-receipt", 7, 11),
        ("result", 8, 12),
    ):
        document = old(f"knowledge-analysis-{name}-v{previous}")
        document["$id"] = KNOWLEDGE + f"knowledge-analysis-{name}/{number}.0"
        document["title"] = f"EOM uploaded material knowledge analysis {name} V{number}"
        document["properties"]["schema_version"] = version(f"knowledge-analysis-{name}/{number}.0")
        document["properties"]["source"] = {"$ref": SOURCE}
        if name == "request":
            document["properties"]["accepted_result_schema_ref"] = version(
                KNOWLEDGE + "knowledge-analysis-result/12.0"
            )
            document["properties"]["general_knowledge_mode"] = version("DISABLED")
        values[f"knowledge-analysis-{name}-v{number}"] = ("knowledge", document)
    plan = json.loads(
        (ROOT / "schemas/workflow/control-plane/resolved-execution-plan-v5.schema.json").read_text()
    )
    plan["$id"] = "eom://schemas/workflow/resolved-execution-plan/34.0"
    plan["title"] = "EOM uploaded material knowledge analysis resolved plan V34"
    plan["properties"]["schema_version"] = version("resolved-execution-plan/34.0")
    plan["properties"]["document_source"] = {"$ref": SOURCE}
    plan["properties"]["workflow_definition_version"] = version("12.0.0")
    plan["properties"]["resolver_version"] = version("34.0.0")
    template = json.loads(
        (
            ROOT / "schemas/workflow/control-plane/resolved-execution-plan-v33.schema.json"
        ).read_text()
    )
    plan["properties"]["steps"] = copy.deepcopy(template["properties"]["steps"])
    plan["properties"]["steps"]["items"]["properties"]["step_key"] = version("analyze")
    values["resolved-execution-plan-v34"] = ("control-plane", plan)
    for name in ("input", "proposal-result"):
        document = json.loads(
            (ROOT / f"schemas/workflow/roles/knowledge-analysis-{name}-v8.schema.json").read_text()
        )
        document["$id"] = (
            f"https://eom.local/schemas/workflow/roles/knowledge-analysis-{name}-v12.schema.json"
        )
        document["properties"]["protocol_version"] = version("workflow-role/1.38.0")
        if name == "input":
            document["$defs"]["request"]["properties"]["analysis_request"] = {
                "$ref": KNOWLEDGE + "knowledge-analysis-request/12.0"
            }
        values[f"knowledge-analysis-{name}-v12"] = ("roles", document)
    return values


def main() -> None:
    for name, (category, document) in contracts().items():
        payload = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode()
        canonical = (
            ROOT / "schemas" / ("knowledge" if category == "knowledge" else "workflow/" + category)
        )
        resource = ROOT / (
            "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge"
            if category == "knowledge"
            else "packages/workflow/eom_workflow/resources/" + category
        )
        for directory in (canonical, resource):
            (directory / (name + ".schema.json")).write_bytes(payload)
        print(name + " sha256:" + hashlib.sha256(payload).hexdigest())


if __name__ == "__main__":
    main()
