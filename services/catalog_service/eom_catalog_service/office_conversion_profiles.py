"""Closed converter identities; historical inputs never inherit a new renderer silently."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True, slots=True)
class OfficeConversionProfile:
    key: Literal["legacy-v1", "equations-v2"]
    unit_template: str
    h2orestart_bundle: Path
    h2orestart_sha256: str


LEGACY_OFFICE_PROFILE = OfficeConversionProfile(
    key="legacy-v1",
    unit_template="eom-office-converter@{instance}.service",
    h2orestart_bundle=Path("/srv/eom/vendor/h2orestart/0.7.14-eom.1/H2Orestart.oxt"),
    h2orestart_sha256="2b3ead8f1c782ba47cdc800262e99196850b525347843f0bd9b76e8431a7de96",
)
EQUATION_OFFICE_PROFILE = OfficeConversionProfile(
    key="equations-v2",
    unit_template="eom-office-equation-converter@{instance}.service",
    h2orestart_bundle=Path("/srv/eom/vendor/h2orestart/0.7.14-eom.2/H2Orestart.oxt"),
    h2orestart_sha256="50d8cf433f12270b5ee44fa974993bc36b5804ef550f0ce09b39266305b1b2cb",
)


def require_supported_office_profile(profile: OfficeConversionProfile) -> None:
    if profile not in (LEGACY_OFFICE_PROFILE, EQUATION_OFFICE_PROFILE):
        raise ValueError("OFFICE_DOCUMENT_CONVERTER_PROFILE_UNSUPPORTED")
