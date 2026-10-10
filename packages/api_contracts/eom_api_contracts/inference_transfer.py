"""Public selected-pair values reuse the presentation-neutral canonical contracts.

Submission returns the existing eom_api_contracts.common.CommandResult. Actual
principal/permission capture belongs to API composition, never these public bodies.
"""

from eom_catalog_contracts.inference_transfer_invocation import (
    InferenceTransferPairSubmitRequest,
    InferenceTransferWorkflowReadRequest,
    InferenceTransferWorkflowReadResult,
)
from eom_catalog_contracts.inference_transfer_invocation_v11 import (
    InferenceTransferPairSubmitRequestV11,
    InferenceTransferWorkflowReadRequestV11,
    InferenceTransferWorkflowReadResultV11,
)

__all__ = [
    "InferenceTransferPairSubmitRequest",
    "InferenceTransferPairSubmitRequestV11",
    "InferenceTransferWorkflowReadRequest",
    "InferenceTransferWorkflowReadRequestV11",
    "InferenceTransferWorkflowReadResult",
    "InferenceTransferWorkflowReadResultV11",
]
