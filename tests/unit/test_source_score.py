"""Score successor preserves original values; released integer-only drafts stay closed."""

from decimal import Decimal
from pathlib import Path

import pytest
from eom_catalog_contracts.creative_source_draft import PrintedSourceScore
from eom_catalog_contracts.source_score import (
    PrintedSourceScoreV2,
    parse_source_score_v2,
    source_score_decimal,
)
from eom_catalog_contracts.validation import load_schema
from eom_identifiers import content_sha256
from jsonschema import Draft202012Validator


@pytest.mark.parametrize("points", [0, 1, 2, 3, 100, "1.5", "2.5", "3.5", "99.5"])
def test_exact_printed_score_roundtrips_without_float_or_scale(points):
    score = parse_source_score_v2(dict(state="PRINTED", points=points))
    assert isinstance(score, PrintedSourceScoreV2)
    assert score.points == points and type(score.points) is type(points)
    assert source_score_decimal(score) == Decimal(str(points))
    assert type(score).model_validate_json(score.model_dump_json()) == score
    assert content_sha256(score.model_dump(mode="json")) == content_sha256(
        dict(state="PRINTED", points=points)
    )
    with pytest.raises(ValueError):
        score.points = 15


@pytest.mark.parametrize(
    "points",
    [
        True,
        False,
        1.5,
        2.0,
        -1,
        101,
        "15.0",
        "1.50",
        "01.5",
        "2",
        "0.5",
        "0.25",
        "100.5",
        "NaN",
        "1.5\n",
        "2.5\r",
        None,
    ],
)
def test_no_coercion_rounding_or_unannounced_display_family(points):
    with pytest.raises(ValueError):
        parse_source_score_v2(dict(state="PRINTED", points=points))


def test_unprinted_is_not_zero_and_cannot_carry_a_claimed_printed_value():
    absent = parse_source_score_v2(dict(state="UNPRINTED", points=None))
    assert source_score_decimal(absent) is None
    for value in (0, "1.5"):
        with pytest.raises(ValueError):
            parse_source_score_v2(dict(state="UNPRINTED", points=value))
    with pytest.raises(ValueError):
        parse_source_score_v2(dict(state="PRINTED", points="1.5", scale=10))


def test_old_draft_score_stays_integer_only_and_new_schema_is_an_exact_mirror():
    for value in ("1.5", 1.5):
        with pytest.raises(ValueError):
            PrintedSourceScore(state="PRINTED", points=value)
    schema = load_schema("source-score-v2")
    Draft202012Validator.check_schema(schema)
    root = Path(__file__).resolve().parents[2]
    path = "external-item/source-score-v2.schema.json"
    assert (root / "schemas" / path).read_bytes() == (
        root / "packages/catalog_contracts/eom_catalog_contracts/resources" / path
    ).read_bytes()


@pytest.mark.parametrize("points", ["1.5\n", "2.5\r", "1.5 ", "1.50", True, 1.5])
def test_installed_json_schema_rejects_the_same_noncanonical_values(points):
    from eom_catalog_contracts.validation import validate_contract
    from jsonschema.exceptions import ValidationError

    with pytest.raises(ValidationError):
        validate_contract("source-score-v2", dict(state="PRINTED", points=points))
