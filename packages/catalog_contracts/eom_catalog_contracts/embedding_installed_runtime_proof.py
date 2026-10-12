"""Bounded immutable installation proof; JSON validation establishes no installed authority."""

from __future__ import annotations

from types import MappingProxyType
from typing import Annotated, Any, Final, Literal

from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingNumericalDevice
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

INSTALLED_RUNTIME_PROOF_SCHEMA = "embedding-installed-runtime-proof"
INSTALLED_RUNTIME_PROOF_SCHEMA_REF: Final = (
    "eom://schemas/knowledge/embedding-installed-runtime-proof/1.0"
)
MAX_INSTALLED_RUNTIME_PROOF_BYTES = 128 * 1024
type EmbeddingRuntimeProfile = Literal["CPU_INDEX_FP32", "CUDA_INDEX_FP32"]
type ProofId = Annotated[str, Field(pattern=r"^embeddingruntimeproof_[0-9a-f]{32}$")]
type ProofRevisionId = Annotated[str, Field(pattern=r"^embeddingruntimeproofrev_[0-9a-f]{32}$")]
_CPU_PINS = (
    ("numpy", "2.4.6"),
    ("safetensors", "0.6.2"),
    ("tokenizers", "0.22.2"),
    ("torch", "2.7.1+cpu"),
    ("transformers", "4.56.2"),
)
_CUDA_PINS = tuple(
    sorted(
        (
            *((name, "2.7.1+cu128" if name == "torch" else version) for name, version in _CPU_PINS),
            ("nvidia-cublas-cu12", "12.8.3.14"),
            ("nvidia-cuda-cupti-cu12", "12.8.57"),
            ("nvidia-cuda-nvrtc-cu12", "12.8.61"),
            ("nvidia-cuda-runtime-cu12", "12.8.57"),
            ("nvidia-cudnn-cu12", "9.7.1.26"),
            ("nvidia-cufft-cu12", "11.3.3.41"),
            ("nvidia-cufile-cu12", "1.13.0.11"),
            ("nvidia-curand-cu12", "10.3.9.55"),
            ("nvidia-cusolver-cu12", "11.7.2.55"),
            ("nvidia-cusparse-cu12", "12.5.7.53"),
            ("nvidia-cusparselt-cu12", "0.6.3"),
            ("nvidia-nccl-cu12", "2.26.2"),
            ("nvidia-nvjitlink-cu12", "12.8.61"),
            ("nvidia-nvtx-cu12", "12.8.55"),
            ("triton", "3.3.1"),
        )
    )
)
_PROFILE_PINS = MappingProxyType({"CPU_INDEX_FP32": _CPU_PINS, "CUDA_INDEX_FP32": _CUDA_PINS})


def embedding_numeric_library_versions(
    profile: EmbeddingRuntimeProfile,
) -> tuple[tuple[str, str], ...]:
    """Exact reviewed numeric closure, not the complete environment package audit."""
    return _PROFILE_PINS[profile]


class _ProofContract(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")


class InstalledRuntimeMetadataMember(_ProofContract):
    sha256: Sha256
    size_bytes: int = Field(ge=1, le=128 * 1024, strict=True)


class InstalledRuntimeRecordMember(_ProofContract):
    sha256: Sha256
    size_bytes: int = Field(ge=1, le=8 * 1024**2, strict=True)


class NumericWheelArchive(_ProofContract):
    wheel_filename: str = Field(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.+-]+\.whl$", max_length=255)
    sha256: Sha256
    size_bytes: int = Field(ge=1, le=2 * 1024**3, strict=True)


class InstalledConsoleScript(_ProofContract):
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$", max_length=96)
    sha256: Sha256
    size_bytes: int = Field(ge=1, le=16 * 1024, strict=True)


class InstalledNumericLibraryProof(_ProofContract):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    version: str = Field(pattern=r"^[0-9][A-Za-z0-9.+_-]{0,95}$")
    archive: NumericWheelArchive
    installed_record: InstalledRuntimeRecordMember
    requested: bool = Field(strict=True)
    direct_url: InstalledRuntimeMetadataMember | None
    console_scripts: tuple[InstalledConsoleScript, ...] = Field(max_length=16)

    @model_validator(mode="after")
    def sorted_console_names(self) -> InstalledNumericLibraryProof:
        names = tuple(script.name for script in self.console_scripts)
        if names != tuple(sorted(set(names))):
            raise ValueError("installed console script names must be sorted and unique")
        return self


class CpuRuntimeDeviceCapture(_ProofContract):
    source: Literal["LINUX_CPUINFO_VENDOR_FAMILY_MODEL_STEPPING/1.0"]
    numeric_device: EmbeddingNumericalDevice

    @model_validator(mode="after")
    def cpu_kind(self) -> CpuRuntimeDeviceCapture:
        if self.numeric_device.kind != "CPU":
            raise ValueError("CPU capture requires CPU numeric identity")
        return self


class CudaRuntimeDeviceCapture(_ProofContract):
    source: Literal["OWNER_GPU_CAPTURE_LINUX_PROC/1.0"]
    numeric_device: EmbeddingNumericalDevice
    gpu_uuid: str = Field(
        pattern=r"^GPU-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    pci_bus_id: str = Field(pattern=r"^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]$")
    device_minor: int = Field(ge=0, le=0, strict=True)
    boot_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

    @model_validator(mode="after")
    def cuda_kind(self) -> CudaRuntimeDeviceCapture:
        if self.numeric_device.kind != "CUDA":
            raise ValueError("CUDA capture requires CUDA numeric identity")
        return self


type RuntimeDeviceCapture = Annotated[
    CpuRuntimeDeviceCapture | CudaRuntimeDeviceCapture, Field(discriminator="source")
]


class EmbeddingInstalledRuntimeProof(_ProofContract):
    schema_version: Literal["embedding-installed-runtime-proof/1.0"] = (
        "embedding-installed-runtime-proof/1.0"
    )
    proof_id: ProofId
    proof_revision_id: ProofRevisionId
    profile: EmbeddingRuntimeProfile
    python_version: Literal["3.12.13"]
    torch_build_cuda_version: Literal["12.8"] | None
    device_capture: RuntimeDeviceCapture
    numeric_libraries: tuple[InstalledNumericLibraryProof, ...] = Field(min_length=5, max_length=20)
    proof_sha256: Sha256

    @model_validator(mode="after")
    def exact_profile_closure(self) -> EmbeddingInstalledRuntimeProof:
        pairs = tuple((library.name, library.version) for library in self.numeric_libraries)
        if pairs != embedding_numeric_library_versions(self.profile):
            raise ValueError("installed proof numeric library set/order/version differs")
        cuda = self.profile == "CUDA_INDEX_FP32"
        if isinstance(
            self.device_capture, CudaRuntimeDeviceCapture
        ) != cuda or self.torch_build_cuda_version != ("12.8" if cuda else None):
            raise ValueError("installed proof profile/device/build differs")
        if (
            len(canonical_json_bytes(self.model_dump(mode="json")))
            > MAX_INSTALLED_RUNTIME_PROOF_BYTES
        ):
            raise ValueError("installed runtime proof exceeds its byte bound")
        if self.proof_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"proof_sha256"})
        ):
            raise ValueError("installed runtime proof canonical hash differs")
        return self


class EmbeddingInstalledRuntimeProofPointer(_ProofContract):
    schema_version: Literal["embedding-installed-runtime-proof-pointer/1.0"] = (
        "embedding-installed-runtime-proof-pointer/1.0"
    )
    schema_ref: Literal["eom://schemas/knowledge/embedding-installed-runtime-proof/1.0"] = (
        INSTALLED_RUNTIME_PROOF_SCHEMA_REF
    )
    proof_id: ProofId
    proof_revision_id: ProofRevisionId
    profile: EmbeddingRuntimeProfile
    proof_sha256: Sha256
    proof_raw_sha256: Sha256


def installed_runtime_proof_bytes(proof: EmbeddingInstalledRuntimeProof) -> bytes:
    checked = EmbeddingInstalledRuntimeProof.model_validate(proof.model_dump(mode="json"))
    return canonical_json_bytes(checked.model_dump(mode="json"))


def validate_installed_runtime_proof_pointer(
    proof: EmbeddingInstalledRuntimeProof,
    pointer: EmbeddingInstalledRuntimeProofPointer,
    raw: bytes,
) -> None:
    checked = EmbeddingInstalledRuntimeProof.model_validate(proof.model_dump(mode="json"))
    pinned = EmbeddingInstalledRuntimeProofPointer.model_validate(pointer.model_dump(mode="json"))
    if (
        checked.proof_id != pinned.proof_id
        or checked.proof_revision_id != pinned.proof_revision_id
        or checked.profile != pinned.profile
        or checked.proof_sha256 != pinned.proof_sha256
        or raw != installed_runtime_proof_bytes(checked)
        or sha256_bytes(raw) != pinned.proof_raw_sha256
    ):
        raise ValueError("installed runtime proof pointer/raw closure differs")


def parse_installed_runtime_proof(document: dict[str, Any]) -> EmbeddingInstalledRuntimeProof:
    validate_contract(INSTALLED_RUNTIME_PROOF_SCHEMA, document)
    return EmbeddingInstalledRuntimeProof.model_validate(document)
