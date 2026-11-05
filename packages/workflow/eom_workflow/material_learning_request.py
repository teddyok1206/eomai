"""Isolated material purpose; historical WorkflowRequest bytes/fields are unchanged."""

from __future__ import annotations

from typing import Literal

from eom_catalog_contracts.material_learning import MaterialLearningWork
from eom_catalog_contracts.models import FrozenModel


class MaterialLearningWorkerRequest(FrozenModel):
    request_name: Literal["MATERIAL_LEARNING_REQUEST"] = "MATERIAL_LEARNING_REQUEST"
    work_input: MaterialLearningWork


class MaterialLearningWorkflowRequest(FrozenModel):
    request_name: Literal["MATERIAL_LEARNING_REQUEST"] = "MATERIAL_LEARNING_REQUEST"
    execution_preset_key: Literal["material-learning"] = "material-learning"
    work_input: MaterialLearningWork

    def worker_request(self) -> MaterialLearningWorkerRequest:
        return MaterialLearningWorkerRequest(work_input=self.work_input)
