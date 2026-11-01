"""Private provenance plus existing common numerical QUERY2; no live Chat/model proof."""

from contextlib import contextmanager
from dataclasses import FrozenInstanceError

import pytest
from eom_catalog_contracts.private_chat_query_basis import build_private_chat_query_basis
from eom_catalog_contracts.public_solution_query import PublicSolutionQueryInput
from eom_catalog_contracts.registered_public_solution_similarity import (
    PublicSolutionSimilarityViewV4,
)
from eom_catalog_service.embedding_encoder_adapter import encode_public_solution_query
from eom_catalog_service.embedding_native_stdio import (
    NativeEmbeddingHandoffError,
    run_native_private_chat_query_descriptors,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.general_chat_public_query_projection import (
    PreparedPrivateChatPublicQuery,
    project_private_chat_public_query,
    validate_private_chat_public_query_result,
)
from eom_orchestrator.general_chat_similarity_basis import PreparedPrivateChatQuery

from tests.unit.inference_transfer_embedding_fixtures import embedding_space
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_embedding_private_chat_query import private_descriptors as private_descriptors
from tests.unit.test_private_chat_query_basis import CONVERSATION, TEXT, TURN, payload, pointer
from tests.unit.test_registered_public_solution_similarity_contracts import (
    registered_similarity_case,
)


def inputs(*, device="CPU", text=TEXT):
    original = registered_similarity_case()[0].views[0].model_dump(mode="json")
    original["index"]["spaces"] = dict(
        query=embedding_space(device=device, purpose="QUERY").model_dump(mode="json"),
        document=embedding_space(device=device).model_dump(mode="json"),
    )
    view = PublicSolutionSimilarityViewV4.model_validate(original)
    basis = build_private_chat_query_basis(
        conversation_id=CONVERSATION, turn_id=TURN, message=pointer(payload(text=text)), text=text
    )
    return PreparedPrivateChatQuery(basis, text), view


def project(prepared, view, **updates):
    return project_private_chat_public_query(
        prepared,
        view,
        **(
            dict(
                context_request_sha256="sha256:" + "a" * 64,
                job_id="job_" + "b" * 32,
                query_request_id="embeddingquery_" + "c" * 32,
                batch_size=4,
                threads=1,
            )
            | updates
        ),
    )


@pytest.mark.parametrize("device", ("CPU", "CUDA"))
def test_exact_owned_text_becomes_the_existing_recipe2_query_without_private_identity(device):
    prepared, view = inputs(device=device)
    result = project(prepared, view)
    assert type(result.native) is PublicSolutionQueryInput
    assert result.basis == prepared.basis
    assert result.native.rows[0].text == prepared.text
    assert result.native.rows[0].view == "CONCRETE_FACETS"
    assert result.native.recipe == view.recipe and result.native.spaces == view.index.spaces
    assert "source" not in result.native.model_dump() and "basis" not in result.native.model_dump()
    raw = canonical_json_bytes(result.native)
    assert b'"conversation_id"' not in raw and b'"turn_id"' not in raw
    assert TEXT not in repr(result)
    backend = SyntheticNativeBackend(result.native.spaces.query)
    backend.batch_size, backend.threads = result.native.batch_size, result.native.threads
    encoded = encode_public_solution_query(result.native, backend)
    assert backend.calls == [((TEXT,), "QUERY")]
    assert validate_private_chat_public_query_result(result, encoded.result) == encoded.result
    with pytest.raises(FrozenInstanceError):
        result.basis = prepared.basis


def test_spaces_newlines_unicode_and_negation_are_not_rewritten():
    text = "  속도 −36 km/h가 아니다.\n  이 조건 그대로 찾아줘.  "  # noqa: RUF001
    prepared, view = inputs(text=text)
    result = project(prepared, view)
    assert result.native.rows[0].text == text
    assert result.basis.query_text_sha256 == prepared.basis.query_text_sha256


@pytest.mark.parametrize(
    "field", ("batch_size", "threads", "job_id", "query_request_id", "context_request_sha256")
)
def test_invalid_trusted_metadata_does_not_create_a_partial_query(field):
    prepared, view = inputs()
    bad = True if field in {"batch_size", "threads"} else "invalid"
    with pytest.raises(ValueError, match=r"^PRIVATE_CHAT_PUBLIC_QUERY_PROJECTION_INVALID$"):
        project(prepared, view, **{field: bad})


@pytest.mark.parametrize(
    "fault", ("changed_text", "copied_basis", "legacy_view", "copied_recipe", "foreign_space")
)
def test_forged_values_do_not_bypass_exact_text_or_common_space(fault):
    prepared, view = inputs()
    if fault == "changed_text":
        object.__setattr__(prepared, "text", TEXT + "changed")
    elif fault == "copied_basis":
        object.__setattr__(
            prepared, "basis", prepared.basis.model_copy(update={"basis": "APPROVED_ITEM"})
        )
    elif fault == "legacy_view":
        view = view.model_copy(update={"view": "CONTENT_ONLY"})
    elif fault == "copied_recipe":
        view = view.model_copy(
            update={"recipe": view.recipe.model_copy(update={"facets": "PRIVATE_REASONING"})}
        )
    else:
        view = view.model_copy(
            update={
                "index": view.index.model_copy(
                    update={
                        "spaces": view.index.spaces.model_copy(
                            update={"query": view.index.spaces.document}
                        )
                    }
                )
            }
        )
    with pytest.raises(
        ValueError, match=r"^PRIVATE_CHAT_PUBLIC_QUERY_PROJECTION_INVALID$"
    ) as caught:
        project(prepared, view)
    assert TEXT not in str(caught.value)


def test_foreign_result_cannot_attach_to_another_original_private_context():
    prepared, view = inputs()
    first = project(prepared, view)
    other = project(prepared, view, context_request_sha256="sha256:" + "d" * 64)
    backend = SyntheticNativeBackend(first.native.spaces.query)
    backend.batch_size, backend.threads = first.native.batch_size, first.native.threads
    encoded = encode_public_solution_query(first.native, backend)
    with pytest.raises(ValueError, match=r"^PRIVATE_CHAT_PUBLIC_QUERY_RESULT_INVALID$"):
        validate_private_chat_public_query_result(other, encoded.result)
    with pytest.raises(ValueError, match=r"^PRIVATE_CHAT_PUBLIC_QUERY_PROJECTION_INVALID$"):
        PreparedPrivateChatPublicQuery(
            prepared.basis.model_copy(update={"query_text_sha256": "sha256:" + "f" * 64}),
            first.native,
        )


def test_projection_is_not_permission_to_use_the_old_private_native_purpose(
    private_descriptors, tmp_path
):
    prepared, view = inputs()
    projected = project(prepared, view)
    (tmp_path / "input.json").write_bytes(canonical_json_bytes(projected.native))
    calls = []

    @contextmanager
    def backend_scope():
        calls.append("MODEL_CONSTRUCTED")
        yield SyntheticNativeBackend(projected.native.spaces.query)

    with pytest.raises(NativeEmbeddingHandoffError):
        run_native_private_chat_query_descriptors(private_descriptors, backend_scope)
    assert calls == []
    assert (tmp_path / "result.json").read_bytes() == (tmp_path / "vectors.f32").read_bytes() == b""
