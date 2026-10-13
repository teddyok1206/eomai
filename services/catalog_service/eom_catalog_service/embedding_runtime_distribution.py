"""Typed numerical adapter over one authoritative stdlib wheel/member closure."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from eom_catalog_contracts.embedding_installed_runtime_proof import InstalledNumericLibraryProof
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingNumericLibraryPin

from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
)
from eom_catalog_service.embedding_runtime_wheel_closure import (
    RuntimeWheelArchivePin,
    RuntimeWheelConsoleScriptPin,
    RuntimeWheelInstallationPin,
    RuntimeWheelMemberPin,
    observe_runtime_wheel_installation,
    validate_runtime_console_wrapper,
    verify_installed_runtime_wheel,
)


@dataclass(frozen=True, slots=True)
class VerifiedInstalledNumericDistribution:
    pin: EmbeddingNumericLibraryPin
    namespace_roots: frozenset[Path]
    installed_members: frozenset[Path]
    torch_version: tuple[str, str | None] | None


def capture_installed_numeric_distribution(
    archive: RuntimeWheelArchivePin,
    name: str,
    version: str,
    *,
    prefix: Path,
    archive_root: Path,
    files: NumericalRuntimeFileSnapshots,
) -> tuple[InstalledNumericLibraryProof, VerifiedInstalledNumericDistribution]:
    """Read actual metadata and verify it against the pinned archive, without ML imports.

    Both values reuse one file capture. This does not attest whole-prefix admission, current
    interpreter/device, unit isolation or the caller's authority to publish a proof.
    """
    try:
        observed = observe_runtime_wheel_installation(
            archive, name, version, prefix=prefix, files=files
        )
        proof = InstalledNumericLibraryProof.model_validate(asdict(observed))
        verified = verify_installed_numeric_distribution(
            proof, prefix=prefix, archive_root=archive_root, files=files
        )
        files.assert_unchanged()
        return proof, verified
    except InstalledRuntimeProofError:
        raise
    except Exception as exc:
        raise InstalledRuntimeProofError("INSTALLED_RUNTIME_DISTRIBUTION_INVALID") from exc


def validate_numeric_console_wrapper(raw: bytes, prefix: Path, entry: tuple[str, str]) -> None:
    """Preserve the numerical API; the stdlib closure owns the three exact byte recipes."""
    validate_runtime_console_wrapper(raw, prefix, entry)


def verify_installed_numeric_distribution(
    library: InstalledNumericLibraryProof,
    *,
    prefix: Path,
    archive_root: Path,
    files: NumericalRuntimeFileSnapshots,
) -> VerifiedInstalledNumericDistribution:
    """Keep typed numeric output/errors without importing contracts into the owner audit."""
    try:
        pinned = RuntimeWheelInstallationPin(
            name=library.name,
            version=library.version,
            archive=RuntimeWheelArchivePin(
                library.archive.wheel_filename,
                library.archive.sha256,
                library.archive.size_bytes,
            ),
            installed_record=RuntimeWheelMemberPin(
                library.installed_record.sha256, library.installed_record.size_bytes
            ),
            requested=library.requested,
            direct_url=None
            if library.direct_url is None
            else RuntimeWheelMemberPin(library.direct_url.sha256, library.direct_url.size_bytes),
            console_scripts=tuple(
                RuntimeWheelConsoleScriptPin(script.name, script.sha256, script.size_bytes)
                for script in library.console_scripts
            ),
        )
        verified = verify_installed_runtime_wheel(
            pinned, prefix=prefix, archive_root=archive_root, files=files
        )
        return VerifiedInstalledNumericDistribution(
            EmbeddingNumericLibraryPin(
                name=verified.name,
                version=verified.version,
                distribution_sha256=verified.archive_sha256,
            ),
            verified.namespace_roots,
            verified.installed_members,
            verified.torch_version,
        )
    except InstalledRuntimeProofError:
        raise
    except Exception as exc:
        raise InstalledRuntimeProofError("INSTALLED_RUNTIME_DISTRIBUTION_INVALID") from exc
