"""Native visual preparation changes catalogs, never base documents or historical schemas."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts import material_native_visual_preparation as visual_contract
from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_learning_preparation import MaterialPreparedArtifact
from eom_catalog_contracts.material_native_intake import MaterialNativePreparedArtifact
from eom_catalog_contracts.material_native_visual_preparation import (
    MATERIAL_NATIVE_VISUAL_PREPARED_REF,
    MaterialNativeQuestionVisualScope,
    MaterialNativeVisualCatalogSupplement,
    MaterialNativeVisualPreparationProfile,
    MaterialNativeVisualPreparedArtifact,
    require_native_visual_prepared_base,
)
from eom_catalog_contracts.validation import load_schema, validate_contract
from eom_identifiers import canonical_json_bytes, content_sha256
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaError

from tests.unit.test_material_learning_contracts import rehash
from tests.unit.test_material_native_files import binding_data, pointer
from tests.unit.test_material_native_intake import native_prepared


def base_prepared():
    body = native_prepared()
    for source, letter in zip(body["sources"], ("a", "e"), strict=True):
        catalog = pointer(
            "picture-use-catalog.json",
            "application/json",
            "eom://schemas/image-provider/office-picture-use-catalog/1.0",
        )
        catalog["artifact_id"] = "artifact_" + letter * 32
        catalog["artifact_revision_id"] = "rev_" + letter * 32
        catalog["sha256"] = "sha256:" + letter * 64
        source["office_catalog"] = catalog
    return MaterialNativePreparedArtifact.model_validate(rehash(body, "prepared_sha256"))


def visual_profile():
    body = dict(
        source_commit="0" * 40,
        office_tool_source_commit="1" * 40,
        parser_implementation_sha256="sha256:" + "2" * 64,
        options_sha256="sha256:" + "3" * 64,
    )
    return {**body, "profile_sha256": content_sha256(body)}


def question_scope(number=1):
    binding = binding_data()
    document = deepcopy(binding["question"]["document"])
    evidence = deepcopy(binding["question"]["split_evidence"])
    document["member_path"] = f"items/{number}/question.hwpx"
    evidence["member_path"] = f"items/{number}/question.json"
    return dict(
        item_number=number,
        question_document=document,
        split_evidence=evidence,
        source_catalog_sha256="sha256:" + "f" * 64,
        allowed_picture_use_ids=["officeobj_" + "1" * 32],
    )


def visual_prepared(count=1):
    base = base_prepared()
    value = base.model_dump(mode="json")
    base_pointer = pointer(
        "material/prepared.json",
        "application/json",
        "eom://schemas/material-learning/prepared/2.0",
    )
    base_pointer.update(sha256=content_sha256(value), bytes=len(canonical_json_bytes(value)))
    catalog = deepcopy(value["sources"][0]["office_catalog"])
    catalog.update(artifact_revision_id="rev_" + "f" * 32, sha256="sha256:" + "f" * 64)
    value.update(
        schema_version="material-learning-prepared/3.0",
        base_prepared=base_pointer,
        visual_profile=visual_profile(),
        catalog_supplements=[
            dict(
                source_role="MAIN",
                base_catalog=deepcopy(value["sources"][0]["office_catalog"]),
                catalog=catalog,
            )
        ],
        question_visual_scopes=[question_scope(number) for number in range(1, count + 1)],
    )
    return rehash(value, "prepared_sha256")


@pytest.mark.parametrize("count", [1, 25])
def test_successor_reuses_exact_native_base_and_roundtrips_without_binary_values(count):
    base = base_prepared()
    value = visual_prepared(count)
    prepared = MaterialNativeVisualPreparedArtifact.model_validate(value)
    require_native_visual_prepared_base(prepared, base=base, base_pointer=prepared.base_prepared)
    assert prepared.sources == base.sources
    assert prepared.profile_sha256 == base.profile_sha256
    assert prepared.intake_manifest == base.intake_manifest
    assert prepared.native_bundle == base.native_bundle
    assert len(prepared.question_visual_scopes) == count
    assert prepared.model_validate_json(prepared.model_dump_json()) == prepared
    assert MATERIAL_NATIVE_VISUAL_PREPARED_REF == "eom://schemas/material-learning/prepared/3.0"
    assert all(
        scope.question_document.media_type != "image/png"
        for scope in prepared.question_visual_scopes
    )
    validate_contract("material-learning-prepared-v3", value)
    with pytest.raises(ValueError):
        MaterialNativePreparedArtifact.model_validate(value)
    with pytest.raises(ValueError):
        MaterialPreparedArtifact.model_validate(value)


def test_schema_precedes_models_is_draft_2020_12_and_mirrors_are_exact():
    schema = load_schema("material-learning-prepared-v3")
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == MATERIAL_NATIVE_VISUAL_PREPARED_REF
    root = Path(__file__).resolve().parents[2]
    relative = Path("material-learning/material-learning-prepared-v3.schema.json")
    assert (root / "schemas" / relative).read_bytes() == (
        root / "packages/catalog_contracts/eom_catalog_contracts/resources" / relative
    ).read_bytes()


def test_prepared_canonical_size_is_bounded_before_publication_and_matches_reader_limit(
    monkeypatch,
):
    value = visual_prepared(25)
    size = len(canonical_json_bytes(value))
    monkeypatch.setattr(visual_contract, "_MAX_METADATA", size)
    assert MaterialNativeVisualPreparedArtifact.model_validate(value).material_id
    monkeypatch.setattr(visual_contract, "_MAX_METADATA", size - 1)
    with pytest.raises(ValueError, match="PREPARED_METADATA_TOO_LARGE"):
        MaterialNativeVisualPreparedArtifact.model_validate(value)


@pytest.mark.parametrize(
    "field", ["profile_sha256", "parser_implementation_sha256", "options_sha256"]
)
def test_visual_profile_hash_is_closed_over_tool_and_options(field):
    body = visual_profile()
    body[field] = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="VISUAL_PROFILE_HASH_MISMATCH"):
        MaterialNativeVisualPreparationProfile.model_validate(body)


@pytest.mark.parametrize("field", ["source_commit", "office_tool_source_commit"])
def test_visual_profile_requires_explicit_immutable_source_commits(field):
    body = visual_profile()
    body[field] = "latest"
    with pytest.raises(ValueError):
        MaterialNativeVisualPreparationProfile.model_validate(body)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_ref", "eom://schemas/image-provider/office-picture-use-catalog/2.0"),
        ("media_type", "application/pdf"),
        ("member_path", "other.json"),
        ("bytes", 8 * 1024 * 1024 + 1),
    ],
)
def test_catalog_supplement_is_only_a_new_exact_catalog1_pointer(field, value):
    supplement = visual_prepared()["catalog_supplements"][0]
    supplement["catalog"][field] = value
    with pytest.raises(ValueError, match="VISUAL_POINTER_INVALID"):
        MaterialNativeVisualCatalogSupplement.model_validate(supplement)


def test_fixed_catalog_can_be_reused_but_immutable_member_cannot_claim_a_different_hash():
    supplement = visual_prepared()["catalog_supplements"][0]
    supplement["catalog"] = deepcopy(supplement["base_catalog"])
    assert MaterialNativeVisualCatalogSupplement.model_validate(supplement).catalog == (
        MaterialNativeVisualCatalogSupplement.model_validate(supplement).base_catalog
    )
    supplement["catalog"] = {**supplement["base_catalog"], "sha256": "sha256:" + "f" * 64}
    with pytest.raises(ValueError, match="CATALOG_POINTER_CONFLICT"):
        MaterialNativeVisualCatalogSupplement.model_validate(supplement)


def test_new_pipeline_can_add_native_scopes_to_an_already_fixed_base_catalog():
    body = visual_prepared()
    supplement = body["catalog_supplements"][0]
    supplement["catalog"] = deepcopy(supplement["base_catalog"])
    body["question_visual_scopes"][0]["source_catalog_sha256"] = supplement["catalog"]["sha256"]
    prepared = MaterialNativeVisualPreparedArtifact.model_validate(rehash(body, "prepared_sha256"))
    require_native_visual_prepared_base(
        prepared, base=base_prepared(), base_pointer=prepared.base_prepared
    )


def test_empty_and_64_use_scopes_are_supported_without_inventing_a_required_picture():
    body = question_scope()
    body["allowed_picture_use_ids"] = []
    assert MaterialNativeQuestionVisualScope.model_validate(body).allowed_picture_use_ids == ()
    body["allowed_picture_use_ids"] = [f"officeobj_{index:032x}" for index in range(64)]
    assert len(MaterialNativeQuestionVisualScope.model_validate(body).allowed_picture_use_ids) == 64


@pytest.mark.parametrize(
    "ids",
    [
        ["officeobj_" + "1" * 32] * 2,
        ["officeobj_" + "2" * 32, "officeobj_" + "1" * 32],
        ["not-a-picture-use"],
        [f"officeobj_{index:032x}" for index in range(65)],
    ],
)
def test_scope_use_ids_are_bounded_sorted_unique_values(ids):
    body = question_scope()
    body["allowed_picture_use_ids"] = ids
    with pytest.raises(ValueError):
        MaterialNativeQuestionVisualScope.model_validate(body)


@pytest.mark.parametrize(
    "case",
    [
        "pdf",
        "wrong_document_schema",
        "wrong_evidence_schema",
        "same_member",
        "oversize_document",
        "oversize_evidence",
        "bool_number",
    ],
)
def test_scope_cannot_substitute_pdf_capture_or_unrelated_receipt(case):
    body = question_scope()
    if case == "pdf":
        body["question_document"]["media_type"] = "application/pdf"
    elif case == "wrong_document_schema":
        body["question_document"]["schema_ref"] = "eom://schemas/pdf-source/1.0"
    elif case == "wrong_evidence_schema":
        body["split_evidence"]["schema_ref"] = "eom://schemas/pdf-source/1.0"
    elif case == "same_member":
        body["split_evidence"]["member_path"] = body["question_document"]["member_path"]
    elif case == "oversize_document":
        body["question_document"]["bytes"] = 256 * 1024 * 1024 + 1
    elif case == "oversize_evidence":
        body["split_evidence"]["bytes"] = 4 * 1024 * 1024 + 1
    else:
        body["item_number"] = True
    with pytest.raises(ValueError):
        MaterialNativeQuestionVisualScope.model_validate(body)


@pytest.mark.parametrize(
    "case",
    [
        "duplicate_role",
        "reversed_roles",
        "base_catalog",
        "duplicate_number",
        "reverse_numbers",
        "duplicate_document",
        "duplicate_evidence",
        "wrong_catalog",
        "empty_scopes",
        "unknown_field",
    ],
)
def test_prepared_rejects_wrong_catalog_chain_and_ambiguous_question_references(case):
    body = visual_prepared(2)
    if case == "duplicate_role":
        body["catalog_supplements"] *= 2
    elif case == "reversed_roles":
        other = deepcopy(body["catalog_supplements"][0])
        other.update(source_role="SOLUTIONS", base_catalog=body["sources"][1]["office_catalog"])
        body["catalog_supplements"].insert(0, other)
    elif case == "base_catalog":
        body["catalog_supplements"][0]["base_catalog"]["sha256"] = "sha256:" + "0" * 64
    elif case == "duplicate_number":
        body["question_visual_scopes"][1]["item_number"] = 1
    elif case == "reverse_numbers":
        body["question_visual_scopes"].reverse()
    elif case == "duplicate_document":
        body["question_visual_scopes"][1]["question_document"] = body["question_visual_scopes"][0][
            "question_document"
        ]
    elif case == "duplicate_evidence":
        body["question_visual_scopes"][1]["split_evidence"] = body["question_visual_scopes"][0][
            "split_evidence"
        ]
    elif case == "wrong_catalog":
        body["question_visual_scopes"][0]["source_catalog_sha256"] = "sha256:" + "0" * 64
    elif case == "empty_scopes":
        body["question_visual_scopes"] = []
    else:
        body["question_visual_scopes"][0]["image_bytes"] = "do-not-store-image-bytes"
    with pytest.raises(ValueError):
        MaterialNativeVisualPreparedArtifact.model_validate(rehash(body, "prepared_sha256"))


@pytest.mark.parametrize("field", ["intake_manifest", "native_bundle", "base_prepared"])
def test_prepared_rejects_wrong_checkpoint_family(field):
    body = visual_prepared()
    body[field]["schema_ref"] = "eom://schemas/material-learning/prepared/1.0"
    with pytest.raises(ValueError, match="VISUAL_POINTER_INVALID"):
        MaterialNativeVisualPreparedArtifact.model_validate(rehash(body, "prepared_sha256"))


@pytest.mark.parametrize(
    "field",
    [
        "material_id",
        "material_revision_id",
        "profile_sha256",
        "sources",
        "native_bundle",
        "intake_manifest",
    ],
)
def test_resolved_base_guard_rejects_changed_identity_pages_source_and_metadata(field):
    base = base_prepared()
    body = visual_prepared()
    if field == "material_id":
        body[field] = "material_" + "0" * 32
    elif field == "material_revision_id":
        body[field] = "materialrev_" + "0" * 32
    elif field == "profile_sha256":
        body[field] = "sha256:" + "0" * 64
    elif field == "sources":
        body[field][0]["pdf"]["sha256"] = "sha256:" + "0" * 64
    else:
        body[field]["artifact_revision_id"] = "rev_" + "0" * 32
    prepared = MaterialNativeVisualPreparedArtifact.model_validate(rehash(body, "prepared_sha256"))
    with pytest.raises(ValueError, match="PREPARED_BASE_MISMATCH"):
        require_native_visual_prepared_base(
            prepared, base=base, base_pointer=prepared.base_prepared
        )


@pytest.mark.parametrize("field", ["sha256", "bytes", "artifact_revision_id"])
def test_resolved_base_guard_requires_exact_canonical_pointer_hash_size_and_revision(field):
    prepared = MaterialNativeVisualPreparedArtifact.model_validate(visual_prepared())
    values = prepared.base_prepared.model_dump(mode="json")
    values[field] = {
        "sha256": "sha256:" + "0" * 64,
        "bytes": 1,
        "artifact_revision_id": "rev_" + "0" * 32,
    }[field]
    with pytest.raises(ValueError, match="PREPARED_BASE_MISMATCH"):
        require_native_visual_prepared_base(
            prepared,
            base=base_prepared(),
            base_pointer=MaterialArtifactMember.model_validate(values),
        )


@pytest.mark.parametrize("field", ["sha256", "bytes"])
def test_base_content_hash_and_size_are_checked_even_when_supplied_pointer_matches(field):
    body = visual_prepared()
    body["base_prepared"][field] = "sha256:" + "0" * 64 if field == "sha256" else 1
    prepared = MaterialNativeVisualPreparedArtifact.model_validate(rehash(body, "prepared_sha256"))
    with pytest.raises(ValueError, match="PREPARED_BASE_MISMATCH"):
        require_native_visual_prepared_base(
            prepared, base=base_prepared(), base_pointer=prepared.base_prepared
        )


def test_prepared_hash_and_closed_wire_are_checked_in_both_validators():
    body = visual_prepared()
    body["prepared_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="PREPARATION_HASH_MISMATCH"):
        MaterialNativeVisualPreparedArtifact.model_validate(body)
    body = visual_prepared()
    body["image_bytes"] = "forbidden"
    with pytest.raises(SchemaError):
        validate_contract("material-learning-prepared-v3", body)
    with pytest.raises(ValueError):
        MaterialNativeVisualPreparedArtifact.model_validate(body)
