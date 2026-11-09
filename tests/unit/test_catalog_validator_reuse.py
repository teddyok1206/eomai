"""Reuse installed schema machinery, never caller data or acceptance decisions."""

import gc
import weakref
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import patch

import pytest
from eom_catalog_contracts import validation
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from tests.unit.test_catalog_contract_resources import _prompt_envelope


@pytest.fixture(autouse=True)
def clear_compiled_validators():
    validation._contract_validator.cache_clear()
    yield
    validation._contract_validator.cache_clear()


def original_validator(name):
    return Draft202012Validator(
        validation.load_schema(name),
        format_checker=FormatChecker(),
        registry=validation.catalog_schema_registry(),
    )


def outcome(validate, value):
    try:
        validate(value)
        return None
    except ValidationError as error:
        return error.message, tuple(error.absolute_path), tuple(error.absolute_schema_path)


def test_repeated_validation_builds_schema_resolver_once_but_checks_each_payload():
    value = _prompt_envelope()
    validation.catalog_schema_registry()
    with patch.object(validation, "Draft202012Validator", wraps=Draft202012Validator) as build:
        for _ in range(25):
            validation.validate_contract("prompt-envelope", value)
        assert build.call_count == 1
        value["workflow_id"] = "invalid"
        with pytest.raises(ValidationError):
            validation.validate_contract("prompt-envelope", value)
        assert build.call_count == 1


@pytest.mark.parametrize("fault", (None, "id", "extra", "missing", "array", "hash"))
def test_compiled_and_original_validation_have_identical_outcomes(fault):
    value = _prompt_envelope()
    if fault == "id":
        value["workflow_id"] = "invalid"
    elif fault == "extra":
        value["unexpected"] = True
    elif fault == "missing":
        del value["pack_release_id"]
    elif fault == "array":
        value["source_intake_batch_ids"] = ["invalid"]
    elif fault == "hash":
        value["pack_release_sha256"] = "sha256:bad"
    before = deepcopy(value)
    reference = original_validator("prompt-envelope")
    expected = outcome(reference.validate, value)
    for _ in range(3):
        assert outcome(lambda raw: validation.validate_contract("prompt-envelope", raw), value) == (
            expected
        )
        assert value == before


def test_compiled_validator_preserves_cross_schema_references():
    from tests.unit.test_public_solution_indexing_policy import public_policy_document

    name = "education-retrieval-access-policy-v1.4"
    value = public_policy_document()
    reference = original_validator(name)
    assert outcome(reference.validate, value) is None
    validation.validate_contract(name, value)
    value["service"]["service_id"] = "invalid"
    expected = outcome(reference.validate, value)
    assert expected is not None
    assert outcome(lambda raw: validation.validate_contract(name, raw), value) == expected


def test_compiled_validator_keeps_format_checks(monkeypatch):
    schema = {"type": "object", "properties": {"address": {"format": "ipv4"}}}
    monkeypatch.setattr(validation, "load_schema", lambda name: schema)
    name = "test-format-only"
    validation.validate_contract(name, {"address": "127.0.0.1"})
    invalid = {"address": "999.0.0.1"}
    expected = outcome(original_validator(name).validate, invalid)
    assert expected is not None
    assert outcome(lambda raw: validation.validate_contract(name, raw), invalid) == expected


@pytest.mark.parametrize("name", ("prompt-envelope", "education-retrieval-access-policy-v1.4"))
def test_threads_do_not_share_validation_input_or_failure_state(name):
    if name == "prompt-envelope":
        good = _prompt_envelope()
        bad = {**good, "workflow_id": "invalid"}
    else:
        from tests.unit.test_public_solution_indexing_policy import public_policy_document

        good = public_policy_document()
        bad = deepcopy(good)
        bad["service"]["service_id"] = "invalid"
    validation.validate_contract(name, good)
    expected_error = outcome(original_validator(name).validate, bad)

    def check(number):
        value = deepcopy(good if number % 2 == 0 else bad)
        return outcome(lambda raw: validation.validate_contract(name, raw), value)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = tuple(executor.map(check, range(100)))
    assert results == tuple(None if index % 2 == 0 else expected_error for index in range(100))


@pytest.mark.parametrize("invalid", (False, True))
def test_compiled_validator_does_not_retain_caller_payload_or_error(invalid):
    class WeakPayload(dict):
        pass

    def validate_temporary_payload():
        payload = WeakPayload(_prompt_envelope())
        if invalid:
            payload["workflow_id"] = "invalid"
        reference = weakref.ref(payload)
        result = outcome(lambda raw: validation.validate_contract("prompt-envelope", raw), payload)
        assert (result is not None) == invalid
        return reference

    reference = validate_temporary_payload()
    gc.collect()
    assert validation._contract_validator.cache_info().currsize == 1
    assert reference() is None


def test_unknown_or_broken_package_resources_never_become_cached_acceptance(monkeypatch):
    with pytest.raises(validation.CatalogSchemaError, match="unknown"):
        validation.validate_contract("not-a-catalog-schema", {})
    original = validation.load_schema

    def broken(name):
        raise validation.CatalogSchemaError("package resource hash mismatch")

    monkeypatch.setattr(validation, "load_schema", broken)
    with pytest.raises(validation.CatalogSchemaError, match="hash mismatch"):
        validation.validate_contract("prompt-envelope", _prompt_envelope())
    assert validation._contract_validator.cache_info().currsize == 0
    monkeypatch.setattr(validation, "load_schema", original)
    validation.validate_contract("prompt-envelope", _prompt_envelope())
    assert validation._contract_validator.cache_info().maxsize == len(
        validation.CATALOG_SCHEMA_RESOURCES
    )
