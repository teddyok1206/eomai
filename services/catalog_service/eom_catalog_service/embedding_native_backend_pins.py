"""Small profile-independent owner configuration value, never admission or device choice."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NativeEmbeddingBackendPins:
    configuration_id: str
    configuration_revision_id: str
    configuration_sha256: str
    configuration_raw_sha256: str
    receipt_raw_sha256: str

    def __post_init__(self) -> None:
        for value, pattern in (
            (self.configuration_id, r"embeddingnativeconfig_[0-9a-f]{32}"),
            (self.configuration_revision_id, r"embeddingnativeconfigrev_[0-9a-f]{32}"),
            (self.configuration_sha256, r"sha256:[0-9a-f]{64}"),
            (self.configuration_raw_sha256, r"sha256:[0-9a-f]{64}"),
            (self.receipt_raw_sha256, r"sha256:[0-9a-f]{64}"),
        ):
            if type(value) is not str or re.fullmatch(pattern, value, re.ASCII) is None:
                raise ValueError("NATIVE_EMBEDDING_OWNER_PINS_INVALID")
