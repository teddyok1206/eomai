"""Restricted dot-path substitution with no executable template features."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from eom_identifiers import content_sha256, sha256_bytes

from eom_content_pack.errors import ContentPackError, ContentPackErrorCode

VARIABLE = re.compile(r"{{\s*([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)\s*}}")
ANY_DELIMITER = re.compile(r"{{|}}|{%|%}|{#|#}")


@dataclass(frozen=True)
class RenderedPrompt:
    text: str
    context_hash: str
    prompt_hash: str
    variables: tuple[str, ...]


def validate_prompt_template(template: str, required_variables: tuple[str, ...]) -> tuple[str, ...]:
    matches = tuple(VARIABLE.finditer(template))
    residue = VARIABLE.sub("", template)
    if ANY_DELIMITER.search(residue):
        raise ContentPackError(
            ContentPackErrorCode.CONTENT_PACK_TEMPLATE_INVALID,
            "prompt uses an unsupported template expression",
        )
    variables = tuple(match.group(1) for match in matches)
    if set(variables) != set(required_variables):
        raise ContentPackError(
            ContentPackErrorCode.CONTENT_PACK_TEMPLATE_INVALID,
            "prompt variables do not match the declared context",
        )
    return tuple(sorted(set(variables)))


def render_prompt(
    template: str, context: Mapping[str, Any], required_variables: tuple[str, ...]
) -> RenderedPrompt:
    variables = validate_prompt_template(template, required_variables)

    def replace(match: re.Match[str]) -> str:
        path = match.group(1)
        value: Any = context
        for part in path.split("."):
            if not isinstance(value, Mapping) or part not in value:
                raise ContentPackError(
                    ContentPackErrorCode.CONTENT_PACK_TEMPLATE_INVALID,
                    f"required prompt variable is missing: {path}",
                )
            value = value[part]
        if not isinstance(value, (str, int, bool)):
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_TEMPLATE_INVALID,
                f"prompt variable is not a scalar: {path}",
            )
        return str(value)

    rendered = VARIABLE.sub(replace, template)
    return RenderedPrompt(
        text=rendered,
        context_hash=content_sha256(context),
        prompt_hash=sha256_bytes(rendered.encode("utf-8")),
        variables=variables,
    )
