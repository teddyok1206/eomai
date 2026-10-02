#!/usr/bin/env python3
"""Fail-closed audit for canonical JSON Schema identities and packaged mirrors."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_ROOT = ROOT / "schemas"


@dataclass(frozen=True)
class SchemaDocument:
    path: Path
    value: dict[str, Any]

    @property
    def schema_id(self) -> str:
        value = self.value.get("$id")
        if not isinstance(value, str) or not value:
            raise ValueError(f"schema has no non-empty $id: {self.path.relative_to(ROOT)}")
        return value


HISTORICAL_SCHEMA_VERSION_COLLISIONS = {
    "integrated-science-editorial-outline/1.0": {
        "schemas/curriculum/integrated-science-editorial-outline-v1.schema.json": (
            "6b3e0bff6435827b322337f5c8a48e920c3fffc149e4e047e71374ededb28745"
        ),
        "schemas/web-gui/curriculum-editorial-outline-v1.schema.json": (
            "8a9d34ff5641112fcecb20635984e808de15824449693e90987eace29e05d328"
        ),
    }
}

HISTORICAL_MIRROR_BYTE_EXCEPTIONS = {
    "hwpx-content-team-exam-render-request-v1.schema.json": (
        "f5f13dbfe6fd5c86e001cc28ae0069fddb748c6c3d432f54de2f783620b6e914",
        "bb63dcd2a4eb3f8e57f83276373b7fe0cbd7195fbe08cda1d2397c7f931745cd",
    ),
    "hwpx-content-team-exam-build-result-v1.schema.json": (
        "381fae2dd00f56522dcc6cd783dc763d754ceae840125115ffacaabc20a46154",
        "e132f05c86fdf77aa1d333c58430bf3cca0af8d377a786e8f2951fc9270f9e9a",
    ),
}

CURRENT_WIRE_IDENTITIES = {
    "schemas/web-gui/curriculum-editorial-outline-v2.schema.json": (
        "https://eom.local/schemas/web-gui/curriculum-editorial-outline-v2.schema.json"
    ),
    "schemas/api/v1/mock-exam-assembly-policy-view-v1.schema.json": (
        "eom://schemas/api/v1/mock-exam-assembly-policy-view/1.0"
    ),
    "schemas/api/v1/execution-preset-draft-request-v1.schema.json": (
        "eom://schemas/api/v1/execution-preset-draft-request/1.0"
    ),
    "schemas/api/v1/mock-exam-explicit-rating-set-v1.schema.json": (
        "https://eom.local/schemas/api/v1/mock-exam-explicit-rating-set-v1.schema.json"
    ),
    "schemas/api/v1/mock-exam-graph-publication-input-v1.schema.json": (
        "https://eom.local/schemas/api/v1/mock-exam-graph-publication-input-v1.schema.json"
    ),
    "schemas/api/v1/educational-quality-review-command-v1.schema.json": (
        "https://eom.local/schemas/api/v1/educational-quality-review-command-v1.schema.json"
    ),
    "schemas/api/v1/educational-quality-review-workbench-v1.schema.json": (
        "https://eom.local/schemas/api/v1/educational-quality-review-workbench-v1.schema.json"
    ),
    "schemas/infra/artifact-store-snapshot-manifest-v1.schema.json": (
        "eom://schemas/infra/artifact-store-snapshot-manifest/1.0"
    ),
    "schemas/infra/recovery-validation-receipt-v1.schema.json": (
        "eom://schemas/infra/recovery-validation-receipt/1.0"
    ),
    "schemas/hwpx/hwpx-render-request-v1.schema.json": "eom://schemas/hwpx/render-request/1.0",
    "schemas/hwpx/hwpx-template-binding-manifest-v1.schema.json": (
        "eom://schemas/hwpx/template-binding-manifest/1.0"
    ),
    "schemas/hwpx/hwpx-kordoc-bridge-report-v1.schema.json": (
        "eom://schemas/hwpx/kordoc-bridge-report/1.0"
    ),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"schema root is not an object: {path.relative_to(ROOT)}")
    Draft202012Validator.check_schema(value)
    return value


def canonical_documents() -> tuple[SchemaDocument, ...]:
    return tuple(
        SchemaDocument(path=path, value=_load(path))
        for path in sorted(CANONICAL_ROOT.rglob("*.schema.json"))
    )


def _walk_refs(value: Any) -> tuple[str, ...]:
    refs: list[str] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                refs.append(ref)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return tuple(refs)


def _resolve_pointer(value: Any, fragment: str, *, context: str) -> None:
    if not fragment:
        return
    if not fragment.startswith("/"):
        raise ValueError(f"unsupported JSON Schema anchor in {context}: #{fragment}")
    current = value
    for raw in fragment[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ValueError(f"unresolved JSON Schema pointer in {context}: #{fragment}")


def audit_references(documents: tuple[SchemaDocument, ...]) -> int:
    by_id: dict[str, SchemaDocument] = {}
    for document in documents:
        if document.schema_id in by_id:
            raise ValueError(f"duplicate canonical $id: {document.schema_id}")
        by_id[document.schema_id] = document
    checked = 0
    for document in documents:
        for ref in _walk_refs(document.value):
            checked += 1
            target_uri, fragment = urldefrag(ref)
            if not target_uri:
                target = document
            elif "://" in target_uri:
                try:
                    target = by_id[target_uri]
                except KeyError as exc:
                    raise ValueError(
                        f"unresolved external $ref in {document.path.relative_to(ROOT)}: {ref}"
                    ) from exc
            else:
                target_path = (document.path.parent / target_uri).resolve()
                if not target_path.is_relative_to(CANONICAL_ROOT.resolve()):
                    raise ValueError(f"relative $ref escaped canonical schemas: {ref}")
                target = SchemaDocument(path=target_path, value=_load(target_path))
            _resolve_pointer(
                target.value,
                fragment,
                context=f"{document.path.relative_to(ROOT)} -> {ref}",
            )
    return checked


def audit_root_schema_versions(documents: tuple[SchemaDocument, ...]) -> None:
    occurrences: dict[str, list[tuple[SchemaDocument, tuple[str, ...], tuple[str, ...]]]] = (
        defaultdict(list)
    )
    for document in documents:
        properties = document.value.get("properties")
        if not isinstance(properties, dict):
            continue
        schema_version = properties.get("schema_version")
        if not isinstance(schema_version, dict):
            continue
        discriminator = schema_version.get("const")
        if not isinstance(discriminator, str) or "/" not in discriminator:
            continue
        required = document.value.get("required", [])
        occurrences[discriminator].append(
            (document, tuple(sorted(properties)), tuple(sorted(required)))
        )

    for discriminator, rows in occurrences.items():
        signatures = {(properties, required) for _, properties, required in rows}
        if len(signatures) <= 1:
            continue
        expected = HISTORICAL_SCHEMA_VERSION_COLLISIONS.get(discriminator)
        actual = {
            str(document.path.relative_to(ROOT)): _sha256(document.path) for document, _, _ in rows
        }
        if expected != actual:
            raise ValueError(
                f"schema_version identifies multiple root shapes: {discriminator}: {actual}"
            )


def audit_mirrors() -> int:
    pairs = (
        (
            ROOT / "schemas/api/v1",
            ROOT / "packages/api_contracts/eom_api_contracts/schemas",
        ),
        (
            ROOT / "schemas/hwpx",
            ROOT / "packages/hwpx_contracts/eom_hwpx_contracts/schemas",
        ),
    )
    checked = 0
    for canonical_root, packaged_root in pairs:
        for canonical in sorted(canonical_root.glob("*.schema.json")):
            packaged = packaged_root / canonical.name
            if not packaged.exists():
                continue
            checked += 1
            canonical_value = _load(canonical)
            packaged_value = _load(packaged)
            if canonical_value != packaged_value:
                raise ValueError(f"canonical/package schema semantics drifted: {canonical.name}")
            if canonical.read_bytes() == packaged.read_bytes():
                if canonical.name in HISTORICAL_MIRROR_BYTE_EXCEPTIONS:
                    raise ValueError(f"historical mirror exception became stale: {canonical.name}")
                continue
            expected = HISTORICAL_MIRROR_BYTE_EXCEPTIONS.get(canonical.name)
            actual = (_sha256(canonical), _sha256(packaged))
            if expected != actual:
                raise ValueError(f"canonical/package schema bytes drifted: {canonical.name}")
    return checked


def audit_current_identities(documents: tuple[SchemaDocument, ...]) -> None:
    by_path = {str(document.path.relative_to(ROOT)): document for document in documents}
    for relative, expected_id in CURRENT_WIRE_IDENTITIES.items():
        try:
            actual_id = by_path[relative].schema_id
        except KeyError as exc:
            raise ValueError(f"current wire schema is missing: {relative}") from exc
        if actual_id != expected_id:
            raise ValueError(f"current wire schema identity drifted: {relative}")


def audit() -> dict[str, int]:
    documents = canonical_documents()
    reference_count = audit_references(documents)
    audit_root_schema_versions(documents)
    mirror_count = audit_mirrors()
    audit_current_identities(documents)
    return {
        "canonical_schema_count": len(documents),
        "reference_count": reference_count,
        "mirror_count": mirror_count,
    }


def main() -> int:
    print(json.dumps(audit(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
