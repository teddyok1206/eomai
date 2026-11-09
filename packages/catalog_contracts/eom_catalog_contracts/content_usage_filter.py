"""Read-only academic-year membership; absence means no recorded system use."""

from typing import Literal

from eom_catalog_contracts.content_planning import AcademicYear
from eom_catalog_contracts.models import FrozenModel


class ContentUsageFilter(FrozenModel):
    state: Literal["USED", "UNUSED"]
    academic_year: AcademicYear | None
