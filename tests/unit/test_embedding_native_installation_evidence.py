"""ROOTLOCAL metadata SOURCE tests only; no prefix/unit observation, seal or runtime grant."""

from __future__ import annotations

import ast
import json
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import eom_catalog_contracts.embedding_native_installation_evidence as evidence
import pytest
from eom_catalog_contracts.embedding_installed_runtime_proof import (
    EmbeddingInstalledRuntimeProof,
    installed_runtime_proof_bytes,
)
from eom_catalog_contracts.embedding_native_installation_evidence import (
    ADMISSION_EVIDENCE_DRAFT_RAW_SHA256,
    MAX_ROOTLOCAL_ADMISSION_EVIDENCE_BYTES,
    MAX_ROOTLOCAL_PREFIX_INVENTORY_BYTES,
    PREFIX_INVENTORY_DRAFT_RAW_SHA256,
    ROOTLOCAL_ADMISSION_EVIDENCE_REF,
    ROOTLOCAL_PREFIX_INVENTORY_REF,
    RootLocalInstallationEvidenceError,
    RootLocalNativeAdmissionReceiptMetadata,
    RootLocalPrefixInventoryCandidate,
    parse_rootlocal_native_admission_receipt_metadata,
    parse_rootlocal_prefix_inventory_candidate,
    rootlocal_native_admission_receipt_metadata_bytes,
    rootlocal_prefix_inventory_candidate_bytes,
    validate_rootlocal_native_installation_metadata_references,
)
from eom_catalog_contracts.embedding_native_runtime_config import (
    EmbeddingNativeRuntimeConfig,
    embedding_native_runtime_config_bytes,
)
from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingRuntimeBundle,
    embedding_runtime_bundle_bytes,
)
from eom_catalog_contracts.validation import catalog_schema_inventory, catalog_schema_registry
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from referencing import Registry

from tests.unit.embedding_native_runtime_config_fixtures import native_config_metadata
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import sha

ROOT = Path(__file__).resolve().parents[2]
INVENTORY_DRAFT = (
    ROOT / "docs/architecture/embedding-native-prefix-inventory-v1.schema.proposal.json"
)
RECEIPT_DRAFT = (
    ROOT / "docs/architecture/embedding-native-admission-receipt-v1.schema.proposal.json"
)


def epoch(kind: int, inode: int, *, size: int = 1, links: int = 1) -> list[int]:
    return [1, inode, 0, 0, kind | 0o755, links, size, 1000, 1000]


def inventory_body() -> dict[str, Any]:
    return seal(
        {
            "schema_version": "embedding-native-prefix-inventory/1.0",
            "evidence_state": "CANDIDATE_NOT_ADMITTED",
            "profile": "CPU_INDEX_FP32",
            "owner_input_raw_sha256": sha("1"),
            "host_seed_sha256": sha("2"),
            "boot_id": "12345678-1234-1234-1234-123456789abc",
            "prefix_root_epoch": epoch(stat.S_IFDIR, 10, size=4096, links=2),
            "fixed_ancestor_epochs": [epoch(stat.S_IFDIR, index)[:5] for index in range(1, 6)],
            "audit": {
                "source_closure_sha256": sha("3"),
                "member_inventory_sha256": sha("4"),
                "byte_closure_sha256": sha("5"),
                "elf_closure_sha256": sha("6"),
                "regular_members": 1,
                "link_members": 1,
                "size_bytes": 1,
                "elf_members": 1,
            },
            "entries": [
                {
                    "relative_member": "lib",
                    "kind": "DIRECTORY",
                    "epoch": epoch(stat.S_IFDIR, 11, links=2),
                    "sha256": None,
                    "symlink_target": None,
                },
                {
                    "relative_member": "lib/encoder.py",
                    "kind": "REGULAR",
                    "epoch": epoch(stat.S_IFREG, 12),
                    "sha256": sha("7"),
                    "symlink_target": None,
                },
                {
                    "relative_member": "lib/encoder_alias.py",
                    "kind": "SYMLINK",
                    "epoch": epoch(stat.S_IFLNK, 13),
                    "sha256": None,
                    "symlink_target": "encoder.py",
                },
            ],
        },
        "inventory_sha256",
    )


@dataclass(frozen=True)
class MetadataCase:
    inventory: RootLocalPrefixInventoryCandidate
    receipt: RootLocalNativeAdmissionReceiptMetadata
    config: EmbeddingNativeRuntimeConfig
    bundle: EmbeddingRuntimeBundle
    proof: EmbeddingInstalledRuntimeProof


def receipt_body(
    inventory: RootLocalPrefixInventoryCandidate, config: EmbeddingNativeRuntimeConfig
) -> dict[str, Any]:
    return seal(
        {
            "schema_version": "embedding-native-admission-receipt/1.0",
            "evidence_state": "SEALED_INSTALLATION_EVIDENCE",
            "profile": "CPU_INDEX_FP32",
            "configuration": {
                "configuration_id": config.configuration_id,
                "configuration_revision_id": config.configuration_revision_id,
                "configuration_raw_sha256": sha256_bytes(
                    embedding_native_runtime_config_bytes(config)
                ),
                "configuration_sha256": config.config_sha256,
            },
            "inventory": {
                "schema_ref": ROOTLOCAL_PREFIX_INVENTORY_REF,
                "inventory_raw_sha256": sha256_bytes(
                    rootlocal_prefix_inventory_candidate_bytes(inventory)
                ),
                "inventory_sha256": inventory.inventory_sha256,
            },
            "installed_proof": config.installed_proof.model_dump(mode="json"),
            "bundle": config.bundle.model_dump(mode="json"),
            "runtime_sha256": config.runtime_sha256,
            "unit_probe": {
                "recipe": "NATIVE_CPU_FIXED_UNIT_NO_MODEL_NO_FORWARD_NEGATIVES/1.0",
                "execution_id": "a" * 32,
                "invocation_id": "b" * 32,
                "pid": 123,
                "start_time_ticks": 987,
                "worker_uid": 2013,
                "worker_gid": 2013,
                "supplementary_gids": [],
                "unit_template_sha256": sha("8"),
                "probe_code_sha256": sha("9"),
                "effective_policy_sha256": sha("a"),
                "probe_report_raw_sha256": sha("b"),
                "loaded_elf_members_sha256": sha("c"),
                "observed_runtime_sha256": config.runtime_sha256,
                "model_constructor_calls": 0,
                "tokenizer_constructor_calls": 0,
                "forward_calls": 0,
                "terminal_exec_main_code": 1,
                "terminal_exec_main_status": 0,
                "terminal_main_pid": 0,
                "terminal_cgroup_member_count": 0,
                "terminated_at_utc": "2026-10-13T00:00:00Z",
            },
            "sealed_at_utc": "2026-10-13T00:00:01Z",
        },
        "receipt_sha256",
    )


@pytest.fixture(scope="module")
def metadata_case() -> MetadataCase:
    config, bundle, proof = native_config_metadata()
    inventory = parse_rootlocal_prefix_inventory_candidate(
        canonical_json_bytes(inventory_body()), schema_raw=INVENTORY_DRAFT.read_bytes()
    )
    receipt = parse_rootlocal_native_admission_receipt_metadata(
        canonical_json_bytes(receipt_body(inventory, config)), schema_raw=RECEIPT_DRAFT.read_bytes()
    )
    return MetadataCase(inventory, receipt, config, bundle, proof)


def parse_bytes(kind: str, raw: bytes, *, schema: bytes | None = None) -> object:
    if kind == "inventory":
        return parse_rootlocal_prefix_inventory_candidate(
            raw, schema_raw=schema if schema is not None else INVENTORY_DRAFT.read_bytes()
        )
    return parse_rootlocal_native_admission_receipt_metadata(
        raw, schema_raw=schema if schema is not None else RECEIPT_DRAFT.read_bytes()
    )


def reference_frame(case: MetadataCase, **changes: Any) -> None:
    receipt_raw = rootlocal_native_admission_receipt_metadata_bytes(case.receipt)
    arguments: dict[str, Any] = {
        "receipt": case.receipt,
        "receipt_raw": receipt_raw,
        "expected_receipt_raw_sha256": sha256_bytes(receipt_raw),
        "inventory": case.inventory,
        "inventory_raw": rootlocal_prefix_inventory_candidate_bytes(case.inventory),
        "config": case.config,
        "config_raw": embedding_native_runtime_config_bytes(case.config),
        "proof": case.proof,
        "proof_raw": installed_runtime_proof_bytes(case.proof),
        "bundle": case.bundle,
        "bundle_raw": embedding_runtime_bundle_bytes(case.bundle),
    } | changes
    validate_rootlocal_native_installation_metadata_references(**arguments)


def test_exact_unregistered_draft_schema_readers_and_whole_reference_resolution(
    metadata_case: MetadataCase,
) -> None:
    before = catalog_schema_inventory()
    for path, ref, digest in (
        (INVENTORY_DRAFT, ROOTLOCAL_PREFIX_INVENTORY_REF, PREFIX_INVENTORY_DRAFT_RAW_SHA256),
        (RECEIPT_DRAFT, ROOTLOCAL_ADMISSION_EVIDENCE_REF, ADMISSION_EVIDENCE_DRAFT_RAW_SHA256),
    ):
        raw = path.read_bytes()
        assert sha256_bytes(raw) == digest
        schema = json.loads(raw)
        Draft202012Validator.check_schema(schema)
        assert schema["$id"] == ref and schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        assert catalog_schema_registry().get(ref) is None
    reference_frame(metadata_case)
    assert catalog_schema_inventory() == before


def test_missing_installed_schema_reference_is_explicit_metadata_failure(
    metadata_case: MetadataCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(evidence, "catalog_schema_registry", lambda: Registry())
    with pytest.raises(
        RootLocalInstallationEvidenceError, match="ROOTLOCAL_ADMISSION_EVIDENCE_INVALID"
    ):
        parse_bytes(
            "receipt", rootlocal_native_admission_receipt_metadata_bytes(metadata_case.receipt)
        )


def test_exact_canonical_frozen_metadata_has_separate_raw_and_semantic_pins(
    metadata_case: MetadataCase,
) -> None:
    case = metadata_case
    for kind, value, raw in (
        ("inventory", case.inventory, rootlocal_prefix_inventory_candidate_bytes(case.inventory)),
        ("receipt", case.receipt, rootlocal_native_admission_receipt_metadata_bytes(case.receipt)),
    ):
        assert parse_bytes(kind, raw) == value
        assert raw == canonical_json_bytes(value.model_dump(mode="json"))
        with pytest.raises(ValueError):
            cast(Any, value).profile = "CUDA_INDEX_FP32"
    assert (
        sha256_bytes(rootlocal_prefix_inventory_candidate_bytes(case.inventory))
        != case.inventory.inventory_sha256
    )
    assert (
        sha256_bytes(rootlocal_native_admission_receipt_metadata_bytes(case.receipt))
        != case.receipt.receipt_sha256
    )
    assert case.inventory.evidence_state == "CANDIDATE_NOT_ADMITTED"
    assert not hasattr(case.inventory, "seal") and not hasattr(case.receipt, "assert_current")


@pytest.mark.parametrize("kind", ["inventory", "receipt"])
@pytest.mark.parametrize(
    "fault",
    [
        "whitespace",
        "duplicate",
        "float",
        "nan",
        "invalid_utf8",
        "array",
        "extra",
        "missing",
        "hash",
        "schema_override",
    ],
)
def test_raw_closed_canonical_decoder_rejects_without_repair(
    metadata_case: MetadataCase, kind: str, fault: str
) -> None:
    value = metadata_case.inventory if kind == "inventory" else metadata_case.receipt
    raw = canonical_json_bytes(value.model_dump(mode="json"))
    schema = None
    if fault == "whitespace":
        raw += b"\n"
    elif fault == "duplicate":
        raw = b'{"profile":"CPU_INDEX_FP32",' + raw[1:]
    elif fault in {"float", "nan"}:
        raw = b'{"value":' + (b"1.0" if fault == "float" else b"NaN") + b"}"
    elif fault == "invalid_utf8":
        raw = b'{"value":"\xff"}'
    elif fault == "array":
        raw = b"[]"
    elif fault == "schema_override":
        schema = (INVENTORY_DRAFT if kind == "inventory" else RECEIPT_DRAFT).read_bytes() + b" "
    else:
        body = value.model_dump(mode="json")
        hash_field = "inventory_sha256" if kind == "inventory" else "receipt_sha256"
        if fault == "extra":
            body["admitted"] = True
        elif fault == "missing":
            body.pop("evidence_state")
        else:
            body[hash_field] = sha("f")
        raw = canonical_json_bytes(body if fault == "hash" else seal(body, hash_field))
    with pytest.raises(RootLocalInstallationEvidenceError):
        parse_bytes(kind, raw, schema=schema)


@pytest.mark.parametrize("kind", ["inventory", "receipt"])
@pytest.mark.parametrize("fault", ["oversize", "depth", "integer_lexeme"])
def test_allocation_bounds_are_checked_before_json(
    kind: str, fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    limit = (
        MAX_ROOTLOCAL_PREFIX_INVENTORY_BYTES
        if kind == "inventory"
        else MAX_ROOTLOCAL_ADMISSION_EVIDENCE_BYTES
    )
    raw = (
        b" " * (limit + 1)
        if fault == "oversize"
        else b'{"value":' + (b"[" * 16 + b"0" + b"]" * 16 if fault == "depth" else b"1" * 21) + b"}"
    )
    schema = (INVENTORY_DRAFT if kind == "inventory" else RECEIPT_DRAFT).read_bytes()

    def no_json(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("bad allocation frame must be rejected before JSON")

    monkeypatch.setattr(json, "loads", no_json)
    with pytest.raises(RootLocalInstallationEvidenceError):
        parse_bytes(kind, raw, schema=schema)


@pytest.mark.parametrize(
    "fault",
    [
        "order",
        "duplicate",
        "kind",
        "uid",
        "bool",
        "range",
        "parent",
        "regular_hash",
        "directory_hash",
        "link_hash",
        "link_target",
        "count",
        "size",
        "elf",
        "state",
    ],
)
def test_inventory_domain_frame_after_resealing(fault: str) -> None:
    body = inventory_body()
    if fault == "order":
        body["entries"].reverse()
    elif fault == "duplicate":
        body["entries"][2] = body["entries"][1]
    elif fault == "kind":
        body["entries"][1]["epoch"][4] = stat.S_IFDIR | 0o755
    elif fault in {"uid", "bool", "range"}:
        body["entries"][1]["epoch"][2 if fault == "uid" else 0] = (
            1000 if fault == "uid" else True if fault == "bool" else 18446744073709551616
        )
    elif fault == "parent":
        body["entries"].pop(0)
    elif fault == "regular_hash":
        body["entries"][1]["sha256"] = None
    elif fault == "directory_hash":
        body["entries"][0]["sha256"] = sha("0")
    elif fault == "link_hash":
        body["entries"][2]["sha256"] = sha("0")
    elif fault == "link_target":
        body["entries"][2]["symlink_target"] = "/outside"
    elif fault in {"count", "size", "elf"}:
        body["audit"][
            {"count": "regular_members", "size": "size_bytes", "elf": "elf_members"}[fault]
        ] = 2
    else:
        body["evidence_state"] = "SEALED_INSTALLATION_EVIDENCE"
    raw = canonical_json_bytes(seal(body, "inventory_sha256"))
    with pytest.raises(RootLocalInstallationEvidenceError):
        parse_bytes("inventory", raw)
    with pytest.raises(ValueError):
        RootLocalPrefixInventoryCandidate.model_validate(json.loads(raw))


@pytest.mark.parametrize(
    "name",
    [
        "/absolute",
        "../escape",
        "lib//file",
        "lib/./file",
        "lib\\file",
        "lib/file/",
        "lib/\x7f",
        "한" * 171,
    ],
)
def test_inventory_relative_names_are_strict_utf8_bounded(name: str) -> None:
    body = inventory_body()
    body["entries"][1]["relative_member"] = name
    with pytest.raises(ValueError):
        RootLocalPrefixInventoryCandidate.model_validate(seal(body, "inventory_sha256"))


@pytest.mark.parametrize(
    "fault",
    [
        "CPU_only",
        "bool",
        "pid",
        "gids",
        "forward",
        "constructor",
        "exit",
        "live_pid",
        "cgroup",
        "runtime",
        "proof_profile",
        "time_order",
    ],
)
def test_receipt_claim_cannot_bypass_fixed_no_model_terminal_cpu_frame(
    metadata_case: MetadataCase, fault: str
) -> None:
    body = metadata_case.receipt.model_dump(mode="json")
    probe = body["unit_probe"]
    if fault == "CPU_only":
        body["profile"] = "CUDA_INDEX_FP32"
    elif fault in {"bool", "pid"}:
        probe["pid"] = True if fault == "bool" else 0
    elif fault == "gids":
        probe["supplementary_gids"] = [2013]
    elif fault in {"forward", "constructor", "exit", "live_pid", "cgroup"}:
        probe[
            {
                "forward": "forward_calls",
                "constructor": "model_constructor_calls",
                "exit": "terminal_exec_main_status",
                "live_pid": "terminal_main_pid",
                "cgroup": "terminal_cgroup_member_count",
            }[fault]
        ] = 1
    elif fault == "runtime":
        probe["observed_runtime_sha256"] = sha("f")
    elif fault == "proof_profile":
        body["installed_proof"]["profile"] = "CUDA_INDEX_FP32"
    else:
        body["sealed_at_utc"] = "2026-10-12T23:59:59Z"
    raw = canonical_json_bytes(seal(body, "receipt_sha256"))
    with pytest.raises(RootLocalInstallationEvidenceError):
        parse_bytes("receipt", raw)
    with pytest.raises(ValueError):
        RootLocalNativeAdmissionReceiptMetadata.model_validate(json.loads(raw))


@pytest.mark.parametrize("field", ["sealed_at_utc", "terminated_at_utc"])
@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-02-30T00:00:00Z",
        "2026-10-13T25:00:00Z",
        "2026-10-13T00:00:60Z",
        "2026-10-13T00:00:00+00:00",
        "2026-10-13T00:00:00Z\n",
        "2026-10-13T00:00:00.0000001Z",
    ],
)
def test_receipt_actual_calendar_utc_is_not_an_optional_format_annotation(
    metadata_case: MetadataCase, field: str, timestamp: str
) -> None:
    body = metadata_case.receipt.model_dump(mode="json")
    (body if field == "sealed_at_utc" else body["unit_probe"])[field] = timestamp
    with pytest.raises(ValueError):
        RootLocalNativeAdmissionReceiptMetadata.model_validate(seal(body, "receipt_sha256"))


@pytest.mark.parametrize(
    "field",
    [
        "pid",
        "start_time_ticks",
        "worker_uid",
        "worker_gid",
        "model_constructor_calls",
        "tokenizer_constructor_calls",
        "forward_calls",
        "terminal_exec_main_code",
        "terminal_exec_main_status",
        "terminal_main_pid",
        "terminal_cgroup_member_count",
    ],
)
@pytest.mark.parametrize("bad", [True, False])
def test_every_unit_integer_rejects_bool_even_when_equal_to_zero_or_one(
    metadata_case: MetadataCase, field: str, bad: bool
) -> None:
    body = metadata_case.receipt.model_dump(mode="json")
    body["unit_probe"][field] = bad
    with pytest.raises(ValueError):
        RootLocalNativeAdmissionReceiptMetadata.model_validate(seal(body, "receipt_sha256"))


@pytest.mark.parametrize("index", range(9))
def test_every_stat_integer_is_exact_raw_not_bool(index: int) -> None:
    body = inventory_body()
    body["prefix_root_epoch"][index] = False
    with pytest.raises(ValueError):
        RootLocalPrefixInventoryCandidate.model_validate(seal(body, "inventory_sha256"))


@pytest.mark.parametrize("kind", ["inventory", "receipt"])
@pytest.mark.parametrize(
    "fault", ["extra", "nested_extra", "nested_bool", "missing", "semantic_hash"]
)
def test_frozen_copied_constructed_values_revalidated_before_dump(
    metadata_case: MetadataCase, kind: str, fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = metadata_case.inventory if kind == "inventory" else metadata_case.receipt
    if fault == "extra":
        value = value.model_copy(update={"authority": "ROOT"})
    elif fault == "missing":
        body = value.model_dump()
        body.pop("profile")
        value = type(value).model_construct(**body)
    elif fault == "semantic_hash":
        value = value.model_copy(
            update={"inventory_sha256" if kind == "inventory" else "receipt_sha256": sha("f")}
        )
    elif kind == "inventory":
        entry = metadata_case.inventory.entries[1]
        change = (
            {"authority": "ROOT"}
            if fault == "nested_extra"
            else {"epoch": (True, *entry.epoch[1:])}
        )
        entries = (
            metadata_case.inventory.entries[0],
            entry.model_copy(update=change),
            metadata_case.inventory.entries[2],
        )
        value = metadata_case.inventory.model_copy(update={"entries": entries})
    else:
        probe = metadata_case.receipt.unit_probe.model_copy(
            update={"authority": "ROOT"}
            if fault == "nested_extra"
            else {"terminal_exec_main_status": False}
        )
        value = metadata_case.receipt.model_copy(update={"unit_probe": probe})

    def no_dump(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("bad raw construction must fail before dump")

    if fault != "semantic_hash":
        monkeypatch.setattr(type(value), "model_dump", no_dump)
    with pytest.raises(ValueError):
        (
            rootlocal_prefix_inventory_candidate_bytes
            if kind == "inventory"
            else rootlocal_native_admission_receipt_metadata_bytes
        )(cast(Any, value))


@pytest.mark.parametrize(
    "fault",
    [
        "independent_raw",
        "receipt_raw",
        "inventory_raw",
        "config_raw",
        "proof_raw",
        "bundle_raw",
        "inventory_semantic",
        "config_revision",
        "config_semantic",
        "proof_revision",
        "bundle_revision",
        "proof_semantic",
        "bundle_semantic",
        "runtime",
    ],
)
def test_independent_raw_semantic_revision_reference_closure(
    metadata_case: MetadataCase, fault: str
) -> None:
    changes: dict[str, Any] = {}
    if fault == "independent_raw":
        changes["expected_receipt_raw_sha256"] = metadata_case.receipt.receipt_sha256
    elif fault.endswith("_raw"):
        key = fault
        original = {
            "receipt_raw": rootlocal_native_admission_receipt_metadata_bytes(metadata_case.receipt),
            "inventory_raw": rootlocal_prefix_inventory_candidate_bytes(metadata_case.inventory),
            "config_raw": embedding_native_runtime_config_bytes(metadata_case.config),
            "proof_raw": installed_runtime_proof_bytes(metadata_case.proof),
            "bundle_raw": embedding_runtime_bundle_bytes(metadata_case.bundle),
        }[key]
        changes[key] = original + b"\n"
    else:
        body = metadata_case.receipt.model_dump(mode="json")
        if fault == "inventory_semantic":
            body["inventory"]["inventory_sha256"] = body["inventory"]["inventory_raw_sha256"]
        elif fault == "config_revision":
            body["configuration"]["configuration_revision_id"] = (
                "embeddingnativeconfigrev_" + "f" * 32
            )
        elif fault == "config_semantic":
            body["configuration"]["configuration_sha256"] = sha("f")
        elif fault == "proof_revision":
            body["installed_proof"]["proof_revision_id"] = "embeddingruntimeproofrev_" + "f" * 32
        elif fault == "bundle_revision":
            body["bundle"]["bundle_revision_id"] = "embeddingbundlerev_" + "f" * 32
        elif fault == "proof_semantic":
            body["installed_proof"]["proof_sha256"] = sha("f")
        elif fault == "bundle_semantic":
            body["bundle"]["bundle_sha256"] = sha("f")
        else:
            body["runtime_sha256"] = body["unit_probe"]["observed_runtime_sha256"] = sha("f")
        receipt = RootLocalNativeAdmissionReceiptMetadata.model_validate(
            seal(body, "receipt_sha256")
        )
        raw = rootlocal_native_admission_receipt_metadata_bytes(receipt)
        changes = {
            "receipt": receipt,
            "receipt_raw": raw,
            "expected_receipt_raw_sha256": sha256_bytes(raw),
        }
    with pytest.raises(
        RootLocalInstallationEvidenceError, match="ROOTLOCAL_INSTALLATION_REFERENCE_INVALID"
    ):
        reference_frame(metadata_case, **changes)


@pytest.mark.parametrize("field", ["config", "proof", "bundle"])
def test_reference_objects_with_copied_extra_are_not_reinterpreted(
    metadata_case: MetadataCase, field: str
) -> None:
    original = {
        "config": metadata_case.config,
        "proof": metadata_case.proof,
        "bundle": metadata_case.bundle,
    }[field]
    with pytest.raises(
        RootLocalInstallationEvidenceError, match="ROOTLOCAL_INSTALLATION_REFERENCE_INVALID"
    ):
        reference_frame(metadata_case, **{field: original.model_copy(update={"authority": "ROOT"})})


def test_inventory_array_limit_rejects_before_materialization() -> None:
    body = inventory_body()
    body["entries"] = [body["entries"][1]] * 100_001
    with pytest.raises(ValueError, match="array bound"):
        RootLocalPrefixInventoryCandidate.model_validate(body)


def test_larger_than_similarity_array_limit_remains_bounded_sorted_inventory() -> None:
    body = inventory_body()
    body["entries"] = [
        {
            "relative_member": f"member_{index:05d}",
            "kind": "REGULAR",
            "epoch": epoch(stat.S_IFREG, index + 10),
            "sha256": sha("7"),
            "symlink_target": None,
        }
        for index in range(1100)
    ]
    body["audit"].update(regular_members=1100, link_members=0, size_bytes=1100)
    raw = canonical_json_bytes(seal(body, "inventory_sha256"))
    parsed = parse_rootlocal_prefix_inventory_candidate(
        raw, schema_raw=INVENTORY_DRAFT.read_bytes()
    )
    assert len(parsed.entries) == 1100


def test_cuda_candidate_and_relative_link_metadata_do_not_become_a_seal() -> None:
    body = inventory_body()
    body["profile"] = "CUDA_INDEX_FP32"
    body["entries"][2]["symlink_target"] = "../lib/encoder.py"
    raw = canonical_json_bytes(seal(body, "inventory_sha256"))
    parsed = parse_rootlocal_prefix_inventory_candidate(
        raw, schema_raw=INVENTORY_DRAFT.read_bytes()
    )
    assert parsed.profile == "CUDA_INDEX_FP32"
    assert parsed.evidence_state == "CANDIDATE_NOT_ADMITTED"
    assert parsed.entries[2].symlink_target == "../lib/encoder.py"
    with pytest.raises(RootLocalInstallationEvidenceError):
        parse_rootlocal_native_admission_receipt_metadata(
            raw, schema_raw=RECEIPT_DRAFT.read_bytes()
        )


def test_complete_inventory_preserves_valid_empty_directory_metadata() -> None:
    body = inventory_body()
    body["entries"].append(
        {
            "relative_member": "unused",
            "kind": "DIRECTORY",
            "epoch": epoch(stat.S_IFDIR, 14, links=2),
            "sha256": None,
            "symlink_target": None,
        }
    )
    body = seal(body, "inventory_sha256")
    schema_raw = INVENTORY_DRAFT.read_bytes()
    Draft202012Validator(json.loads(schema_raw), registry=catalog_schema_registry()).validate(body)
    parsed = parse_rootlocal_prefix_inventory_candidate(
        canonical_json_bytes(body), schema_raw=schema_raw
    )
    assert parsed.entries[-1].relative_member == "unused"


def test_directory_entry_also_requires_its_immediate_parent_metadata() -> None:
    body = inventory_body()
    body["entries"].append(
        {
            "relative_member": "missing/unused",
            "kind": "DIRECTORY",
            "epoch": epoch(stat.S_IFDIR, 14, links=2),
            "sha256": None,
            "symlink_target": None,
        }
    )
    with pytest.raises(RootLocalInstallationEvidenceError):
        parse_bytes("inventory", canonical_json_bytes(seal(body, "inventory_sha256")))


def test_contract_module_has_no_io_infrastructure_or_grant_export() -> None:
    path = (
        ROOT
        / "packages/catalog_contracts/eom_catalog_contracts"
        / "embedding_native_installation_evidence.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = {"os", "pathlib", "subprocess", "socket", "sqlalchemy", "requests"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] not in forbidden for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None and node.module.split(".")[0] not in forbidden
            assert not node.module.startswith(
                ("eom_catalog_service", "eom_orchestrator", "eom_application_api")
            )
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in {"open", "eval", "exec", "__import__"}
            elif isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {
                    "read_bytes",
                    "write_bytes",
                    "publish",
                    "seal",
                    "execute",
                    "assert_current",
                }
