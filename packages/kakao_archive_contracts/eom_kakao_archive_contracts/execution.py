"""Small immutable execution identity shared by collection and PDF worker protocols."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkerExecution(FrozenModel):
    command_id: Annotated[str, Field(pattern=r"^kakaocommand_[0-9a-f]{32}$")]
    task_id: Annotated[str, Field(pattern=r"^kakaotask_[0-9a-f]{32}$")]
    attempt_id: Annotated[str, Field(pattern=r"^kakaoattempt_[0-9a-f]{32}$")]
    attempt_number: int = Field(ge=1, le=2147483647, strict=True)
    fence: int = Field(ge=1, le=9007199254740991, strict=True)
