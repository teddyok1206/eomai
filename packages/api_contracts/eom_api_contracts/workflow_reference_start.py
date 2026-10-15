"""A preparation is never represented as an accepted Item Workflow command."""

from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel, CommandResult


class WorkflowReferenceStartReply(ApiModel):
    model_config = ApiModel.model_config | {
        "json_schema_extra": {
            "allOf": [
                {
                    "if": {"properties": {"status": {"const": "PENDING"}}},
                    "then": {
                        "properties": {
                            "reference_query_workflow_id": {"type": "string"},
                            "command": {"type": "null"},
                        }
                    },
                    "else": {
                        "properties": {
                            "reference_query_workflow_id": {"type": "null"},
                            "command": {
                                "type": "object",
                                "properties": {
                                    "resource_type": {"const": "workflow"},
                                    "resource_id": {"pattern": "^workflow_[0-9a-f]{32}$"},
                                    "status": {"const": "ACCEPTED"},
                                    "status_url": {
                                        "pattern": "^/api/v1/workflows/workflow_[0-9a-f]{32}$"
                                    },
                                },
                            },
                        }
                    },
                }
            ]
        }
    }
    schema_version: Literal["workflow-reference-start-reply/1.0"] = (
        "workflow-reference-start-reply/1.0"
    )
    status: Literal["PENDING", "ACCEPTED"]
    reference_query_workflow_id: str | None = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    command: CommandResult | None

    @model_validator(mode="after")
    def preparation_or_accepted_command(self) -> Self:
        if self.status == "PENDING":
            if self.reference_query_workflow_id is None or self.command is not None:
                raise ValueError("pending reference preparation cannot claim an accepted Item")
        elif self.reference_query_workflow_id is not None or self.command is None:
            raise ValueError("accepted reference Item requires its exact command")
        elif (
            self.command.resource_type != "workflow"
            or self.command.status != "ACCEPTED"
            or re.fullmatch(r"workflow_[0-9a-f]{32}", self.command.resource_id) is None
            or self.command.status_url != f"/api/v1/workflows/{self.command.resource_id}"
        ):
            raise ValueError("accepted reference Item command target differs")
        return self
