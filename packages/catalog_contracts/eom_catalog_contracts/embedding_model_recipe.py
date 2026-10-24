"""Payload/semantic recipe comparison, not runtime or numerical equivalence admission."""

from __future__ import annotations

from eom_identifiers import canonical_json_bytes

from eom_catalog_contracts.embedding_contract_values import raw_similarity_contract_value
from eom_catalog_contracts.item_inference_transfer import LocalEmbeddingModelSpec

_EXECUTION_REVISION_FIELDS = frozenset({"model_revision_id", "runtime_versions", "manifest_sha256"})


def same_embedding_payload_recipe(
    left: LocalEmbeddingModelSpec, right: LocalEmbeddingModelSpec
) -> bool:
    """Compare canonical weights/tokenizer/recipe while retaining distinct execution pins.

    This is the existing RuntimeBundle payload-successor comparison, shared by new
    routing and index pairing. Equal values neither unify runtime/space identities
    nor prove CPU/CUDA vectors interchangeable. The owner still validates bundles.
    """
    raw_left, raw_right = raw_similarity_contract_value(left), raw_similarity_contract_value(right)
    checked_left = LocalEmbeddingModelSpec.model_validate(raw_left)
    checked_right = LocalEmbeddingModelSpec.model_validate(raw_right)
    try:
        left_bytes, right_bytes = canonical_json_bytes(raw_left), canonical_json_bytes(raw_right)
    except TypeError:
        raise ValueError("embedding payload recipe contains noncanonical scalar types") from None
    if left_bytes != canonical_json_bytes(
        checked_left.model_dump(mode="json")
    ) or right_bytes != canonical_json_bytes(checked_right.model_dump(mode="json")):
        raise ValueError("embedding payload recipe contains noncanonical scalar types")
    excluded = set(_EXECUTION_REVISION_FIELDS)
    return checked_left.model_dump(mode="json", exclude=excluded) == checked_right.model_dump(
        mode="json", exclude=excluded
    )
