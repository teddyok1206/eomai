"""One explicit derived recipe, never a source pointer or an authority assertion."""

import re
import unicodedata
from typing import Literal, Self

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.models import FrozenModel, Sha256, _safe_text
from eom_catalog_contracts.validation import validate_contract

PUBLIC_SOLUTION_TEXT_VERSION: Literal["public-solution-text/1.0"] = "public-solution-text/1.0"
MAX_PUBLIC_SOLUTION_CHARACTERS = 524288
_LAYOUT_WHITESPACE = re.compile(r"[ \t\r\n]+")


def _normalized_text(text: str) -> str:
    # NFC preserves superscripts and scientific symbols; NFKC would not.
    return _LAYOUT_WHITESPACE.sub(" ", unicodedata.normalize("NFC", text)).strip()


class PublicSolutionText(FrozenModel):
    schema_version: Literal["public-solution-text/1.0"] = PUBLIC_SOLUTION_TEXT_VERSION
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    text: str | None = Field(max_length=MAX_PUBLIC_SOLUTION_CHARACTERS)
    text_sha256: Sha256 | None

    @model_validator(mode="after")
    def canonical(self) -> Self:
        validate_contract("public-solution-text-v1", self.model_dump(mode="json"))
        if self.status == "AVAILABLE":
            if (
                self.text is None
                or not self.text
                or _normalized_text(self.text) != self.text
                or self.text_sha256 != content_sha256(self.text)
            ):
                raise ValueError("PUBLIC_SOLUTION_TEXT_NON_CANONICAL")
            _safe_text(self.text)
        elif self.text is not None or self.text_sha256 is not None:
            raise ValueError("PUBLIC_SOLUTION_TEXT_UNAVAILABLE_HAS_CONTENT")
        return self


def build_public_solution_text(parts: tuple[str, ...]) -> PublicSolutionText:
    """Preserve complete scientific fields in source order; no solving or inference.

    Separating the same text into fields or steps must not affect its encoding.
    Missing content is unavailable, never a zero vector or a fabricated answer.
    """
    if type(parts) is not tuple or len(parts) > 128:
        raise ValueError("PUBLIC_SOLUTION_TEXT_INPUT_INVALID")
    size = 0
    for part in parts:
        if type(part) is not str:
            raise ValueError("PUBLIC_SOLUTION_TEXT_INPUT_INVALID")
        _safe_text(part)
        size += len(part) + 1
        if size > MAX_PUBLIC_SOLUTION_CHARACTERS + 1:
            raise ValueError("PUBLIC_SOLUTION_TEXT_TOO_LARGE")
    text = _normalized_text(" ".join(parts))
    if not text:
        return PublicSolutionText(status="UNAVAILABLE", text=None, text_sha256=None)
    return PublicSolutionText(status="AVAILABLE", text=text, text_sha256=content_sha256(text))
