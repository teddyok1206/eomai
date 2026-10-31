"""Pure delta selection after Catalog source admission and registered-row resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from eom_catalog_contracts.embedding_index_families import embedding_entry_source
from eom_catalog_contracts.inference_transfer_embedding import (
    MAX_EMBEDDING_ROWS,
    EmbeddingEncodingIdentity,
    EmbeddingSpace,
    EmbeddingTextInput,
    EmbeddingVectorRowRef,
)
from eom_catalog_contracts.inference_transfer_experiment import (
    VIEWS,
    ExperimentView,
    StagedExperimentEntry,
    experiment_view_text,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_catalog_contracts.public_solution_embedding_index import (
    MAX_PUBLIC_SOLUTION_SOURCES,
    PublicSolutionProfilePointer,
)
from eom_catalog_contracts.registered_public_solution_embedding import (
    RegisteredPublicSolutionEmbeddingEntry,
)
from eom_catalog_contracts.registered_public_solution_index import (
    RegisteredPublicSolutionProfilePointer,
)
from eom_catalog_contracts.registered_review_profile import RegisteredReviewProfilePointer
from eom_identifiers import content_sha256

from eom_catalog_service.registered_review_embedding_entry import (
    RegisteredReviewEmbeddingEntry,
    registered_review_embedding_view_text,
    validate_registered_review_embedding_entry,
)

type EmbeddingProfilePointer = (
    InferenceTransferProfilePointer
    | RegisteredReviewProfilePointer
    | PublicSolutionProfilePointer
    | RegisteredPublicSolutionProfilePointer
)
type IncrementalEmbeddingEntry = (
    StagedExperimentEntry
    | RegisteredReviewEmbeddingEntry
    | PublicSolutionEmbeddingEntry
    | RegisteredPublicSolutionEmbeddingEntry
)


class EmbeddingDeltaError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class RegisteredEmbeddingRow:
    """Small registry projection; its owner still resolves and authorizes Artifact bytes."""

    encoding: EmbeddingEncodingIdentity
    row_ref: EmbeddingVectorRowRef


@dataclass(frozen=True, slots=True)
class EmbeddingBindingDemand:
    source_revision_id: str
    profile: EmbeddingProfilePointer
    view: ExperimentView
    encoding: EmbeddingEncodingIdentity


@dataclass(frozen=True, slots=True)
class UnavailableEmbeddingView:
    source_revision_id: str
    profile: EmbeddingProfilePointer
    view: ExperimentView
    reason: Literal["VIEW_NOT_MATERIALIZED", "EMPTY_VIEW", "PUBLIC_SOLUTION_TEXT_LIMIT"]


@dataclass(frozen=True, slots=True)
class EmbeddingDeltaPlan:
    """Encoding reuse does not merge source identities or imply binding readiness."""

    demands: tuple[EmbeddingBindingDemand, ...]
    new_inputs: tuple[EmbeddingTextInput, ...]
    reusable_rows: tuple[RegisteredEmbeddingRow, ...]
    unavailable_views: tuple[UnavailableEmbeddingView, ...]


def plan_embedding_delta(
    entries: tuple[IncrementalEmbeddingEntry, ...],
    *,
    space: EmbeddingSpace,
    storage_partition: str,
    registered_rows: tuple[RegisteredEmbeddingRow, ...] = (),
    views: tuple[ExperimentView, ...] = VIEWS,
) -> EmbeddingDeltaPlan:
    """Select by key in O(NV), plus canonical ordering in O(K log K).

    Report-missing population coverage belongs to the Catalog admission query;
    such sources cannot become staged profiles and are not invented here. The
    caller batches the returned unique inputs to the native request's row bound.
    Text hashing/validation cost is proportional to materialized input bytes.
    """

    space = EmbeddingSpace.model_validate(space.model_dump(mode="json"))
    if space.purpose != "DOCUMENT":
        raise EmbeddingDeltaError("EMBEDDING_DELTA_PURPOSE_INVALID")
    if (
        not isinstance(entries, tuple)
        or len(entries)
        > (
            MAX_PUBLIC_SOLUTION_SOURCES
            if all(
                isinstance(
                    value, PublicSolutionEmbeddingEntry | RegisteredPublicSolutionEmbeddingEntry
                )
                for value in entries
            )
            else MAX_EMBEDDING_ROWS
        )
        or not isinstance(views, tuple)
        or not views
        or len(views) != len(set(views))
        or not set(views).issubset(VIEWS)
    ):
        raise EmbeddingDeltaError("EMBEDDING_DELTA_SELECTION_INVALID")
    # Validate partition even when there are no eligible entries or available views.
    partition_probe = {
        "storage_partition": storage_partition,
        "space_sha256": space.space_sha256,
        "input_text_sha256": content_sha256(""),
    }
    EmbeddingEncodingIdentity.model_validate(
        partition_probe | {"encoding_sha256": content_sha256(partition_probe)}
    )
    by_encoding: dict[str, RegisteredEmbeddingRow] = {}
    for registered in registered_rows:
        encoding = EmbeddingEncodingIdentity.model_validate(
            registered.encoding.model_dump(mode="json")
        )
        row_ref = EmbeddingVectorRowRef.model_validate(registered.row_ref.model_dump(mode="json"))
        key = encoding.encoding_sha256
        if (
            key in by_encoding
            or row_ref.encoding_sha256 != key
            or encoding.storage_partition != storage_partition
            or encoding.space_sha256 != space.space_sha256
        ):
            raise EmbeddingDeltaError("EMBEDDING_DELTA_REGISTERED_ROW_INVALID")
        by_encoding[key] = RegisteredEmbeddingRow(encoding, row_ref)
    source_revisions: set[str] = set()
    by_text: dict[str, EmbeddingTextInput] = {}
    demands: list[EmbeddingBindingDemand] = []
    unavailable: list[UnavailableEmbeddingView] = []
    for original in entries:
        entry: IncrementalEmbeddingEntry
        profile: EmbeddingProfilePointer
        if isinstance(original, RegisteredPublicSolutionEmbeddingEntry):
            entry = RegisteredPublicSolutionEmbeddingEntry.model_validate(original)
            profile = RegisteredPublicSolutionProfilePointer.from_entry(entry)
        elif isinstance(original, PublicSolutionEmbeddingEntry):
            entry = PublicSolutionEmbeddingEntry.model_validate(original.model_dump(mode="json"))
            profile = PublicSolutionProfilePointer.from_entry(entry)
        elif isinstance(original, RegisteredReviewEmbeddingEntry):
            entry = validate_registered_review_embedding_entry(original)
            profile = RegisteredReviewProfilePointer.from_profile(entry.profile)
        else:
            entry = StagedExperimentEntry.model_validate(original.model_dump(mode="json"))
            profile = InferenceTransferProfilePointer.from_profile(entry.profile)
        revision = embedding_entry_source(entry).item_revision_id
        if revision in source_revisions:
            raise EmbeddingDeltaError("EMBEDDING_DELTA_DUPLICATE_SOURCE")
        source_revisions.add(revision)
        for view in views:
            if isinstance(
                entry, PublicSolutionEmbeddingEntry | RegisteredPublicSolutionEmbeddingEntry
            ):
                text = entry.public_solution.text if view == "CONCRETE_FACETS" else None
                if text is not None and len(text.encode("utf-8")) > entry.recipe.maximum_text_bytes:
                    unavailable.append(
                        UnavailableEmbeddingView(
                            revision, profile, view, "PUBLIC_SOLUTION_TEXT_LIMIT"
                        )
                    )
                    continue
            else:
                text = (
                    registered_review_embedding_view_text(entry, view)
                    if isinstance(entry, RegisteredReviewEmbeddingEntry)
                    else experiment_view_text(entry, view)
                )
            if text is None or not text.strip():
                reason: Literal["VIEW_NOT_MATERIALIZED", "EMPTY_VIEW"] = (
                    "VIEW_NOT_MATERIALIZED" if text is None else "EMPTY_VIEW"
                )
                unavailable.append(UnavailableEmbeddingView(revision, profile, view, reason))
                continue
            row = by_text.get(text)
            if row is None:
                body = {
                    "storage_partition": storage_partition,
                    "space_sha256": space.space_sha256,
                    "input_text_sha256": content_sha256(text),
                }
                encoding = EmbeddingEncodingIdentity.model_validate(
                    body | {"encoding_sha256": content_sha256(body)}
                )
                row = EmbeddingTextInput(encoding=encoding, text=text)
                by_text[text] = row
            demands.append(EmbeddingBindingDemand(revision, profile, view, row.encoding))
    demanded_encodings: dict[str, EmbeddingTextInput] = {}
    for row in by_text.values():
        key = row.encoding.encoding_sha256
        other = demanded_encodings.get(key)
        if other is not None and other != row:
            raise EmbeddingDeltaError("EMBEDDING_DELTA_ENCODING_COLLISION")
        demanded_encodings[key] = row
    ordered_keys = tuple(sorted(demanded_encodings))
    if any(
        by_encoding[key].encoding != demanded_encodings[key].encoding
        for key in ordered_keys
        if key in by_encoding
    ):
        raise EmbeddingDeltaError("EMBEDDING_DELTA_ENCODING_COLLISION")
    return EmbeddingDeltaPlan(
        demands=tuple(sorted(demands, key=lambda demand: (demand.source_revision_id, demand.view))),
        new_inputs=tuple(demanded_encodings[key] for key in ordered_keys if key not in by_encoding),
        reusable_rows=tuple(by_encoding[key] for key in ordered_keys if key in by_encoding),
        unavailable_views=tuple(
            sorted(unavailable, key=lambda value: (value.source_revision_id, value.view))
        ),
    )
