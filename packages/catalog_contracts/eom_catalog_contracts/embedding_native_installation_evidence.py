"""ROOTLOCAL parsed metadata only: no prefix observation, candidate seal or runtime grant."""

from __future__ import annotations

import json
import re
import stat
from typing import Annotated, Any, Final, Literal

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator
from referencing.exceptions import Unresolvable

from eom_catalog_contracts.embedding_installed_runtime_proof import (
    MAX_INSTALLED_RUNTIME_PROOF_BYTES,
    EmbeddingInstalledRuntimeProof,
    EmbeddingInstalledRuntimeProofPointer,
    EmbeddingRuntimeProfile,
    parse_installed_runtime_proof,
    validate_installed_runtime_proof_pointer,
)
from eom_catalog_contracts.embedding_native_runtime_config import (
    InstalledEmbeddingNativeRuntimeConfig,
    parse_installed_embedding_native_runtime_config,
    parse_installed_embedding_native_runtime_config_bytes,
    validate_installed_embedding_native_runtime_config_raw,
    validate_installed_embedding_native_runtime_config_references,
)
from eom_catalog_contracts.embedding_runtime_bundle import (
    MAX_RUNTIME_BUNDLE_BYTES,
    EmbeddingRuntimeBundle,
    EmbeddingRuntimeBundlePointer,
    parse_embedding_runtime_bundle,
    validate_embedding_runtime_bundle_pointer,
)
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import catalog_schema_registry

ROOTLOCAL_PREFIX_INVENTORY_REF: Final = "eom://local/embedding-native-prefix-inventory/1.0"
ROOTLOCAL_ADMISSION_EVIDENCE_REF: Final = "eom://local/embedding-native-admission-receipt/1.0"
PREFIX_INVENTORY_DRAFT_RAW_SHA256: Final = (
    "sha256:1c9c8b2a05fe8534e95b4955a8111f4882138b70b7374dd93d0770558b1f21d1"
)
ADMISSION_EVIDENCE_DRAFT_RAW_SHA256: Final = (
    "sha256:210b56190b6c71a7c49f6ae290d5dc3c206fdfb9f5c36745ea7aa271e2d1cd1f"
)
MAX_ROOTLOCAL_PREFIX_INVENTORY_BYTES: Final = 16 * 1024**2
MAX_ROOTLOCAL_ADMISSION_EVIDENCE_BYTES: Final = 32 * 1024
_MAX_PREFIX_BYTES = 16 * 1024**3
_MAX_MEMBERS = 100_000
_UTC_PATTERN = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z"
type _Unsigned64 = Annotated[int, Field(ge=0, le=18446744073709551615, strict=True)]
type _Positive64 = Annotated[int, Field(ge=1, le=18446744073709551615, strict=True)]
type _RootUid = Annotated[int, Field(ge=0, le=0, strict=True)]
type _Uid = Annotated[int, Field(ge=0, le=4294967294, strict=True)]
type _Mode = Annotated[int, Field(ge=0, le=65535, strict=True)]
type _Links = Annotated[int, Field(ge=1, le=_MAX_MEMBERS, strict=True)]
type _Size = Annotated[int, Field(ge=0, le=_MAX_PREFIX_BYTES, strict=True)]
type _Zero = Annotated[int, Field(ge=0, le=0, strict=True)]
type _One = Annotated[int, Field(ge=1, le=1, strict=True)]
type _EvidenceSha = Annotated[Sha256, Field(min_length=71, max_length=71, strict=True)]
type RootLocalStatEpoch = tuple[
    _Unsigned64, _Positive64, _RootUid, _Uid, _Mode, _Links, _Size, _Unsigned64, _Unsigned64
]
type RootLocalAncestorEpoch = tuple[_Unsigned64, _Positive64, _RootUid, _Uid, _Mode]
type _RelativeName = Annotated[str, Field(min_length=1, max_length=512, strict=True)]
type _UtcText = Annotated[str, Field(min_length=20, max_length=27, strict=True)]


class RootLocalInstallationEvidenceError(ValueError):
    """Content-free metadata failure, never a statement about actual installation outcome."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _raw_metadata(value: object) -> Any:
    """Two fixed local documents need larger arrays than the public similarity reader permits."""
    nodes = 0

    def read(item: object, depth: int) -> Any:
        nonlocal nodes
        nodes += 1
        if depth > 16 or nodes > 4_000_000:
            raise ValueError("ROOTLOCAL metadata depth/node bound differs")
        if isinstance(item, BaseModel):
            fields = type(item).model_fields
            if item.__pydantic_extra__ or set(item.__dict__) != set(fields):
                raise ValueError("ROOTLOCAL copied/constructed fields differ")
            return {name: read(item.__dict__[name], depth + 1) for name in fields}
        if type(item) is dict:
            if len(item) > 64 or any(type(name) is not str for name in item):
                raise ValueError("ROOTLOCAL metadata object keys/size differ")
            return {name: read(child, depth + 1) for name, child in item.items()}
        if isinstance(item, list | tuple):
            if type(item) not in (list, tuple):
                raise ValueError("ROOTLOCAL metadata sequence type differs")
            if len(item) > _MAX_MEMBERS:
                raise ValueError("ROOTLOCAL metadata array bound differs")
            return [read(child, depth + 1) for child in item]
        if item is None or type(item) in (str, int, bool):
            return item
        raise ValueError("ROOTLOCAL metadata contains a non-JSON or floating scalar")

    return read(value, 0)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in pairs:
        if key in values or len(values) >= 64:
            raise ValueError("ROOTLOCAL metadata duplicate/object bound differs")
        values[key] = value
    return values


def _integer(value: str) -> int:
    if len(value) > 20:
        raise ValueError("ROOTLOCAL integer lexical bound differs")
    return int(value)


def _no_float(value: str) -> Any:
    raise ValueError("ROOTLOCAL metadata cannot contain floating/nonfinite numbers")


def _document(raw: bytes, maximum: int) -> dict[str, Any]:
    """Bound raw bytes/depth/integer lexemes before allocating the JSON value tree."""
    if type(raw) is not bytes or not 0 < len(raw) <= maximum:
        raise ValueError("ROOTLOCAL metadata external byte bound differs")
    depth, number_length, quoted, escaped = 0, 0, False, False
    for character in raw:
        if quoted:
            if escaped:
                escaped = False
            elif character == 92:
                escaped = True
            elif character == 34:
                quoted = False
            continue
        if 48 <= character <= 57 or character == 45:
            number_length += 1
            if number_length > 20:
                raise ValueError("ROOTLOCAL integer pre-allocation bound differs")
        else:
            if number_length and character in (46, 101, 69, 43):
                raise ValueError("ROOTLOCAL floating number is forbidden")
            number_length = 0
        if character == 34:
            quoted = True
        elif character in (91, 123):
            depth += 1
            if depth > 16:
                raise ValueError("ROOTLOCAL metadata pre-allocation depth differs")
        elif character in (93, 125):
            depth -= 1
            if depth < 0:
                raise ValueError("ROOTLOCAL metadata JSON frame differs")
    if depth or quoted:
        raise ValueError("ROOTLOCAL metadata JSON frame is incomplete")
    document: object = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_object,
        parse_int=_integer,
        parse_float=_no_float,
        parse_constant=_no_float,
    )
    if not isinstance(document, dict):
        raise ValueError("ROOTLOCAL metadata requires an object")
    return document


def _validate_draft(
    raw: bytes, document: dict[str, Any], expected_sha256: str, expected_ref: str
) -> None:
    # These are fixed source schema pins, not a caller-chosen plugin or authority assertion.
    if (
        type(raw) is not bytes
        or not 0 < len(raw) <= 32 * 1024
        or sha256_bytes(raw) != expected_sha256
    ):
        raise ValueError("ROOTLOCAL fixed draft raw pin differs")
    schema = _document(raw, 32 * 1024)
    if schema.get("$id") != expected_ref or schema.get("$schema") != (
        "https://json-schema.org/draft/2020-12/schema"
    ):
        raise ValueError("ROOTLOCAL fixed draft identity differs")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(
        schema, format_checker=FormatChecker(), registry=catalog_schema_registry()
    ).validate(document)


class _EvidenceValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def preserve_raw_fields(cls, value: object) -> object:
        return _raw_metadata(value)


def _hash(value: FrozenModel, field: str, maximum: int) -> None:
    document = value.model_dump(mode="json")
    if len(canonical_json_bytes(document)) > maximum or getattr(value, field) != content_sha256(
        {name: child for name, child in document.items() if name != field}
    ):
        raise ValueError("ROOTLOCAL metadata canonical size/semantic hash differs")


def _relative(value: str, *, link: bool = False) -> str:
    if (
        len(value.encode("utf-8")) > 512
        or value.startswith("/")
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or (not link and any(part in {"", ".", ".."} for part in value.split("/")))
    ):
        raise ValueError("ROOTLOCAL relative metadata name differs")
    return value


def _utc(value: str) -> str:
    if re.fullmatch(_UTC_PATTERN, value) is None:
        raise ValueError("ROOTLOCAL UTC spelling differs")
    TypeAdapter(UtcDatetime).validate_python(value)
    return value


class RootLocalPrefixInventoryEntry(_EvidenceValue):
    relative_member: _RelativeName
    kind: Literal["REGULAR", "DIRECTORY", "SYMLINK"]
    epoch: RootLocalStatEpoch
    sha256: _EvidenceSha | None
    symlink_target: _RelativeName | None

    @model_validator(mode="after")
    def exact_kind(self) -> RootLocalPrefixInventoryEntry:
        _relative(self.relative_member)
        mode = self.epoch[4]
        if self.kind == "REGULAR":
            valid = (
                stat.S_ISREG(mode)
                and self.epoch[5] == 1
                and not mode & 0o6022
                and (self.sha256 is not None and self.symlink_target is None)
            )
        elif self.kind == "DIRECTORY":
            valid = (
                stat.S_ISDIR(mode)
                and not mode & 0o022
                and (self.sha256 is None and self.symlink_target is None)
            )
        else:
            valid = (
                stat.S_ISLNK(mode)
                and self.epoch[5] == 1
                and (self.sha256 is None and self.symlink_target is not None)
            )
            if self.symlink_target is not None:
                _relative(self.symlink_target, link=True)
        if not valid:
            raise ValueError("ROOTLOCAL inventory kind/epoch/hash/link frame differs")
        return self


class RootLocalPrefixAuditMetadata(_EvidenceValue):
    source_closure_sha256: _EvidenceSha
    member_inventory_sha256: _EvidenceSha
    byte_closure_sha256: _EvidenceSha
    elf_closure_sha256: _EvidenceSha
    regular_members: int = Field(ge=1, le=_MAX_MEMBERS, strict=True)
    link_members: int = Field(ge=0, le=_MAX_MEMBERS, strict=True)
    size_bytes: int = Field(ge=1, le=_MAX_PREFIX_BYTES, strict=True)
    elf_members: int = Field(ge=1, le=_MAX_MEMBERS, strict=True)


class RootLocalPrefixInventoryCandidate(_EvidenceValue):
    """Declared candidate metadata only; parsing never attests a same-audit prefix origin."""

    schema_version: Literal["embedding-native-prefix-inventory/1.0"]
    evidence_state: Literal["CANDIDATE_NOT_ADMITTED"]
    profile: EmbeddingRuntimeProfile
    owner_input_raw_sha256: _EvidenceSha
    host_seed_sha256: _EvidenceSha
    boot_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        min_length=36,
        max_length=36,
        strict=True,
    )
    prefix_root_epoch: RootLocalStatEpoch
    fixed_ancestor_epochs: tuple[RootLocalAncestorEpoch, ...] = Field(min_length=5, max_length=5)
    audit: RootLocalPrefixAuditMetadata
    entries: tuple[RootLocalPrefixInventoryEntry, ...] = Field(
        min_length=1, max_length=_MAX_MEMBERS
    )
    inventory_sha256: _EvidenceSha

    @model_validator(mode="after")
    def exact_candidate(self) -> RootLocalPrefixInventoryCandidate:
        epochs = (self.prefix_root_epoch, *self.fixed_ancestor_epochs)
        if any(not stat.S_ISDIR(epoch[4]) or epoch[4] & 0o022 for epoch in epochs):
            raise ValueError("ROOTLOCAL inventory root/ancestor directory frame differs")
        previous: str | None = None
        directories: set[str] = set()
        required: set[str] = set()
        regular = links = size = 0
        for entry in self.entries:
            if previous is not None and previous >= entry.relative_member:
                raise ValueError("ROOTLOCAL inventory entries must be sorted and unique")
            previous = entry.relative_member
            parent = entry.relative_member.rpartition("/")[0]
            if parent:
                required.add(parent)
            if entry.kind == "DIRECTORY":
                directories.add(entry.relative_member)
            if entry.kind == "REGULAR":
                regular += 1
                size += entry.epoch[6]
            elif entry.kind == "SYMLINK":
                links += 1
        if (
            not required.issubset(directories)
            or (regular, links, size)
            != (self.audit.regular_members, self.audit.link_members, self.audit.size_bytes)
            or self.audit.elf_members > regular
        ):
            raise ValueError("ROOTLOCAL inventory directory/count/size frame differs")
        _hash(self, "inventory_sha256", MAX_ROOTLOCAL_PREFIX_INVENTORY_BYTES)
        return self


class RootLocalNativeConfigurationPin(_EvidenceValue):
    configuration_id: str = Field(
        pattern=r"^embeddingnativeconfig_[0-9a-f]{32}$", min_length=54, max_length=54
    )
    configuration_revision_id: str = Field(
        pattern=r"^embeddingnativeconfigrev_[0-9a-f]{32}$", min_length=57, max_length=57
    )
    configuration_raw_sha256: _EvidenceSha
    configuration_sha256: _EvidenceSha


class RootLocalPrefixInventoryPin(_EvidenceValue):
    schema_ref: Literal["eom://local/embedding-native-prefix-inventory/1.0"]
    inventory_raw_sha256: _EvidenceSha
    inventory_sha256: _EvidenceSha


class RootLocalNativeUnitProbeMetadata(_EvidenceValue):
    """Declared unit facts, not independent observations or a successful execution grant."""

    recipe: Literal["NATIVE_CPU_FIXED_UNIT_NO_MODEL_NO_FORWARD_NEGATIVES/1.0"]
    execution_id: str = Field(pattern=r"^[0-9a-f]{32}$", min_length=32, max_length=32)
    invocation_id: str = Field(pattern=r"^[0-9a-f]{32}$", min_length=32, max_length=32)
    pid: int = Field(ge=1, le=2147483647, strict=True)
    start_time_ticks: _Positive64
    worker_uid: int = Field(ge=1, le=4294967294, strict=True)
    worker_gid: int = Field(ge=1, le=4294967294, strict=True)
    supplementary_gids: tuple[int, ...] = Field(max_length=0)
    unit_template_sha256: _EvidenceSha
    probe_code_sha256: _EvidenceSha
    effective_policy_sha256: _EvidenceSha
    probe_report_raw_sha256: _EvidenceSha
    loaded_elf_members_sha256: _EvidenceSha
    observed_runtime_sha256: _EvidenceSha
    model_constructor_calls: _Zero
    tokenizer_constructor_calls: _Zero
    forward_calls: _Zero
    terminal_exec_main_code: _One
    terminal_exec_main_status: _Zero
    terminal_main_pid: _Zero
    terminal_cgroup_member_count: _Zero
    terminated_at_utc: _UtcText

    @field_validator("terminated_at_utc")
    @classmethod
    def valid_utc(cls, value: str) -> str:
        return _utc(value)


class RootLocalNativeAdmissionReceiptMetadata(_EvidenceValue):
    """Parsed SEALED claim only: this model cannot actually seal a candidate or admit work."""

    schema_version: Literal["embedding-native-admission-receipt/1.0"]
    evidence_state: Literal["SEALED_INSTALLATION_EVIDENCE"]
    profile: Literal["CPU_INDEX_FP32"]
    configuration: RootLocalNativeConfigurationPin
    inventory: RootLocalPrefixInventoryPin
    installed_proof: EmbeddingInstalledRuntimeProofPointer
    bundle: EmbeddingRuntimeBundlePointer
    runtime_sha256: _EvidenceSha
    unit_probe: RootLocalNativeUnitProbeMetadata
    sealed_at_utc: _UtcText
    receipt_sha256: _EvidenceSha

    @field_validator("sealed_at_utc")
    @classmethod
    def valid_utc(cls, value: str) -> str:
        return _utc(value)

    @model_validator(mode="after")
    def exact_receipt_metadata(self) -> RootLocalNativeAdmissionReceiptMetadata:
        if (
            self.installed_proof.profile != "CPU_INDEX_FP32"
            or self.unit_probe.observed_runtime_sha256 != self.runtime_sha256
            or TypeAdapter(UtcDatetime).validate_python(self.sealed_at_utc)
            < TypeAdapter(UtcDatetime).validate_python(self.unit_probe.terminated_at_utc)
        ):
            raise ValueError("ROOTLOCAL receipt profile/runtime/time frame differs")
        _hash(self, "receipt_sha256", MAX_ROOTLOCAL_ADMISSION_EVIDENCE_BYTES)
        return self


def rootlocal_prefix_inventory_candidate_bytes(value: RootLocalPrefixInventoryCandidate) -> bytes:
    """Canonical candidate metadata, not audit-origin proof, publication or seal."""
    checked = RootLocalPrefixInventoryCandidate.model_validate(value)
    return canonical_json_bytes(checked.model_dump(mode="json"))


def rootlocal_native_admission_receipt_metadata_bytes(
    value: RootLocalNativeAdmissionReceiptMetadata,
) -> bytes:
    """Serialize an input claim only; never creates independently accepted sealed evidence."""
    checked = RootLocalNativeAdmissionReceiptMetadata.model_validate(value)
    return canonical_json_bytes(checked.model_dump(mode="json"))


def parse_rootlocal_prefix_inventory_candidate(
    raw: bytes, *, schema_raw: bytes
) -> RootLocalPrefixInventoryCandidate:
    """Validate the fixed unregistered draft and exact canonical candidate; grants nothing."""
    try:
        document = _document(raw, MAX_ROOTLOCAL_PREFIX_INVENTORY_BYTES)
        _validate_draft(
            schema_raw, document, PREFIX_INVENTORY_DRAFT_RAW_SHA256, ROOTLOCAL_PREFIX_INVENTORY_REF
        )
        candidate = RootLocalPrefixInventoryCandidate.model_validate(document)
        if raw != canonical_json_bytes(candidate.model_dump(mode="json")):
            raise ValueError("ROOTLOCAL candidate raw bytes are not canonical")
        return candidate
    except (
        ValueError,
        TypeError,
        SchemaError,
        JsonSchemaValidationError,
        RecursionError,
        Unresolvable,
    ):
        raise RootLocalInstallationEvidenceError("ROOTLOCAL_PREFIX_INVENTORY_INVALID") from None


def parse_rootlocal_native_admission_receipt_metadata(
    raw: bytes, *, schema_raw: bytes
) -> RootLocalNativeAdmissionReceiptMetadata:
    """Validate a fixed CPU SEALED metadata claim; not actual unit observation or admission."""
    try:
        document = _document(raw, MAX_ROOTLOCAL_ADMISSION_EVIDENCE_BYTES)
        _validate_draft(
            schema_raw,
            document,
            ADMISSION_EVIDENCE_DRAFT_RAW_SHA256,
            ROOTLOCAL_ADMISSION_EVIDENCE_REF,
        )
        receipt = RootLocalNativeAdmissionReceiptMetadata.model_validate(document)
        if raw != canonical_json_bytes(receipt.model_dump(mode="json")):
            raise ValueError("ROOTLOCAL receipt raw bytes are not canonical")
        return receipt
    except (
        ValueError,
        TypeError,
        SchemaError,
        JsonSchemaValidationError,
        RecursionError,
        Unresolvable,
    ):
        raise RootLocalInstallationEvidenceError("ROOTLOCAL_ADMISSION_EVIDENCE_INVALID") from None


def validate_rootlocal_native_installation_metadata_references(
    receipt: RootLocalNativeAdmissionReceiptMetadata,
    receipt_raw: bytes,
    *,
    expected_receipt_raw_sha256: str,
    inventory: RootLocalPrefixInventoryCandidate,
    inventory_raw: bytes,
    config: InstalledEmbeddingNativeRuntimeConfig,
    config_raw: bytes,
    proof: EmbeddingInstalledRuntimeProof,
    proof_raw: bytes,
    bundle: EmbeddingRuntimeBundle,
    bundle_raw: bytes,
) -> None:
    """Close supplied raw/semantic pins only; expected receipt pin must come from its real owner."""
    try:
        receipt = RootLocalNativeAdmissionReceiptMetadata.model_validate(receipt)
        inventory = RootLocalPrefixInventoryCandidate.model_validate(inventory)
        expected_raw: str = TypeAdapter(_EvidenceSha).validate_python(expected_receipt_raw_sha256)
        if (
            type(receipt_raw) is not bytes
            or receipt_raw != rootlocal_native_admission_receipt_metadata_bytes(receipt)
            or sha256_bytes(receipt_raw) != expected_raw
            or type(inventory_raw) is not bytes
            or inventory_raw != rootlocal_prefix_inventory_candidate_bytes(inventory)
            or sha256_bytes(inventory_raw) != receipt.inventory.inventory_raw_sha256
            or inventory.inventory_sha256 != receipt.inventory.inventory_sha256
            or inventory.profile != receipt.profile
        ):
            raise ValueError("ROOTLOCAL receipt/inventory raw/semantic pin differs")
        resolved_config = parse_installed_embedding_native_runtime_config_bytes(config_raw)
        resolved_proof = parse_installed_runtime_proof(
            _document(proof_raw, MAX_INSTALLED_RUNTIME_PROOF_BYTES)
        )
        resolved_bundle = parse_embedding_runtime_bundle(
            _document(bundle_raw, MAX_RUNTIME_BUNDLE_BYTES)
        )
        config = parse_installed_embedding_native_runtime_config(_raw_metadata(config))
        proof = EmbeddingInstalledRuntimeProof.model_validate(_raw_metadata(proof))
        bundle = EmbeddingRuntimeBundle.model_validate(_raw_metadata(bundle))
        if config != resolved_config or proof != resolved_proof or bundle != resolved_bundle:
            raise ValueError("ROOTLOCAL supplied metadata differs from actual raw references")
        validate_installed_embedding_native_runtime_config_raw(
            config, config_raw, receipt.configuration.configuration_raw_sha256
        )
        validate_installed_embedding_native_runtime_config_references(
            config, bundle, bundle_raw, proof, proof_raw
        )
        validate_installed_runtime_proof_pointer(proof, receipt.installed_proof, proof_raw)
        validate_embedding_runtime_bundle_pointer(bundle, receipt.bundle, bundle_raw)
        if (
            receipt.configuration.configuration_id != config.configuration_id
            or receipt.configuration.configuration_revision_id != config.configuration_revision_id
            or receipt.configuration.configuration_sha256 != config.config_sha256
            or receipt.installed_proof != config.installed_proof
            or receipt.bundle != config.bundle
            or receipt.runtime_sha256 != config.runtime_sha256
            or config.profile != "CPU_INDEX_FP32"
        ):
            raise ValueError("ROOTLOCAL receipt/configuration identity/runtime frame differs")
    except (
        ValueError,
        TypeError,
        SchemaError,
        JsonSchemaValidationError,
        RecursionError,
        Unresolvable,
    ):
        raise RootLocalInstallationEvidenceError(
            "ROOTLOCAL_INSTALLATION_REFERENCE_INVALID"
        ) from None
