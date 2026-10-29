"""Share exact encoder inputs for query/document purposes after source admission."""

from dataclasses import dataclass
from typing import Literal

from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingEncodingIdentity,
    EmbeddingSpace,
    EmbeddingTextInput,
)
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_identifiers import content_sha256


@dataclass(frozen=True, slots=True)
class PublicSolutionEncodingInput:
    source: PublicSolutionEmbeddingEntry
    input: EmbeddingTextInput | None
    unavailable_reason: Literal["MISSING_PUBLIC_SOLUTION", "PUBLIC_SOLUTION_TEXT_LIMIT"] | None


def prepare_public_solution_encoding(
    entry: PublicSolutionEmbeddingEntry,
    *,
    space: EmbeddingSpace,
    storage_partition: str,
) -> PublicSolutionEncodingInput:
    """O(text bytes). No IO/claim or source authority; the source owner calls this.

    The same renderer serves QUERY and DOCUMENT. Numerical purpose/prefix and
    device remain in the supplied released space, not in rewritten report text.
    """
    entry = PublicSolutionEmbeddingEntry.model_validate(entry.model_dump(mode="json"))
    space = EmbeddingSpace.model_validate(space.model_dump(mode="json"))
    # Validate the partition even for unavailable views, without making an input.
    probe = {
        "storage_partition": storage_partition,
        "space_sha256": space.space_sha256,
        "input_text_sha256": content_sha256(""),
    }
    EmbeddingEncodingIdentity.model_validate(probe | {"encoding_sha256": content_sha256(probe)})
    text = entry.public_solution.text
    if text is None:
        return PublicSolutionEncodingInput(entry, None, "MISSING_PUBLIC_SOLUTION")
    if len(text.encode("utf-8")) > entry.recipe.maximum_text_bytes:
        return PublicSolutionEncodingInput(entry, None, "PUBLIC_SOLUTION_TEXT_LIMIT")
    key = probe | {"input_text_sha256": entry.public_solution.text_sha256}
    encoding = EmbeddingEncodingIdentity.model_validate(
        key | {"encoding_sha256": content_sha256(key)}
    )
    return PublicSolutionEncodingInput(
        entry, EmbeddingTextInput(encoding=encoding, text=text), None
    )
