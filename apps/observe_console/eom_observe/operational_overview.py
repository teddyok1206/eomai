"""Application projection for actionable and historical operational state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from eom_observe_contracts import OperationalOverview


@dataclass(frozen=True)
class OperationalOverviewRows:
    observed_at: datetime
    counts: dict[str, Any]
    attention: list[dict[str, Any]]


class OperationalOverviewRepository(Protocol):
    def operational_overview_rows(
        self, *, recent_failure_window_seconds: int, attention_limit: int
    ) -> OperationalOverviewRows: ...


class OperationalOverviewBuilder:
    """Map one all-or-nothing read-only repository snapshot to the public contract."""

    def __init__(
        self,
        repository: OperationalOverviewRepository,
        *,
        recent_failure_window_seconds: int = 3600,
        attention_limit: int = 100,
    ) -> None:
        self._repository = repository
        self._recent_failure_window_seconds = recent_failure_window_seconds
        self._attention_limit = attention_limit

    def build(self) -> OperationalOverview:
        rows = self._repository.operational_overview_rows(
            recent_failure_window_seconds=self._recent_failure_window_seconds,
            attention_limit=self._attention_limit,
        )
        return OperationalOverview.model_validate(
            {
                "generated_at": rows.observed_at,
                "recent_failure_window_seconds": self._recent_failure_window_seconds,
                "counts": rows.counts,
                "attention": rows.attention,
            }
        )
