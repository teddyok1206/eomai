#!/usr/bin/env python3
"""Detect the intentionally supported subset of OpenAPI breaking changes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("OpenAPI document must be an object")
    return value


def resolve(document: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    reference = schema.get("$ref")
    if not isinstance(reference, str):
        return schema
    if not reference.startswith("#/components/schemas/"):
        return schema
    name = reference.rsplit("/", 1)[-1]
    resolved = document.get("components", {}).get("schemas", {}).get(name, {})
    return resolved if isinstance(resolved, dict) else {}


def request_schema(operation: dict[str, Any]) -> dict[str, Any]:
    body = operation.get("requestBody", {})
    content = body.get("content", {}) if isinstance(body, dict) else {}
    for media_type in ("application/json", "application/problem+json"):
        media = content.get(media_type)
        if isinstance(media, dict) and isinstance(media.get("schema"), dict):
            return media["schema"]
    return {}


def required_fields(document: dict[str, Any], schema: dict[str, Any]) -> set[str]:
    actual = resolve(document, schema)
    required = actual.get("required", [])
    return {value for value in required if isinstance(value, str)}


def compare_schema(
    old_document: dict[str, Any],
    new_document: dict[str, Any],
    old_schema: dict[str, Any],
    new_schema: dict[str, Any],
    location: str,
    findings: list[str],
) -> None:
    old_value = resolve(old_document, old_schema)
    new_value = resolve(new_document, new_schema)
    old_type = old_value.get("type")
    new_type = new_value.get("type")
    if old_type is not None and new_type is not None and old_type != new_type:
        findings.append(f"schema type changed: {location}: {old_type!r} -> {new_type!r}")
    old_enum = old_value.get("enum")
    new_enum = new_value.get("enum")
    if isinstance(old_enum, list) and isinstance(new_enum, list):
        removed = set(map(str, old_enum)) - set(map(str, new_enum))
        if removed:
            findings.append(f"enum values removed: {location}: {sorted(removed)}")
    old_properties = old_value.get("properties", {})
    new_properties = new_value.get("properties", {})
    if isinstance(old_properties, dict) and isinstance(new_properties, dict):
        for name, child in old_properties.items():
            if name not in new_properties:
                findings.append(f"response field deleted: {location}/{name}")
            elif isinstance(child, dict) and isinstance(new_properties[name], dict):
                compare_schema(
                    old_document,
                    new_document,
                    child,
                    new_properties[name],
                    f"{location}/{name}",
                    findings,
                )
    if isinstance(old_value.get("items"), dict) and isinstance(new_value.get("items"), dict):
        compare_schema(
            old_document,
            new_document,
            old_value["items"],
            new_value["items"],
            f"{location}[]",
            findings,
        )


def breaking_changes(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    old_paths = old.get("paths", {})
    new_paths = new.get("paths", {})
    for path, old_path_item in old_paths.items():
        if path not in new_paths:
            findings.append(f"endpoint deleted: {path}")
            continue
        new_path_item = new_paths[path]
        for method, old_operation in old_path_item.items():
            if method not in HTTP_METHODS:
                continue
            if method not in new_path_item:
                findings.append(f"HTTP method deleted: {method.upper()} {path}")
                continue
            new_operation = new_path_item[method]
            old_id = old_operation.get("operationId")
            new_id = new_operation.get("operationId")
            if old_id != new_id:
                findings.append(
                    f"operationId changed: {method.upper()} {path}: {old_id!r} -> {new_id!r}"
                )
            old_security = old_operation.get("security", old.get("security", []))
            new_security = new_operation.get("security", new.get("security", []))
            if old_security and not new_security:
                findings.append(f"security requirement weakened: {method.upper()} {path}")
            old_request = request_schema(old_operation)
            new_request = request_schema(new_operation)
            added_required = required_fields(new, new_request) - required_fields(old, old_request)
            if added_required:
                findings.append(
                    f"required request fields added: {method.upper()} {path}: "
                    f"{sorted(added_required)}"
                )
            old_responses = old_operation.get("responses", {})
            new_responses = new_operation.get("responses", {})
            for status, old_response in old_responses.items():
                new_response = new_responses.get(status)
                if not isinstance(old_response, dict) or not isinstance(new_response, dict):
                    continue
                old_content = old_response.get("content", {})
                new_content = new_response.get("content", {})
                for media_type, old_media in old_content.items():
                    new_media = new_content.get(media_type)
                    if not isinstance(old_media, dict) or not isinstance(new_media, dict):
                        continue
                    if isinstance(old_media.get("schema"), dict) and isinstance(
                        new_media.get("schema"), dict
                    ):
                        compare_schema(
                            old,
                            new,
                            old_media["schema"],
                            new_media["schema"],
                            f"{method.upper()} {path} response {status}",
                            findings,
                        )
    old_components = old.get("components", {}).get("schemas", {})
    new_components = new.get("components", {}).get("schemas", {})
    for name, old_schema in old_components.items():
        new_schema = new_components.get(name)
        if isinstance(old_schema, dict) and isinstance(new_schema, dict):
            compare_schema(old, new, old_schema, new_schema, f"schema {name}", findings)
    return sorted(set(findings))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("old", type=Path)
    parser.add_argument("new", type=Path)
    arguments = parser.parse_args()
    findings = breaking_changes(load(arguments.old), load(arguments.new))
    for finding in findings:
        print(f"BREAKING: {finding}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
