"""JSON Schema 2020-12 registry for definitions and role messages."""

from __future__ import annotations

import copy
import json
import re
from contextlib import suppress
from datetime import datetime
from functools import cache, lru_cache
from importlib import metadata, resources
from importlib.resources.abc import Traversable
from typing import Any, Literal, cast

from eom_catalog_contracts import (
    ContentTeamMaterialRequirement,
    ContentTeamMaterialRequirementV2,
    KnowledgeAnalysisRequestV3,
    KnowledgeAnalysisRequestV4,
    KnowledgeAnalysisRequestV5,
    KnowledgeAnalysisRequestV6,
    KnowledgeAnalysisRequestV7,
    KnowledgeAnalysisRequestV8,
    KnowledgeAnalysisRequestV9,
    KnowledgeAnalysisRequestV10,
    KnowledgeAnalysisRequestV11,
    catalog_schema_registry,
    content_team_material_required_retrieval_elements,
    validate_worker_knowledge_edge_endpoint_types,
)
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.item_inference_transfer import ClaimId
from eom_catalog_contracts.models import FrozenModel
from eom_catalog_contracts.validation import CatalogSchemaError
from eom_hwpx_contracts import (
    ContentTeamLabeledBlock,
    ContentTeamMarkdownError,
    derive_content_team_equation_sources,
    normalize_content_team_answer_line,
    normalize_content_team_bottom_stem,
    normalize_content_team_inline_math,
    normalize_content_team_labeled_block_content,
    normalize_content_team_labeled_block_projection,
    normalize_content_team_statement_marker,
    normalize_content_team_stem,
    serialize_content_team_markdown,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError, model_validator
from referencing import Registry, Resource

from eom_workflow.control_plane import ResolvedExecutionPlanV3
from eom_workflow.document_review import (
    PairedDocumentReviewWorkerRequest,
    PairedDocumentReviewWorkerRequestV2,
    PairedDocumentReviewWorkerRequestV3,
    PdfDocumentReviewWorkerRequest,
    PdfDocumentReviewWorkerRequestV5,
)
from eom_workflow.inference_transfer import (
    InferenceTransferPairWorkerRequest,
    InferenceTransferPairWorkerRequestV11,
)
from eom_workflow.inference_transfer_workflow import (
    InferenceTransferWorkflowRequest,
    InferenceTransferWorkflowRequestV11,
)
from eom_workflow.models import (
    AuthoringRoleResult,
    ContentTeamAuthoringRoleResultV7,
    ContentTeamAuthoringRoleResultV8,
    ContentTeamAuthoringRoleResultV9,
    ContentTeamAuthoringRoleResultV10,
    ContentTeamAuthoringRoleResultV11,
    ContentTeamAuthoringRoleResultV12,
    ContentTeamImageRoleResultV8,
    ContentTeamImageRoleResultV9,
    ContentTeamImageRoleResultV10,
    ContentTeamImageRoleResultV11,
    ContentTeamImageRoleResultV12,
    ContentTeamRegistrationRoleResultV7,
    ContentTeamRegistrationRoleResultV8,
    ContentTeamRegistrationRoleResultV9,
    ContentTeamRegistrationRoleResultV10,
    ContentTeamRegistrationRoleResultV11,
    ContentTeamRegistrationRoleResultV12,
    ContentTeamReviewRoleResultV7,
    ContentTeamReviewRoleResultV8,
    ContentTeamReviewRoleResultV9,
    ContentTeamReviewRoleResultV10,
    ContentTeamReviewRoleResultV11,
    ContentTeamReviewRoleResultV12,
    CustomerSupportRoleResult,
    ExternalItemLearningRoleResult,
    ExternalItemLearningRoleResultV2,
    ExternalItemLearningWorkerRequest,
    GeneratedAuthoringRoleResult,
    GeneratedAuthoringRoleResultV4,
    GeneratedAuthoringRoleResultV5,
    GeneratedAuthoringRoleResultV6,
    GeneratedImageRoleResult,
    GeneratedImageRoleResultV4,
    GeneratedImageRoleResultV5,
    GeneratedImageRoleResultV6,
    GeneratedRegistrationRoleResult,
    GeneratedRegistrationRoleResultV4,
    GeneratedRegistrationRoleResultV5,
    GeneratedRegistrationRoleResultV6,
    GeneratedReviewRoleResult,
    GeneratedReviewRoleResultV4,
    GeneratedReviewRoleResultV5,
    GeneratedReviewRoleResultV6,
    ImageRoleResult,
    InferenceTransferPairRoleResult,
    InferenceTransferPairRoleResultV11,
    KnowledgeAnalysisProposalRoleResult,
    KnowledgeAnalysisProposalRoleResultV2,
    KnowledgeAnalysisProposalRoleResultV3,
    KnowledgeAnalysisProposalRoleResultV4,
    KnowledgeAnalysisProposalRoleResultV5,
    KnowledgeAnalysisProposalRoleResultV6,
    KnowledgeAnalysisProposalRoleResultV7,
    KnowledgeAnalysisProposalRoleResultV8,
    KnowledgeAnalysisProposalRoleResultV9,
    KnowledgeAnalysisProposalRoleResultV10,
    KnowledgeAnalysisProposalRoleResultV11,
    KnowledgeAnalysisWorkerRequest,
    KnowledgeAuthoringRoleResult,
    KnowledgeImageRoleResult,
    KnowledgeRegistrationRoleResult,
    KnowledgeReviewRoleResult,
    LegacyItemEditorialCompatibilityRoleResult,
    LegacyItemEditorialCompatibilityWorkerRequest,
    LegacyItemExtractionRoleResult,
    LegacyItemExtractionWorkerRequest,
    PairedDocumentReviewRoleResult,
    PairedDocumentReviewRoleResultV3,
    PairedDocumentReviewRoleResultV4,
    PdfDocumentReviewRoleResult,
    PdfDocumentReviewRoleResultV4,
    PdfDocumentReviewRoleResultV5,
    RegistrationRoleResult,
    ReviewRoleResult,
    RoleResult,
    RoleWorkerInput,
)

WORKFLOW_RESOURCE_ROOT = resources.files("eom_workflow").joinpath("resources")
ROLE_RESOURCE_ROOT = WORKFLOW_RESOURCE_ROOT.joinpath("roles")
_CANONICAL_SAFE_ARTIFACT_MEMBER_PATTERN = (
    r"^(?!/)(?!.*(?:^|/)\.{1,2}(?:/|$))(?!.*\\)[^/]+(?:/[^/]+)*$"
)
_CODEX_SAFE_ARTIFACT_MEMBER_PATTERN = (
    r"^([^./\\][^/\\]*|\.[^./\\][^/\\]*|\.\.[^/\\][^/\\]*)"
    r"(/([^./\\][^/\\]*|\.[^./\\][^/\\]*|\.\.[^/\\][^/\\]*))*$"
)
_CANONICAL_SAFE_TEXT_PATTERN = r"^[^\u0000-\u0008\u000B\u000C\u000E-\u001F]*$"
_CODEX_NONEMPTY_SAFE_TEXT_PATTERN = r"^[^\u0000-\u0008\u000B\u000C\u000E-\u001F]+$"
ROLE_RESULT_SCHEMAS: dict[str, str] = {
    "authoring": "authoring-result@1.0",
    "image": "image-result@1.0",
    "review": "review-result@1.0",
    "item_management": "registration-result@1.0",
}
ROLE_ALLOWED_RESULT_SCHEMAS: dict[str, frozenset[str]] = {
    "authoring": frozenset(
        {
            "authoring-result@1.0",
            "authoring-result@2.0",
            "authoring-result@3.0",
            "authoring-result@4.0",
            "authoring-result@5.0",
            "authoring-result@6.0",
            "authoring-result@7.0",
            "authoring-result@8.0",
            "authoring-result@9.0",
            "authoring-result@10.0",
            "authoring-result@11.0",
            "authoring-result@12.0",
        }
    ),
    "image": frozenset(
        {
            "image-result@1.0",
            "image-result@2.0",
            "image-result@3.0",
            "image-result@4.0",
            "image-result@5.0",
            "image-result@6.0",
            "image-result@8.0",
            "image-result@9.0",
            "image-result@10.0",
            "image-result@11.0",
            "image-result@12.0",
        }
    ),
    "review": frozenset(
        {
            "review-result@1.0",
            "review-result@2.0",
            "review-result@3.0",
            "review-result@4.0",
            "review-result@5.0",
            "review-result@6.0",
            "review-result@7.0",
            "review-result@8.0",
            "review-result@9.0",
            "review-result@10.0",
            "review-result@11.0",
            "review-result@12.0",
        }
    ),
    "item_management": frozenset(
        {
            "registration-result@1.0",
            "registration-result@2.0",
            "registration-result@3.0",
            "registration-result@4.0",
            "registration-result@5.0",
            "registration-result@6.0",
            "registration-result@7.0",
            "registration-result@8.0",
            "registration-result@9.0",
            "registration-result@10.0",
            "registration-result@11.0",
            "registration-result@12.0",
        }
    ),
    "support": frozenset(
        {
            "knowledge-analysis-proposal-result@1.0",
            "knowledge-analysis-proposal-result@2.0",
            "knowledge-analysis-proposal-result@3.0",
            "knowledge-analysis-proposal-result@4.0",
            "knowledge-analysis-proposal-result@5.0",
            "knowledge-analysis-proposal-result@6.0",
            "knowledge-analysis-proposal-result@7.0",
            "knowledge-analysis-proposal-result@8.0",
            "knowledge-analysis-proposal-result@9.0",
            "knowledge-analysis-proposal-result@10.0",
            "knowledge-analysis-proposal-result@11.0",
            "legacy-item-extraction-result@1.0",
            "external-item-learning-result@1.0",
            "external-item-learning-result@2.0",
            "legacy-item-editorial-compatibility-result@1.0",
            "customer-support-result@1.0",
            "pdf-document-review-result@1.0",
            "pdf-document-review-result@2.0",
            "pdf-document-review-result@3.0",
            "pdf-document-review-result@4.0",
            "pdf-document-review-result@5.0",
            "pdf-document-review-result@6.0",
            "item-inference-transfer-pair-result@1.0",
            "item-inference-transfer-pair-result@1.1",
        }
    ),
}
RESULT_SCHEMA_FILES = {
    "authoring-result@1.0": "authoring-result.schema.json",
    "image-result@1.0": "image-result.schema.json",
    "review-result@1.0": "review-result.schema.json",
    "registration-result@1.0": "registration-result.schema.json",
    "authoring-result@2.0": "authoring-result-v2.schema.json",
    "image-result@2.0": "image-result-v2.schema.json",
    "review-result@2.0": "review-result-v2.schema.json",
    "registration-result@2.0": "registration-result-v2.schema.json",
    "authoring-result@3.0": "authoring-result-v3.schema.json",
    "image-result@3.0": "image-result-v3.schema.json",
    "review-result@3.0": "review-result-v3.schema.json",
    "registration-result@3.0": "registration-result-v3.schema.json",
    "authoring-result@4.0": "authoring-result-v4.schema.json",
    "image-result@4.0": "image-result-v4.schema.json",
    "review-result@4.0": "review-result-v4.schema.json",
    "registration-result@4.0": "registration-result-v4.schema.json",
    "authoring-result@5.0": "authoring-result-v5.schema.json",
    "image-result@5.0": "image-result-v5.schema.json",
    "review-result@5.0": "review-result-v5.schema.json",
    "registration-result@5.0": "registration-result-v5.schema.json",
    "authoring-result@6.0": "authoring-result-v6.schema.json",
    "image-result@6.0": "image-result-v6.schema.json",
    "review-result@6.0": "review-result-v6.schema.json",
    "registration-result@6.0": "registration-result-v6.schema.json",
    "authoring-result@7.0": "authoring-result-v7.schema.json",
    "review-result@7.0": "review-result-v7.schema.json",
    "registration-result@7.0": "registration-result-v7.schema.json",
    "authoring-result@8.0": "authoring-result-v8.schema.json",
    "image-result@8.0": "image-result-v8.schema.json",
    "review-result@8.0": "review-result-v8.schema.json",
    "registration-result@8.0": "registration-result-v8.schema.json",
    "authoring-result@9.0": "authoring-result-v9.schema.json",
    "image-result@9.0": "image-result-v9.schema.json",
    "review-result@9.0": "review-result-v9.schema.json",
    "registration-result@9.0": "registration-result-v9.schema.json",
    "authoring-result@10.0": "authoring-result-v10.schema.json",
    "image-result@10.0": "image-result-v10.schema.json",
    "review-result@10.0": "review-result-v10.schema.json",
    "registration-result@10.0": "registration-result-v10.schema.json",
    "authoring-result@11.0": "authoring-result-v11.schema.json",
    "image-result@11.0": "image-result-v11.schema.json",
    "review-result@11.0": "review-result-v11.schema.json",
    "registration-result@11.0": "registration-result-v11.schema.json",
    "authoring-result@12.0": "authoring-result-v12.schema.json",
    "image-result@12.0": "image-result-v12.schema.json",
    "review-result@12.0": "review-result-v12.schema.json",
    "registration-result@12.0": "registration-result-v12.schema.json",
    "knowledge-analysis-proposal-result@1.0": ("knowledge-analysis-proposal-result-v1.schema.json"),
    "knowledge-analysis-proposal-result@2.0": ("knowledge-analysis-proposal-result-v2.schema.json"),
    "knowledge-analysis-proposal-result@3.0": ("knowledge-analysis-proposal-result-v3.schema.json"),
    "knowledge-analysis-proposal-result@4.0": ("knowledge-analysis-proposal-result-v4.schema.json"),
    "knowledge-analysis-proposal-result@5.0": ("knowledge-analysis-proposal-result-v5.schema.json"),
    "knowledge-analysis-proposal-result@6.0": ("knowledge-analysis-proposal-result-v6.schema.json"),
    "knowledge-analysis-proposal-result@7.0": ("knowledge-analysis-proposal-result-v7.schema.json"),
    "knowledge-analysis-proposal-result@8.0": ("knowledge-analysis-proposal-result-v8.schema.json"),
    "knowledge-analysis-proposal-result@9.0": ("knowledge-analysis-proposal-result-v9.schema.json"),
    "knowledge-analysis-proposal-result@10.0": (
        "knowledge-analysis-proposal-result-v10.schema.json"
    ),
    "knowledge-analysis-proposal-result@11.0": (
        "knowledge-analysis-proposal-result-v11.schema.json"
    ),
    "legacy-item-extraction-result@1.0": "legacy-item-extraction-result-v1.schema.json",
    "external-item-learning-result@1.0": "external-item-learning-result-v1.schema.json",
    "external-item-learning-result@2.0": "external-item-learning-result-v2.schema.json",
    "legacy-item-editorial-compatibility-result@1.0": (
        "legacy-item-editorial-compatibility-result-v1.schema.json"
    ),
    "customer-support-result@1.0": "customer-support-result-v1.schema.json",
    "pdf-document-review-result@1.0": "pdf-document-review-result-v1.schema.json",
    "pdf-document-review-result@2.0": "paired-document-review-result-v2.schema.json",
    "pdf-document-review-result@3.0": "paired-document-review-result-v3.schema.json",
    "pdf-document-review-result@4.0": "pdf-document-review-result-v4.schema.json",
    "pdf-document-review-result@5.0": "pdf-document-review-result-v5.schema.json",
    "pdf-document-review-result@6.0": "paired-document-review-result-v4.schema.json",
    "item-inference-transfer-pair-result@1.0": "item-inference-transfer-pair-result-v1.schema.json",
    "item-inference-transfer-pair-result@1.1": "item-inference-transfer-pair-result-v2.schema.json",
}
INPUT_SCHEMA_FILES = {
    "authoring": "authoring-input.schema.json",
    "image": "image-input.schema.json",
    "review": "review-input.schema.json",
    "item_management": "registration-input.schema.json",
}
INPUT_SCHEMA_FILES_V1_1 = INPUT_SCHEMA_FILES
INPUT_SCHEMA_FILES_V1_4 = {"support": "knowledge-analysis-input-v1.schema.json"}
INPUT_SCHEMA_FILES_V1_5 = {"support": "knowledge-analysis-input-v2.schema.json"}
INPUT_SCHEMA_FILES_V1_6 = {"support": "knowledge-analysis-input-v3.schema.json"}
INPUT_SCHEMA_FILES_V1_7 = {"support": "knowledge-analysis-input-v4.schema.json"}
INPUT_SCHEMA_FILES_V1_8 = {"support": "knowledge-analysis-input-v5.schema.json"}
INPUT_SCHEMA_FILES_V1_9 = {"support": "knowledge-analysis-input-v6.schema.json"}
INPUT_SCHEMA_FILES_V1_10 = {"support": "knowledge-analysis-input-v7.schema.json"}
INPUT_SCHEMA_FILES_V1_11 = {"support": "knowledge-analysis-input-v8.schema.json"}
INPUT_SCHEMA_FILES_V1_14 = {"support": "legacy-item-extraction-input-v1.schema.json"}
INPUT_SCHEMA_FILES_V1_15 = {
    "authoring": "authoring-input.schema.json",
    "review": "review-input.schema.json",
    "item_management": "registration-input.schema.json",
}
INPUT_SCHEMA_FILES_V1_16 = {"support": "legacy-item-editorial-compatibility-input-v1.schema.json"}
INPUT_SCHEMA_FILES_V1_17 = INPUT_SCHEMA_FILES_V1_15 | {"image": "image-input.schema.json"}
INPUT_SCHEMA_FILES_V1_18 = {"support": "knowledge-analysis-input-v9.schema.json"}
INPUT_SCHEMA_FILES_V1_19 = INPUT_SCHEMA_FILES_V1_17
INPUT_SCHEMA_FILES_V1_20 = INPUT_SCHEMA_FILES_V1_17
INPUT_SCHEMA_FILES_V1_21 = {"support": "knowledge-analysis-input-v10.schema.json"}
INPUT_SCHEMA_FILES_V1_22 = {"support": "customer-support-input-v1.schema.json"}
INPUT_SCHEMA_FILES_V1_23 = INPUT_SCHEMA_FILES_V1_17
INPUT_SCHEMA_FILES_V1_24 = INPUT_SCHEMA_FILES_V1_17
INPUT_SCHEMA_FILES_V1_25 = {"support": "pdf-document-review-input-v1.schema.json"}
INPUT_SCHEMA_FILES_V1_26 = {"support": "paired-document-review-input-v2.schema.json"}
INPUT_SCHEMA_FILES_V1_27 = {"support": "paired-document-review-input-v3.schema.json"}
INPUT_SCHEMA_FILES_V1_28 = {"support": "pdf-document-review-input-v4.schema.json"}
INPUT_SCHEMA_FILES_V1_29 = {"support": "item-inference-transfer-pair-input-v1.schema.json"}
INPUT_SCHEMA_FILES_V1_30 = {"support": "item-inference-transfer-pair-input-v2.schema.json"}
INPUT_SCHEMA_FILES_V1_31 = {"support": "pdf-document-review-input-v5.schema.json"}
INPUT_SCHEMA_FILES_V1_32 = {"support": "paired-document-review-input-v4.schema.json"}
INPUT_SCHEMA_FILES_V1_33 = {"support": "external-item-learning-input-v1.schema.json"}
INPUT_SCHEMA_FILES_V1_34 = {"support": "external-item-learning-input-v2.schema.json"}
INPUT_SCHEMA_FILES_V1_35 = {"support": "knowledge-analysis-input-v11.schema.json"}
RESULT_SCHEMA_PROTOCOLS = {
    **{schema_id: "workflow-role/1.0.1" for schema_id in ROLE_RESULT_SCHEMAS.values()},
    **{
        schema_id: "workflow-role/1.1.0"
        for schema_id in RESULT_SCHEMA_FILES
        if schema_id.endswith("@2.0")
    },
    **{
        schema_id: "workflow-role/1.2.0"
        for schema_id in RESULT_SCHEMA_FILES
        if schema_id.endswith("@3.0")
    },
    **{
        schema_id: "workflow-role/1.3.0"
        for schema_id in RESULT_SCHEMA_FILES
        if schema_id.endswith("@4.0")
    },
    "knowledge-analysis-proposal-result@1.0": "workflow-role/1.4.0",
    "knowledge-analysis-proposal-result@2.0": "workflow-role/1.5.0",
    "knowledge-analysis-proposal-result@3.0": "workflow-role/1.6.0",
    "knowledge-analysis-proposal-result@4.0": "workflow-role/1.7.0",
    "knowledge-analysis-proposal-result@5.0": "workflow-role/1.8.0",
    "knowledge-analysis-proposal-result@6.0": "workflow-role/1.9.0",
    "knowledge-analysis-proposal-result@7.0": "workflow-role/1.10.0",
    "knowledge-analysis-proposal-result@8.0": "workflow-role/1.11.0",
    "knowledge-analysis-proposal-result@9.0": "workflow-role/1.18.0",
    "knowledge-analysis-proposal-result@10.0": "workflow-role/1.21.0",
    "knowledge-analysis-proposal-result@11.0": "workflow-role/1.35.0",
    "customer-support-result@1.0": "workflow-role/1.22.0",
    "pdf-document-review-result@1.0": "workflow-role/1.25.0",
    "pdf-document-review-result@2.0": "workflow-role/1.26.0",
    "pdf-document-review-result@3.0": "workflow-role/1.27.0",
    "pdf-document-review-result@4.0": "workflow-role/1.28.0",
    "pdf-document-review-result@5.0": "workflow-role/1.31.0",
    "pdf-document-review-result@6.0": "workflow-role/1.32.0",
    "item-inference-transfer-pair-result@1.0": "workflow-role/1.29.0",
    "item-inference-transfer-pair-result@1.1": "workflow-role/1.30.0",
    "authoring-result@5.0": "workflow-role/1.12.0",
    "image-result@5.0": "workflow-role/1.12.0",
    "review-result@5.0": "workflow-role/1.12.0",
    "registration-result@5.0": "workflow-role/1.12.0",
    "authoring-result@6.0": "workflow-role/1.13.0",
    "image-result@6.0": "workflow-role/1.13.0",
    "review-result@6.0": "workflow-role/1.13.0",
    "registration-result@6.0": "workflow-role/1.13.0",
    "legacy-item-extraction-result@1.0": "workflow-role/1.14.0",
    "external-item-learning-result@1.0": "workflow-role/1.33.0",
    "external-item-learning-result@2.0": "workflow-role/1.34.0",
    "authoring-result@7.0": "workflow-role/1.15.0",
    "review-result@7.0": "workflow-role/1.15.0",
    "registration-result@7.0": "workflow-role/1.15.0",
    "legacy-item-editorial-compatibility-result@1.0": "workflow-role/1.16.0",
    "authoring-result@8.0": "workflow-role/1.17.0",
    "image-result@8.0": "workflow-role/1.17.0",
    "review-result@8.0": "workflow-role/1.17.0",
    "registration-result@8.0": "workflow-role/1.17.0",
    "authoring-result@9.0": "workflow-role/1.19.0",
    "image-result@9.0": "workflow-role/1.19.0",
    "review-result@9.0": "workflow-role/1.19.0",
    "registration-result@9.0": "workflow-role/1.19.0",
    "authoring-result@10.0": "workflow-role/1.20.0",
    "image-result@10.0": "workflow-role/1.20.0",
    "review-result@10.0": "workflow-role/1.20.0",
    "registration-result@10.0": "workflow-role/1.20.0",
    "authoring-result@11.0": "workflow-role/1.23.0",
    "image-result@11.0": "workflow-role/1.23.0",
    "review-result@11.0": "workflow-role/1.23.0",
    "registration-result@11.0": "workflow-role/1.23.0",
    "authoring-result@12.0": "workflow-role/1.24.0",
    "image-result@12.0": "workflow-role/1.24.0",
    "review-result@12.0": "workflow-role/1.24.0",
    "registration-result@12.0": "workflow-role/1.24.0",
}
PROTOCOL_INPUT_SCHEMAS = {
    "workflow-role/1.0.1": INPUT_SCHEMA_FILES,
    "workflow-role/1.1.0": INPUT_SCHEMA_FILES_V1_1,
    "workflow-role/1.2.0": INPUT_SCHEMA_FILES_V1_1,
    "workflow-role/1.3.0": INPUT_SCHEMA_FILES_V1_1,
    "workflow-role/1.4.0": INPUT_SCHEMA_FILES_V1_4,
    "workflow-role/1.5.0": INPUT_SCHEMA_FILES_V1_5,
    "workflow-role/1.6.0": INPUT_SCHEMA_FILES_V1_6,
    "workflow-role/1.7.0": INPUT_SCHEMA_FILES_V1_7,
    "workflow-role/1.8.0": INPUT_SCHEMA_FILES_V1_8,
    "workflow-role/1.9.0": INPUT_SCHEMA_FILES_V1_9,
    "workflow-role/1.10.0": INPUT_SCHEMA_FILES_V1_10,
    "workflow-role/1.11.0": INPUT_SCHEMA_FILES_V1_11,
    "workflow-role/1.12.0": INPUT_SCHEMA_FILES_V1_1,
    "workflow-role/1.13.0": INPUT_SCHEMA_FILES_V1_1,
    "workflow-role/1.14.0": INPUT_SCHEMA_FILES_V1_14,
    "workflow-role/1.15.0": INPUT_SCHEMA_FILES_V1_15,
    "workflow-role/1.16.0": INPUT_SCHEMA_FILES_V1_16,
    "workflow-role/1.17.0": INPUT_SCHEMA_FILES_V1_17,
    "workflow-role/1.18.0": INPUT_SCHEMA_FILES_V1_18,
    "workflow-role/1.19.0": INPUT_SCHEMA_FILES_V1_19,
    "workflow-role/1.20.0": INPUT_SCHEMA_FILES_V1_20,
    "workflow-role/1.21.0": INPUT_SCHEMA_FILES_V1_21,
    "workflow-role/1.22.0": INPUT_SCHEMA_FILES_V1_22,
    "workflow-role/1.23.0": INPUT_SCHEMA_FILES_V1_23,
    "workflow-role/1.24.0": INPUT_SCHEMA_FILES_V1_24,
    "workflow-role/1.25.0": INPUT_SCHEMA_FILES_V1_25,
    "workflow-role/1.26.0": INPUT_SCHEMA_FILES_V1_26,
    "workflow-role/1.27.0": INPUT_SCHEMA_FILES_V1_27,
    "workflow-role/1.28.0": INPUT_SCHEMA_FILES_V1_28,
    "workflow-role/1.29.0": INPUT_SCHEMA_FILES_V1_29,
    "workflow-role/1.30.0": INPUT_SCHEMA_FILES_V1_30,
    "workflow-role/1.31.0": INPUT_SCHEMA_FILES_V1_31,
    "workflow-role/1.32.0": INPUT_SCHEMA_FILES_V1_32,
    "workflow-role/1.33.0": INPUT_SCHEMA_FILES_V1_33,
    "workflow-role/1.34.0": INPUT_SCHEMA_FILES_V1_34,
    "workflow-role/1.35.0": INPUT_SCHEMA_FILES_V1_35,
}
WorkflowProtocolVersion = Literal[
    "workflow-role/1.0.1",
    "workflow-role/1.1.0",
    "workflow-role/1.2.0",
    "workflow-role/1.3.0",
    "workflow-role/1.4.0",
    "workflow-role/1.5.0",
    "workflow-role/1.6.0",
    "workflow-role/1.7.0",
    "workflow-role/1.8.0",
    "workflow-role/1.9.0",
    "workflow-role/1.10.0",
    "workflow-role/1.11.0",
    "workflow-role/1.12.0",
    "workflow-role/1.13.0",
    "workflow-role/1.14.0",
    "workflow-role/1.15.0",
    "workflow-role/1.16.0",
    "workflow-role/1.17.0",
    "workflow-role/1.18.0",
    "workflow-role/1.19.0",
    "workflow-role/1.20.0",
    "workflow-role/1.21.0",
    "workflow-role/1.22.0",
    "workflow-role/1.23.0",
    "workflow-role/1.24.0",
    "workflow-role/1.25.0",
    "workflow-role/1.26.0",
    "workflow-role/1.27.0",
    "workflow-role/1.28.0",
    "workflow-role/1.29.0",
    "workflow-role/1.30.0",
    "workflow-role/1.31.0",
    "workflow-role/1.32.0",
    "workflow-role/1.33.0",
    "workflow-role/1.34.0",
    "workflow-role/1.35.0",
]
ROLE_SCHEMA_FILES = tuple(
    sorted(
        {
            *RESULT_SCHEMA_FILES.values(),
            *INPUT_SCHEMA_FILES.values(),
            *INPUT_SCHEMA_FILES_V1_1.values(),
            *INPUT_SCHEMA_FILES_V1_4.values(),
            *INPUT_SCHEMA_FILES_V1_5.values(),
            *INPUT_SCHEMA_FILES_V1_6.values(),
            *INPUT_SCHEMA_FILES_V1_7.values(),
            *INPUT_SCHEMA_FILES_V1_8.values(),
            *INPUT_SCHEMA_FILES_V1_9.values(),
            *INPUT_SCHEMA_FILES_V1_10.values(),
            *INPUT_SCHEMA_FILES_V1_11.values(),
            *INPUT_SCHEMA_FILES_V1_14.values(),
            *INPUT_SCHEMA_FILES_V1_15.values(),
            *INPUT_SCHEMA_FILES_V1_16.values(),
            *INPUT_SCHEMA_FILES_V1_18.values(),
            *INPUT_SCHEMA_FILES_V1_19.values(),
            *INPUT_SCHEMA_FILES_V1_20.values(),
            *INPUT_SCHEMA_FILES_V1_21.values(),
            *INPUT_SCHEMA_FILES_V1_22.values(),
            *INPUT_SCHEMA_FILES_V1_23.values(),
            *INPUT_SCHEMA_FILES_V1_24.values(),
            *INPUT_SCHEMA_FILES_V1_25.values(),
            *INPUT_SCHEMA_FILES_V1_26.values(),
            *INPUT_SCHEMA_FILES_V1_27.values(),
            *INPUT_SCHEMA_FILES_V1_28.values(),
            *INPUT_SCHEMA_FILES_V1_29.values(),
            *INPUT_SCHEMA_FILES_V1_30.values(),
            *INPUT_SCHEMA_FILES_V1_31.values(),
            *INPUT_SCHEMA_FILES_V1_32.values(),
            *INPUT_SCHEMA_FILES_V1_33.values(),
        }
    )
)


class WorkflowSchemaError(ValueError):
    pass


REFERENCE_QUERY_EXECUTION_SCHEMA_RESOURCE = (
    "reference-query-execution-v1.schema.json",
    "eom://schemas/workflow/reference-query-execution/1.0",
    "sha256:68e741506fec708956096aa5af6199e7c03821219385775cf9623aea88246c9b",
)
REFERENCE_QUERY_PUBLIC_EXECUTION_SCHEMA_RESOURCE = (
    "reference-query-execution-v2.schema.json",
    "eom://schemas/workflow/reference-query-execution/2.0",
    "sha256:504959a2de7aae1cf4636a277e7144ff0f80526ee11fd4157c98c2776ef09892",
)
REFERENCE_QUERY_REQUEST_V11_SCHEMA_RESOURCE = (
    "reference-query-workflow-request-v1_1.schema.json",
    "eom://schemas/workflow/reference-query-workflow-request/1.1",
    "sha256:4b52a34d7970189de9d6447a5ebdd2b073b1999059f5e2a9c9263b0f9e890ae3",
)
REFERENCE_QUERY_REQUEST_V2_SCHEMA_RESOURCE = (
    "reference-query-workflow-request-v2.schema.json",
    "eom://schemas/workflow/reference-query-workflow-request/2.0",
    "sha256:2239f158e9aebd5495e57b12751cf63b1302259a19ce229e35c7de0a579ac20a",
)
type ReferenceQueryMessageName = Literal[
    "definition", "request", "policy", "launch", "receipt", "step-output"
]
_REFERENCE_QUERY_MESSAGES = frozenset(
    {"definition", "request", "policy", "launch", "receipt", "step-output"}
)


class ReferenceQueryContractError(ValueError):
    """Stable content-free contract failure; no permission or runtime claim."""


def _load_pinned_reference_query_schema(resource: tuple[str, str, str]) -> dict[str, Any]:
    filename, schema_id, expected = resource
    try:
        with WORKFLOW_RESOURCE_ROOT.joinpath(filename).open("rb") as stream:
            payload = stream.read(64 * 1024 + 1)
        if not 0 < len(payload) <= 64 * 1024 or sha256_bytes(payload) != expected:
            raise ValueError("QUERY resource differs")
        raw = json.loads(payload)
        if not isinstance(raw, dict) or raw.get("$id") != schema_id:
            raise ValueError("QUERY schema differs")
        Draft202012Validator.check_schema(raw)
        return raw
    except Exception:
        raise ReferenceQueryContractError("REFERENCE_QUERY_SCHEMA_UNAVAILABLE") from None


@cache
def _reference_query_execution_schema() -> dict[str, Any]:
    return _load_pinned_reference_query_schema(REFERENCE_QUERY_EXECUTION_SCHEMA_RESOURCE)


@cache
def _reference_query_request_v11_schema() -> dict[str, Any]:
    return _load_pinned_reference_query_schema(REFERENCE_QUERY_REQUEST_V11_SCHEMA_RESOURCE)


@cache
def _reference_query_request_v2_schema() -> dict[str, Any]:
    return _load_pinned_reference_query_schema(REFERENCE_QUERY_REQUEST_V2_SCHEMA_RESOURCE)


def load_reference_query_request_v11_schema() -> dict[str, Any]:
    return copy.deepcopy(_reference_query_request_v11_schema())


def load_reference_query_request_v2_schema() -> dict[str, Any]:
    return copy.deepcopy(_reference_query_request_v2_schema())


def load_reference_query_execution_schema() -> dict[str, Any]:
    return copy.deepcopy(_reference_query_execution_schema())


@cache
def _reference_query_public_execution_schema() -> dict[str, Any]:
    return _load_pinned_reference_query_schema(REFERENCE_QUERY_PUBLIC_EXECUTION_SCHEMA_RESOURCE)


def load_reference_query_public_execution_schema() -> dict[str, Any]:
    return copy.deepcopy(_reference_query_public_execution_schema())


@cache
def _reference_query_execution_registry() -> Registry[Any]:
    try:
        return local_embedding_admission_schema_registry().with_resources(
            (
                (
                    REFERENCE_QUERY_EXECUTION_SCHEMA_RESOURCE[1],
                    Resource.from_contents(_reference_query_execution_schema()),
                ),
            )
        )
    except (LocalEmbeddingAdmissionContractError, CatalogSchemaError):
        raise ReferenceQueryContractError("REFERENCE_QUERY_SCHEMA_UNAVAILABLE") from None


def reference_query_execution_schema_registry() -> Registry[Any]:
    """Fresh public values cannot mutate the parser's pinned resource."""
    try:
        return local_embedding_admission_schema_registry().with_resources(
            (
                (
                    REFERENCE_QUERY_EXECUTION_SCHEMA_RESOURCE[1],
                    Resource.from_contents(load_reference_query_execution_schema()),
                ),
            )
        )
    except (LocalEmbeddingAdmissionContractError, CatalogSchemaError):
        raise ReferenceQueryContractError("REFERENCE_QUERY_SCHEMA_UNAVAILABLE") from None


def validate_reference_query_message(name: ReferenceQueryMessageName, value: object) -> None:
    """Only six fixed QUERY frames; no operation dispatch or installation admission."""
    try:
        if name not in _REFERENCE_QUERY_MESSAGES:
            raise ValueError("QUERY message differs")
        document = raw_similarity_contract_value(value)
        maximum = 8 * 1024 if name == "step-output" else 64 * 1024
        if len(canonical_json_bytes(document)) > maximum:
            raise ValueError("QUERY message exceeds its bound")
        _reference_query_execution_schema()
        Draft202012Validator(
            {"$ref": REFERENCE_QUERY_EXECUTION_SCHEMA_RESOURCE[1] + "#/$defs/" + name},
            registry=_reference_query_execution_registry(),
            format_checker=FormatChecker(),
        ).validate(document)
    except ReferenceQueryContractError:
        raise
    except Exception:
        raise ReferenceQueryContractError("REFERENCE_QUERY_CONTRACT_INVALID") from None


@cache
def _reference_query_public_execution_registry() -> Registry[Any]:
    registry: Registry[Any] = _reference_query_execution_registry().with_resource(
        REFERENCE_QUERY_PUBLIC_EXECUTION_SCHEMA_RESOURCE[1],
        Resource.from_contents(_reference_query_public_execution_schema()),
    )
    return registry


def validate_reference_query_public_message(
    name: Literal["definition", "request", "receipt", "step-output"], value: object
) -> None:
    """Explicit public QUERY2 successor; no old frame is relabelled or broadened."""
    try:
        if name not in {"definition", "request", "receipt", "step-output"}:
            raise ValueError("public QUERY message differs")
        document = raw_similarity_contract_value(value)
        maximum = 8 * 1024 if name == "step-output" else 64 * 1024
        if len(canonical_json_bytes(document)) > maximum:
            raise ValueError("public QUERY message exceeds its bound")
        Draft202012Validator(
            {"$ref": REFERENCE_QUERY_PUBLIC_EXECUTION_SCHEMA_RESOURCE[1] + "#/$defs/" + name},
            registry=_reference_query_public_execution_registry(),
            format_checker=FormatChecker(),
        ).validate(document)
    except ReferenceQueryContractError:
        raise
    except Exception:
        raise ReferenceQueryContractError("REFERENCE_QUERY_CONTRACT_INVALID") from None


@cache
def _reference_query_request_v11_registry() -> Registry[Any]:
    registry: Registry[Any] = _reference_query_execution_registry().with_resource(
        REFERENCE_QUERY_REQUEST_V11_SCHEMA_RESOURCE[1],
        Resource.from_contents(_reference_query_request_v11_schema()),
    )
    return registry


def validate_reference_query_request_v11(value: object) -> None:
    """Literal input1.1 only; existing request1.0 and other frames stay unchanged."""
    _validate_reference_query_request_successor(value, REFERENCE_QUERY_REQUEST_V11_SCHEMA_RESOURCE)


def validate_reference_query_request_v2(value: object) -> None:
    """Mixed context metadata only; numerical QUERY protocol stays exact1.1."""
    _validate_reference_query_request_successor(value, REFERENCE_QUERY_REQUEST_V2_SCHEMA_RESOURCE)


def _validate_reference_query_request_successor(
    value: object, resource: tuple[str, str, str]
) -> None:
    try:
        document = raw_similarity_contract_value(value)
        if len(canonical_json_bytes(document)) > 64 * 1024:
            raise ValueError("QUERY request exceeds its bound")
        schema = (
            _reference_query_request_v2_schema()
            if resource == REFERENCE_QUERY_REQUEST_V2_SCHEMA_RESOURCE
            else _reference_query_request_v11_schema()
        )
        Draft202012Validator(
            {"$ref": resource[1]},
            registry=_reference_query_execution_registry().with_resource(
                resource[1], Resource.from_contents(schema)
            ),
            format_checker=FormatChecker(),
        ).validate(document)
    except ReferenceQueryContractError:
        raise
    except Exception:
        raise ReferenceQueryContractError("REFERENCE_QUERY_CONTRACT_INVALID") from None


LOCAL_EMBEDDING_SCHEMA_RESOURCES = (
    (
        "request",
        "local-embedding-workflow-request-v1_1.schema.json",
        "eom://schemas/workflow/local-embedding-workflow-request/1.1",
        "sha256:042c77c73507eca65d58223186117c456e6171eb0ed2abfd1ad55c908a36bee1",
    ),
    (
        "source-plan",
        "local-embedding-source-plan-v1.schema.json",
        "eom://schemas/workflow/local-embedding-source-plan/1.0",
        "sha256:8ba4b285504c2c0c4ad668def7b276c71d900bf889a498c7cb6d6c24d822372e",
    ),
    (
        "encoding-job",
        "embedding-encoding-job-v1.schema.json",
        "eom://schemas/workflow/embedding-encoding-job/1.0",
        "sha256:8ee755604333e84772d62c037d2487ead6f6f4b25a71eb92fa05c12bda748549",
    ),
    (
        "execution-policy",
        "local-embedding-execution-policy-v1.schema.json",
        "eom://schemas/workflow/local-embedding-execution-policy/1.0",
        "sha256:07f1a6abc3635a927900149f949ade9dad28690b3948a0a7370bfc291c6d0963",
    ),
)

MIXED_EMBEDDING_SOURCE_PLAN_SCHEMA_RESOURCE = (
    "mixed-source-plan",
    "local-embedding-source-plan-v2.schema.json",
    "eom://schemas/workflow/local-embedding-source-plan/2.0",
    "sha256:cbf7c6647484bc59efa1a857669ebb67aa6cf49a2a1bfaa28a326bca364f88d0",
)
PUBLIC_EMBEDDING_SOURCE_PLAN_SCHEMA_RESOURCE = (
    "public-source-plan",
    "local-embedding-source-plan-v3.schema.json",
    "eom://schemas/workflow/local-embedding-source-plan/3.0",
    "sha256:74928b617a8c3588f2c348b6803d2d898fad24774532b2b11f15a544adf25ae4",
)

MIXED_NATIVE_WORKFLOW_SCHEMA_RESOURCES = (
    (
        "mixed-request",
        "local-embedding-workflow-request-v2.schema.json",
        "eom://schemas/workflow/local-embedding-workflow-request/2.0",
        "sha256:014f00be34d03ce80a1913339a8b21e00baff445cad71ea77c7e2257c17589a5",
    ),
    (
        "mixed-ownership",
        "embedding-encoding-ownership-v2.schema.json",
        "eom://schemas/workflow/embedding-encoding-ownership/2.0",
        "sha256:9bd1fe4ce7b097681ae8195ec1b3f7a365400ca6f917c47eb2ea3218116c1db1",
    ),
    (
        "mixed-completion",
        "local-embedding-completion-v2.schema.json",
        "eom://schemas/workflow/local-embedding-completion/2.0",
        "sha256:543283984d92ef61d59d044c396e2001267c6f15532081f71f45c0034200b5b1",
    ),
)
PUBLIC_NATIVE_WORKFLOW_SCHEMA_RESOURCES = (
    (
        "registered-public-coordinator",
        "native-embedding-coordinator-v4.schema.json",
        "eom://schemas/workflow/native-embedding-coordinator/4.0",
        "sha256:542b52c9572b69df24ec7d3a707e828c71b050c23dc5ed3bb023bb3014cb96ba",
    ),
    (
        "registered-public-completion",
        "local-embedding-completion-v4.schema.json",
        "eom://schemas/workflow/local-embedding-completion/4.0",
        "sha256:6f5724a071d44927b04430d097d0671c2027488961f96fe61800e386b239b4e1",
    ),
    (
        "registered-public-ownership",
        "embedding-encoding-ownership-v4.schema.json",
        "eom://schemas/workflow/embedding-encoding-ownership/4.0",
        "sha256:28d2448abee1c67b7b48ea2717aa59029aa5bf2a4a31a1aff9699c8ba9780284",
    ),
    (
        "registered-public-request",
        "local-embedding-workflow-request-v4.schema.json",
        "eom://schemas/workflow/local-embedding-workflow-request/4.0",
        "sha256:7e2a32a4c211f5a13d8b1ad9b9894a1eceee9ae352166e51b192428931d9dc5e",
    ),
    (
        "registered-public-source-plan",
        "local-embedding-source-plan-v4.schema.json",
        "eom://schemas/workflow/local-embedding-source-plan/4.0",
        "sha256:1c1a2db1ae0643e1e8843d9866fe789b9877e06cabbb9cc9a798d2e82335b8d7",
    ),
    (
        "public-completion",
        "local-embedding-completion-v3.schema.json",
        "eom://schemas/workflow/local-embedding-completion/3.0",
        "sha256:63cb7949b7c71ec0cc6f83bd95463a31269a789f5b4f0642cdbf6f7c24c2627b",
    ),
    (
        "public-coordinator",
        "native-embedding-coordinator-v3.schema.json",
        "eom://schemas/workflow/native-embedding-coordinator/3.0",
        "sha256:5da92e6ddbaf39f8f4c9aee371be929f58f68a6919015da7a01e48d2d225d2a0",
    ),
    (
        "public-request",
        "local-embedding-workflow-request-v3.schema.json",
        "eom://schemas/workflow/local-embedding-workflow-request/3.0",
        "sha256:81f38bd9a5996ca02e5463d6fffe89d01d61c9972d50abb049ebbdbcd4304e4f",
    ),
    (
        "public-ownership",
        "embedding-encoding-ownership-v3.schema.json",
        "eom://schemas/workflow/embedding-encoding-ownership/3.0",
        "sha256:d30a5355499c7576249ca46c147411b52ac11407f2115003f87b20fcaa4db465",
    ),
)

WORKFLOW_DEFINITION_V1_4_SCHEMA_RESOURCE = (
    "definition-v2",
    "workflow-definition-v1_4.schema.json",
    "https://eom.local/schemas/workflow/workflow-definition-v1_4.schema.json",
    "sha256:64fe5bbf63c7c2ee4e3b7994b2eb4293610bd82dee569a809def0ceb4910cb67",
)

LOCAL_EMBEDDING_SERVICE_SCHEMA_RESOURCES = (
    (
        "service-request",
        "local-embedding-workflow-request-v1_2.schema.json",
        "eom://schemas/workflow/local-embedding-workflow-request/1.2",
        "sha256:635bf4c24d3e2bf17d070b6c971d97c2436139dac6dc57f2ca22cfc0d32ac581",
    ),
    (
        "service-execution-policy",
        "local-embedding-execution-policy-v1_1.schema.json",
        "eom://schemas/workflow/local-embedding-execution-policy/1.1",
        "sha256:95d87832450cd8823fdafa3458ee21a513b1c9a49c1196a4a867f354d9565f37",
    ),
)
PRIVATE_CHAT_QUERY_EXECUTION_SCHEMA_RESOURCE = (
    "private-chat-execution",
    "private-chat-query-execution-v1.schema.json",
    "eom://schemas/workflow/private-chat-query-execution/1.0",
    "sha256:b1a2d42eb5d7ed9ce8b6447e7524a90121820961a22882d5b91f331312609a6f",
)
PRIVATE_CHAT_QUERY_PUBLICATION_SCHEMA_RESOURCE = (
    "private-chat-publication",
    "private-chat-query-publication-v1.schema.json",
    "eom://schemas/workflow/private-chat-query-publication/1.0",
    "sha256:0e1282a4f912a4aaa25cb7cb4062179742a5d8165a875c3b17d101547eaacf0a",
)
PRIVATE_CHAT_QUERY_RUNNER_SCHEMA_RESOURCE = (
    "private-chat-runner",
    "private-chat-query-runner-v1.schema.json",
    "eom://schemas/workflow/private-chat-query-runner/1.0",
    "sha256:694c6043fc7f78f662b01bf05d7d812453efdbdfa400b3b4fcfc85c31f21195a",
)
PRIVATE_CHAT_QUERY_SUBMISSION_SCHEMA_RESOURCE = (
    "private-chat-submission",
    "private-chat-query-submission-context-v1.schema.json",
    "eom://schemas/workflow/private-chat-query-submission-context/1.0",
    "sha256:49ad0ce351838678b75c5ca94a35628067785536a31ed4c38c0e353c624d1493",
)
EMBEDDING_BENCHMARK_LAUNCH_CONTROL_SCHEMA_RESOURCE = (
    "benchmark-launch-control",
    "embedding-benchmark-launch-control-v1.schema.json",
    "eom://schemas/workflow/embedding-benchmark-launch-control/1.0",
    "sha256:2ceb6cb0150ffc64f2b4e94fed17cff36181b486885c8f78d8e6c0cd4c34de27",
)
type LocalEmbeddingSchemaName = Literal[
    "registered-public-coordinator",
    "registered-public-completion",
    "registered-public-ownership",
    "registered-public-request",
    "registered-public-source-plan",
    "private-chat-submission",
    "private-chat-runner",
    "private-chat-publication",
    "private-chat-execution",
    "benchmark-launch-control",
    "request",
    "source-plan",
    "mixed-source-plan",
    "public-source-plan",
    "mixed-request",
    "public-request",
    "public-ownership",
    "public-completion",
    "public-coordinator",
    "mixed-ownership",
    "mixed-completion",
    "definition-v2",
    "encoding-job",
    "execution-policy",
    "service-request",
    "service-execution-policy",
]


class LocalEmbeddingAdmissionContractError(ValueError):
    """Content-free protocol error; not an authorization or runtime readiness result."""


def _native_contract_values(value: object, depth: int = 0) -> Any:
    # A serializer can coerce a model_copy bool into its declared int. Reparse
    # the actual value tree instead of accepting that lossy serialization.
    if depth > 32:
        raise ValueError("native contract value nesting exceeds its bound")
    if isinstance(value, BaseModel):
        return _native_contract_values(value.__dict__, depth + 1)
    if isinstance(value, dict):
        if len(value) > 64 or not all(isinstance(key, str) for key in value):
            raise ValueError("native contract object frame exceeds its bound")
        return {key: _native_contract_values(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        if len(value) > 1024:
            raise ValueError("native contract collection exceeds its bound")
        return [_native_contract_values(item, depth + 1) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise ValueError("native contract values must be integer-only JSON or UTC timestamps")


class NativeEmbeddingContract(FrozenModel):
    """Reparse nested values, including unvalidated model_copy/construct instances."""

    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def reparse_native_values(cls, value: object) -> Any:
        return _native_contract_values(value)


@cache
def _local_embedding_admission_schema(name: LocalEmbeddingSchemaName) -> dict[str, Any]:
    try:
        _, filename, schema_id, expected = next(
            entry
            for entry in (
                *LOCAL_EMBEDDING_SCHEMA_RESOURCES,
                MIXED_EMBEDDING_SOURCE_PLAN_SCHEMA_RESOURCE,
                PUBLIC_EMBEDDING_SOURCE_PLAN_SCHEMA_RESOURCE,
                *MIXED_NATIVE_WORKFLOW_SCHEMA_RESOURCES,
                *PUBLIC_NATIVE_WORKFLOW_SCHEMA_RESOURCES,
                WORKFLOW_DEFINITION_V1_4_SCHEMA_RESOURCE,
                *LOCAL_EMBEDDING_SERVICE_SCHEMA_RESOURCES,
                PRIVATE_CHAT_QUERY_EXECUTION_SCHEMA_RESOURCE,
                PRIVATE_CHAT_QUERY_PUBLICATION_SCHEMA_RESOURCE,
                PRIVATE_CHAT_QUERY_RUNNER_SCHEMA_RESOURCE,
                PRIVATE_CHAT_QUERY_SUBMISSION_SCHEMA_RESOURCE,
                EMBEDDING_BENCHMARK_LAUNCH_CONTROL_SCHEMA_RESOURCE,
            )
            if entry[0] == name
        )
        with WORKFLOW_RESOURCE_ROOT.joinpath(filename).open("rb") as stream:
            payload = stream.read(64 * 1024 + 1)
        if not 0 < len(payload) <= 64 * 1024 or sha256_bytes(payload) != expected:
            raise ValueError("native installed schema identity differs")
        raw = json.loads(payload)
        if not isinstance(raw, dict) or raw.get("$id") != schema_id:
            raise ValueError("native installed schema root differs")
        Draft202012Validator.check_schema(raw)
        return raw
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_SCHEMA_UNAVAILABLE") from None


def load_local_embedding_admission_schema(name: LocalEmbeddingSchemaName) -> dict[str, Any]:
    """Only pinned native resources; no role inventory or legacy hash change."""
    return copy.deepcopy(_local_embedding_admission_schema(name))


@cache
def _local_embedding_admission_schema_registry() -> Registry[Any]:
    """Extend the existing public Catalog reference boundary, never fetch remote schemas."""
    return catalog_schema_registry().with_resources(
        (
            schema_id,
            Resource.from_contents(
                _local_embedding_admission_schema(cast(LocalEmbeddingSchemaName, name))
            ),
        )
        for name, _, schema_id, _ in (
            *LOCAL_EMBEDDING_SCHEMA_RESOURCES,
            MIXED_EMBEDDING_SOURCE_PLAN_SCHEMA_RESOURCE,
            PUBLIC_EMBEDDING_SOURCE_PLAN_SCHEMA_RESOURCE,
            *MIXED_NATIVE_WORKFLOW_SCHEMA_RESOURCES,
            *PUBLIC_NATIVE_WORKFLOW_SCHEMA_RESOURCES,
            WORKFLOW_DEFINITION_V1_4_SCHEMA_RESOURCE,
            *LOCAL_EMBEDDING_SERVICE_SCHEMA_RESOURCES,
            PRIVATE_CHAT_QUERY_EXECUTION_SCHEMA_RESOURCE,
            PRIVATE_CHAT_QUERY_PUBLICATION_SCHEMA_RESOURCE,
            PRIVATE_CHAT_QUERY_RUNNER_SCHEMA_RESOURCE,
            PRIVATE_CHAT_QUERY_SUBMISSION_SCHEMA_RESOURCE,
            EMBEDDING_BENCHMARK_LAUNCH_CONTROL_SCHEMA_RESOURCE,
        )
    )


def local_embedding_admission_schema_registry() -> Registry[Any]:
    """Return isolated native resources; a caller cannot mutate parser-pinned schemas."""
    return catalog_schema_registry().with_resources(
        (
            schema_id,
            Resource.from_contents(
                load_local_embedding_admission_schema(cast(LocalEmbeddingSchemaName, name))
            ),
        )
        for name, _, schema_id, _ in (
            *LOCAL_EMBEDDING_SCHEMA_RESOURCES,
            MIXED_EMBEDDING_SOURCE_PLAN_SCHEMA_RESOURCE,
            PUBLIC_EMBEDDING_SOURCE_PLAN_SCHEMA_RESOURCE,
            *MIXED_NATIVE_WORKFLOW_SCHEMA_RESOURCES,
            *PUBLIC_NATIVE_WORKFLOW_SCHEMA_RESOURCES,
            WORKFLOW_DEFINITION_V1_4_SCHEMA_RESOURCE,
            *LOCAL_EMBEDDING_SERVICE_SCHEMA_RESOURCES,
            PRIVATE_CHAT_QUERY_EXECUTION_SCHEMA_RESOURCE,
            PRIVATE_CHAT_QUERY_PUBLICATION_SCHEMA_RESOURCE,
            PRIVATE_CHAT_QUERY_RUNNER_SCHEMA_RESOURCE,
            PRIVATE_CHAT_QUERY_SUBMISSION_SCHEMA_RESOURCE,
            EMBEDDING_BENCHMARK_LAUNCH_CONTROL_SCHEMA_RESOURCE,
        )
    )


def validate_local_embedding_admission_message(
    name: LocalEmbeddingSchemaName, value: object
) -> None:
    """Closed frame and integer-only byte bound before typed semantic validation."""
    try:
        maximum = (
            64 * 1024
            if name
            in {
                "request",
                "mixed-request",
                "public-request",
                "registered-public-request",
                "public-completion",
                "registered-public-completion",
                "public-coordinator",
                "registered-public-coordinator",
                "mixed-completion",
                "definition-v2",
                "execution-policy",
                "service-request",
                "service-execution-policy",
                "benchmark-launch-control",
                "private-chat-execution",
                "private-chat-publication",
                "private-chat-runner",
                "private-chat-submission",
            }
            else 64 * 1024**2
        )
        if len(canonical_json_bytes(value)) > maximum:
            raise ValueError("native contract byte bound differs")
        validator = Draft202012Validator(
            _local_embedding_admission_schema(name),
            registry=_local_embedding_admission_schema_registry(),
            format_checker=FormatChecker(),
        )
        if not validator.is_valid(value):
            raise ValueError("native contract closed schema differs")
    except LocalEmbeddingAdmissionContractError:
        raise
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


LOCAL_EMBEDDING_RECEIPT_SCHEMA_RESOURCES = (
    (
        "step-output",
        "local-embedding-step-output-v1.schema.json",
        "eom://schemas/workflow/local-embedding-step-output/1.0",
        "sha256:369ac4f4d72a55b7b19483f3a2dc8b52ad37bf35c590aaf0487dd50154d8a772",
    ),
    (
        "workflow-receipt",
        "local-embedding-workflow-receipt-v1.schema.json",
        "eom://schemas/workflow/local-embedding-workflow-receipt/1.0",
        "sha256:16a18269d60ef05e2868b96682af48d9ea0c4a54a766c49dea46f9750fb3bdc3",
    ),
)
type LocalEmbeddingReceiptSchemaName = Literal["step-output", "workflow-receipt"]


@cache
def _local_embedding_receipt_schema(name: LocalEmbeddingReceiptSchemaName) -> dict[str, Any]:
    try:
        _, filename, schema_id, expected = next(
            entry for entry in LOCAL_EMBEDDING_RECEIPT_SCHEMA_RESOURCES if entry[0] == name
        )
        with WORKFLOW_RESOURCE_ROOT.joinpath(filename).open("rb") as stream:
            payload = stream.read(64 * 1024 + 1)
        if not 0 < len(payload) <= 64 * 1024 or sha256_bytes(payload) != expected:
            raise ValueError("native receipt installed schema identity differs")
        raw = json.loads(payload)
        if not isinstance(raw, dict) or raw.get("$id") != schema_id:
            raise ValueError("native receipt installed schema root differs")
        Draft202012Validator.check_schema(raw)
        return raw
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_SCHEMA_UNAVAILABLE") from None


def load_local_embedding_receipt_schema(name: LocalEmbeddingReceiptSchemaName) -> dict[str, Any]:
    """Two separate receipt resources; released four-family/role inventories are unchanged."""
    return copy.deepcopy(_local_embedding_receipt_schema(name))


@cache
def _local_embedding_receipt_schema_registry() -> Registry[Any]:
    return _local_embedding_admission_schema_registry().with_resources(
        (
            schema_id,
            Resource.from_contents(
                _local_embedding_receipt_schema(cast(LocalEmbeddingReceiptSchemaName, name))
            ),
        )
        for name, _, schema_id, _ in LOCAL_EMBEDDING_RECEIPT_SCHEMA_RESOURCES
    )


def local_embedding_receipt_schema_registry() -> Registry[Any]:
    """Public isolated reference registry, with no remote schema retrieval."""
    return local_embedding_admission_schema_registry().with_resources(
        (
            schema_id,
            Resource.from_contents(
                load_local_embedding_receipt_schema(cast(LocalEmbeddingReceiptSchemaName, name))
            ),
        )
        for name, _, schema_id, _ in LOCAL_EMBEDDING_RECEIPT_SCHEMA_RESOURCES
    )


def validate_local_embedding_receipt_message(
    name: LocalEmbeddingReceiptSchemaName, value: object
) -> None:
    """Closed integer-only frame and fixed carrier/receipt cap, never owner admission."""
    try:
        document = _native_contract_values(value)
        maximum = 8 * 1024 if name == "step-output" else 64 * 1024
        if len(canonical_json_bytes(document)) > maximum:
            raise ValueError("native receipt byte bound differs")
        validator = Draft202012Validator(
            _local_embedding_receipt_schema(name),
            registry=_local_embedding_receipt_schema_registry(),
            format_checker=FormatChecker(),
        )
        if not validator.is_valid(document):
            raise ValueError("native receipt closed schema differs")
    except LocalEmbeddingAdmissionContractError:
        raise
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


NATIVE_EMBEDDING_COORDINATOR_SCHEMA_RESOURCE = (
    "native-embedding-coordinator-v1.schema.json",
    "eom://schemas/workflow/native-embedding-coordinator/1.0",
    "sha256:796268d09fb8004b3f1ce17e16c8d44e19e151d3434c5288324bf1292707fd08",
)
NATIVE_EMBEDDING_COORDINATOR_V2_SCHEMA_RESOURCE = (
    "native-embedding-coordinator-v2.schema.json",
    "eom://schemas/workflow/native-embedding-coordinator/2.0",
    "sha256:5f099421f63b83c8d6847a232c4235d8e3708fd4241a61b8341984c8826a6249",
)


@cache
def _native_embedding_coordinator_schema(
    resource: tuple[str, str, str] = NATIVE_EMBEDDING_COORDINATOR_SCHEMA_RESOURCE,
) -> dict[str, Any]:
    filename, schema_id, expected = resource
    try:
        with WORKFLOW_RESOURCE_ROOT.joinpath(filename).open("rb") as stream:
            raw = stream.read(64 * 1024 + 1)
        if not 0 < len(raw) <= 64 * 1024 or sha256_bytes(raw) != expected:
            raise ValueError("coordinator schema differs")
        document = json.loads(raw)
        if not isinstance(document, dict) or document.get("$id") != schema_id:
            raise ValueError("coordinator schema identity differs")
        Draft202012Validator.check_schema(document)
        return document
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_SCHEMA_UNAVAILABLE") from None


def load_native_embedding_coordinator_schema() -> dict[str, Any]:
    return copy.deepcopy(_native_embedding_coordinator_schema())


def load_native_embedding_coordinator_v2_schema() -> dict[str, Any]:
    return copy.deepcopy(
        _native_embedding_coordinator_schema(NATIVE_EMBEDDING_COORDINATOR_V2_SCHEMA_RESOURCE)
    )


def validate_native_embedding_coordinator_message(value: object) -> None:
    """One separate owner-only frame; released encoding/receipt/role schemas stay exact."""
    _validate_native_embedding_coordinator_message(
        value, NATIVE_EMBEDDING_COORDINATOR_SCHEMA_RESOURCE
    )


def validate_native_embedding_coordinator_v2_message(value: object) -> None:
    """Mixed checkpoint metadata only; never retag or widen an original checkpoint1."""
    _validate_native_embedding_coordinator_message(
        value, NATIVE_EMBEDDING_COORDINATOR_V2_SCHEMA_RESOURCE
    )


def _validate_native_embedding_coordinator_message(
    value: object, resource: tuple[str, str, str]
) -> None:
    try:
        document = _native_contract_values(value)
        if len(canonical_json_bytes(document)) > 16 * 1024:
            raise ValueError("coordinator metadata exceeds its bound")
        schema = _native_embedding_coordinator_schema(resource)
        Draft202012Validator(
            schema,
            registry=_local_embedding_receipt_schema_registry().with_resource(
                resource[1], Resource.from_contents(schema)
            ),
            format_checker=FormatChecker(),
        ).validate(document)
    except LocalEmbeddingAdmissionContractError:
        raise
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


NATIVE_REFERENCE_QUERY_COORDINATOR_SCHEMA_RESOURCE = (
    "native-reference-query-coordinator-v1.schema.json",
    "eom://schemas/workflow/native-reference-query-coordinator/1.0",
    "sha256:b3711bf1f8722b9a0b884dac7f3ef032c0bd28bd4e76351f3d7ee4d1e0f17745",
)
NATIVE_REFERENCE_QUERY_COORDINATOR_V11_SCHEMA_RESOURCE = (
    "native-reference-query-coordinator-v1.1.schema.json",
    "eom://schemas/workflow/native-reference-query-coordinator/1.1",
    "sha256:a3f08ea22ec5f71582f86598f6fa16737115e23742a332173da034f59860e6ed",
)
NATIVE_REFERENCE_QUERY_COORDINATOR_V12_SCHEMA_RESOURCE = (
    "native-reference-query-coordinator-v1.2.schema.json",
    "eom://schemas/workflow/native-reference-query-coordinator/1.2",
    "sha256:8e00ce9ceb8f0717bf6eb0c9a42481df4585b055d449a986e0471839df65bf65",
)
NATIVE_REFERENCE_QUERY_COORDINATOR_V2_SCHEMA_RESOURCE = (
    "native-reference-query-coordinator-v2.schema.json",
    "eom://schemas/workflow/native-reference-query-coordinator/2.0",
    "sha256:bc03cc4d0d9435ccf836810736586fc9fc5ab149c4cba8e963827b5ee1d264d1",
)
NATIVE_PRIVATE_CHAT_QUERY_COORDINATOR_SCHEMA_RESOURCE = (
    "native-private-chat-query-coordinator-v1.schema.json",
    "eom://schemas/workflow/native-private-chat-query-coordinator/1.0",
    "sha256:52b9d892e9010a923ed287163d60030113f2f03dc19fc79c1f26902e7187ae3f",
)


@cache
def _native_reference_query_coordinator_schema(
    resource: tuple[str, str, str] = NATIVE_REFERENCE_QUERY_COORDINATOR_SCHEMA_RESOURCE,
) -> dict[str, Any]:
    filename, schema_id, expected = resource
    try:
        with WORKFLOW_RESOURCE_ROOT.joinpath(filename).open("rb") as stream:
            payload = stream.read(16 * 1024 + 1)
        if not 0 < len(payload) <= 16 * 1024 or sha256_bytes(payload) != expected:
            raise ValueError("QUERY checkpoint schema differs")
        document = json.loads(payload)
        if not isinstance(document, dict) or document.get("$id") != schema_id:
            raise ValueError("QUERY checkpoint schema identity differs")
        Draft202012Validator.check_schema(document)
        return document
    except Exception:
        raise ReferenceQueryContractError("REFERENCE_QUERY_SCHEMA_UNAVAILABLE") from None


def load_native_reference_query_coordinator_schema() -> dict[str, Any]:
    return copy.deepcopy(_native_reference_query_coordinator_schema())


def load_native_reference_query_coordinator_v2_schema() -> dict[str, Any]:
    return copy.deepcopy(
        _native_reference_query_coordinator_schema(
            NATIVE_REFERENCE_QUERY_COORDINATOR_V2_SCHEMA_RESOURCE
        )
    )


def load_native_private_chat_query_coordinator_schema() -> dict[str, Any]:
    return copy.deepcopy(
        _native_reference_query_coordinator_schema(
            NATIVE_PRIVATE_CHAT_QUERY_COORDINATOR_SCHEMA_RESOURCE
        )
    )


def validate_native_private_chat_query_checkpoint(value: object) -> None:
    """Separate private purpose; no remote resolution or mutation of old resources."""
    try:
        document = raw_similarity_contract_value(value)
        if len(canonical_json_bytes(document)) > 64 * 1024:
            raise ValueError()
        registry = _local_embedding_admission_schema_registry().with_resources(
            (
                (
                    NATIVE_EMBEDDING_COORDINATOR_SCHEMA_RESOURCE[1],
                    Resource.from_contents(_native_embedding_coordinator_schema()),
                ),
                (
                    NATIVE_REFERENCE_QUERY_COORDINATOR_SCHEMA_RESOURCE[1],
                    Resource.from_contents(_native_reference_query_coordinator_schema()),
                ),
            )
        )
        Draft202012Validator(
            _native_reference_query_coordinator_schema(
                NATIVE_PRIVATE_CHAT_QUERY_COORDINATOR_SCHEMA_RESOURCE
            ),
            registry=registry,
            format_checker=FormatChecker(),
        ).validate(document)
    except Exception:
        raise LocalEmbeddingAdmissionContractError(
            "PRIVATE_CHAT_QUERY_CHECKPOINT_INVALID"
        ) from None


def validate_native_reference_query_checkpoint(value: object) -> None:
    _validate_native_reference_query_checkpoint(
        value, NATIVE_REFERENCE_QUERY_COORDINATOR_SCHEMA_RESOURCE
    )


def validate_native_reference_query_checkpoint_v11(value: object) -> None:
    _validate_native_reference_query_checkpoint(
        value, NATIVE_REFERENCE_QUERY_COORDINATOR_V11_SCHEMA_RESOURCE
    )


def validate_native_reference_query_checkpoint_v12(value: object) -> None:
    _validate_native_reference_query_checkpoint(
        value, NATIVE_REFERENCE_QUERY_COORDINATOR_V12_SCHEMA_RESOURCE
    )


def validate_native_reference_query_checkpoint_v2(value: object) -> None:
    _validate_native_reference_query_checkpoint(
        value, NATIVE_REFERENCE_QUERY_COORDINATOR_V2_SCHEMA_RESOURCE
    )


def _validate_native_reference_query_checkpoint(
    value: object, resource: tuple[str, str, str]
) -> None:
    try:
        document = raw_similarity_contract_value(value)
        if len(canonical_json_bytes(document)) > 16 * 1024:
            raise ValueError("QUERY checkpoint metadata exceeds its bound")
        registry = (
            (
                _reference_query_public_execution_registry()
                if resource == NATIVE_REFERENCE_QUERY_COORDINATOR_V2_SCHEMA_RESOURCE
                else _reference_query_execution_registry()
            )
            .with_resource(
                NATIVE_EMBEDDING_COORDINATOR_SCHEMA_RESOURCE[1],
                Resource.from_contents(_native_embedding_coordinator_schema()),
            )
            .with_resource(
                NATIVE_REFERENCE_QUERY_COORDINATOR_SCHEMA_RESOURCE[1],
                Resource.from_contents(_native_reference_query_coordinator_schema()),
            )
        )
        if resource == NATIVE_REFERENCE_QUERY_COORDINATOR_V2_SCHEMA_RESOURCE:
            registry = registry.with_resources(
                (
                    selected[1],
                    Resource.from_contents(_native_reference_query_coordinator_schema(selected)),
                )
                for selected in (
                    NATIVE_REFERENCE_QUERY_COORDINATOR_V11_SCHEMA_RESOURCE,
                    NATIVE_REFERENCE_QUERY_COORDINATOR_V12_SCHEMA_RESOURCE,
                )
            )
        Draft202012Validator(
            _native_reference_query_coordinator_schema(resource),
            registry=registry,
            format_checker=FormatChecker(),
        ).validate(document)
    except ReferenceQueryContractError:
        raise
    except Exception:
        raise ReferenceQueryContractError("REFERENCE_QUERY_CHECKPOINT_INVALID") from None


def load_json_schema(resource: Traversable, logical_name: str) -> dict[str, Any]:
    try:
        raw: object = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkflowSchemaError(_resource_error(logical_name)) from exc
    if not isinstance(raw, dict):
        raise WorkflowSchemaError(f"workflow schema is not an object: {logical_name}")
    try:
        Draft202012Validator.check_schema(raw)
    except SchemaError as exc:
        raise WorkflowSchemaError(f"workflow schema is invalid: {logical_name}") from exc
    return raw


def load_definition_schema() -> dict[str, Any]:
    logical_name = "workflow-definition.schema.json"
    return load_json_schema(WORKFLOW_RESOURCE_ROOT.joinpath(logical_name), logical_name)


@cache
def _inference_transfer_workflow_request_schema() -> dict[str, Any]:
    logical_name = "inference-transfer-workflow-request-v1.schema.json"
    return load_json_schema(WORKFLOW_RESOURCE_ROOT.joinpath(logical_name), logical_name)


def load_inference_transfer_workflow_request_schema() -> dict[str, Any]:
    """Return an isolated copy of the process-pinned installed schema resource."""

    return copy.deepcopy(_inference_transfer_workflow_request_schema())


def validate_inference_transfer_workflow_request(value: object) -> InferenceTransferWorkflowRequest:
    """Validate the installed closed schema and exact bounded typed pair context."""

    validate_schema_message(
        _inference_transfer_workflow_request_schema(), value, "inference-transfer-workflow"
    )
    try:
        return InferenceTransferWorkflowRequest.model_validate(value)
    except ValidationError as exc:
        raise WorkflowSchemaError("inference-transfer-workflow failed typed validation") from exc


@cache
def _inference_transfer_workflow_request_schema_v11() -> dict[str, Any]:
    name = "inference-transfer-workflow-request-v1_1.schema.json"
    return load_json_schema(WORKFLOW_RESOURCE_ROOT.joinpath(name), name)


def load_inference_transfer_workflow_request_schema_v11() -> dict[str, Any]:
    return copy.deepcopy(_inference_transfer_workflow_request_schema_v11())


def validate_inference_transfer_workflow_request_v11(
    value: object,
) -> InferenceTransferWorkflowRequestV11:
    validate_schema_message(
        _inference_transfer_workflow_request_schema_v11(), value, "inference-transfer-workflow-v1.1"
    )
    try:
        return InferenceTransferWorkflowRequestV11.model_validate(value)
    except ValidationError as exc:
        raise WorkflowSchemaError(
            "three-axis inference-transfer Workflow failed typed validation"
        ) from exc


def load_review_rework_directive_schema() -> dict[str, Any]:
    logical_name = "workflow-review-rework-directive-v1.schema.json"
    return load_json_schema(WORKFLOW_RESOURCE_ROOT.joinpath(logical_name), logical_name)


def load_review_rework_directive_v2_schema() -> dict[str, Any]:
    logical_name = "workflow-review-rework-directive-v2.schema.json"
    return load_json_schema(WORKFLOW_RESOURCE_ROOT.joinpath(logical_name), logical_name)


def load_review_escalation_directive_schema() -> dict[str, Any]:
    logical_name = "workflow-review-escalation-directive-v1.schema.json"
    return load_json_schema(WORKFLOW_RESOURCE_ROOT.joinpath(logical_name), logical_name)


def load_review_correction_directive_schema() -> dict[str, Any]:
    logical_name = "workflow-review-correction-directive-v1.schema.json"
    return load_json_schema(WORKFLOW_RESOURCE_ROOT.joinpath(logical_name), logical_name)


def load_knowledge_item_brief_schema() -> dict[str, Any]:
    logical_name = "knowledge-item-brief-v1.schema.json"
    return load_json_schema(WORKFLOW_RESOURCE_ROOT.joinpath(logical_name), logical_name)


def load_knowledge_item_brief_v2_schema() -> dict[str, Any]:
    logical_name = "knowledge-item-brief-v2.schema.json"
    return load_json_schema(WORKFLOW_RESOURCE_ROOT.joinpath(logical_name), logical_name)


def load_knowledge_item_brief_v3_schema() -> dict[str, Any]:
    logical_name = "knowledge-item-brief-v3.schema.json"
    return load_json_schema(WORKFLOW_RESOURCE_ROOT.joinpath(logical_name), logical_name)


def load_content_team_material_requirement_schema() -> dict[str, Any]:
    logical_name = "content-team-material-requirement-v1.schema.json"
    return load_json_schema(WORKFLOW_RESOURCE_ROOT.joinpath(logical_name), logical_name)


def load_content_team_material_requirement_v2_schema() -> dict[str, Any]:
    logical_name = "content-team-material-requirement-v2.schema.json"
    return load_json_schema(WORKFLOW_RESOURCE_ROOT.joinpath(logical_name), logical_name)


def load_knowledge_item_brief_v4_schema() -> dict[str, Any]:
    logical_name = "knowledge-item-brief-v4.schema.json"
    return load_json_schema(WORKFLOW_RESOURCE_ROOT.joinpath(logical_name), logical_name)


def load_knowledge_item_brief_v5_schema() -> dict[str, Any]:
    logical_name = "knowledge-item-brief-v5.schema.json"
    return load_json_schema(WORKFLOW_RESOURCE_ROOT.joinpath(logical_name), logical_name)


@lru_cache(maxsize=1)
def _content_team_editorial_material_schema() -> dict[str, Any]:
    file_name = "content-team-editorial-material-v1.schema.json"
    return load_json_schema(ROLE_RESOURCE_ROOT.joinpath(file_name), f"roles/{file_name}")


def load_content_team_editorial_material_schema() -> dict[str, Any]:
    """Return an isolated copy of the canonical editorial-material schema."""

    return copy.deepcopy(_content_team_editorial_material_schema())


@lru_cache(maxsize=1)
def _content_team_image_route_schema() -> dict[str, Any]:
    file_name = "content-team-image-route-v1.schema.json"
    return load_json_schema(ROLE_RESOURCE_ROOT.joinpath(file_name), f"roles/{file_name}")


def load_content_team_image_route_schema() -> dict[str, Any]:
    """Return an isolated copy of the canonical image-route schema."""

    return copy.deepcopy(_content_team_image_route_schema())


@cache
def _role_input_schema(role: str, protocol_version: str = "workflow-role/1.0.1") -> dict[str, Any]:
    try:
        file_name = PROTOCOL_INPUT_SCHEMAS[protocol_version][role]
    except KeyError as exc:
        raise WorkflowSchemaError(
            f"unknown worker role or protocol: {role}@{protocol_version}"
        ) from exc
    logical_name = f"roles/{file_name}"
    schema = load_json_schema(ROLE_RESOURCE_ROOT.joinpath(file_name), logical_name)
    if protocol_version in {
        "workflow-role/1.1.0",
        "workflow-role/1.2.0",
        "workflow-role/1.3.0",
        "workflow-role/1.12.0",
        "workflow-role/1.13.0",
        "workflow-role/1.15.0",
        "workflow-role/1.17.0",
        "workflow-role/1.19.0",
        "workflow-role/1.20.0",
        "workflow-role/1.23.0",
        "workflow-role/1.24.0",
    }:
        schema = copy.deepcopy(schema)
        _mapping(_mapping(schema, "properties"), "protocol_version")["const"] = protocol_version
        request = _mapping(_mapping(schema, "$defs"), "request")
        request_name = _mapping(_mapping(request, "properties"), "request_name")
        request_name.pop("const", None)
        request_name["const"] = (
            "GENERATED_KNOWLEDGE_ITEM_REQUEST"
            if protocol_version
            in {
                "workflow-role/1.2.0",
                "workflow-role/1.3.0",
                "workflow-role/1.12.0",
                "workflow-role/1.13.0",
                "workflow-role/1.15.0",
                "workflow-role/1.17.0",
                "workflow-role/1.19.0",
                "workflow-role/1.20.0",
                "workflow-role/1.23.0",
                "workflow-role/1.24.0",
            }
            else "KNOWLEDGE_ITEM_REQUEST"
        )
    return _inline_catalog_schema(
        schema,
        require_reference_closure=protocol_version
        in {
            "workflow-role/1.9.0",
            "workflow-role/1.10.0",
            "workflow-role/1.11.0",
            "workflow-role/1.14.0",
            "workflow-role/1.16.0",
            "workflow-role/1.18.0",
            "workflow-role/1.21.0",
            "workflow-role/1.35.0",
            "workflow-role/1.29.0",
            "workflow-role/1.30.0",
            "workflow-role/1.31.0",
            "workflow-role/1.32.0",
            "workflow-role/1.33.0",
        },
    )


def load_role_input_schema(
    role: str, protocol_version: str = "workflow-role/1.0.1"
) -> dict[str, Any]:
    """Return an isolated copy while retaining one validated canonical schema per identity."""

    return copy.deepcopy(_role_input_schema(role, protocol_version))


@cache
def _role_result_schema(schema_id: str) -> dict[str, Any]:
    try:
        file_name = RESULT_SCHEMA_FILES[schema_id]
    except KeyError as exc:
        raise WorkflowSchemaError(f"unknown role result schema: {schema_id}") from exc
    logical_name = f"roles/{file_name}"
    schema = load_json_schema(ROLE_RESOURCE_ROOT.joinpath(file_name), logical_name)
    return _inline_catalog_schema(
        schema,
        require_reference_closure=schema_id
        in {
            "knowledge-analysis-proposal-result@6.0",
            "knowledge-analysis-proposal-result@7.0",
            "knowledge-analysis-proposal-result@8.0",
            "knowledge-analysis-proposal-result@9.0",
            "knowledge-analysis-proposal-result@10.0",
            "knowledge-analysis-proposal-result@11.0",
            "legacy-item-extraction-result@1.0",
            "external-item-learning-result@1.0",
            "external-item-learning-result@2.0",
            "legacy-item-editorial-compatibility-result@1.0",
            "item-inference-transfer-pair-result@1.0",
            "item-inference-transfer-pair-result@1.1",
            "pdf-document-review-result@5.0",
            "pdf-document-review-result@6.0",
        },
    )


def load_role_result_schema(schema_id: str) -> dict[str, Any]:
    """Return an isolated copy while retaining one validated canonical schema per identity."""

    return copy.deepcopy(_role_result_schema(schema_id))


def validate_schema_message(schema: dict[str, Any], value: object, name: str) -> None:
    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
        registry=catalog_schema_registry(),
    )
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        raise WorkflowSchemaError(f"{name} at {path}: {error.message}")


def validate_role_input(
    value: object, role: str, protocol_version: str = "workflow-role/1.0.1"
) -> RoleWorkerInput:
    validate_schema_message(_role_input_schema(role, protocol_version), value, f"{role}-input")
    try:
        parsed = RoleWorkerInput.model_validate(value)
    except ValidationError as exc:
        raise WorkflowSchemaError(f"{role}-input failed typed validation") from exc
    if parsed.role != role:
        raise WorkflowSchemaError("role input does not match requested role")
    return parsed


def _filter_invalid_knowledge_analysis_v9_edges(value: object) -> object:
    """Apply ADR 0047 edge filtering before the V9 proposal model is constructed.

    The canonical JSON Schema has already validated the complete message before this function is
    called.  Only the untrusted edge array is copied and filtered; every other proposal value is
    passed to the existing typed and staging validators without reinterpretation.
    """

    if not isinstance(value, dict):
        return value
    output = value.get("output")
    if not isinstance(output, dict):
        return value
    proposal = output.get("proposal")
    if not isinstance(proposal, dict):
        return value
    nodes = proposal.get("nodes")
    edges = proposal.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return value

    node_types: dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, dict):
            return value
        node_id = node.get("node_id")
        node_type = node.get("node_type")
        if not isinstance(node_id, str) or not isinstance(node_type, str):
            return value
        if node_id in node_types:
            # Duplicate identities are ambiguous and remain an error for the typed validator.
            return value
        node_types[node_id] = node_type

    compatible_edges: list[object] = []
    edge_ids: set[str] = set()
    for edge in copy.deepcopy(edges):
        if not isinstance(edge, dict):
            return value
        edge_id = edge.get("edge_id")
        if not isinstance(edge_id, str) or edge_id in edge_ids:
            # Filtering must not select one meaning for an ambiguous immutable identity.
            # Return the original value so the existing typed validator rejects it.
            return value
        edge_ids.add(edge_id)
        relationship = edge.get("relationship")
        from_node_id = edge.get("from_node_id")
        to_node_id = edge.get("to_node_id")
        if (
            not isinstance(relationship, dict)
            or not isinstance(from_node_id, str)
            or not isinstance(to_node_id, str)
        ):
            return value
        edge_type = relationship.get("edge_type")
        declared_from_type = relationship.get("from_node_type")
        declared_to_type = relationship.get("to_node_type")
        if (
            not isinstance(edge_type, str)
            or not isinstance(declared_from_type, str)
            or not isinstance(declared_to_type, str)
        ):
            return value

        if from_node_id == to_node_id:
            continue
        actual_from_type = node_types.get(from_node_id)
        actual_to_type = node_types.get(to_node_id)
        if actual_from_type is None or actual_to_type is None:
            continue
        if actual_from_type != declared_from_type or actual_to_type != declared_to_type:
            continue
        try:
            validate_worker_knowledge_edge_endpoint_types(
                edge_type,
                declared_from_type,
                declared_to_type,
            )
        except ValueError:
            continue
        compatible_edges.append(edge)

    canonical = value.copy()
    canonical_output = output.copy()
    canonical_proposal = proposal.copy()
    canonical_proposal["edges"] = compatible_edges
    canonical_output["proposal"] = canonical_proposal
    canonical["output"] = canonical_output
    return canonical


def _canonicalize_knowledge_analysis_solution_result(value: object) -> object:
    """Order bounded V10 set-like collections after raw JSON Schema validation.

    The canonical schema rejects duplicate members before this function is called.  Sorting is the
    only transformation: identities and values are never added, removed, replaced, or deduplicated.
    Pydantic and the request-bound semantic resolver remain the authoritative closure checks.
    """

    if not isinstance(value, dict):
        return value
    output = value.get("output")
    if not isinstance(output, dict):
        return value
    proposal = output.get("proposal")
    if not isinstance(proposal, dict):
        return value
    report = proposal.get("solution_report")
    if not isinstance(report, dict):
        return value

    canonical = copy.deepcopy(value)
    canonical_output = _mapping(canonical, "output")
    canonical_proposal = _mapping(canonical_output, "proposal")
    canonical_report = _mapping(canonical_proposal, "solution_report")

    solution_steps = canonical_report.get("solution_steps")
    if isinstance(solution_steps, list):
        for step in solution_steps:
            if isinstance(step, dict):
                for field_name in (
                    "depends_on_step_ids",
                    "node_ids",
                    "item_element_node_ids",
                    "anchor_ids",
                ):
                    values = step.get(field_name)
                    if isinstance(values, list):
                        values.sort()
        solution_steps.sort(
            key=lambda step: step.get("ordinal", 0) if isinstance(step, dict) else 0
        )

    concept_links = canonical_report.get("concept_assessment_links")
    if isinstance(concept_links, list):
        for link in concept_links:
            if isinstance(link, dict):
                for field_name in (
                    "reasoning_step_ids",
                    "assessment_pattern_node_ids",
                    "item_element_node_ids",
                ):
                    values = link.get(field_name)
                    if isinstance(values, list):
                        values.sort()
        concept_links.sort(
            key=lambda link: (
                (
                    link.get("concept_node_id", ""),
                    link.get("role", ""),
                )
                if isinstance(link, dict)
                else ("", "")
            )
        )

    choice_diagnostics = canonical_report.get("choice_diagnostics")
    if isinstance(choice_diagnostics, list):
        for choice in choice_diagnostics:
            if isinstance(choice, dict):
                for field_name in ("reasoning_step_ids", "node_ids", "anchor_ids"):
                    values = choice.get(field_name)
                    if isinstance(values, list):
                        values.sort()
        choice_diagnostics.sort(
            key=lambda choice: choice.get("choice_key", "") if isinstance(choice, dict) else ""
        )

    comparison = canonical_report.get("official_explanation_comparison")
    if isinstance(comparison, dict):
        answer_anchor_ids = comparison.get("answer_explanation_anchor_ids")
        if isinstance(answer_anchor_ids, list):
            answer_anchor_ids.sort()

    unresolved_issues = canonical_report.get("unresolved_issues")
    if isinstance(unresolved_issues, list):
        for issue in unresolved_issues:
            if isinstance(issue, dict):
                anchor_ids = issue.get("anchor_ids")
                if isinstance(anchor_ids, list):
                    anchor_ids.sort()
        unresolved_issues.sort(
            key=lambda issue: issue.get("code", "") if isinstance(issue, dict) else ""
        )
    return canonical


def validate_role_result(value: object, role: str, schema_id: str) -> RoleResult:
    canonical_value = value
    if (
        schema_id
        in {
            "authoring-result@7.0",
            "authoring-result@8.0",
            "authoring-result@9.0",
            "authoring-result@10.0",
            "authoring-result@11.0",
            "authoring-result@12.0",
        }
        and role == "authoring"
    ):
        canonical_value = _canonicalize_content_team_authoring_result(value, schema_id=schema_id)
    elif schema_id == "review-result@11.0" and role == "review":
        canonical_value = _canonicalize_graph_review_v11_result(value)
    elif schema_id == "review-result@12.0" and role == "review":
        canonical_value = _canonicalize_graph_review_v12_result(value)
    elif schema_id == "legacy-item-extraction-result@1.0" and role == "support":
        canonical_value = _canonicalize_legacy_item_extraction_result(value)
    elif schema_id == "external-item-learning-result@1.0" and role == "support":
        canonical_value = _canonicalize_external_item_learning_result(value)
    elif schema_id == "external-item-learning-result@2.0" and role == "support":
        canonical_value = _canonicalize_external_item_learning_result_v2(value)
    elif schema_id == "legacy-item-editorial-compatibility-result@1.0" and role == "support":
        canonical_value = _canonicalize_legacy_editorial_compatibility_result(value)
    elif schema_id == "item-inference-transfer-pair-result@1.1" and role == "support":
        canonical_value = _canonicalize_inference_transfer_pair_result_v11(value)
    elif (
        schema_id
        in {
            "pdf-document-review-result@1.0",
            "pdf-document-review-result@2.0",
            "pdf-document-review-result@3.0",
            "pdf-document-review-result@4.0",
            "pdf-document-review-result@5.0",
            "pdf-document-review-result@6.0",
        }
        and role == "support"
    ):
        canonical_value = _canonicalize_pdf_document_review_result(value)
    if (
        schema_id
        in {
            "authoring-result@10.0",
            "authoring-result@11.0",
            "authoring-result@12.0",
        }
        and role == "authoring"
    ):
        if not isinstance(canonical_value, dict):
            raise WorkflowSchemaError("content-team authoring result is not an object")
        output = canonical_value.get("output")
        draft = output.get("draft") if isinstance(output, dict) else None
        validate_schema_message(
            _content_team_editorial_material_schema(),
            draft,
            "content-team-editorial-material/1.0",
        )
    elif (
        schema_id
        in {
            "image-result@10.0",
            "image-result@11.0",
            "image-result@12.0",
        }
        and role == "image"
    ):
        validate_schema_message(
            _content_team_image_route_schema(),
            canonical_value,
            "content-team-image-route/1.0",
        )
    validate_schema_message(_role_result_schema(schema_id), canonical_value, schema_id)
    if schema_id == "knowledge-analysis-proposal-result@9.0" and role == "support":
        canonical_value = _filter_invalid_knowledge_analysis_v9_edges(canonical_value)
    elif (
        schema_id
        in {
            "knowledge-analysis-proposal-result@10.0",
            "knowledge-analysis-proposal-result@11.0",
        }
        and role == "support"
    ):
        canonical_value = _canonicalize_knowledge_analysis_solution_result(canonical_value)
    try:
        if schema_id == "authoring-result@4.0" and role == "authoring":
            return GeneratedAuthoringRoleResultV4.model_validate(value)
        if schema_id == "image-result@4.0" and role == "image":
            return GeneratedImageRoleResultV4.model_validate(value)
        if schema_id == "review-result@4.0" and role == "review":
            return GeneratedReviewRoleResultV4.model_validate(value)
        if schema_id == "registration-result@4.0" and role == "item_management":
            return GeneratedRegistrationRoleResultV4.model_validate(value)
        if schema_id == "authoring-result@5.0" and role == "authoring":
            return GeneratedAuthoringRoleResultV5.model_validate(value)
        if schema_id == "image-result@5.0" and role == "image":
            return GeneratedImageRoleResultV5.model_validate(value)
        if schema_id == "review-result@5.0" and role == "review":
            return GeneratedReviewRoleResultV5.model_validate(value)
        if schema_id == "registration-result@5.0" and role == "item_management":
            return GeneratedRegistrationRoleResultV5.model_validate(value)
        if schema_id == "authoring-result@6.0" and role == "authoring":
            return GeneratedAuthoringRoleResultV6.model_validate(value)
        if schema_id == "image-result@6.0" and role == "image":
            return GeneratedImageRoleResultV6.model_validate(value)
        if schema_id == "review-result@6.0" and role == "review":
            return GeneratedReviewRoleResultV6.model_validate(value)
        if schema_id == "registration-result@6.0" and role == "item_management":
            return GeneratedRegistrationRoleResultV6.model_validate(value)
        if schema_id == "authoring-result@7.0" and role == "authoring":
            return ContentTeamAuthoringRoleResultV7.model_validate(canonical_value)
        if schema_id == "review-result@7.0" and role == "review":
            return ContentTeamReviewRoleResultV7.model_validate(value)
        if schema_id == "registration-result@7.0" and role == "item_management":
            return ContentTeamRegistrationRoleResultV7.model_validate(value)
        if schema_id == "authoring-result@8.0" and role == "authoring":
            return ContentTeamAuthoringRoleResultV8.model_validate(canonical_value)
        if schema_id == "image-result@8.0" and role == "image":
            return ContentTeamImageRoleResultV8.model_validate(value)
        if schema_id == "review-result@8.0" and role == "review":
            return ContentTeamReviewRoleResultV8.model_validate(value)
        if schema_id == "registration-result@8.0" and role == "item_management":
            return ContentTeamRegistrationRoleResultV8.model_validate(value)
        if schema_id == "authoring-result@9.0" and role == "authoring":
            return ContentTeamAuthoringRoleResultV9.model_validate(canonical_value)
        if schema_id == "image-result@9.0" and role == "image":
            return ContentTeamImageRoleResultV9.model_validate(value)
        if schema_id == "review-result@9.0" and role == "review":
            return ContentTeamReviewRoleResultV9.model_validate(value)
        if schema_id == "registration-result@9.0" and role == "item_management":
            return ContentTeamRegistrationRoleResultV9.model_validate(value)
        if schema_id == "authoring-result@10.0" and role == "authoring":
            return ContentTeamAuthoringRoleResultV10.model_validate(canonical_value)
        if schema_id == "image-result@10.0" and role == "image":
            return ContentTeamImageRoleResultV10.model_validate(value)
        if schema_id == "review-result@10.0" and role == "review":
            return ContentTeamReviewRoleResultV10.model_validate(canonical_value)
        if schema_id == "registration-result@10.0" and role == "item_management":
            return ContentTeamRegistrationRoleResultV10.model_validate(value)
        if schema_id == "authoring-result@11.0" and role == "authoring":
            return ContentTeamAuthoringRoleResultV11.model_validate(canonical_value)
        if schema_id == "image-result@11.0" and role == "image":
            return ContentTeamImageRoleResultV11.model_validate(value)
        if schema_id == "review-result@11.0" and role == "review":
            return ContentTeamReviewRoleResultV11.model_validate(canonical_value)
        if schema_id == "registration-result@11.0" and role == "item_management":
            return ContentTeamRegistrationRoleResultV11.model_validate(value)
        if schema_id == "authoring-result@12.0" and role == "authoring":
            return ContentTeamAuthoringRoleResultV12.model_validate(canonical_value)
        if schema_id == "image-result@12.0" and role == "image":
            return ContentTeamImageRoleResultV12.model_validate(value)
        if schema_id == "review-result@12.0" and role == "review":
            return ContentTeamReviewRoleResultV12.model_validate(canonical_value)
        if schema_id == "registration-result@12.0" and role == "item_management":
            return ContentTeamRegistrationRoleResultV12.model_validate(value)
        if schema_id == "knowledge-analysis-proposal-result@1.0" and role == "support":
            return KnowledgeAnalysisProposalRoleResult.model_validate(value)
        if schema_id == "knowledge-analysis-proposal-result@2.0" and role == "support":
            return KnowledgeAnalysisProposalRoleResultV2.model_validate(value)
        if schema_id == "knowledge-analysis-proposal-result@3.0" and role == "support":
            return KnowledgeAnalysisProposalRoleResultV3.model_validate(value)
        if schema_id == "knowledge-analysis-proposal-result@4.0" and role == "support":
            return KnowledgeAnalysisProposalRoleResultV4.model_validate(value)
        if schema_id == "knowledge-analysis-proposal-result@5.0" and role == "support":
            return KnowledgeAnalysisProposalRoleResultV5.model_validate(value)
        if schema_id == "knowledge-analysis-proposal-result@6.0" and role == "support":
            return KnowledgeAnalysisProposalRoleResultV6.model_validate(value)
        if schema_id == "knowledge-analysis-proposal-result@7.0" and role == "support":
            return KnowledgeAnalysisProposalRoleResultV7.model_validate(value)
        if schema_id == "knowledge-analysis-proposal-result@8.0" and role == "support":
            return KnowledgeAnalysisProposalRoleResultV8.model_validate(value)
        if schema_id == "knowledge-analysis-proposal-result@9.0" and role == "support":
            return KnowledgeAnalysisProposalRoleResultV9.model_validate(canonical_value)
        if schema_id == "knowledge-analysis-proposal-result@10.0" and role == "support":
            return KnowledgeAnalysisProposalRoleResultV10.model_validate(canonical_value)
        if schema_id == "knowledge-analysis-proposal-result@11.0" and role == "support":
            return KnowledgeAnalysisProposalRoleResultV11.model_validate(canonical_value)
        if schema_id == "legacy-item-extraction-result@1.0" and role == "support":
            return LegacyItemExtractionRoleResult.model_validate(canonical_value)
        if schema_id == "external-item-learning-result@1.0" and role == "support":
            return ExternalItemLearningRoleResult.model_validate(canonical_value)
        if schema_id == "external-item-learning-result@2.0" and role == "support":
            return ExternalItemLearningRoleResultV2.model_validate(canonical_value)
        if schema_id == "legacy-item-editorial-compatibility-result@1.0" and role == "support":
            return LegacyItemEditorialCompatibilityRoleResult.model_validate(canonical_value)
        if schema_id == "customer-support-result@1.0" and role == "support":
            return CustomerSupportRoleResult.model_validate(canonical_value)
        if schema_id == "item-inference-transfer-pair-result@1.0" and role == "support":
            return InferenceTransferPairRoleResult.model_validate(canonical_value)
        if schema_id == "item-inference-transfer-pair-result@1.1" and role == "support":
            return InferenceTransferPairRoleResultV11.model_validate(canonical_value)
        if schema_id == "pdf-document-review-result@1.0" and role == "support":
            return PdfDocumentReviewRoleResult.model_validate(canonical_value)
        if schema_id == "pdf-document-review-result@4.0" and role == "support":
            return PdfDocumentReviewRoleResultV4.model_validate(canonical_value)
        if schema_id == "pdf-document-review-result@5.0" and role == "support":
            return PdfDocumentReviewRoleResultV5.model_validate(canonical_value)
        if schema_id == "pdf-document-review-result@2.0" and role == "support":
            return PairedDocumentReviewRoleResult.model_validate(canonical_value)
        if schema_id == "pdf-document-review-result@3.0" and role == "support":
            return PairedDocumentReviewRoleResultV3.model_validate(canonical_value)
        if schema_id == "pdf-document-review-result@6.0" and role == "support":
            return PairedDocumentReviewRoleResultV4.model_validate(canonical_value)
        if schema_id == "authoring-result@3.0" and role == "authoring":
            return GeneratedAuthoringRoleResult.model_validate(value)
        if schema_id == "image-result@3.0" and role == "image":
            return GeneratedImageRoleResult.model_validate(value)
        if schema_id == "review-result@3.0" and role == "review":
            return GeneratedReviewRoleResult.model_validate(value)
        if schema_id == "registration-result@3.0" and role == "item_management":
            return GeneratedRegistrationRoleResult.model_validate(value)
        if schema_id == "authoring-result@2.0" and role == "authoring":
            return KnowledgeAuthoringRoleResult.model_validate(value)
        if schema_id == "image-result@2.0" and role == "image":
            return KnowledgeImageRoleResult.model_validate(value)
        if schema_id == "review-result@2.0" and role == "review":
            return KnowledgeReviewRoleResult.model_validate(value)
        if schema_id == "registration-result@2.0" and role == "item_management":
            return KnowledgeRegistrationRoleResult.model_validate(value)
        if schema_id == "authoring-result@1.0" and role == "authoring":
            return AuthoringRoleResult.model_validate(value)
        if schema_id == "image-result@1.0" and role == "image":
            return ImageRoleResult.model_validate(value)
        if schema_id == "review-result@1.0" and role == "review":
            return ReviewRoleResult.model_validate(value)
        if schema_id == "registration-result@1.0" and role == "item_management":
            return RegistrationRoleResult.model_validate(value)
        raise WorkflowSchemaError(f"result schema does not match worker role: {schema_id}")
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_context=False, include_input=False)
        first = errors[0] if errors else None
        if first is None:
            detail = ""
        else:
            location = ".".join(str(part) for part in first["loc"]) or "$"
            detail = f" at {location}: {first['msg']}"
        raise WorkflowSchemaError(f"{schema_id} failed typed validation{detail}") from exc


def _derive_content_team_visual_layout(draft: dict[str, Any]) -> str:
    inquiry = draft.get("inquiry")
    visuals = draft.get("visuals")
    if not isinstance(visuals, list):
        raise WorkflowSchemaError("content-team projected visuals are invalid")
    if inquiry is not None:
        if visuals:
            raise WorkflowSchemaError("content-team inquiry cannot include general visual slots")
        return "INQUIRY_BOX"

    signature_items: list[tuple[str, str]] = []
    for visual in visuals:
        if not isinstance(visual, dict):
            raise WorkflowSchemaError("content-team projected visual entry is invalid")
        kind = visual.get("kind")
        label = visual.get("label")
        if not isinstance(kind, str) or not isinstance(label, str):
            raise WorkflowSchemaError("content-team projected visual identity is invalid")
        signature_items.append((kind, label))
    layouts: dict[tuple[tuple[str, str], ...], str] = {
        (): "NONE",
        (("IMAGE", ""),): "IMAGE_ONLY",
        (("TABLE", ""),): "TABLE_ONLY",
        (("IMAGE", ""), ("TABLE", "")): "IMAGE_TABLE",
        (("TABLE", ""), ("IMAGE", "")): "TABLE_IMAGE",
        (("IMAGE", "(가)"), ("IMAGE", "(나)")): "IMAGE_IMAGE",
        (("TABLE", "(가)"), ("TABLE", "(나)")): "TABLE_TABLE",
    }
    derived_layout = layouts.get(tuple(signature_items))
    if derived_layout is None:
        raise WorkflowSchemaError("content-team projected visual order is not canonical")
    return derived_layout


def _canonicalize_content_team_authoring_result(
    value: object,
    *,
    schema_id: str,
) -> object:
    """Canonicalize source-format fields and prove the draft is editor-materializable."""

    if not isinstance(value, dict):
        return value
    output = value.get("output")
    if not isinstance(output, dict):
        return value
    draft = output.get("draft")
    if not isinstance(draft, dict):
        return value

    projected = "visual_layout" not in draft
    derived_layout: str | None = None
    if projected:
        validate_schema_message(
            load_codex_result_schema(schema_id),
            value,
            f"{schema_id} projected",
        )
        derived_layout = _derive_content_team_visual_layout(draft)

    canonical = copy.deepcopy(value)
    canonical_output = _mapping(canonical, "output")
    canonical_draft = _mapping(canonical_output, "draft")
    for key, item in tuple(canonical_draft.items()):
        if key != "equation_sources":
            canonical_draft[key] = _normalize_content_team_math_values(item)
    labeled_blocks = canonical_draft.get("labeled_blocks")
    typed_labeled_blocks: tuple[ContentTeamLabeledBlock, ...] = ()
    if isinstance(labeled_blocks, list):
        for block in labeled_blocks:
            if isinstance(block, dict) and isinstance(block.get("content"), str):
                block["content"] = normalize_content_team_labeled_block_content(block["content"])
        with suppress(ValidationError):
            typed_labeled_blocks = tuple(
                ContentTeamLabeledBlock.model_validate(block) for block in labeled_blocks
            )
    item_number = canonical_draft.get("item_number")
    stem = canonical_draft.get("stem")
    if isinstance(item_number, int) and isinstance(stem, str):
        normalized_stem = normalize_content_team_stem(item_number, stem)
        statements = canonical_draft.get("statements")
        if isinstance(statements, list):
            normalized_stem = normalize_content_team_statement_marker(
                normalized_stem,
                has_statements=bool(statements),
            )
        normalized_stem = normalize_content_team_labeled_block_projection(
            normalized_stem,
            labeled_blocks=typed_labeled_blocks,
        )
        canonical_draft["stem"] = normalized_stem
    score_display = canonical_draft.get("score_display")
    bottom_stem = canonical_draft.get("bottom_stem")
    if isinstance(score_display, str) and isinstance(bottom_stem, str):
        canonical_draft["bottom_stem"] = normalize_content_team_bottom_stem(
            score_display, bottom_stem
        )
    answer = canonical_draft.get("answer")
    if isinstance(answer, dict):
        number = answer.get("number")
        answer_content = answer.get("answer_content")
        raw_line = answer.get("raw_line")
        if (
            isinstance(number, str)
            and isinstance(answer_content, str)
            and isinstance(raw_line, str)
        ):
            answer["raw_line"] = normalize_content_team_answer_line(
                number,
                answer_content,
                raw_line,
            )
    _normalize_evidence_usage_order(canonical_output)
    if projected:
        canonical_draft["visual_layout"] = derived_layout
    canonical_draft["equation_sources"] = []
    try:
        preliminary: (
            ContentTeamAuthoringRoleResultV7
            | ContentTeamAuthoringRoleResultV8
            | ContentTeamAuthoringRoleResultV9
            | ContentTeamAuthoringRoleResultV10
            | ContentTeamAuthoringRoleResultV11
            | ContentTeamAuthoringRoleResultV12
        )
        if schema_id == "authoring-result@7.0":
            preliminary = ContentTeamAuthoringRoleResultV7.model_validate(canonical)
        elif schema_id == "authoring-result@8.0":
            preliminary = ContentTeamAuthoringRoleResultV8.model_validate(canonical)
        elif schema_id == "authoring-result@9.0":
            preliminary = ContentTeamAuthoringRoleResultV9.model_validate(canonical)
        elif schema_id == "authoring-result@10.0":
            preliminary = ContentTeamAuthoringRoleResultV10.model_validate(canonical)
        elif schema_id == "authoring-result@11.0":
            preliminary = ContentTeamAuthoringRoleResultV11.model_validate(canonical)
        else:
            preliminary = ContentTeamAuthoringRoleResultV12.model_validate(canonical)
        canonical_draft["equation_sources"] = list(
            derive_content_team_equation_sources(preliminary.output.draft)
        )
        validated: (
            ContentTeamAuthoringRoleResultV7
            | ContentTeamAuthoringRoleResultV8
            | ContentTeamAuthoringRoleResultV9
            | ContentTeamAuthoringRoleResultV10
            | ContentTeamAuthoringRoleResultV11
            | ContentTeamAuthoringRoleResultV12
        )
        if schema_id == "authoring-result@7.0":
            validated = ContentTeamAuthoringRoleResultV7.model_validate(canonical)
        elif schema_id == "authoring-result@8.0":
            validated = ContentTeamAuthoringRoleResultV8.model_validate(canonical)
        elif schema_id == "authoring-result@9.0":
            validated = ContentTeamAuthoringRoleResultV9.model_validate(canonical)
        elif schema_id == "authoring-result@10.0":
            validated = ContentTeamAuthoringRoleResultV10.model_validate(canonical)
        elif schema_id == "authoring-result@11.0":
            validated = ContentTeamAuthoringRoleResultV11.model_validate(canonical)
        else:
            validated = ContentTeamAuthoringRoleResultV12.model_validate(canonical)
        serialize_content_team_markdown(validated.output.draft)
    except ValidationError as exc:
        raise WorkflowSchemaError(f"{schema_id} failed typed validation") from exc
    except ContentTeamMarkdownError as exc:
        raise WorkflowSchemaError(
            f"{schema_id} cannot be materialized by the content-team profile"
        ) from exc
    return canonical


def _normalize_evidence_usage_order(output: dict[str, Any]) -> None:
    """Sort semantically unordered evidence members without hiding duplicates or bad values."""

    usage = output.get("evidence_usage")
    if not isinstance(usage, dict):
        return
    citations = usage.get("citations")
    if not isinstance(citations, list):
        return
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        for field_name in ("anchor_ids", "draft_json_paths"):
            values = citation.get(field_name)
            if (
                isinstance(values, list)
                and all(isinstance(value, str) for value in values)
                and len(values) == len(set(values))
            ):
                values.sort()
    evidence_ids = tuple(
        citation.get("evidence_id") if isinstance(citation, dict) else None
        for citation in citations
    )
    if all(isinstance(evidence_id, str) for evidence_id in evidence_ids) and len(
        evidence_ids
    ) == len(set(evidence_ids)):
        citations.sort(key=lambda citation: citation["evidence_id"])


def _canonicalize_graph_review_v11_result(value: object) -> object:
    """Order bounded set-like review members without repairing identities or values."""

    if not isinstance(value, dict):
        return value
    canonical = copy.deepcopy(value)
    output = canonical.get("output")
    if not isinstance(output, dict):
        return canonical
    attestation = output.get("evidence_usage_attestation")
    if isinstance(attestation, dict):
        citations = attestation.get("citations")
        if isinstance(citations, list):
            for citation in citations:
                if isinstance(citation, dict):
                    for field_name in ("anchor_ids", "draft_json_paths"):
                        _sort_unique_strings(citation.get(field_name))
            _sort_dicts_by_unique_string(citations, "evidence_id")

    report = output.get("independent_review_report")
    if not isinstance(report, dict):
        return canonical
    references = report.get("evidence_references")
    if isinstance(references, list):
        for reference in references:
            if isinstance(reference, dict):
                _sort_unique_strings(reference.get("anchor_ids"))
                _sort_unique_strings(reference.get("purposes"))
        _sort_dicts_by_unique_string(references, "evidence_id")

    answer_review = report.get("answer_review")
    if isinstance(answer_review, dict):
        claims = answer_review.get("claims")
        if isinstance(claims, list):
            for claim in claims:
                if isinstance(claim, dict):
                    _sort_unique_strings(claim.get("draft_json_paths"))
                    _sort_unique_strings(claim.get("evidence_ids"))
            _sort_dicts_by_unique_string(claims, "claim_key")

    choice_order = {value: index for index, value in enumerate(("①", "②", "③", "④", "⑤"))}
    choices = report.get("choice_diagnostics")
    if isinstance(choices, list):
        for choice in choices:
            if isinstance(choice, dict):
                _sort_unique_strings(choice.get("draft_json_paths"))
                _sort_unique_strings(choice.get("evidence_ids"))
        if len({choice.get("number") for choice in choices if isinstance(choice, dict)}) == len(
            choices
        ):
            choices.sort(
                key=lambda choice: (
                    choice_order.get(str(choice.get("number")), len(choice_order))
                    if isinstance(choice, dict)
                    else len(choice_order)
                )
            )

    statement_order = {value: index for index, value in enumerate(("ㄱ", "ㄴ", "ㄷ"))}
    statements = report.get("statement_diagnostics")
    if isinstance(statements, list):
        for statement in statements:
            if isinstance(statement, dict):
                _sort_unique_strings(statement.get("draft_json_paths"))
                _sort_unique_strings(statement.get("evidence_ids"))
        if len(
            {statement.get("label") for statement in statements if isinstance(statement, dict)}
        ) == len(statements):
            statements.sort(
                key=lambda statement: (
                    statement_order.get(str(statement.get("label")), len(statement_order))
                    if isinstance(statement, dict)
                    else len(statement_order)
                )
            )

    for field_name in (
        "explanation_assessment",
        "curriculum_assessment",
        "originality_assessment",
        "visual_assessment",
    ):
        assessment = report.get(field_name)
        if isinstance(assessment, dict):
            _sort_unique_strings(assessment.get("draft_json_paths"))
            _sort_unique_strings(assessment.get("evidence_ids"))
    return canonical


def _canonicalize_graph_review_v12_result(value: object) -> object:
    """Extend V11 canonical ordering to verification targets, candidates, and reasons."""

    canonical = _canonicalize_graph_review_v11_result(value)
    if not isinstance(canonical, dict):
        return canonical
    output = canonical.get("output")
    report = output.get("independent_review_report") if isinstance(output, dict) else None
    if not isinstance(report, dict):
        return canonical
    targets = report.get("verification_targets")
    if isinstance(targets, list):
        for target in targets:
            if isinstance(target, dict):
                for field_name in (
                    "draft_json_paths",
                    "verification_terms",
                    "required_source_classes",
                    "selected_evidence_ids",
                ):
                    _sort_unique_strings(target.get(field_name))
        _sort_dicts_by_unique_string(targets, "target_id")
    candidates = report.get("candidate_findings")
    if isinstance(candidates, list):
        for candidate in candidates:
            if isinstance(candidate, dict):
                _sort_unique_strings(candidate.get("draft_json_paths"))
                _sort_unique_strings(candidate.get("evidence_ids"))
        _sort_dicts_by_unique_string(candidates, "candidate_id")
    assessment = report.get("escalation_assessment")
    if isinstance(assessment, dict):
        _sort_unique_strings(assessment.get("reason_codes"))
    return canonical


def _sort_unique_strings(value: object) -> None:
    if (
        isinstance(value, list)
        and all(isinstance(item, str) for item in value)
        and len(value) == len(set(value))
    ):
        value.sort()


def _sort_dicts_by_unique_string(values: list[object], field_name: str) -> None:
    keys = tuple(value.get(field_name) if isinstance(value, dict) else None for value in values)
    if all(isinstance(key, str) for key in keys) and len(keys) == len(set(keys)):
        values.sort(key=lambda value: value[field_name] if isinstance(value, dict) else "")


def _normalize_content_team_math_values(value: object) -> object:
    if isinstance(value, str):
        return normalize_content_team_inline_math(value)
    if isinstance(value, list):
        return [_normalize_content_team_math_values(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_content_team_math_values(item) for key, item in value.items()}
    return value


def _canonicalize_legacy_editorial_compatibility_result(value: object) -> object:
    """Derive the immutable proposal hash at the trusted validation boundary."""

    if not isinstance(value, dict):
        return value
    output = value.get("output")
    if not isinstance(output, dict):
        return value
    proposal = output.get("proposal")
    if not isinstance(proposal, dict):
        return value

    canonical = copy.deepcopy(value)
    canonical_output = _mapping(canonical, "output")
    canonical_proposal = _mapping(canonical_output, "proposal")
    canonical_proposal["proposal_sha256"] = content_sha256(
        {key: item for key, item in canonical_proposal.items() if key != "proposal_sha256"}
    )
    return canonical


def _canonicalize_inference_transfer_pair_result_v11(value: object) -> object:
    """Serialize unique claim-reference sets and derive only an omitted self-hash.

    The worker owns comparison content, object order and reference membership. The Orchestrator
    owns canonical set ordering and its hash. Supplied hashes bypass all normalization.
    """

    if not isinstance(value, dict):
        return value
    output = value.get("output")
    if not isinstance(output, dict) or "result_sha256" in output:
        return value

    canonical = value.copy()
    canonical_output = output.copy()
    canonical["output"] = canonical_output
    claim_ids = TypeAdapter(list[ClaimId])
    for collection_name in ("axes", "mappings", "differences", "new_reasoning"):
        collection = output.get(collection_name)
        if not isinstance(collection, list):
            continue
        canonical_collection = None
        for index, member in enumerate(collection):
            if not isinstance(member, dict):
                continue
            canonical_member = None
            for side in ("left_claim_ids", "right_claim_ids"):
                references = member.get(side)
                if not isinstance(references, list) or len(references) > 16:
                    continue
                try:
                    checked = claim_ids.validate_python(references, strict=True)
                except ValidationError:
                    continue
                # A duplicate is invalid input, not permission to remove a reference.
                if len(checked) != len(set(checked)):
                    continue
                ordered = sorted(checked)
                if ordered == references:
                    continue
                if canonical_member is None:
                    canonical_member = member.copy()
                canonical_member[side] = ordered
            if canonical_member is not None:
                if canonical_collection is None:
                    canonical_collection = collection.copy()
                canonical_collection[index] = canonical_member
        if canonical_collection is not None:
            canonical_output[collection_name] = canonical_collection
    canonical_output["result_sha256"] = content_sha256(canonical_output)
    return canonical


def _canonicalize_pdf_document_review_result(value: object) -> object:
    """Derive omitted quote hashes without repairing a supplied mismatch.

    The worker authors the exact quote and page location.  The orchestrator owns the canonical
    serialization hash, so the worker-only schema omits ``quote_sha256``.  A caller that supplies
    the field remains accountable for it: an incorrect supplied digest is left untouched and the
    canonical Pydantic boundary rejects it.
    """

    if not isinstance(value, dict):
        return value
    output = value.get("output")
    if not isinstance(output, dict):
        return value

    canonical = copy.deepcopy(value)
    canonical_output = _mapping(canonical, "output")
    collection_names = ("verification_targets", "candidate_findings", "findings")
    for collection_name in collection_names:
        collection = canonical_output.get(collection_name)
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict):
                continue
            anchors = item.get("anchors")
            if not isinstance(anchors, list):
                continue
            for anchor in anchors:
                if not isinstance(anchor, dict) or "quote_sha256" in anchor:
                    continue
                quote = anchor.get("quote")
                if quote is None:
                    anchor["quote_sha256"] = None
                elif isinstance(quote, str):
                    anchor["quote_sha256"] = content_sha256(quote)
    cross_checks = canonical_output.get("cross_document_checks")
    if isinstance(cross_checks, list):
        for check in cross_checks:
            if not isinstance(check, dict):
                continue
            for anchor_key in ("question_anchors", "solution_anchors"):
                anchors = check.get(anchor_key)
                if not isinstance(anchors, list):
                    continue
                for anchor in anchors:
                    if not isinstance(anchor, dict) or "quote_sha256" in anchor:
                        continue
                    quote = anchor.get("quote")
                    anchor["quote_sha256"] = (
                        content_sha256(quote) if isinstance(quote, str) else None
                    )
    textbook_usage = canonical_output.get("textbook_usage")
    if isinstance(textbook_usage, dict) and "usage_sha256" not in textbook_usage:
        textbook_usage["usage_sha256"] = content_sha256(textbook_usage)
    return canonical


def _canonicalize_legacy_item_extraction_result(value: object) -> object:
    """Derive the extraction self-hash at the trusted validation boundary.

    Workers author the semantic extraction document. The orchestrator owns its canonical
    serialization identity, so an untrusted model-provided digest is never authoritative.
    """

    if not isinstance(value, dict):
        return value
    output = value.get("output")
    if not isinstance(output, dict):
        return value
    extraction_result = output.get("extraction_result")
    if not isinstance(extraction_result, dict):
        return value

    canonical = copy.deepcopy(value)
    canonical_output = _mapping(canonical, "output")
    canonical_result = _mapping(canonical_output, "extraction_result")
    _normalize_duplicate_legacy_source_anchor_ids(canonical_result)
    canonical_result["result_sha256"] = content_sha256(
        {key: item for key, item in canonical_result.items() if key != "result_sha256"}
    )
    return canonical


def _canonicalize_external_item_learning_result(value: object) -> object:
    """Derive an omitted proposal hash, but never replace an incorrect supplied hash."""

    if not isinstance(value, dict):
        return value
    output = value.get("output")
    result = output.get("learning_result") if isinstance(output, dict) else None
    if not isinstance(result, dict) or "result_sha256" in result:
        return value
    canonical = copy.deepcopy(value)
    learning_result = _mapping(_mapping(canonical, "output"), "learning_result")
    learning_result["result_sha256"] = content_sha256(learning_result)
    return canonical


def _canonicalize_external_item_learning_result_v2(value: object) -> object:
    """Normalize source defaults before stamping; never repair an existing hash."""
    from eom_catalog_contracts.external_item_learning_result_v2 import (
        stamp_external_item_learning_result_v2,
    )

    if not isinstance(value, dict):
        return value
    output = value.get("output")
    result = output.get("learning_result") if isinstance(output, dict) else None
    if not isinstance(result, dict) or "result_sha256" in result:
        return value
    try:
        stamped = stamp_external_item_learning_result_v2(result)
    except ValueError as exc:
        raise WorkflowSchemaError("creative source successor body is invalid") from exc
    canonical = copy.deepcopy(value)
    _mapping(canonical, "output")["learning_result"] = stamped.model_dump(mode="json")
    return canonical


def _normalize_duplicate_legacy_source_anchor_ids(
    extraction_result: dict[str, Any],
) -> None:
    """Repair only ambiguous local IDs while preserving every source pointer.

    Structured Outputs cannot express array-wide uniqueness.  If a model reuses one local
    ``anchor_id`` for distinct source anchors, assign deterministic result-owned IDs and expand
    each reference to the complete corresponding anchor set.  No source evidence is removed or
    guessed; malformed or dangling references remain for the canonical validator to reject.
    """

    items = extraction_result.get("items")
    if not isinstance(items, list):
        return
    reference_collections = (
        "content_anchor_map",
        "curriculum_observations",
        "linguistic_patterns",
        "visual_patterns",
        "metadata_observations",
        "conflicts",
    )
    for item_index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        anchors = item.get("source_anchors")
        if not isinstance(anchors, list):
            continue
        counts: dict[str, int] = {}
        for anchor in anchors:
            if isinstance(anchor, dict) and isinstance(anchor.get("anchor_id"), str):
                anchor_id = anchor["anchor_id"]
                counts[anchor_id] = counts.get(anchor_id, 0) + 1
        duplicated = {anchor_id for anchor_id, count in counts.items() if count > 1}
        if not duplicated:
            continue

        replacements: dict[str, list[str]] = {}
        used = {anchor_id for anchor_id, count in counts.items() if count == 1}
        for anchor_index, anchor in enumerate(anchors):
            if not isinstance(anchor, dict):
                continue
            original_id = anchor.get("anchor_id")
            if not isinstance(original_id, str) or original_id not in duplicated:
                continue
            identity = {
                "protocol": "legacy-source-anchor-local-id-normalization/1.0",
                "item_index": item_index,
                "item_proposal_id": item.get("item_proposal_id"),
                "anchor_index": anchor_index,
                "source_anchor": {
                    key: item_value for key, item_value in anchor.items() if key != "anchor_id"
                },
            }
            candidate = "assessmentanchor_" + content_sha256(identity).removeprefix("sha256:")[:32]
            if candidate in used:  # pragma: no cover - cryptographic collision guard
                identity["collision_ordinal"] = anchor_index
                candidate = (
                    "assessmentanchor_" + content_sha256(identity).removeprefix("sha256:")[:32]
                )
            used.add(candidate)
            anchor["anchor_id"] = candidate
            replacements.setdefault(original_id, []).append(candidate)

        for collection_name in reference_collections:
            collection = item.get(collection_name)
            if not isinstance(collection, list):
                continue
            for observation in collection:
                if not isinstance(observation, dict):
                    continue
                source_anchor_ids = observation.get("source_anchor_ids")
                if not isinstance(source_anchor_ids, list):
                    continue
                expanded: list[object] = []
                for anchor_id in source_anchor_ids:
                    values: list[object] = (
                        list(replacements[anchor_id])
                        if isinstance(anchor_id, str) and anchor_id in replacements
                        else [anchor_id]
                    )
                    for reference_id in values:
                        if reference_id not in expanded:
                            expanded.append(reference_id)
                observation["source_anchor_ids"] = expanded


def _bind_solution_id_array(
    field_schema: dict[str, Any],
    allowed_ids: tuple[str, ...],
    *,
    field_name: str,
) -> None:
    """Constrain one report reference array to the exact immutable request index."""

    items = _mapping(field_schema, "items")
    if allowed_ids:
        items["enum"] = list(allowed_ids)
        return
    if int(field_schema.get("minItems", 0)) > 0:
        raise WorkflowSchemaError(f"solution reference index has no values for {field_name}")
    field_schema["maxItems"] = 0


def _bind_solution_reference_index(
    report_properties: dict[str, Any],
    request: KnowledgeAnalysisRequestV10 | KnowledgeAnalysisRequestV11,
) -> None:
    """Project the exact accepted base's node/anchor index into the full-report schema."""

    index = request.base_analysis.reference_index
    node_ids = tuple(sorted(node.node_id for node in index.nodes))
    item_element_ids = tuple(
        sorted(node.node_id for node in index.nodes if node.node_type == "ITEM_ELEMENT")
    )
    concept_ids = tuple(
        sorted(
            node.node_id
            for node in index.nodes
            if node.node_type in {"CONCEPT", "PROCESS", "OBSERVABLE_PROPERTY", "FORMULA"}
        )
    )
    assessment_pattern_ids = tuple(
        sorted(node.node_id for node in index.nodes if node.node_type == "ASSESSMENT_PATTERN")
    )
    all_anchor_ids = tuple(sorted(index.anchor_ids))
    problem_anchor_ids = tuple(sorted(index.problem_anchor_ids))
    answer_anchor_ids = tuple(sorted(index.answer_explanation_anchor_ids))

    steps = _mapping(report_properties, "solution_steps")
    step_properties = _mapping(_mapping(steps, "items"), "properties")
    _bind_solution_id_array(
        _mapping(step_properties, "node_ids"), node_ids, field_name="solution_steps.node_ids"
    )
    _bind_solution_id_array(
        _mapping(step_properties, "item_element_node_ids"),
        item_element_ids,
        field_name="solution_steps.item_element_node_ids",
    )
    _bind_solution_id_array(
        _mapping(step_properties, "anchor_ids"),
        problem_anchor_ids,
        field_name="solution_steps.anchor_ids",
    )

    links = _mapping(report_properties, "concept_assessment_links")
    link_properties = _mapping(_mapping(links, "items"), "properties")
    concept_node = _mapping(link_properties, "concept_node_id")
    if not concept_ids:
        raise WorkflowSchemaError("solution reference index has no concept-like node")
    concept_node["enum"] = list(concept_ids)
    _bind_solution_id_array(
        _mapping(link_properties, "assessment_pattern_node_ids"),
        assessment_pattern_ids,
        field_name="concept_assessment_links.assessment_pattern_node_ids",
    )
    _bind_solution_id_array(
        _mapping(link_properties, "item_element_node_ids"),
        item_element_ids,
        field_name="concept_assessment_links.item_element_node_ids",
    )

    choices = _mapping(report_properties, "choice_diagnostics")
    choice_properties = _mapping(_mapping(choices, "items"), "properties")
    _bind_solution_id_array(
        _mapping(choice_properties, "node_ids"),
        node_ids,
        field_name="choice_diagnostics.node_ids",
    )
    _bind_solution_id_array(
        _mapping(choice_properties, "anchor_ids"),
        all_anchor_ids,
        field_name="choice_diagnostics.anchor_ids",
    )

    comparison = _mapping(report_properties, "official_explanation_comparison")
    comparison_properties = _mapping(comparison, "properties")
    _bind_solution_id_array(
        _mapping(comparison_properties, "answer_explanation_anchor_ids"),
        answer_anchor_ids,
        field_name="official_explanation_comparison.answer_explanation_anchor_ids",
    )

    issues = _mapping(report_properties, "unresolved_issues")
    issue_properties = _mapping(_mapping(issues, "items"), "properties")
    _bind_solution_id_array(
        _mapping(issue_properties, "anchor_ids"),
        all_anchor_ids,
        field_name="unresolved_issues.anchor_ids",
    )


def _describe_document_review_result_order(definitions: dict[str, Any]) -> None:
    """Expose existing typed ordering rules without repairing worker attestations."""

    output = _mapping(_mapping(definitions, "output"), "properties")
    output["verification_targets"]["description"] = "Sort by target_id with no duplicates."
    output["candidate_findings"]["description"] = "Sort by candidate_id with no duplicates."
    output["findings"]["description"] = (
        "Match only CONFIRMED candidates in candidate_id order, exactly once each, and assign "
        "contiguous ordinals starting at 1. Keep finding IDs unique."
    )
    for definition in ("target", "candidate", "finding"):
        properties = _mapping(_mapping(definitions, definition), "properties")
        properties["anchors"]["description"] = (
            "Sort by anchor_id with no duplicates, using lexicographic ID order, not page or "
            "region order. Keep each anchor's location and content attached to its ID."
        )
    finding = _mapping(_mapping(definitions, "finding"), "properties")
    finding["anchors"]["description"] += (
        " Use the exact content and anchor_id order of the corresponding CONFIRMED candidate."
    )


def constrained_result_schema(
    schema_id: str,
    worker_input: RoleWorkerInput,
    *,
    evidence_access: Literal["NONE", "EVIDENCE_CONTEXT"] | None = None,
    resolved_evidence_plan: ResolvedExecutionPlanV3 | None = None,
    material_requirement: ContentTeamMaterialRequirement | None = None,
) -> dict[str, Any]:
    schema = load_codex_result_schema(schema_id)
    properties = _mapping(schema, "properties")
    for key, value in (
        ("job_id", worker_input.job_id),
        ("workflow_id", worker_input.workflow_id),
        ("step_run_id", worker_input.step_run_id),
    ):
        _mapping(properties, key)["const"] = value
    definitions = _mapping(schema, "$defs")
    artifact = definitions.get("artifact", definitions.get("ArtifactSpec"))
    if not isinstance(artifact, dict):
        raise WorkflowSchemaError("schema is missing artifact definition")
    artifact_properties = _mapping(artifact, "properties")
    _mapping(artifact_properties, "logical_artifact_id")["const"] = (
        worker_input.artifact.logical_artifact_id
    )
    _mapping(artifact_properties, "revision_id")["const"] = worker_input.artifact.revision_id
    _bind_evidence_result_branch(
        schema,
        schema_id=schema_id,
        evidence_access=evidence_access,
        resolved_evidence_plan=resolved_evidence_plan,
        material_requirement=material_requirement,
    )
    if schema_id in {
        "item-inference-transfer-pair-result@1.0",
        "item-inference-transfer-pair-result@1.1",
    }:
        if not isinstance(worker_input.request, InferenceTransferPairWorkerRequest):
            raise WorkflowSchemaError("inference-transfer result requires its typed request")
        is_v11 = schema_id == "item-inference-transfer-pair-result@1.1"
        if is_v11 != isinstance(worker_input.request, InferenceTransferPairWorkerRequestV11):
            raise WorkflowSchemaError(
                "inference-transfer result purpose differs from its exact request"
            )
        comparison = worker_input.request.comparison
        output = _mapping(
            definitions,
            "InferenceTransferPairResultV11" if is_v11 else "InferenceTransfer_pairResult",
        )
        output_properties = _mapping(output, "properties")
        for key, value in (
            ("request_id", comparison.request_id),
            ("request_sha256", comparison.request_sha256),
        ):
            _bind_result_string_const(schema, _mapping(output_properties, key), value)
        for key, identity_pointer in (
            ("left_profile", comparison.left_profile),
            ("right_profile", comparison.right_profile),
            ("rubric", comparison.rubric),
        ):
            field = _mapping(output_properties, key)
            reference = field.get("$ref")
            if not isinstance(reference, str) or not reference.startswith("#/$defs/"):
                raise WorkflowSchemaError("inference-transfer identity reference is invalid")
            resolved = copy.deepcopy(_mapping(definitions, reference.removeprefix("#/$defs/")))
            identity_properties = _mapping(resolved, "properties")
            for identity_key, identity_value in identity_pointer.model_dump(mode="json").items():
                _bind_result_string_const(
                    schema, _mapping(identity_properties, identity_key), str(identity_value)
                )
            output_properties[key] = resolved
        for name in ("InferenceTransfer_mapping", "InferenceTransfer_difference"):
            reference_properties = _mapping(_mapping(definitions, name), "properties")
            for key, claim_ids in (
                ("left_claim_ids", comparison.left_claim_ids),
                ("right_claim_ids", comparison.right_claim_ids),
            ):
                field = _mapping(reference_properties, key)
                if claim_ids:
                    field["items"] = {"type": "string", "enum": list(claim_ids)}
                else:
                    field["maxItems"] = 0
        if is_v11:
            axis = _mapping(
                _mapping(definitions, "InferenceTransferPairResultV11_axisAssessment"), "properties"
            )
            for key, claim_ids in (
                ("left_claim_ids", comparison.left_claim_ids),
                ("right_claim_ids", comparison.right_claim_ids),
            ):
                field = axis[key] = copy.deepcopy(
                    _mapping(definitions, "InferenceTransferPairResultV11_claimRefs")
                )
                if claim_ids:
                    field["items"] = {"type": "string", "enum": list(claim_ids)}
                else:
                    field["maxItems"] = 0
        _prune_unreferenced_definitions(schema)
    if schema_id in {
        "knowledge-analysis-proposal-result@1.0",
        "knowledge-analysis-proposal-result@2.0",
        "knowledge-analysis-proposal-result@3.0",
        "knowledge-analysis-proposal-result@4.0",
        "knowledge-analysis-proposal-result@5.0",
        "knowledge-analysis-proposal-result@6.0",
        "knowledge-analysis-proposal-result@7.0",
        "knowledge-analysis-proposal-result@8.0",
        "knowledge-analysis-proposal-result@9.0",
        "knowledge-analysis-proposal-result@10.0",
        "knowledge-analysis-proposal-result@11.0",
    }:
        if not isinstance(worker_input.request, KnowledgeAnalysisWorkerRequest):
            raise WorkflowSchemaError("knowledge analysis result requires its typed worker request")
        output = _mapping(_mapping(schema, "properties"), "output")
        if output.get("$ref") != "#/$defs/output":
            raise WorkflowSchemaError("knowledge analysis output reference is not projectable")
        output_definition = _mapping(_mapping(schema, "$defs"), "output")
        proposal_ref = _mapping(_mapping(output_definition, "properties"), "proposal")
        proposal_definition_name = {
            "knowledge-analysis-proposal-result@1.0": "KnowledgeAnalysisWorkerProposal",
            "knowledge-analysis-proposal-result@2.0": "KnowledgeAnalysisWorkerProposal",
            "knowledge-analysis-proposal-result@3.0": "KnowledgeAnalysisWorkerProposalV2",
            "knowledge-analysis-proposal-result@4.0": "KnowledgeAnalysisWorkerProposalV3",
            "knowledge-analysis-proposal-result@5.0": "KnowledgeAnalysisWorkerProposalV4",
            "knowledge-analysis-proposal-result@6.0": "KnowledgeAnalysisWorkerProposalV4",
            "knowledge-analysis-proposal-result@7.0": "KnowledgeAnalysisWorkerProposalV5",
            "knowledge-analysis-proposal-result@8.0": "KnowledgeAnalysisWorkerProposalV6",
            "knowledge-analysis-proposal-result@9.0": "KnowledgeAnalysisWorkerProposalV7",
            "knowledge-analysis-proposal-result@10.0": "KnowledgeAnalysisWorkerProposalV8",
            "knowledge-analysis-proposal-result@11.0": "KnowledgeAnalysisWorkerProposalV8",
        }[schema_id]
        if proposal_ref.get("$ref") != f"#/$defs/{proposal_definition_name}":
            raise WorkflowSchemaError("knowledge analysis proposal reference is not projectable")
        proposal_definition = _mapping(_mapping(schema, "$defs"), proposal_definition_name)
        proposal_properties = _mapping(proposal_definition, "properties")
        _mapping(proposal_properties, "analysis_request_id")["const"] = (
            worker_input.request.analysis_request.analysis_request_id
        )
        analysis_request = worker_input.request.analysis_request
        if isinstance(analysis_request, (KnowledgeAnalysisRequestV10, KnowledgeAnalysisRequestV11)):
            _mapping(proposal_properties, "base_analysis_result_id")["const"] = (
                analysis_request.base_analysis.analysis_result_id
            )
            report = _mapping(proposal_properties, "solution_report")
            report_reference = report.get("$ref")
            prefix = "#/$defs/"
            if not isinstance(report_reference, str) or not report_reference.startswith(prefix):
                raise WorkflowSchemaError("solution report reference is not projectable")
            report_properties = _mapping(
                _mapping(definitions, report_reference.removeprefix(prefix)), "properties"
            )
            _mapping(report_properties, "analysis_request_id")["const"] = (
                analysis_request.analysis_request_id
            )
            _mapping(report_properties, "base_analysis_result_id")["const"] = (
                analysis_request.base_analysis.analysis_result_id
            )
            _mapping(report_properties, "general_knowledge_used")["const"] = (
                analysis_request.general_knowledge_mode == "AUXILIARY_UNATTRIBUTED"
            )
            _bind_solution_reference_index(report_properties, analysis_request)
            _prune_unreferenced_definitions(schema)
            validate_codex_structured_output_schema(schema)
            return schema
        source = analysis_request.source
        if isinstance(analysis_request, KnowledgeAnalysisRequestV9):
            _bind_assessment_source_anchors(schema, proposal_properties, analysis_request)
            anchor_properties = None
        else:
            anchor_properties = _knowledge_analysis_anchor_properties(schema, proposal_properties)
            for field_name, value in (
                ("artifact_revision_id", source.artifact_member.artifact_revision_id),
                ("member_path", source.artifact_member.member_path),
            ):
                _bind_result_string_const(schema, _mapping(anchor_properties, field_name), value)
        if isinstance(
            analysis_request,
            (
                KnowledgeAnalysisRequestV3,
                KnowledgeAnalysisRequestV4,
                KnowledgeAnalysisRequestV5,
                KnowledgeAnalysisRequestV6,
                KnowledgeAnalysisRequestV7,
                KnowledgeAnalysisRequestV8,
            ),
        ):
            assert anchor_properties is not None
            document_source = analysis_request.source
            pages = "|".join(
                str(page)
                for page in range(
                    document_source.first_physical_page,
                    document_source.last_physical_page + 1,
                )
            )
            _mapping(anchor_properties, "locator")["pattern"] = (
                rf"^physical_page=(?:{pages})(?:;.{{1,220}})?$"
            )
        if isinstance(
            analysis_request,
            (KnowledgeAnalysisRequestV6, KnowledgeAnalysisRequestV7, KnowledgeAnalysisRequestV8),
        ):
            _bind_page_image_observations(
                schema,
                proposal_properties,
                analysis_request,
            )
            _prune_unreferenced_definitions(schema)
        if isinstance(analysis_request, KnowledgeAnalysisRequestV9):
            _bind_assessment_page_image_observations(
                schema,
                proposal_properties,
                analysis_request,
            )
            _prune_unreferenced_definitions(schema)
    if schema_id in {"external-item-learning-result@1.0", "external-item-learning-result@2.0"}:
        if not isinstance(worker_input.request, ExternalItemLearningWorkerRequest):
            raise WorkflowSchemaError("creative learning result requires its pinned work input")
        work = worker_input.request.work_input
        result = _mapping(
            definitions,
            "ExternalItemLearningResultV2"
            if schema_id.endswith("@2.0")
            else "ExternalItemLearningResult",
        )
        result_properties = _mapping(result, "properties")
        for field_name, pinned_value in (
            ("input_sha256", work.source.input_sha256),
            ("source_id", work.source.source_id),
            ("source_revision_id", work.source.source_revision_id),
            ("external_number", work.source.external_number),
        ):
            _bind_result_string_const(schema, _mapping(result_properties, field_name), pinned_value)
        region = _mapping(definitions, "ExternalItemLearningResult_region")
        _mapping(_mapping(region, "properties"), "physical_page")["maximum"] = len(
            work.page_set.pages
        )
    if schema_id == "legacy-item-extraction-result@1.0":
        if not isinstance(worker_input.request, LegacyItemExtractionWorkerRequest):
            raise WorkflowSchemaError("legacy extraction result requires its typed worker request")
        output = _mapping(_mapping(schema, "properties"), "output")
        if output.get("$ref") != "#/$defs/output":
            raise WorkflowSchemaError("legacy extraction output reference is not projectable")
        output_definition = _mapping(definitions, "output")
        extraction_ref = _mapping(_mapping(output_definition, "properties"), "extraction_result")
        if extraction_ref.get("$ref") != "#/$defs/LegacyItemExtractionResult":
            raise WorkflowSchemaError("legacy extraction result reference is not projectable")
        result_definition = _mapping(definitions, "LegacyItemExtractionResult")
        result_properties = _mapping(result_definition, "properties")
        request = worker_input.request.extraction_request
        _bind_result_string_const(
            schema,
            _mapping(result_properties, "extraction_request_id"),
            request.extraction_request_id,
        )
        _bind_result_string_const(
            schema,
            _mapping(result_properties, "request_sha256"),
            request.request_sha256,
        )
        _bind_result_string_const(
            schema,
            _mapping(result_properties, "result_sha256"),
            "sha256:" + "0" * 64,
        )
        observed_pages = _mapping(result_properties, "observed_page_input_ids")
        observed_pages["minItems"] = len(request.page_inputs)
        observed_pages["maxItems"] = len(request.page_inputs)
        observed_pages["items"] = {
            "type": "string",
            "enum": [page.page_input_id for page in request.page_inputs],
        }
        observed_pages["description"] = (
            "Return every supplied page_input_id exactly once and in the same order as the "
            "request. Do not repeat, omit, or reorder page IDs."
        )
        items = _mapping(result_properties, "items")
        items["minItems"] = len(request.expected_item_numbers)
        items["maxItems"] = len(request.expected_item_numbers)
        items["description"] = (
            "Return exactly one proposal for each requested item number, with no duplicates, "
            "in the same ascending order as expected_item_numbers."
        )
        item_schema = _mapping(items, "items")
        item_properties = _mapping(item_schema, "properties")
        _mapping(item_properties, "item_number")["enum"] = list(request.expected_item_numbers)
        _project_legacy_extraction_relations(
            schema,
            item_properties=item_properties,
            request=worker_input.request,
        )
        content_anchor_map = _mapping(item_properties, "content_anchor_map")
        # Codex's supported Structured Outputs subset cannot express the canonical
        # cross-item existential rule with `contains` or positional array schemas.
        # Strengthen the supported part of the projection and state the remaining
        # ordering contract explicitly; canonical Pydantic validation below the
        # worker boundary remains the authoritative fail-closed check.
        content_anchor_map["minItems"] = 2
        content_anchor_map["description"] = (
            "Return mappings in deterministic source order. The first mapping MUST use "
            'content_path exactly "title". At least one later mapping MUST use a '
            'content_path beginning with "body[". Reuse only source_anchor_ids declared '
            "in this item, and add mappings for every other grounded content element."
        )
        _prune_unreferenced_definitions(schema)
    if schema_id in {
        "pdf-document-review-result@1.0",
        "pdf-document-review-result@4.0",
        "pdf-document-review-result@5.0",
    }:
        expected_request = (
            PdfDocumentReviewWorkerRequestV5
            if schema_id == "pdf-document-review-result@5.0"
            else PdfDocumentReviewWorkerRequest
        )
        if not isinstance(worker_input.request, expected_request):
            raise WorkflowSchemaError("PDF document review result requires its typed request")
        pdf_request = worker_input.request.review_request
        _describe_document_review_result_order(definitions)
        target_properties = _mapping(_mapping(definitions, "target"), "properties")
        target_properties["page_numbers"]["description"] = (
            "Sort page numbers in ascending numeric order with no duplicates. Every target "
            "anchor must refer to one of these pages."
        )
        output_properties = _mapping(_mapping(definitions, "output"), "properties")
        if schema_id in {
            "pdf-document-review-result@4.0",
            "pdf-document-review-result@5.0",
        }:
            output_properties["review_status"]["description"] = (
                "Return NEEDS_HUMAN_DECISION if any of the ten verification targets is FAILED "
                "or INSUFFICIENT, or any candidate is UNCERTAIN. Otherwise return COMPLETE. "
                "Do not relabel failed or insufficient checks as VERIFIED."
            )
        for field_name, value in (
            ("review_request_sha256", pdf_request.request_sha256),
            ("document_id", pdf_request.document.document_id),
            ("document_revision_id", pdf_request.document.document_revision_id),
            ("source_pdf_sha256", pdf_request.document.source_pdf.sha256),
            ("preset_key", pdf_request.preset.preset_key),
            ("preset_revision_id", pdf_request.preset.preset_revision_id),
            ("preset_sha256", pdf_request.preset.preset_sha256),
        ):
            field = _mapping(output_properties, field_name)
            field.clear()
            field.update({"type": "string", "const": value})
        guidance_hash = _mapping(output_properties, "additional_guidance_sha256")
        guidance_hash.clear()
        if pdf_request.additional_guidance_sha256 is None:
            guidance_hash["type"] = "null"
        else:
            guidance_hash.update(
                {"type": "string", "const": pdf_request.additional_guidance_sha256}
            )
        anchor_properties = _mapping(_mapping(definitions, "anchor"), "properties")
        page_numbers = _mapping(anchor_properties, "page_number")
        page_numbers.clear()
        page_numbers.update(
            {
                "type": "integer",
                "enum": [page.page_number for page in pdf_request.document.pages],
            }
        )
        image_hashes = _mapping(anchor_properties, "page_image_sha256")
        image_hashes.clear()
        image_hashes.update(
            {
                "type": "string",
                "enum": [page.page_image.sha256 for page in pdf_request.document.pages],
            }
        )
        if schema_id == "pdf-document-review-result@5.0":
            if not isinstance(worker_input.request, PdfDocumentReviewWorkerRequestV5):
                raise WorkflowSchemaError("textbook review requires its exact typed request")
            textbook = worker_input.request.textbook_evidence
            usage = _mapping(definitions, "ReviewTextbookUsage")
            usage_properties = _mapping(usage, "properties")
            _bind_result_string_const(
                schema,
                _mapping(usage_properties, "binding_sha256"),
                textbook.binding_sha256,
            )
            citation = _mapping(definitions, "ReviewTextbookUsage_citation")
            citation_properties = _mapping(citation, "properties")
            _mapping(citation_properties, "evidence_id")["enum"] = list(
                textbook.textbook_evidence_ids
            )
            _mapping(_mapping(citation_properties, "conclusion_paths"), "items")["enum"] = [
                f"/verification_targets/{index}/conclusion" for index in range(10)
            ]
    if schema_id in {
        "pdf-document-review-result@2.0",
        "pdf-document-review-result@3.0",
        "pdf-document-review-result@6.0",
    }:
        expected_request_type = (
            PairedDocumentReviewWorkerRequestV3
            if schema_id == "pdf-document-review-result@6.0"
            else PairedDocumentReviewWorkerRequestV2
            if schema_id == "pdf-document-review-result@3.0"
            else PairedDocumentReviewWorkerRequest
        )
        if not isinstance(worker_input.request, expected_request_type):
            raise WorkflowSchemaError("paired document review result requires its typed request")
        paired_request = worker_input.request.review_request
        output_properties = _mapping(_mapping(definitions, "output"), "properties")
        for field_name, value in (
            ("review_request_sha256", paired_request.request_sha256),
            ("preset_key", paired_request.preset.preset_key),
            ("preset_revision_id", paired_request.preset.preset_revision_id),
            ("preset_sha256", paired_request.preset.preset_sha256),
        ):
            field = _mapping(output_properties, field_name)
            field.clear()
            field.update({"type": "string", "const": value})
        guidance_hash = _mapping(output_properties, "additional_guidance_sha256")
        guidance_hash.clear()
        if paired_request.additional_guidance_sha256 is None:
            guidance_hash["type"] = "null"
        else:
            guidance_hash.update(
                {"type": "string", "const": paired_request.additional_guidance_sha256}
            )
        anchor_properties = _mapping(_mapping(definitions, "anchor"), "properties")
        page_numbers = _mapping(anchor_properties, "page_number")
        page_numbers.clear()
        page_numbers.update(
            {
                "type": "integer",
                "enum": sorted(
                    {
                        page.page_number
                        for document in paired_request.documents
                        for page in document.document.pages
                    }
                ),
            }
        )
        image_hashes = _mapping(anchor_properties, "page_image_sha256")
        image_hashes.clear()
        image_hashes.update(
            {
                "type": "string",
                "enum": sorted(
                    {
                        page.page_image.sha256
                        for document in paired_request.documents
                        for page in document.document.pages
                    }
                ),
            }
        )
        _describe_document_review_result_order(definitions)
        output_properties["cross_document_checks"]["description"] = (
            "Sort by check_id with no duplicates."
        )
        target_properties = _mapping(_mapping(definitions, "target"), "properties")
        target_properties["page_refs"]["description"] = (
            "Sort unique entries by document_role and then page_number."
        )
        cross_check_properties = _mapping(
            _mapping(definitions, "cross_document_check"),
            "properties",
        )
        cross_check_properties["question_anchors"]["description"] = (
            "Sort by anchor_id with no duplicates."
        )
        cross_check_properties["solution_anchors"]["description"] = (
            "Sort by anchor_id with no duplicates."
        )
        if schema_id in {"pdf-document-review-result@3.0", "pdf-document-review-result@6.0"}:
            output_properties["page_coverage"]["description"] = (
                "Return every QUESTION page followed by every SOLUTION page, sorted by role and "
                "page_number, with no omission or duplicate."
            )
            output_properties["item_reviews"]["description"] = (
                "Return one ordered item review per question. Independently solve each item, "
                "check every condition, applicable unit, choice, and explanation step, and cite "
                "the staged Graph evidence."
            )
            # Keep the reference node pure; the strict worker schema rejects $ref siblings.
            _mapping(definitions, "evidence_usage")["description"] = (
                "Use exact identities from references/evidence/manifest.json and cite only "
                "manifest evidence and anchors. Every citation path must end at a non-null "
                "primitive leaf under item_reviews."
            )
        if schema_id == "pdf-document-review-result@6.0":
            if not isinstance(worker_input.request, PairedDocumentReviewWorkerRequestV3):
                raise WorkflowSchemaError("paired textbook review requires its exact request")
            textbook = worker_input.request.textbook_evidence
            publication = textbook.publication
            paired_usage_properties = _mapping(
                _mapping(definitions, "evidence_usage"), "properties"
            )
            for property_name, property_value in (
                ("evidence_bundle_id", publication.evidence_bundle_id),
                ("evidence_bundle_revision_id", publication.evidence_bundle_revision_id),
                ("retrieval_request_id", publication.retrieval_request_id),
                (
                    "graph_snapshot_revision_id",
                    publication.graph_snapshot.graph_snapshot_revision_id,
                ),
                ("manifest_sha256", publication.manifest_sha256),
                ("context_sha256", publication.context_artifact.sha256),
            ):
                _bind_result_string_const(
                    schema,
                    _mapping(paired_usage_properties, property_name),
                    property_value,
                )
            paired_citation_properties = _mapping(
                _mapping(definitions, "evidence_citation"), "properties"
            )
            _mapping(paired_citation_properties, "evidence_id")["enum"] = list(
                textbook.textbook_evidence_ids
            )
            usage = _mapping(definitions, "ReviewTextbookUsage")
            usage_properties = _mapping(usage, "properties")
            _bind_result_string_const(
                schema,
                _mapping(usage_properties, "binding_sha256"),
                textbook.binding_sha256,
            )
            citation = _mapping(definitions, "ReviewTextbookUsage_citation")
            citation_properties = _mapping(citation, "properties")
            _mapping(citation_properties, "evidence_id")["enum"] = list(
                textbook.textbook_evidence_ids
            )
            _mapping(_mapping(citation_properties, "conclusion_paths"), "items")["enum"] = [
                *(f"/verification_targets/{index}/conclusion" for index in range(10)),
                *(f"/item_reviews/{index}/conclusion" for index in range(256)),
            ]
    if schema_id == "legacy-item-editorial-compatibility-result@1.0":
        if not isinstance(
            worker_input.request,
            LegacyItemEditorialCompatibilityWorkerRequest,
        ):
            raise WorkflowSchemaError(
                "legacy editorial compatibility result requires its typed worker request"
            )
        output = _mapping(_mapping(schema, "properties"), "output")
        if output.get("$ref") != "#/$defs/output":
            raise WorkflowSchemaError(
                "legacy editorial compatibility output reference is not projectable"
            )
        output_definition = _mapping(definitions, "output")
        proposal_ref = _mapping(_mapping(output_definition, "properties"), "proposal")
        if proposal_ref.get("$ref") != "#/$defs/LegacyItemEditorialCompatibilityProposal":
            raise WorkflowSchemaError(
                "legacy editorial compatibility proposal reference is not projectable"
            )
        proposal_definition = _mapping(
            definitions,
            "LegacyItemEditorialCompatibilityProposal",
        )
        proposal_properties = _mapping(proposal_definition, "properties")
        proposal_required = proposal_definition.get("required")
        if not isinstance(proposal_required, list) or "proposal_sha256" not in proposal_required:
            raise WorkflowSchemaError(
                "legacy editorial compatibility proposal hash is not projectable"
            )
        proposal_required.remove("proposal_sha256")
        proposal_properties.pop("proposal_sha256")
        compatibility_request = worker_input.request.compatibility_request
        _bind_result_string_const(
            schema,
            _mapping(proposal_properties, "compatibility_request_id"),
            compatibility_request.compatibility_request_id,
        )
        _bind_result_string_const(
            schema,
            _mapping(proposal_properties, "request_sha256"),
            compatibility_request.request_sha256,
        )
        compatibility_source_properties = _local_definition_properties(
            schema,
            _mapping(proposal_properties, "source"),
        )
        for key, value in (
            ("item_id", compatibility_request.source.item_id),
            ("item_revision_id", compatibility_request.source.item_revision_id),
            ("item_manifest_sha256", compatibility_request.source.item_manifest_sha256),
        ):
            _bind_result_string_const(
                schema,
                _mapping(compatibility_source_properties, key),
                value,
            )
        issue_definition = _mapping(
            definitions,
            "LegacyItemEditorialCompatibilityProposal_issue",
        )
        issue_properties = _mapping(issue_definition, "properties")
        content_paths = _mapping(issue_properties, "item_content_paths")
        content_path_items = _mapping(content_paths, "items")
        content_path_items["pattern"] = r"^[^/\u0000-\u001f][^\u0000-\u001f]*$"
        content_paths["description"] = (
            "Use canonical dot paths into Item content, for example title, body.0.text, "
            "interaction.choices, or solution.correct_choice_ids. JSON Pointer paths that "
            "start with '/' are invalid."
        )
        _prune_unreferenced_definitions(schema)
    if schema_id in {"review-result@10.0", "review-result@11.0", "review-result@12.0"}:
        authoring_schema = (
            "authoring-result@12.0"
            if schema_id == "review-result@12.0"
            else (
                "authoring-result@11.0"
                if schema_id == "review-result@11.0"
                else "authoring-result@10.0"
            )
        )
        authoring = tuple(
            pointer
            for pointer in worker_input.upstream_artifacts
            if pointer.step_key == "authoring" and pointer.result_schema == authoring_schema
        )
        if len(authoring) != 1:
            raise WorkflowSchemaError(
                f"evidence review requires one exact {authoring_schema} pointer"
            )
        pointer_definition = (
            "EvidenceAuthoringArtifactPointerV3"
            if schema_id == "review-result@12.0"
            else (
                "EvidenceAuthoringArtifactPointerV2"
                if schema_id == "review-result@11.0"
                else "EvidenceAuthoringArtifactPointerV1"
            )
        )
        authoring_properties = _mapping(_mapping(definitions, pointer_definition), "properties")
        for field_name, field_value in (
            ("logical_artifact_id", authoring[0].logical_artifact_id),
            ("revision_id", authoring[0].revision_id),
            ("content_hash", authoring[0].content_hash),
        ):
            _bind_result_string_const(
                schema,
                _mapping(authoring_properties, field_name),
                field_value,
            )
    validate_codex_structured_output_schema(schema)
    return schema


def _bind_evidence_result_branch(
    schema: dict[str, Any],
    *,
    schema_id: str,
    evidence_access: Literal["NONE", "EVIDENCE_CONTEXT"] | None,
    resolved_evidence_plan: ResolvedExecutionPlanV3 | None,
    material_requirement: ContentTeamMaterialRequirement | None,
) -> None:
    """Bind nullable evidence branches to the immutable resolved-plan step.

    Codex Structured Outputs cannot retain the canonical cross-field conditional. The resolved
    plan already owns whether this step receives evidence, so this O(1) projection prevents a
    worker from selecting the contradictory nullable branch while canonical validation remains
    authoritative.
    """

    if schema_id not in {
        "authoring-result@10.0",
        "review-result@10.0",
        "authoring-result@11.0",
        "review-result@11.0",
        "authoring-result@12.0",
        "review-result@12.0",
    }:
        return
    if evidence_access is None:
        return
    if evidence_access not in {"NONE", "EVIDENCE_CONTEXT"}:  # pragma: no cover - typed guard
        raise WorkflowSchemaError("result evidence access is invalid")

    definitions = _mapping(schema, "$defs")
    grounded = evidence_access == "EVIDENCE_CONTEXT"
    if grounded and resolved_evidence_plan is None:
        raise WorkflowSchemaError("evidence result requires its typed resolved plan")
    if not grounded and resolved_evidence_plan is not None:
        raise WorkflowSchemaError("non-evidence result cannot receive an evidence plan")
    if schema_id in {
        "authoring-result@10.0",
        "authoring-result@11.0",
        "authoring-result@12.0",
    }:
        output_properties = _mapping(
            _mapping(definitions, "ContentTeamAuthoringOutputV10"),
            "properties",
        )
        evidence_usage = _mapping(output_properties, "evidence_usage")
        evidence_usage.clear()
        evidence_usage.update({"$ref": "#/$defs/EvidenceUsageV1"} if grounded else {"type": "null"})
        metadata_properties = _mapping(
            _mapping(definitions, "KnowledgeAuthoringMetadataV2"),
            "properties",
        )
        knowledge_source_mode = _mapping(metadata_properties, "knowledge_source_mode")
        knowledge_source_mode["const"] = "graph_grounded" if grounded else "general_model_knowledge"
        if grounded:
            assert resolved_evidence_plan is not None
            usage_properties = _mapping(_mapping(definitions, "EvidenceUsageV1"), "properties")
            for field_name, field_value in (
                ("evidence_bundle_id", resolved_evidence_plan.evidence_bundle_id),
                (
                    "evidence_bundle_revision_id",
                    resolved_evidence_plan.evidence_bundle_revision_id,
                ),
                ("retrieval_request_id", resolved_evidence_plan.retrieval_request_id),
                (
                    "graph_snapshot_revision_id",
                    resolved_evidence_plan.graph_snapshot.graph_snapshot_revision_id,
                ),
                ("evidence_manifest_sha256", resolved_evidence_plan.evidence_manifest_sha256),
                (
                    "evidence_context_sha256",
                    resolved_evidence_plan.evidence_context_artifact.sha256,
                ),
            ):
                _bind_result_string_const(
                    schema,
                    _mapping(usage_properties, field_name),
                    field_value,
                )
            _bind_required_material_result_branch(
                schema,
                resolved_evidence_plan=resolved_evidence_plan,
                material_requirement=material_requirement,
            )
        return

    review_output_definition = (
        "KnowledgeReviewOutputV12"
        if schema_id == "review-result@12.0"
        else (
            "KnowledgeReviewOutputV11"
            if schema_id == "review-result@11.0"
            else "KnowledgeReviewOutputV10"
        )
    )
    attestation_definition = (
        "EvidenceUsageReviewAttestationV3"
        if schema_id == "review-result@12.0"
        else (
            "EvidenceUsageReviewAttestationV2"
            if schema_id == "review-result@11.0"
            else "EvidenceUsageReviewAttestationV1"
        )
    )
    output_properties = _mapping(
        _mapping(definitions, review_output_definition),
        "properties",
    )
    attestation = _mapping(output_properties, "evidence_usage_attestation")
    attestation.clear()
    attestation.update(
        {"$ref": f"#/$defs/{attestation_definition}"} if grounded else {"type": "null"}
    )


def _bind_required_material_result_branch(
    schema: dict[str, Any],
    *,
    resolved_evidence_plan: ResolvedExecutionPlanV3,
    material_requirement: ContentTeamMaterialRequirement | None,
) -> None:
    """Project plan-required TABLE/IMAGE presence into the authoring response schema.

    The V3 plan owns retrieval requirements and a V4 worker request owns the reviewed material
    form and panel count. The application-level material validator remains independently
    responsible for exact order, labels, DATA blocks, and inquiry relationships.
    """

    required = set(resolved_evidence_plan.retrieval_requirement.required_item_elements)
    image_required = "image" in required
    table_required = "table" in required
    if not image_required and not table_required:
        return

    definitions = _mapping(schema, "$defs")
    draft_properties = _mapping(_mapping(definitions, "AssessmentItemContentV3"), "properties")
    visuals = _mapping(draft_properties, "visuals")
    usage_properties = _mapping(_mapping(definitions, "EvidenceUsageV1"), "properties")
    citations = _mapping(usage_properties, "citations")

    requirement = material_requirement
    if requirement is not None:
        projected_elements = content_team_material_required_retrieval_elements(requirement)
        if projected_elements != (
            resolved_evidence_plan.retrieval_requirement.required_item_elements
        ):
            raise WorkflowSchemaError(
                "reviewed material requirement differs from resolved evidence retrieval"
            )
        _bind_exact_material_shape(draft_properties, requirement)
        source_classes = tuple(
            getattr(resolved_evidence_plan.retrieval_requirement, "source_classes", ())
        )
        if source_classes == ("PAST_EXAM",):
            _bind_exact_past_exam_material_citations(definitions, requirement)
        return

    if image_required and table_required:
        visuals["minItems"] = 2
        _append_projection_instruction(
            visuals,
            "Return exactly two visuals containing one IMAGE and one TABLE in presentation order.",
        )
        _append_projection_instruction(
            citations,
            "Cite /stem and, for each material, its /visuals/{index}/kind plus the required "
            "DATA content or one concrete table header/cell scalar leaf.",
        )
        return

    visual_kind = "IMAGE" if image_required else "TABLE"
    definition_name = "ContentTeamImageSlot" if image_required else "ContentTeamTable"
    visuals["minItems"] = 1
    visuals["items"] = {"$ref": f"#/$defs/{definition_name}"}
    _append_projection_instruction(
        visuals,
        f"Return one or two {visual_kind} visuals; an empty visual list is invalid for this plan.",
    )
    if image_required:
        labeled_blocks = _mapping(draft_properties, "labeled_blocks")
        labeled_blocks["minItems"] = 1
        _append_projection_instruction(
            labeled_blocks,
            "Include exactly one DATA block containing the student-visible image material facts.",
        )
        _append_projection_instruction(
            citations,
            "A PAST_EXAM STRUCTURE_PATTERN citation must include /stem, every IMAGE "
            "/visuals/{index}/kind, and the actual DATA /labeled_blocks/{index}/content leaf.",
        )
    else:
        _append_projection_instruction(
            citations,
            "A PAST_EXAM STRUCTURE_PATTERN citation must include every TABLE "
            "/visuals/{index}/kind and at least one concrete header or cell scalar leaf per table.",
        )


def _bind_exact_material_shape(
    draft_properties: dict[str, Any],
    requirement: ContentTeamMaterialRequirement,
) -> None:
    """Project the reviewed material form into one bounded worker response schema."""

    if requirement.form not in {"TABLE", "IMAGE", "MIXED"}:
        return
    visuals = _mapping(draft_properties, "visuals")
    assert requirement.panel_count is not None
    visuals["minItems"] = requirement.panel_count
    visuals["maxItems"] = requirement.panel_count
    if requirement.form in {"TABLE", "IMAGE"}:
        definition_name = (
            "ContentTeamTable" if requirement.form == "TABLE" else "ContentTeamImageSlot"
        )
        visuals["items"] = {"$ref": f"#/$defs/{definition_name}"}

    if requirement.form == "IMAGE":
        labeled_blocks = _mapping(draft_properties, "labeled_blocks")
        if (
            isinstance(requirement, ContentTeamMaterialRequirementV2)
            and requirement.image_supporting_data == "NONE"
        ):
            block_definition = _mapping(
                _mapping(draft_properties, "labeled_blocks"),
                "items",
            )
            if block_definition.get("$ref") != "#/$defs/ContentTeamLabeledBlock":
                raise WorkflowSchemaError("labeled block projection is incompatible")
            labeled_blocks["maxItems"] = 1
            _append_projection_instruction(
                labeled_blocks,
                "Do not create a DATA block. Put the natural visual introduction in stem; an "
                "independent CONDITION is the only allowed labeled block.",
            )
        else:
            labeled_blocks["minItems"] = 1
            _append_projection_instruction(
                labeled_blocks,
                "The first block must be the one required DATA block; an optional CONDITION may "
                "follow it.",
            )


def _bind_exact_past_exam_material_citations(
    definitions: dict[str, Any],
    requirement: ContentTeamMaterialRequirement,
) -> None:
    """State the exact cross-citation paths checked after V4 PAST_EXAM generation.

    Codex Structured Outputs cannot express this existential union across sibling citation
    records. The projected description guides generation without corrupting the semantic mapping
    of each individual citation. The orchestrator remains the authoritative machine gate: it
    unions eligible citation paths and resolves every path and Evidence entry independently.
    """

    if requirement.form not in {"TABLE", "IMAGE", "MIXED"}:
        return
    usage_properties = _mapping(_mapping(definitions, "EvidenceUsageV1"), "properties")
    citations = _mapping(usage_properties, "citations")
    citation_properties = _mapping(_mapping(definitions, "EvidenceUsageCitationV1"), "properties")
    _bind_result_string_const(
        {"$defs": definitions},
        _mapping(citation_properties, "application"),
        "STRUCTURE_PATTERN",
    )
    path_schema = _mapping(citation_properties, "draft_json_paths")

    if requirement.form == "TABLE":
        assert requirement.panel_count is not None
        required_paths = tuple(
            path
            for ordinal in range(requirement.panel_count)
            for path in (
                f"/visuals/{ordinal}/headers/0",
                f"/visuals/{ordinal}/kind",
            )
        )
        requirement_text = f"Across all citations include {', '.join(required_paths)}."
    elif requirement.form == "IMAGE":
        assert requirement.panel_count is not None
        data_paths = (
            ("/labeled_blocks/0/content",)
            if not isinstance(requirement, ContentTeamMaterialRequirementV2)
            or requirement.image_supporting_data == "LABELED_DATA"
            else ()
        )
        required_paths = (
            *data_paths,
            "/stem",
            *(f"/visuals/{ordinal}/kind" for ordinal in range(requirement.panel_count)),
        )
        requirement_text = f"Across all citations include {', '.join(required_paths)}."
    else:
        first = "/stem, /visuals/0/headers/0, /visuals/0/kind, /visuals/1/kind"
        second = "/stem, /visuals/0/kind, /visuals/1/headers/0, /visuals/1/kind"
        requirement_text = (
            f"Across all citations include exactly one position-aware structural alternative: "
            f"[{first}] when visual 0 is TABLE, or [{second}] when visual 1 is TABLE."
        )
    instruction = (
        f"The union of draft_json_paths from the PAST_EXAM STRUCTURE_PATTERN citations must bind "
        f"the reviewed {requirement.form} material. {requirement_text} Keep other genuinely "
        "grounded citations and scalar paths; do not repeat unrelated paths on every citation."
    )
    _append_projection_instruction(citations, instruction)
    _append_projection_instruction(path_schema, instruction)


def _local_definition_properties(
    schema: dict[str, Any],
    value: dict[str, Any],
) -> dict[str, Any]:
    reference = value.get("$ref")
    prefix = "#/$defs/"
    if set(value) != {"$ref"} or not isinstance(reference, str) or not reference.startswith(prefix):
        raise WorkflowSchemaError("local object reference is not independently projectable")
    definition = _mapping(_mapping(schema, "$defs"), reference.removeprefix(prefix))
    return _mapping(definition, "properties")


def _knowledge_analysis_anchor_properties(
    schema: dict[str, Any], proposal_properties: dict[str, Any]
) -> dict[str, Any]:
    anchors = _mapping(proposal_properties, "anchors")
    items = _mapping(anchors, "items")
    reference = items.get("$ref")
    prefix = "#/$defs/"
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise WorkflowSchemaError("knowledge analysis anchor reference is not projectable")
    anchor_definition = _mapping(_mapping(schema, "$defs"), reference.removeprefix(prefix))
    return _mapping(anchor_definition, "properties")


def _bind_assessment_source_anchors(
    schema: dict[str, Any],
    proposal_properties: dict[str, Any],
    analysis_request: KnowledgeAnalysisRequestV9,
) -> None:
    """Restrict source anchors to the exact Item JSON or delivered page PNG revisions."""

    anchors = _mapping(proposal_properties, "anchors")
    template = _mapping(anchors, "items")
    reference = template.get("$ref")
    prefix = "#/$defs/"
    if (
        set(template) != {"$ref"}
        or not isinstance(reference, str)
        or not reference.startswith(prefix)
    ):
        raise WorkflowSchemaError("assessment source anchor schema is not projectable")
    definition = _mapping(_mapping(schema, "$defs"), reference.removeprefix(prefix))
    pointers = (
        (
            analysis_request.source.artifact_member.artifact_revision_id,
            analysis_request.source.artifact_member.member_path,
            "the immutable promoted Item JSON",
        ),
        *(
            (
                page.image.artifact_revision_id,
                page.image.member_path,
                f"{page.source_role} physical page {page.physical_page} PNG",
            )
            for page in analysis_request.source.page_inputs
        ),
    )
    alternatives: list[dict[str, Any]] = []
    for artifact_revision_id, member_path, label in pointers:
        branch = copy.deepcopy(definition)
        properties = _mapping(branch, "properties")
        _bind_result_string_const(
            schema,
            _mapping(properties, "artifact_revision_id"),
            artifact_revision_id,
        )
        _bind_result_string_const(schema, _mapping(properties, "member_path"), member_path)
        branch["description"] = f"Source anchor into {label}."
        alternatives.append(branch)
    anchors["items"] = {"anyOf": alternatives}
    anchors["description"] = (
        "Ground every claim in the exact promoted Item JSON or one supplied page PNG. "
        "Do not cite the source PDF pointer or any unstaged artifact."
    )


def _bind_result_string_const(
    schema: dict[str, Any], property_schema: dict[str, Any], value: str
) -> None:
    """Bind one exact string without creating a response-format-invalid ref sibling."""

    visited_references: set[str] = set()
    reference = property_schema.get("$ref")
    while reference is not None:
        prefix = "#/$defs/"
        if set(property_schema) != {"$ref"} or not isinstance(reference, str):
            raise WorkflowSchemaError("result string reference is not independently projectable")
        if not reference.startswith(prefix):
            raise WorkflowSchemaError("result string reference is not local")
        if reference in visited_references:
            raise WorkflowSchemaError("result string reference cycle is not projectable")
        visited_references.add(reference)
        definition = copy.deepcopy(
            _mapping(_mapping(schema, "$defs"), reference.removeprefix(prefix))
        )
        property_schema.clear()
        property_schema.update(definition)
        reference = property_schema.get("$ref")
    if property_schema.get("type") != "string" or "$ref" in property_schema:
        raise WorkflowSchemaError("result const binding requires an inline string schema")
    property_schema["const"] = value


def _inline_local_schema(schema: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    """Copy and fully inline one independently referenced local schema node."""

    projected = copy.deepcopy(value)
    visited_references: set[str] = set()
    reference = projected.get("$ref")
    while reference is not None:
        prefix = "#/$defs/"
        if set(projected) != {"$ref"} or not isinstance(reference, str):
            raise WorkflowSchemaError("local schema reference is not independently projectable")
        if not reference.startswith(prefix):
            raise WorkflowSchemaError("local schema reference is not local")
        if reference in visited_references:
            raise WorkflowSchemaError("local schema reference cycle is not projectable")
        visited_references.add(reference)
        projected = copy.deepcopy(
            _mapping(_mapping(schema, "$defs"), reference.removeprefix(prefix))
        )
        reference = projected.get("$ref")
    return projected


def _exact_legacy_source_pointer_schema(
    schema: dict[str, Any],
    template: dict[str, Any],
    pointer: object,
) -> dict[str, Any]:
    projected = _inline_local_schema(schema, template)
    properties = _mapping(projected, "properties")
    model_dump = getattr(pointer, "model_dump", None)
    if not callable(model_dump):
        raise WorkflowSchemaError("legacy source pointer is not serializable")
    value = model_dump(mode="json")
    if not isinstance(value, dict) or set(value) != set(properties):
        raise WorkflowSchemaError("legacy source pointer shape is not projectable")
    for key, item in value.items():
        if not isinstance(item, str):
            raise WorkflowSchemaError("legacy source pointer field is not an exact string")
        _bind_result_string_const(schema, _mapping(properties, key), item)
    return projected


def _exact_legacy_item_media_schema(
    schema: dict[str, Any],
    template: dict[str, Any],
    pointer: object,
) -> dict[str, Any]:
    """Project one request page pointer into the Item-content media field names."""

    projected = _inline_local_schema(schema, template)
    properties = _mapping(projected, "properties")
    values = {
        "artifact_id": getattr(pointer, "artifact_id", None),
        "artifact_revision_id": getattr(pointer, "artifact_revision_id", None),
        "artifact_member": getattr(pointer, "member_path", None),
        "sha256": getattr(pointer, "sha256", None),
        "media_type": getattr(pointer, "media_type", None),
    }
    if set(values) != set(properties) or not all(
        isinstance(value, str) for value in values.values()
    ):
        raise WorkflowSchemaError("legacy Item media pointer is not projectable")
    for key, value in values.items():
        assert isinstance(value, str)
        _bind_result_string_const(schema, _mapping(properties, key), value)
    return projected


def _legacy_source_anchor_variant(
    schema: dict[str, Any],
    template: dict[str, Any],
    *,
    pointer: object,
    source_role: str,
    physical_page: int | None,
    page_image: bool,
) -> dict[str, Any]:
    projected = _inline_local_schema(schema, template)
    properties = _mapping(projected, "properties")
    properties["source"] = _exact_legacy_source_pointer_schema(
        schema,
        _mapping(properties, "source"),
        pointer,
    )
    _mapping(properties, "source_role")["const"] = source_role
    if page_image:
        if physical_page is None:
            raise WorkflowSchemaError("legacy page anchor is missing its physical page")
        properties["physical_page"] = {
            "type": "integer",
            "minimum": 1,
            "maximum": 100000,
            "const": physical_page,
        }
    return projected


def _project_legacy_extraction_relations(
    schema: dict[str, Any],
    *,
    item_properties: dict[str, Any],
    request: LegacyItemExtractionWorkerRequest,
) -> None:
    """Project canonical cross-field rules as exact identities plus model instructions."""

    extraction_request = request.extraction_request
    source_anchors = _mapping(item_properties, "source_anchors")
    source_anchor_template = _mapping(source_anchors, "items")
    anchor_variants = [
        _legacy_source_anchor_variant(
            schema,
            source_anchor_template,
            pointer=page.image,
            source_role=page.source_role,
            physical_page=page.physical_page,
            page_image=True,
        )
        for page in extraction_request.page_inputs
    ]
    anchor_variants.extend(
        _legacy_source_anchor_variant(
            schema,
            source_anchor_template,
            pointer=materialization.source,
            source_role=materialization.source_role,
            physical_page=None,
            page_image=False,
        )
        for materialization in extraction_request.source_materializations
    )
    if not anchor_variants:
        raise WorkflowSchemaError("legacy extraction request has no projectable anchor source")
    source_anchors["items"] = {"anyOf": anchor_variants}
    source_anchors["description"] = (
        "First declare this item's complete source-anchor registry with unique anchor_id values. "
        "Never reuse an anchor_id from another item. Every source anchor MUST use one exact "
        "pointer/role pair offered by this schema. For problem and answer pages, source MUST be "
        "the supplied page image pointer (PNG), never the original PDF source pointer, and "
        "physical_page MUST match that page input. After declaring the registry, every "
        "source_anchor_ids entry anywhere in this item MUST byte-for-byte copy an anchor_id from "
        "this same registry."
    )

    closed_reference_description = (
        "Every entry MUST byte-for-byte copy one anchor_id already declared in this same item's "
        "source_anchors array. Never invent an ID, reuse an ID from another item, or reference an "
        "anchor that is not present in this item's source_anchors."
    )
    for collection_name in (
        "content_anchor_map",
        "curriculum_observations",
        "linguistic_patterns",
        "visual_patterns",
        "metadata_observations",
        "conflicts",
    ):
        collection = _mapping(item_properties, collection_name)
        observation = _mapping(collection, "items")
        if "$ref" in observation:
            observation_properties = _local_definition_properties(schema, observation)
        elif observation.get("type") == "object":
            observation_properties = _mapping(observation, "properties")
        else:
            raise WorkflowSchemaError(
                f"legacy {collection_name} observation is not independently projectable"
            )
        _mapping(observation_properties, "source_anchor_ids")["description"] = (
            closed_reference_description
        )

    content_properties = _local_definition_properties(
        schema,
        _mapping(item_properties, "item_content"),
    )
    image_definition = _mapping(
        _mapping(schema, "$defs"),
        "AssessmentItemContent_imageBlock",
    )
    image_properties = _mapping(image_definition, "properties")
    media_template = _mapping(image_properties, "artifact")
    image_properties["artifact"] = {
        "anyOf": [
            _exact_legacy_item_media_schema(schema, media_template, page.image)
            for page in extraction_request.page_inputs
        ],
        "description": (
            "Byte-for-byte copy one exact page_inputs[].image pointer supplied by this request. "
            "Never invent, repair, or derive an Artifact identity."
        ),
    }
    _mapping(content_properties, "body")["description"] = (
        "Preserve the observed body blocks in source order. If any statement_set block is "
        "present, solution.statement_explanations MUST contain exactly one explanation for every "
        "statement_id and no other IDs. With no statement_set, statement_explanations MUST be "
        "empty."
    )
    _mapping(content_properties, "interaction")["description"] = (
        "For single_choice, return exactly one correct_choice_id that resolves to a declared "
        "choice and keep accepted_answers empty. For constructed_response, keep "
        "correct_choice_ids empty and return at least one accepted answer."
    )
    solution_properties = _local_definition_properties(
        schema,
        _mapping(content_properties, "solution"),
    )
    _mapping(solution_properties, "correct_choice_ids")["description"] = (
        "Exactly one declared choice ID for single_choice; empty for constructed_response."
    )
    _mapping(solution_properties, "accepted_answers")["description"] = (
        "Empty for single_choice; one or more source-grounded answers for constructed_response."
    )
    _mapping(solution_properties, "statement_explanations")["description"] = (
        "Use exactly the statement IDs declared across item_content.body statement_set blocks, "
        "one explanation per ID and no extras. Return an empty array only when no statement_set "
        "exists."
    )
    _mapping(item_properties, "linguistic_patterns")["description"] = (
        "Each observation must be internally coherent: uses_statement_set=true requires "
        "choice_grammar=STATEMENT_COMBINATION; prompt_form=SELECT_COMBINATION also requires "
        "uses_statement_set=true."
    )


def _bind_page_image_observations(
    schema: dict[str, Any],
    proposal_properties: dict[str, Any],
    analysis_request: (
        KnowledgeAnalysisRequestV6 | KnowledgeAnalysisRequestV7 | KnowledgeAnalysisRequestV8
    ),
) -> None:
    """Bind model-visible page attestations to exact immutable request pointers."""

    observations = _mapping(proposal_properties, "page_image_observations")
    item_schema = _mapping(observations, "items")
    reference = item_schema.get("$ref")
    prefix = "#/$defs/"
    if (
        set(item_schema) != {"$ref"}
        or not isinstance(reference, str)
        or not reference.startswith(prefix)
    ):
        raise WorkflowSchemaError("page-image observation schema is not independently projectable")
    definition = _mapping(_mapping(schema, "$defs"), reference.removeprefix(prefix))
    expected_images = tuple(
        member
        for member in analysis_request.source.materialization_members
        if member.member_kind == "PAGE_IMAGE"
    )
    if len(expected_images) != analysis_request.source.page_image_count:
        raise WorkflowSchemaError("page-image request pointer count is inconsistent")
    alternatives: list[dict[str, Any]] = []
    for member in expected_images:
        if member.physical_page is None:
            raise WorkflowSchemaError("page-image request pointer has no physical page")
        branch = copy.deepcopy(definition)
        properties = _mapping(branch, "properties")
        physical_page = _mapping(properties, "physical_page")
        if physical_page.get("type") != "integer":
            raise WorkflowSchemaError("page-image physical page is not projectable")
        physical_page["const"] = member.physical_page
        _bind_result_string_const(schema, _mapping(properties, "image_sha256"), member.sha256)
        alternatives.append(branch)
    observations["minItems"] = len(alternatives)
    observations["maxItems"] = len(alternatives)
    observations["items"] = {"anyOf": alternatives}


def _bind_assessment_page_image_observations(
    schema: dict[str, Any],
    proposal_properties: dict[str, Any],
    analysis_request: KnowledgeAnalysisRequestV9,
) -> None:
    """Bind every Item-level visual attestation to its exact staged PNG pointer."""

    observations = _mapping(proposal_properties, "page_image_observations")
    item_schema = _mapping(observations, "items")
    reference = item_schema.get("$ref")
    prefix = "#/$defs/"
    if (
        set(item_schema) != {"$ref"}
        or not isinstance(reference, str)
        or not reference.startswith(prefix)
    ):
        raise WorkflowSchemaError(
            "assessment page-image observation schema is not independently projectable"
        )
    definition = _mapping(_mapping(schema, "$defs"), reference.removeprefix(prefix))
    alternatives: list[dict[str, Any]] = []
    for page in analysis_request.source.page_inputs:
        branch = copy.deepcopy(definition)
        properties = _mapping(branch, "properties")
        for field_name, value in (
            ("page_input_id", page.page_input_id),
            ("source_role", page.source_role),
            ("image_sha256", page.image.sha256),
        ):
            _bind_result_string_const(schema, _mapping(properties, field_name), value)
        physical_page = _mapping(properties, "physical_page")
        if physical_page.get("type") != "integer":
            raise WorkflowSchemaError("assessment physical page is not projectable")
        physical_page["const"] = page.physical_page
        alternatives.append(branch)
    observations["minItems"] = len(alternatives)
    observations["maxItems"] = len(alternatives)
    observations["items"] = {"anyOf": alternatives}
    observations["description"] = (
        "Return one observation for every supplied assessment page PNG, exactly once and in "
        "request order. Each observation must cite at least one source anchor from that page."
    )


def load_codex_result_schema(schema_id: str) -> dict[str, Any]:
    """Project the canonical result contract into Codex's strict JSON Schema subset."""

    schema = copy.deepcopy(_role_result_schema(schema_id))
    schema.pop("$schema", None)
    schema.pop("$id", None)
    if schema_id == "authoring-result@2.0":
        _project_knowledge_authoring_content(schema)
    if schema_id in {
        "authoring-result@7.0",
        "authoring-result@8.0",
        "authoring-result@9.0",
        "authoring-result@10.0",
        "authoring-result@11.0",
        "authoring-result@12.0",
    }:
        _project_content_team_authoring_contract(schema, schema_id=schema_id)
    if schema_id in {
        "image-result@9.0",
        "image-result@10.0",
        "image-result@11.0",
        "image-result@12.0",
    }:
        _project_content_team_image_v9_codex_contract(schema)
    if schema_id in {
        "knowledge-analysis-proposal-result@1.0",
        "knowledge-analysis-proposal-result@2.0",
        "knowledge-analysis-proposal-result@3.0",
        "knowledge-analysis-proposal-result@4.0",
        "knowledge-analysis-proposal-result@5.0",
        "knowledge-analysis-proposal-result@6.0",
        "knowledge-analysis-proposal-result@7.0",
        "knowledge-analysis-proposal-result@8.0",
        "knowledge-analysis-proposal-result@9.0",
        "knowledge-analysis-proposal-result@10.0",
        "knowledge-analysis-proposal-result@11.0",
    }:
        _project_knowledge_analysis_codex_contract(schema, schema_id=schema_id)
    if schema_id in {
        "knowledge-analysis-proposal-result@5.0",
        "knowledge-analysis-proposal-result@6.0",
        "knowledge-analysis-proposal-result@7.0",
        "knowledge-analysis-proposal-result@8.0",
        "knowledge-analysis-proposal-result@9.0",
        "knowledge-analysis-proposal-result@10.0",
        "knowledge-analysis-proposal-result@11.0",
    }:
        _prune_unreferenced_definitions(schema)
    if schema_id == "legacy-item-extraction-result@1.0":
        _prune_unreferenced_definitions(schema)
    if schema_id == "external-item-learning-result@1.0":
        _project_external_item_learning_codex_contract(schema)
        _prune_unreferenced_definitions(schema)
    if schema_id == "external-item-learning-result@2.0":
        _project_external_item_learning_codex_contract(
            schema, result_definition="ExternalItemLearningResultV2"
        )
        _project_creative_answer_representations(schema)
        _prune_unreferenced_definitions(schema)
    if schema_id == "legacy-item-editorial-compatibility-result@1.0":
        _project_legacy_editorial_compatibility_codex_contract(schema)
        _prune_unreferenced_definitions(schema)
    if schema_id == "customer-support-result@1.0":
        output = _mapping(_mapping(schema, "$defs"), "output")
        output.pop("allOf", None)
    if schema_id == "item-inference-transfer-pair-result@1.0":
        _prune_unreferenced_definitions(schema)
        definitions = _mapping(schema, "$defs")
        # Only generation drops conditional operators; canonical/Pydantic admission retains them.
        for name in ("InferenceTransfer_pairResult", "InferenceTransfer_difference"):
            node = _mapping(definitions, name)
            node.pop("allOf", None)
        _mapping(definitions, "InferenceTransfer_pairResult")["description"] = (
            "Structural/near-identical hypotheses require GIVEN_CONDITION and DECISIVE_INFERENCE "
            "mappings plus shared_idea. INSUFFICIENT requires limitations. Every difference has "
            "at least one source claim. SHA-256 hashes the canonical body excluding result_sha256."
        )
    if schema_id == "item-inference-transfer-pair-result@1.1":
        _prune_unreferenced_definitions(schema)
        definitions = _mapping(schema, "$defs")
        # Only the generation projection relaxes unsupported conditional/tuple
        # keywords. Canonical JSON Schema, frozen models and ref admission retain
        # exact three-axis order and the positive CRUX coherence invariant.
        output = _mapping(definitions, "InferenceTransferPairResultV11")
        output_properties = _mapping(output, "properties")
        if output_properties.pop("result_sha256", None) is None:
            raise WorkflowSchemaError("three-axis result hash is not projectable")
        output_required = output.get("required")
        if not isinstance(output_required, list) or "result_sha256" not in output_required:
            raise WorkflowSchemaError("three-axis result hash requirement is invalid")
        output_required.remove("result_sha256")
        output.pop("allOf", None)
        _mapping(definitions, "InferenceTransfer_difference").pop("allOf", None)
        _mapping(definitions, "InferenceTransferPairResultV11_axisAssessment").pop("allOf", None)
        axes = _mapping(_mapping(output, "properties"), "axes")
        axes.pop("prefixItems", None)
        axes["items"] = {"$ref": "#/$defs/InferenceTransferPairResultV11_axisAssessment"}
        axes["description"] = (
            "Exactly three independent axes in CONCEPT, MATERIAL, CRUX order. "
            "Non-INSUFFICIENT judgments require actual selected claims from both sides. "
            "CRUX claims must be DECISIVE_INFERENCE; positive overall judgments require "
            "CRUX SAME/PARTIAL. Insufficient evidence is not similarity."
        )
        output["description"] = (
            "Machine hypotheses only. Preserve exact request/profile/rubric pins and "
            "selected claim references. Condition and decisive mappings plus shared_idea "
            "are required for positive overall judgments; INSUFFICIENT requires limitations. "
            "Do not output result_sha256: the Orchestrator derives the omitted hash of the exact "
            "canonical body including axes at validation. Unique claim-reference arrays are "
            "sets whose canonical order is serialized by the Orchestrator; membership, sides "
            "and object order remain unchanged. Duplicate or foreign references and supplied "
            "incorrect hashes are rejected."
        )
    if schema_id in {
        "pdf-document-review-result@1.0",
        "pdf-document-review-result@2.0",
        "pdf-document-review-result@3.0",
        "pdf-document-review-result@4.0",
        "pdf-document-review-result@5.0",
        "pdf-document-review-result@6.0",
    }:
        anchor = _mapping(_mapping(schema, "$defs"), "anchor")
        anchor.pop("allOf", None)
        anchor_properties = _mapping(anchor, "properties")
        if anchor_properties.pop("quote_sha256", None) is None:
            raise WorkflowSchemaError("PDF document review quote hash is not projectable")
        anchor_required = anchor.get("required")
        if not isinstance(anchor_required, list) or "quote_sha256" not in anchor_required:
            raise WorkflowSchemaError("PDF document review quote hash requirement is invalid")
        anchor_required.remove("quote_sha256")
        _project_pdf_review_recommendation_codex_contract(schema)
        if schema_id in {
            "pdf-document-review-result@4.0",
            "pdf-document-review-result@5.0",
        }:
            _mapping(_mapping(schema, "$defs"), "output").pop("allOf", None)
        if schema_id in {
            "pdf-document-review-result@5.0",
            "pdf-document-review-result@6.0",
        }:
            usage = _mapping(_mapping(schema, "$defs"), "ReviewTextbookUsage")
            usage_properties = _mapping(usage, "properties")
            if usage_properties.pop("usage_sha256", None) is None:
                raise WorkflowSchemaError("textbook usage hash is not projectable")
            usage_required = usage.get("required")
            if not isinstance(usage_required, list) or "usage_sha256" not in usage_required:
                raise WorkflowSchemaError("textbook usage hash requirement is invalid")
            usage_required.remove("usage_sha256")
        if schema_id in {"pdf-document-review-result@3.0", "pdf-document-review-result@6.0"}:
            _project_paired_document_review_v3_codex_contract(
                schema,
                textbook_successor=schema_id == "pdf-document-review-result@6.0",
            )
    _normalize_codex_schema(schema)
    validate_codex_structured_output_schema(schema)
    return schema


def _project_pdf_review_recommendation_codex_contract(schema: dict[str, Any]) -> None:
    """Represent operation-dependent text fields in Codex's supported ``anyOf`` subset."""

    recommendation = _mapping(_mapping(schema, "$defs"), "recommendation")
    properties = _mapping(recommendation, "properties")
    if (
        recommendation.get("type") != "object"
        or recommendation.get("additionalProperties") is not False
        or set(recommendation.get("required", ())) != set(properties)
        or set(properties) != {"operation", "instruction", "before_text", "after_text"}
    ):
        raise WorkflowSchemaError("PDF review recommendation schema is not projectable")

    def text_schema(field_name: str) -> dict[str, Any]:
        field = _mapping(properties, field_name)
        alternatives = field.get("anyOf")
        if not isinstance(alternatives, list):
            raise WorkflowSchemaError("PDF review recommendation text field is not nullable")
        text = tuple(
            value
            for value in alternatives
            if isinstance(value, dict) and value.get("type") == "string"
        )
        null = tuple(
            value
            for value in alternatives
            if isinstance(value, dict) and value.get("type") == "null"
        )
        if len(text) != 1 or len(null) != 1:
            raise WorkflowSchemaError("PDF review recommendation text union is invalid")
        return copy.deepcopy(text[0])

    before_text = text_schema("before_text")
    after_text = text_schema("after_text")
    base = copy.deepcopy(recommendation)
    branches: list[dict[str, Any]] = []
    for operation, before_required, after_required in (
        ("REPLACE", True, True),
        ("INSERT", False, True),
        ("DELETE", True, False),
        ("MOVE", False, False),
        ("REDRAW", False, False),
        ("VERIFY", False, False),
        ("NONE", False, False),
    ):
        branch = copy.deepcopy(base)
        branch_properties = _mapping(branch, "properties")
        branch_properties["operation"] = {"type": "string", "const": operation}
        branch_properties["before_text"] = (
            copy.deepcopy(before_text) if before_required else {"type": "null"}
        )
        branch_properties["after_text"] = (
            copy.deepcopy(after_text) if after_required else {"type": "null"}
        )
        branches.append(branch)
    recommendation.clear()
    recommendation["anyOf"] = branches


def _project_paired_document_review_v3_codex_contract(
    schema: dict[str, Any], *, textbook_successor: bool = False
) -> None:
    """Project canonical conditional review rules into Codex's supported subset.

    The immutable V3 result contract uses ``allOf``/``contains``/conditionals for exact
    cross-field rules. Codex Structured Outputs cannot express those compositions. The worker
    projection therefore retains every field and bound, states the omitted relationships as
    explicit instructions, and leaves the canonical JSON Schema plus Pydantic boundary as the
    authoritative fail-closed validation.
    """

    definitions = _mapping(schema, "$defs")
    output_properties = _mapping(_mapping(definitions, "output"), "properties")
    verification_targets = _mapping(output_properties, "verification_targets")
    if verification_targets.pop("allOf", None) is None:
        raise WorkflowSchemaError("paired V3 verification target coverage is not projectable")
    _append_projection_instruction(
        verification_targets,
        "Return exactly one target for each axis: SCIENTIFIC_ACCURACY, ANSWER_UNIQUENESS, "
        "SOLUTION_CONSISTENCY, CURRICULUM_SCOPE, ORIGINALITY, VISUAL_CONTENT, "
        "EDITORIAL_CLARITY, TYPOGRAPHY, DOCUMENT_STRUCTURE, and ASSESSMENT_BALANCE.",
    )

    unit_check = _mapping(definitions, "unit_check")
    if unit_check.pop("allOf", None) is None:
        raise WorkflowSchemaError("paired V3 unit check conditions are not projectable")
    _append_projection_instruction(
        unit_check,
        "When status is NOT_APPLICABLE, value_expression, expected_unit, and observed_unit "
        "MUST all be null. Otherwise value_expression and expected_unit MUST be non-empty "
        "strings; observed_unit may be a non-empty string or null.",
    )

    item_review = _mapping(definitions, "item_review")
    if item_review.pop("allOf", None) is None:
        raise WorkflowSchemaError("paired V3 item review conditions are not projectable")
    item_properties = _mapping(item_review, "properties")
    _append_projection_instruction(
        _mapping(item_properties, "choice_checks"),
        "Return at least two entries for MULTIPLE_CHOICE or STATEMENT_COMBINATION; return the "
        "empty array for every other response_format.",
    )
    _append_projection_instruction(
        _mapping(item_properties, "evidence_citation_ids"),
        (
            "Return at least one evidence ID when evidence_status is SUPPORTED. When "
            "INSUFFICIENT, include examined textbook citations even though they do not prove "
            "the missing solution or originality comparison."
            if textbook_successor
            else "Return at least one evidence ID when evidence_status is SUPPORTED; return "
            "the empty array when evidence_status is INSUFFICIENT."
        ),
    )


def _project_content_team_image_v9_codex_contract(schema: dict[str, Any]) -> None:
    """Drop only the SVG negation that Codex Structured Outputs cannot express.

    The canonical ``image-result@9.0`` schema and Pydantic model retain the safe-SVG rejection
    rules. This projection is used only for worker decoding; canonical validation runs before an
    artifact can be committed.
    """

    definitions = _mapping(schema, "$defs")
    drawing = _mapping(definitions, "GeneratedVectorDrawingV9")
    properties = _mapping(drawing, "properties")
    svg_overlay = _mapping(properties, "svg_overlay")
    guard = svg_overlay.pop("not", None)
    if not isinstance(guard, dict) or not isinstance(guard.get("anyOf"), list):
        raise WorkflowSchemaError("image-result@9.0 safe-SVG guard is not projectable")


def _project_legacy_editorial_compatibility_codex_contract(
    schema: dict[str, Any],
) -> None:
    """Flatten canonical refinements that Structured Outputs cannot express.

    The canonical proposal schema and Pydantic model remain the authoritative boundary after
    generation. This projection changes only representation: object refinements are merged into
    their local base definition, the ordered two-authority tuple becomes a bounded union, and the
    status/issues conditional is left to the canonical post-generation validator.
    """

    definitions = _mapping(schema, "$defs")
    prefix = "#/$defs/"

    def flatten_refinement(target: dict[str, Any], *, expected_base: str) -> None:
        composition = target.get("allOf")
        if not isinstance(composition, list) or len(composition) != 2:
            raise WorkflowSchemaError("legacy editorial object refinement is invalid")
        base_reference, refinement = composition
        if (
            base_reference != {"$ref": f"{prefix}{expected_base}"}
            or not isinstance(refinement, dict)
            or set(refinement) != {"properties"}
        ):
            raise WorkflowSchemaError("legacy editorial object refinement is not projectable")
        base = copy.deepcopy(_mapping(definitions, expected_base))
        base_properties = _mapping(base, "properties")
        refinement_properties = _mapping(refinement, "properties")
        for name, value in refinement_properties.items():
            if name not in base_properties or not isinstance(value, dict):
                raise WorkflowSchemaError("legacy editorial field refinement is invalid")
            base_properties[name] = copy.deepcopy(value)
        target.clear()
        target.update(base)

    learned_item = _mapping(definitions, "LegacyItemEditorialCompatibilityProposal_learnedItem")
    flatten_refinement(
        _mapping(_mapping(learned_item, "properties"), "item_content"),
        expected_base="LegacyItemEditorialCompatibilityProposal_artifactMember",
    )
    authority_base = _mapping(
        definitions,
        "LegacyItemEditorialCompatibilityProposal_authorityBase",
    )
    flatten_refinement(
        _mapping(_mapping(authority_base, "properties"), "artifact_member"),
        expected_base="LegacyItemEditorialCompatibilityProposal_artifactMember",
    )
    flatten_refinement(
        _mapping(definitions, "LegacyItemEditorialCompatibilityProposal_contentTeamPrompt"),
        expected_base="LegacyItemEditorialCompatibilityProposal_authorityBase",
    )
    flatten_refinement(
        _mapping(definitions, "LegacyItemEditorialCompatibilityProposal_hwpxProfile"),
        expected_base="LegacyItemEditorialCompatibilityProposal_authorityBase",
    )

    proposal = _mapping(definitions, "LegacyItemEditorialCompatibilityProposal")
    conditional_guards = proposal.pop("allOf", None)
    if not isinstance(conditional_guards, list) or len(conditional_guards) != 2:
        raise WorkflowSchemaError("legacy editorial proposal conditional contract is invalid")
    authorities = _mapping(_mapping(proposal, "properties"), "authorities")
    prefix_items = authorities.pop("prefixItems", None)
    if (
        not isinstance(prefix_items, list)
        or len(prefix_items) != 2
        or authorities.pop("items", None) is not False
        or authorities.get("minItems") != 2
        or authorities.get("maxItems") != 2
    ):
        raise WorkflowSchemaError("legacy editorial authority tuple is not projectable")
    authorities["items"] = {"anyOf": prefix_items}


def _project_content_team_authoring_contract(
    schema: dict[str, Any],
    *,
    schema_id: str,
) -> None:
    """Make the model author semantic visuals while EOM derives their renderer route."""

    definitions = _mapping(schema, "$defs")
    draft_name = (
        "AssessmentItemContentV3"
        if schema_id
        in {
            "authoring-result@9.0",
            "authoring-result@10.0",
            "authoring-result@11.0",
            "authoring-result@12.0",
        }
        else "AssessmentItemContentV2"
    )
    draft = _mapping(definitions, draft_name)
    properties = _mapping(draft, "properties")
    visual_layout = properties.pop("visual_layout", None)
    if not isinstance(visual_layout, dict):
        raise WorkflowSchemaError("content-team visual layout is not projectable")
    required = draft.get("required")
    if not isinstance(required, list) or required.count("visual_layout") != 1:
        raise WorkflowSchemaError("content-team visual layout requirement is not projectable")
    draft["required"] = [name for name in required if name != "visual_layout"]

    if schema_id in {
        "authoring-result@10.0",
        "authoring-result@11.0",
        "authoring-result@12.0",
    }:
        output = _mapping(definitions, "ContentTeamAuthoringOutputV10")
        conditional = output.pop("allOf", None)
        if not isinstance(conditional, list) or len(conditional) != 1:
            raise WorkflowSchemaError("authoring evidence conditional is not projectable")

    _mapping(properties, "bottom_stem")["description"] = (
        "Final question sentence only. The reviewed source format shows a trailing score marker, "
        "but this structured field must omit it; put the exact allowed value in score_display."
    )
    _mapping(properties, "score_display")["description"] = (
        "The score printed once after bottom_stem; never repeat the bracketed score inside "
        "bottom_stem."
    )

    _mapping(properties, "visuals")["description"] = (
        "Ordered semantic visual entries from the reviewed content-team program. A table mentioned "
        "or required by the item must be a TABLE entry containing its actual headers and rows; an "
        "IMAGE entry is only an image slot and must never substitute for table data. Use zero, "
        "one, or two entries exactly as the item requires. For two equal kinds, labels must be "
        "(가), then (나); every other visual label is empty. EOM derives the renderer layout from "
        "this ordered structure."
    )
    _mapping(properties, "inquiry")["description"] = (
        "Use the reviewed 탐구/실험 structure only when the item requires it. When present, keep "
        "visuals empty because the program renders the inquiry box as its own layout."
    )
    if schema_id in {
        "authoring-result@10.0",
        "authoring-result@11.0",
        "authoring-result@12.0",
    }:
        explanations = _mapping(definitions, "ContentTeamExplanationSections")
        wrong_answer = _mapping(_mapping(explanations, "properties"), "wrong_answer")
        wrong_answer["description"] = (
            "For a STATEMENT_COMBINATION answer, include exactly one labeled line for each "
            "incorrect statement and no other text. If answer.statement_labels contains all "
            "three labels ㄱ, ㄴ, ㄷ, there is no incorrect statement: return exactly the empty "
            "string. Never add a generic wrong-answer summary to an all-correct item."
        )


def _project_knowledge_analysis_codex_contract(schema: dict[str, Any], *, schema_id: str) -> None:
    """Retain essential text presence while projecting unsupported canonical guards."""

    if schema_id in {
        "knowledge-analysis-proposal-result@10.0",
        "knowledge-analysis-proposal-result@11.0",
    }:
        _strip_knowledge_analysis_codex_guards(schema)
        _strip_solution_analysis_codex_conditionals(schema)
        properties = _mapping(schema, "properties")
        definitions = _mapping(schema, "$defs")
        if _mapping(properties, "output") != {"$ref": "#/$defs/output"}:
            raise WorkflowSchemaError("knowledge analysis output reference is not projectable")
        proposal_reference = _mapping(
            _mapping(_mapping(definitions, "output"), "properties"), "proposal"
        )
        if proposal_reference != {"$ref": "#/$defs/KnowledgeAnalysisWorkerProposalV8"}:
            raise WorkflowSchemaError("solution analysis proposal reference is not projectable")
        return

    if schema_id in {
        "knowledge-analysis-proposal-result@7.0",
        "knowledge-analysis-proposal-result@8.0",
        "knowledge-analysis-proposal-result@9.0",
    }:
        _project_typed_endpoint_identities(schema)
    _strip_knowledge_analysis_codex_guards(schema)
    properties = _mapping(schema, "properties")
    definitions = _mapping(schema, "$defs")
    if _mapping(properties, "output") != {"$ref": "#/$defs/output"}:
        raise WorkflowSchemaError("knowledge analysis output reference is not projectable")
    output = _mapping(definitions, "output")
    proposal_reference = _mapping(_mapping(output, "properties"), "proposal")
    proposal_definition_name = {
        "knowledge-analysis-proposal-result@1.0": "KnowledgeAnalysisWorkerProposal",
        "knowledge-analysis-proposal-result@2.0": "KnowledgeAnalysisWorkerProposal",
        "knowledge-analysis-proposal-result@3.0": "KnowledgeAnalysisWorkerProposalV2",
        "knowledge-analysis-proposal-result@4.0": "KnowledgeAnalysisWorkerProposalV3",
        "knowledge-analysis-proposal-result@5.0": "KnowledgeAnalysisWorkerProposalV4",
        "knowledge-analysis-proposal-result@6.0": "KnowledgeAnalysisWorkerProposalV4",
        "knowledge-analysis-proposal-result@7.0": "KnowledgeAnalysisWorkerProposalV5",
        "knowledge-analysis-proposal-result@8.0": "KnowledgeAnalysisWorkerProposalV6",
        "knowledge-analysis-proposal-result@9.0": "KnowledgeAnalysisWorkerProposalV7",
    }[schema_id]
    if proposal_reference != {"$ref": f"#/$defs/{proposal_definition_name}"}:
        raise WorkflowSchemaError("knowledge analysis proposal reference is not projectable")
    proposal = _mapping(definitions, proposal_definition_name)
    normalized_markdown = _mapping(_mapping(proposal, "properties"), "normalized_markdown")
    if (
        normalized_markdown.get("type") != "string"
        or normalized_markdown.get("minLength") != 1
        or "pattern" in normalized_markdown
    ):
        raise WorkflowSchemaError(
            "knowledge analysis normalized Markdown contract is not projectable"
        )
    # Codex strict output does not accept minLength. This equivalent lower-bound pattern prevents
    # an empty proposal from passing worker-side validation only to fail the canonical boundary.
    normalized_markdown["pattern"] = r"[\s\S]+"


def _strip_solution_analysis_codex_conditionals(value: object) -> None:
    """Leave cross-field non-empty alternatives to canonical/Pydantic validation.

    Codex strict output cannot express the V10 rule requiring at least one of the pattern or
    item-element reference arrays. Both arrays remain typed and bounded in the generation schema;
    the canonical schema and typed commit boundary enforce the disjunction.
    """

    if isinstance(value, dict):
        alternatives = value.get("anyOf")
        if (
            value.get("type") == "object"
            and isinstance(alternatives, list)
            and all(
                isinstance(branch, dict) and set(branch) == {"properties"}
                for branch in alternatives
            )
        ):
            value.pop("anyOf")
        for child in value.values():
            _strip_solution_analysis_codex_conditionals(child)
    elif isinstance(value, list):
        for child in value:
            _strip_solution_analysis_codex_conditionals(child)


def _project_typed_endpoint_identities(schema: dict[str, Any]) -> None:
    """Expand canonical all-of refinements into Codex-compatible strict any-of branches."""

    definitions = _mapping(schema, "$defs")
    proposal_name = next(
        name
        for name in (
            "KnowledgeAnalysisWorkerProposalV7",
            "KnowledgeAnalysisWorkerProposalV6",
            "KnowledgeAnalysisWorkerProposalV5",
        )
        if name in definitions
    )
    proposal = _mapping(definitions, proposal_name)
    proposal_properties = _mapping(proposal, "properties")
    for property_name in ("nodes", "edges"):
        collection = _mapping(proposal_properties, property_name)
        items = _mapping(collection, "items")
        reference = items.get("$ref")
        prefix = "#/$defs/"
        if not isinstance(reference, str) or not reference.startswith(prefix):
            raise WorkflowSchemaError("typed identity collection is not projectable")
        definition_name = reference.removeprefix(prefix)
        typed_definition = _mapping(definitions, definition_name)
        composition = typed_definition.get("allOf")
        if not isinstance(composition, list) or len(composition) != 2:
            raise WorkflowSchemaError("typed identity contract composition is invalid")
        base_reference = composition[0]
        refinements = composition[1]
        if not isinstance(base_reference, dict) or set(base_reference) != {"$ref"}:
            raise WorkflowSchemaError("typed identity base reference is invalid")
        base_name = base_reference["$ref"]
        if not isinstance(base_name, str) or not base_name.startswith(prefix):
            raise WorkflowSchemaError("typed identity base reference is not local")
        base = _mapping(definitions, base_name.removeprefix(prefix))
        alternatives = refinements.get("anyOf")
        if not isinstance(alternatives, list) or not alternatives:
            raise WorkflowSchemaError("typed identity refinements are empty")
        projected: list[dict[str, Any]] = []
        for refinement in alternatives:
            if not isinstance(refinement, dict) or refinement.get("type") != "object":
                raise WorkflowSchemaError("typed identity refinement is invalid")
            branch = copy.deepcopy(base)
            branch_properties = _mapping(branch, "properties")
            refinement_properties = _mapping(refinement, "properties")
            for name, value in refinement_properties.items():
                if not isinstance(value, dict) or name not in branch_properties:
                    raise WorkflowSchemaError("typed identity field refinement is invalid")
                branch_properties[name] = copy.deepcopy(value)
            projected.append(branch)
        typed_definition.clear()
        typed_definition["anyOf"] = projected


def _strip_knowledge_analysis_codex_guards(value: object) -> None:
    """Leave cross-field/path guards to canonical schema + typed validation after generation."""

    if isinstance(value, dict):
        value.pop("not", None)
        for child in value.values():
            _strip_knowledge_analysis_codex_guards(child)
    elif isinstance(value, list):
        for child in value:
            _strip_knowledge_analysis_codex_guards(child)


def _prune_unreferenced_definitions(schema: dict[str, Any]) -> None:
    """Retain only the local definitions reachable from the projected schema root.

    The v4 knowledge type catalog intentionally contains contracts used by other application
    boundaries.  Bundling every sibling definition into Codex's response schema would make those
    unrelated contracts part of this worker protocol and can retain composition keywords that the
    Codex strict-output subset does not support.  Reachability is a graph traversal over immutable
    local ``$ref`` edges; a missing target fails closed instead of being silently discarded.
    """

    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):
        return

    prefix = "#/$defs/"

    def referenced_names(value: object, *, include_definitions: bool) -> set[str]:
        found: set[str] = set()
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str) and reference.startswith(prefix):
                found.add(reference.removeprefix(prefix))
            for key, child in value.items():
                if key != "$defs" or include_definitions:
                    found.update(referenced_names(child, include_definitions=include_definitions))
        elif isinstance(value, list):
            for child in value:
                found.update(referenced_names(child, include_definitions=include_definitions))
        return found

    pending = list(referenced_names(schema, include_definitions=False))
    reachable: set[str] = set()
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        definition = definitions.get(name)
        if not isinstance(definition, dict):
            raise WorkflowSchemaError(f"projected schema references missing definition: {name}")
        reachable.add(name)
        pending.extend(referenced_names(definition, include_definitions=True) - reachable)

    schema["$defs"] = {
        name: definition for name, definition in definitions.items() if name in reachable
    }


def validate_codex_structured_output_schema(schema: dict[str, Any]) -> None:
    """Fail before worker submission when a result projection is not strict-output compatible."""

    unsupported = {
        "allOf",
        "oneOf",
        "not",
        "dependentRequired",
        "dependentSchemas",
        "if",
        "then",
        "else",
        "prefixItems",
        "minLength",
        "maxLength",
        "uniqueItems",
    }
    unsupported_pattern_tokens = ("(?=", "(?!", "(?<=", "(?<!")

    def visit(value: object, path: tuple[str, ...]) -> None:
        if not isinstance(value, dict):
            return
        if "$ref" in value and set(value) != {"$ref"}:
            raise WorkflowSchemaError(
                f"Codex result reference has sibling keywords at {'.'.join(path) or '$'}"
            )
        found = unsupported.intersection(value)
        if found:
            raise WorkflowSchemaError(
                f"Codex result schema uses unsupported keyword at {'.'.join(path) or '$'}: "
                f"{sorted(found)[0]}"
            )
        pattern = value.get("pattern")
        if isinstance(pattern, str) and any(
            token in pattern for token in unsupported_pattern_tokens
        ):
            raise WorkflowSchemaError(
                f"Codex result schema uses unsupported regex lookaround at {'.'.join(path) or '$'}"
            )
        if "properties" in value:
            properties = _mapping(value, "properties")
            if value.get("type") != "object" or value.get("additionalProperties") is not False:
                raise WorkflowSchemaError(
                    f"Codex result object is not closed at {'.'.join(path) or '$'}"
                )
            required = value.get("required")
            if not isinstance(required, list) or set(required) != set(properties):
                raise WorkflowSchemaError(
                    f"Codex result object fields are not all required at {'.'.join(path) or '$'}"
                )
            for name, child in properties.items():
                if not isinstance(child, dict) or not any(
                    key in child for key in ("type", "$ref", "anyOf")
                ):
                    raise WorkflowSchemaError(
                        f"Codex result property has no explicit type at "
                        f"{'.'.join((*path, 'properties', name))}"
                    )
                visit(child, (*path, "properties", name))
        if isinstance(value.get("items"), dict):
            visit(value["items"], (*path, "items"))
        elif value.get("type") == "array":
            raise WorkflowSchemaError(
                f"Codex result array has no item schema at {'.'.join(path) or '$'}"
            )
        if isinstance(value.get("anyOf"), list):
            for index, child in enumerate(value["anyOf"]):
                visit(child, (*path, "anyOf", str(index)))
        definitions = value.get("$defs")
        if isinstance(definitions, dict):
            for name, child in definitions.items():
                visit(child, (*path, "$defs", name))

    if schema.get("type") != "object":
        raise WorkflowSchemaError("Codex result schema root must be an object")
    visit(schema, ())


def result_schema_protocol(schema_id: str) -> WorkflowProtocolVersion:
    try:
        return cast(WorkflowProtocolVersion, RESULT_SCHEMA_PROTOCOLS[schema_id])
    except KeyError as exc:
        raise WorkflowSchemaError(f"unknown role result schema: {schema_id}") from exc


def role_schema_bundle_hash(protocol_version: str = "workflow-role/1.0.1") -> str:
    if protocol_version == "workflow-role/1.0.1":
        legacy_files = tuple(sorted({*ROLE_RESULT_SCHEMAS.values(), *INPUT_SCHEMA_FILES.values()}))
        legacy_names = tuple(
            sorted(
                {
                    *(RESULT_SCHEMA_FILES[schema_id] for schema_id in ROLE_RESULT_SCHEMAS.values()),
                    *INPUT_SCHEMA_FILES.values(),
                }
            )
        )
        if len(legacy_files) != 8:
            raise WorkflowSchemaError("legacy workflow schema inventory changed")
        return content_sha256(
            {
                file_name: load_json_schema(
                    ROLE_RESOURCE_ROOT.joinpath(file_name), f"roles/{file_name}"
                )
                for file_name in legacy_names
            }
        )
    try:
        input_files = PROTOCOL_INPUT_SCHEMAS[protocol_version]
    except KeyError as exc:
        raise WorkflowSchemaError(f"unknown workflow protocol: {protocol_version}") from exc
    result_ids = sorted(
        schema_id
        for schema_id, version in RESULT_SCHEMA_PROTOCOLS.items()
        if version == protocol_version
    )
    schemas = {
        **{
            f"input/{role}": load_role_input_schema(role, protocol_version)
            for role in sorted(input_files)
        },
        **{f"result/{schema_id}": load_role_result_schema(schema_id) for schema_id in result_ids},
    }
    return content_sha256(schemas)


def _inline_catalog_schema(
    schema: dict[str, Any], *, require_reference_closure: bool = False
) -> dict[str, Any]:
    reference = "eom://schemas/item-registry/assessment-item-content-v1"
    serialized = json.dumps(schema, ensure_ascii=True)
    if reference not in serialized:
        bundled = schema
    else:
        bundled = _inline_assessment_item_schema(schema, reference)
    knowledge_contracts = (
        (
            "eom://schemas/knowledge/review-textbook-evidence/1.0",
            "review-textbook-evidence",
            "ReviewTextbookEvidence",
        ),
        (
            "https://eom.local/schemas/knowledge/review-textbook-usage-v1.schema.json",
            "review-textbook-usage",
            "ReviewTextbookUsage",
        ),
        (
            "eom://schemas/knowledge/educational-retrieval-requirement/1.0",
            "educational-retrieval-requirement",
            "EducationalRetrievalRequirement",
        ),
        (
            "eom://schemas/knowledge/evidence-bundle-publication-result/3.0",
            "evidence-bundle-publication-result-v3",
            "EvidenceBundlePublicationResultV3",
        ),
        (
            "eom://schemas/knowledge/evidence-bundle-publication-result/4.0",
            "evidence-bundle-publication-result-v4",
            "EvidenceBundlePublicationResultV4",
        ),
        (
            "eom://schemas/knowledge/item-inference-transfer-pair-result/1.1",
            "item-inference-transfer-pair-result-v1.1",
            "InferenceTransferPairResultV11",
        ),
        (
            "eom://schemas/knowledge/item-inference-transfer/1.0",
            "item-inference-transfer",
            "InferenceTransfer",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-request/2.0",
            "knowledge-analysis-request-v2",
            "KnowledgeAnalysisRequestV2",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-request/3.0",
            "knowledge-analysis-request-v3",
            "KnowledgeAnalysisRequestV3",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-request/4.0",
            "knowledge-analysis-request-v4",
            "KnowledgeAnalysisRequestV4",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-request/5.0",
            "knowledge-analysis-request-v5",
            "KnowledgeAnalysisRequestV5",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-request/6.0",
            "knowledge-analysis-request-v6",
            "KnowledgeAnalysisRequestV6",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-request/7.0",
            "knowledge-analysis-request-v7",
            "KnowledgeAnalysisRequestV7",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-request/8.0",
            "knowledge-analysis-request-v8",
            "KnowledgeAnalysisRequestV8",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-request/9.0",
            "knowledge-analysis-request-v9",
            "KnowledgeAnalysisRequestV9",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-request/10.0",
            "knowledge-analysis-request-v10",
            "KnowledgeAnalysisRequestV10",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-request/11.0",
            "knowledge-analysis-request-v11",
            "KnowledgeAnalysisRequestV11",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/1.0",
            "knowledge-analysis-worker-proposal",
            "KnowledgeAnalysisWorkerProposal",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/2.0",
            "knowledge-analysis-worker-proposal-v2",
            "KnowledgeAnalysisWorkerProposalV2",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/3.0",
            "knowledge-analysis-worker-proposal-v3",
            "KnowledgeAnalysisWorkerProposalV3",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/4.0",
            "knowledge-analysis-worker-proposal-v4",
            "KnowledgeAnalysisWorkerProposalV4",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/5.0",
            "knowledge-analysis-worker-proposal-v5",
            "KnowledgeAnalysisWorkerProposalV5",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/6.0",
            "knowledge-analysis-worker-proposal-v6",
            "KnowledgeAnalysisWorkerProposalV6",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/7.0",
            "knowledge-analysis-worker-proposal-v7",
            "KnowledgeAnalysisWorkerProposalV7",
        ),
        (
            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/8.0",
            "knowledge-analysis-worker-proposal-v8",
            "KnowledgeAnalysisWorkerProposalV8",
        ),
    )
    for contract_reference, catalog_name, definition_name in knowledge_contracts:
        if contract_reference in json.dumps(bundled, ensure_ascii=True):
            bundled = _inline_knowledge_contract(
                bundled,
                reference=contract_reference,
                catalog_name=catalog_name,
                definition_name=definition_name,
                close_type_dependencies=require_reference_closure,
            )
    legacy_contracts = (
        (
            "eom://schemas/legacy-assessment/legacy-item-extraction-request/1.0",
            "legacy-item-extraction-request",
            "LegacyItemExtractionRequest",
        ),
        (
            "eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0",
            "legacy-item-extraction-result",
            "LegacyItemExtractionResult",
        ),
        (
            "eom://schemas/legacy-assessment/legacy-item-editorial-compatibility-request/1.0",
            "legacy-item-editorial-compatibility-request",
            "LegacyItemEditorialCompatibilityRequest",
        ),
        (
            "eom://schemas/legacy-assessment/legacy-item-editorial-compatibility-proposal/1.0",
            "legacy-item-editorial-compatibility-proposal",
            "LegacyItemEditorialCompatibilityProposal",
        ),
    )
    for contract_reference, catalog_name, definition_name in legacy_contracts:
        if contract_reference in json.dumps(bundled, ensure_ascii=True):
            bundled = _inline_legacy_assessment_contract(
                bundled,
                reference=contract_reference,
                catalog_name=catalog_name,
                definition_name=definition_name,
            )
    creative_input = "eom://schemas/external-item/learning-work-input/1.0"
    creative_result = "eom://schemas/external-item/learning-result/1.0"
    if creative_input in json.dumps(bundled, ensure_ascii=True):
        bundled = _inline_external_item_learning_contract(bundled, result=False)
    if creative_result in json.dumps(bundled, ensure_ascii=True):
        bundled = _inline_external_item_learning_contract(bundled, result=True)
    if "eom://schemas/external-item/learning-result/2.0" in json.dumps(bundled, ensure_ascii=True):
        bundled = _inline_external_item_learning_result_v2_contract(bundled)
    Draft202012Validator.check_schema(bundled)
    if require_reference_closure:
        _validate_local_reference_closure(bundled)
    return bundled


def _inline_legacy_assessment_contract(
    schema: dict[str, Any], *, reference: str, catalog_name: str, definition_name: str
) -> dict[str, Any]:
    """Close one extraction role schema over its immutable Catalog-owned dependencies."""

    from eom_catalog_contracts import load_schema

    sources = (
        (reference, definition_name, copy.deepcopy(load_schema(catalog_name))),
        (
            "eom://schemas/legacy-assessment/legacy-assessment-types/1.0",
            "LegacyAssessmentTypes",
            copy.deepcopy(load_schema("legacy-assessment-types")),
        ),
        (
            "eom://schemas/item-origin/item-origin-types/1.0",
            "ItemOriginTypes",
            copy.deepcopy(load_schema("item-origin-types")),
        ),
        (
            "eom://schemas/item-registry/assessment-item-content-v1",
            "AssessmentItemContent",
            copy.deepcopy(load_schema("assessment-item-content")),
        ),
    )

    return _inline_contract_sources(schema, sources)


def _inline_external_item_learning_contract(
    schema: dict[str, Any], *, result: bool
) -> dict[str, Any]:
    """Close only the source/page or result/Item references used by one role."""

    from eom_catalog_contracts import load_schema

    references = (
        (
            (
                "eom://schemas/external-item/learning-result/1.0",
                "external-item-learning-result-v1",
                "ExternalItemLearningResult",
            ),
            (
                "eom://schemas/item-registry/assessment-item-content-v1",
                "assessment-item-content",
                "AssessmentItemContent",
            ),
        )
        if result
        else (
            (
                "eom://schemas/external-item/learning-work-input/1.0",
                "external-item-learning-work-input-v1",
                "ExternalItemLearningWorkInput",
            ),
            (
                "eom://schemas/external-item/learning-source/1.0",
                "external-item-learning-source-v1",
                "ExternalItemLearningSource",
            ),
            (
                "eom://schemas/external-item/preview-manifest/1.0",
                "external-item-preview-manifest-v1",
                "ExternalItemPreviewManifest",
            ),
            (
                "eom://schemas/external-item/learning-page-set/1.0",
                "external-item-learning-page-set-v1",
                "ExternalItemLearningPageSet",
            ),
        )
    )
    sources = tuple(
        (reference, definition, copy.deepcopy(load_schema(name)))
        for reference, name, definition in references
    )
    return _inline_contract_sources(schema, sources)


def _inline_external_item_learning_result_v2_contract(schema: dict[str, Any]) -> dict[str, Any]:
    """Successor only: reuse historical region types without changing their bytes."""
    from eom_catalog_contracts import load_schema

    references = (
        (
            "eom://schemas/external-item/learning-result/2.0",
            "external-item-learning-result-v2",
            "ExternalItemLearningResultV2",
        ),
        (
            "eom://schemas/external-item/learning-result/1.0",
            "external-item-learning-result-v1",
            "ExternalItemLearningResult",
        ),
        (
            "eom://schemas/external-item/source-item-draft/1.0",
            "creative-source-item-draft-v1",
            "CreativeSourceItemDraft",
        ),
        (
            "eom://schemas/item-registry/assessment-item-content-v1",
            "assessment-item-content",
            "AssessmentItemContent",
        ),
    )
    return _inline_contract_sources(
        schema,
        tuple(
            (reference, name, copy.deepcopy(load_schema(resource)))
            for reference, resource, name in references
        ),
    )


def _inline_contract_sources(
    schema: dict[str, Any],
    sources: tuple[tuple[str, str, dict[str, Any]], ...],
) -> dict[str, Any]:
    """Bundle exact Catalog schemas with collision-free local definition names."""

    def rewrite(value: object, *, local_prefix: str | None = None) -> object:
        if isinstance(value, dict):
            rewritten: dict[str, Any] = {}
            for key, item in value.items():
                if key == "$ref" and isinstance(item, str):
                    replacement: str | None = None
                    for source_id, prefix, _ in sources:
                        if item == source_id:
                            replacement = f"#/$defs/{prefix}"
                            break
                        fragment = source_id + "#/$defs/"
                        if item.startswith(fragment):
                            replacement = f"#/$defs/{prefix}_" + item.removeprefix(fragment)
                            break
                    if replacement is not None:
                        rewritten[key] = replacement
                    elif local_prefix is not None and item.startswith("#/$defs/"):
                        rewritten[key] = f"#/$defs/{local_prefix}_" + item.removeprefix("#/$defs/")
                    else:
                        rewritten[key] = item
                else:
                    rewritten[key] = rewrite(item, local_prefix=local_prefix)
            return rewritten
        if isinstance(value, list):
            return [rewrite(item, local_prefix=local_prefix) for item in value]
        return value

    bundled = rewrite(schema)
    if not isinstance(bundled, dict):
        raise WorkflowSchemaError("bundled Catalog role schema is not an object")
    definitions = bundled.setdefault("$defs", {})
    if not isinstance(definitions, dict):
        raise WorkflowSchemaError("bundled Catalog definitions are not an object")
    for _, prefix, source in sources:
        body = {
            key: item
            for key, item in source.items()
            if key not in {"$schema", "$id", "title", "$defs"}
        }
        rewritten_body = rewrite(body, local_prefix=prefix)
        if not isinstance(rewritten_body, dict):
            raise WorkflowSchemaError("Catalog contract body is not an object")
        definitions[prefix] = rewritten_body
        source_definitions = source.get("$defs", {})
        if not isinstance(source_definitions, dict):
            raise WorkflowSchemaError("Catalog contract definitions are invalid")
        for name, value in source_definitions.items():
            definitions[f"{prefix}_{name}"] = rewrite(value, local_prefix=prefix)
    return bundled


def _inline_assessment_item_schema(schema: dict[str, Any], reference: str) -> dict[str, Any]:
    from eom_catalog_contracts import load_schema

    canonical = load_schema("assessment-item-content")

    def visit(value: object) -> object:
        if isinstance(value, dict):
            if value == {"$ref": reference}:
                return copy.deepcopy(canonical)
            return {key: visit(item) for key, item in value.items()}
        if isinstance(value, list):
            return [visit(item) for item in value]
        return value

    bundled = visit(schema)
    if not isinstance(bundled, dict):
        raise WorkflowSchemaError("bundled role result schema is not an object")
    return bundled


def _inline_knowledge_contract(
    schema: dict[str, Any],
    *,
    reference: str,
    catalog_name: str,
    definition_name: str,
    close_type_dependencies: bool,
) -> dict[str, Any]:
    """Bundle a Catalog-owned contract for Codex and offline JSON Schema validation."""

    from eom_catalog_contracts import load_schema

    root = copy.deepcopy(load_schema(catalog_name))
    solution_types_v2_reference = (
        "eom://schemas/knowledge/knowledge-analysis-solution-types/2.0#/$defs/"
    )
    solution_types_v2 = (
        copy.deepcopy(load_schema("knowledge-analysis-solution-types-v2"))
        if solution_types_v2_reference in json.dumps(root, ensure_ascii=True)
        else None
    )
    solution_types_v1 = copy.deepcopy(load_schema("knowledge-analysis-solution-types-v1"))
    evidence_v5 = copy.deepcopy(load_schema("evidence-bundle-manifest-v5"))
    types_v5 = copy.deepcopy(load_schema("knowledge-analysis-types-v5"))
    types_v4 = copy.deepcopy(load_schema("knowledge-analysis-types-v4"))
    types_v3 = copy.deepcopy(load_schema("knowledge-analysis-types-v3"))
    types_v2 = copy.deepcopy(load_schema("knowledge-analysis-types-v2"))
    types_v1 = copy.deepcopy(load_schema("knowledge-types"))
    legacy_assessment_types = copy.deepcopy(load_schema("legacy-assessment-types"))
    item_origin_types = copy.deepcopy(load_schema("item-origin-types"))
    v5_reference = "eom://schemas/knowledge/knowledge-analysis-types/5.0#/$defs/"
    v4_reference = "eom://schemas/knowledge/knowledge-analysis-types/4.0#/$defs/"
    v3_reference = "eom://schemas/knowledge/knowledge-analysis-types/3.0#/$defs/"
    v2_reference = "eom://schemas/knowledge/knowledge-analysis-types/2.0#/$defs/"
    v1_reference = "eom://schemas/knowledge/knowledge-types-v1#/$defs/"
    legacy_assessment_reference = (
        "eom://schemas/legacy-assessment/legacy-assessment-types/1.0#/$defs/"
    )
    item_origin_reference = "eom://schemas/item-origin/item-origin-types/1.0#/$defs/"
    solution_types_reference = (
        "eom://schemas/knowledge/knowledge-analysis-solution-types/1.0#/$defs/"
    )
    evidence_v5_reference = "eom://schemas/knowledge/evidence-bundle-manifest/5.0#/$defs/"

    def rewrite(value: object, *, local_prefix: str | None = None) -> object:
        if isinstance(value, dict):
            rewritten: dict[str, Any] = {}
            for key, item in value.items():
                if key == "$ref" and isinstance(item, str):
                    if item == reference:
                        rewritten[key] = f"#/$defs/{definition_name}"
                    elif item.startswith(reference + "#/$defs/"):
                        rewritten[key] = f"#/$defs/{definition_name}_" + item.removeprefix(
                            reference + "#/$defs/"
                        )
                    elif item.startswith(v5_reference):
                        rewritten[key] = "#/$defs/AnalysisV5_" + item.removeprefix(v5_reference)
                    elif item.startswith(v4_reference):
                        rewritten[key] = "#/$defs/AnalysisV4_" + item.removeprefix(v4_reference)
                    elif item.startswith(v3_reference):
                        rewritten[key] = "#/$defs/AnalysisV3_" + item.removeprefix(v3_reference)
                    elif item.startswith(v2_reference):
                        rewritten[key] = "#/$defs/AnalysisV2_" + item.removeprefix(v2_reference)
                    elif item.startswith(v1_reference):
                        rewritten[key] = "#/$defs/KnowledgeV1_" + item.removeprefix(v1_reference)
                    elif item.startswith(legacy_assessment_reference):
                        rewritten[key] = "#/$defs/LegacyAssessment_" + item.removeprefix(
                            legacy_assessment_reference
                        )
                    elif item.startswith(item_origin_reference):
                        rewritten[key] = "#/$defs/ItemOrigin_" + item.removeprefix(
                            item_origin_reference
                        )
                    elif item.startswith(solution_types_reference):
                        rewritten[key] = "#/$defs/SolutionV1_" + item.removeprefix(
                            solution_types_reference
                        )
                    elif item.startswith(solution_types_v2_reference):
                        rewritten[key] = "#/$defs/SolutionV2_" + item.removeprefix(
                            solution_types_v2_reference
                        )
                    elif item.startswith(evidence_v5_reference):
                        rewritten[key] = "#/$defs/EvidenceV5_" + item.removeprefix(
                            evidence_v5_reference
                        )
                    elif local_prefix is not None and item.startswith("#/$defs/"):
                        rewritten[key] = f"#/$defs/{local_prefix}_" + item.removeprefix("#/$defs/")
                    else:
                        rewritten[key] = item
                else:
                    rewritten[key] = rewrite(item, local_prefix=local_prefix)
            return rewritten
        if isinstance(value, list):
            return [rewrite(item, local_prefix=local_prefix) for item in value]
        return value

    def body(value: dict[str, Any], *, local_prefix: str | None = None) -> dict[str, Any]:
        cleaned = {
            key: item
            for key, item in value.items()
            if key not in {"$schema", "$id", "title", "$defs"}
        }
        rewritten = rewrite(cleaned, local_prefix=local_prefix)
        if not isinstance(rewritten, dict):
            raise WorkflowSchemaError("knowledge contract body is not an object")
        return rewritten

    bundled = rewrite(schema)
    if not isinstance(bundled, dict):
        raise WorkflowSchemaError("bundled role schema is not an object")
    definitions = bundled.setdefault("$defs", {})
    if not isinstance(definitions, dict):
        raise WorkflowSchemaError("bundled role schema definitions are not an object")
    definitions[definition_name] = body(root, local_prefix=definition_name)
    root_definitions = root.get("$defs", {})
    if not isinstance(root_definitions, dict):
        raise WorkflowSchemaError("knowledge contract definitions are not an object")
    for name, value in root_definitions.items():
        definitions[f"{definition_name}_{name}"] = rewrite(value, local_prefix=definition_name)
    serialized_root = json.dumps(root, ensure_ascii=True)
    if close_type_dependencies:
        type_families: tuple[tuple[str, str, dict[str, Any]], ...] = (
            (v5_reference, "AnalysisV5", types_v5),
            (v4_reference, "AnalysisV4", types_v4),
            (v3_reference, "AnalysisV3", types_v3),
            (v2_reference, "AnalysisV2", types_v2),
            (v1_reference, "KnowledgeV1", types_v1),
            (legacy_assessment_reference, "LegacyAssessment", legacy_assessment_types),
            (item_origin_reference, "ItemOrigin", item_origin_types),
            (solution_types_reference, "SolutionV1", solution_types_v1),
            (evidence_v5_reference, "EvidenceV5", evidence_v5),
        )
        if solution_types_v2 is not None:
            type_families += ((solution_types_v2_reference, "SolutionV2", solution_types_v2),)
        selected_prefixes: set[str] = set()
        pending: list[dict[str, Any]] = [root]
        while pending:
            serialized_source = json.dumps(pending.pop(), ensure_ascii=True)
            for family_reference, prefix, source in type_families:
                if prefix not in selected_prefixes and family_reference in serialized_source:
                    selected_prefixes.add(prefix)
                    pending.append(source)
        type_sources = [
            (prefix, source) for _, prefix, source in type_families if prefix in selected_prefixes
        ]
    else:
        # Preserve the byte-for-byte historical v1.4--v1.8 bundle projection.
        type_sources = [("AnalysisV2", types_v2), ("KnowledgeV1", types_v1)]
        if v4_reference in serialized_root:
            type_sources.insert(0, ("AnalysisV4", types_v4))
        if v5_reference in serialized_root:
            type_sources.insert(0, ("AnalysisV5", types_v5))
        if v3_reference in serialized_root:
            type_sources.insert(0, ("AnalysisV3", types_v3))
    for prefix, source in type_sources:
        source_definitions = source.get("$defs")
        if not isinstance(source_definitions, dict):
            raise WorkflowSchemaError("knowledge type definitions are not an object")
        for name, value in source_definitions.items():
            definitions[f"{prefix}_{name}"] = rewrite(value, local_prefix=prefix)
    return bundled


def _validate_local_reference_closure(schema: dict[str, Any]) -> None:
    """Require every reference in a self-contained role schema to resolve locally."""

    def resolve(reference: str) -> None:
        if reference == "#":
            return
        if not reference.startswith("#/"):
            raise WorkflowSchemaError(f"workflow schema reference is external: {reference}")
        current: object = schema
        for raw_token in reference[2:].split("/"):
            token = raw_token.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict) and token in current:
                current = current[token]
            elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
                current = current[int(token)]
            else:
                raise WorkflowSchemaError(f"workflow schema reference is unresolved: {reference}")

    def visit(value: object) -> None:
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str):
                resolve(reference)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)


def _project_creative_answer_representations(schema: dict[str, Any]) -> None:
    """Make the existing answer XOR rules visible to generation, not just admission.

    Copy only the small schema nodes, never source/results. Canonical contracts
    and historical V1 generation stay unchanged; invalid responses are not repaired.
    """
    from eom_catalog_contracts.creative_source_draft import CREATIVE_SOURCE_STATEMENT_GUIDANCE
    from eom_catalog_contracts.external_item_learning_result_v2 import (
        INDEPENDENT_SOURCE_SOLUTION_GUIDANCE,
    )

    definitions = _mapping(schema, "$defs")
    draft = _mapping(definitions, "CreativeSourceItemDraft")
    solution = _mapping(definitions, "AssessmentItemContent_solution")
    branches = []
    for interaction, used, unused, maximum in (
        ("singleChoice", "correct_choice_ids", "accepted_answers", 1),
        ("constructedResponse", "accepted_answers", "correct_choice_ids", 20),
    ):
        branch = copy.deepcopy(draft)
        properties = _mapping(branch, "properties")
        _append_projection_instruction(
            _mapping(properties, "body"), CREATIVE_SOURCE_STATEMENT_GUIDANCE
        )
        properties["interaction"] = {"$ref": f"#/$defs/AssessmentItemContent_{interaction}"}
        answer = copy.deepcopy(solution)
        answer_properties = _mapping(answer, "properties")
        _append_projection_instruction(
            _mapping(answer_properties, "statement_explanations"),
            CREATIVE_SOURCE_STATEMENT_GUIDANCE,
        )
        _mapping(answer_properties, used).update(minItems=1, maxItems=maximum)
        _mapping(answer_properties, unused)["maxItems"] = 0
        properties["solution"] = answer
        branches.append(branch)
    draft.clear()
    draft["anyOf"] = branches

    report = _mapping(definitions, "ExternalItemLearningResultV2_solutionReport")
    alternatives = []
    for state, answer_field in (
        ("DETERMINED", "answer_labels"),
        ("DETERMINED", "accepted_answers"),
        ("UNDETERMINED", None),
    ):
        branch = copy.deepcopy(report)
        properties = _mapping(branch, "properties")
        properties["answer_state"] = {"type": "string", "const": state}
        for key in ("answer_labels", "accepted_answers"):
            _mapping(properties, key).update(
                {"minItems": 1} if key == answer_field else {"maxItems": 0}
            )
        if state == "UNDETERMINED":
            properties["answer_cross_check"] = {"type": "string", "const": "NOT_DETERMINED"}
        else:
            _mapping(properties, "solution_steps")["minItems"] = 1
            properties["answer_cross_check"] = {
                "type": "string",
                "enum": ["MATCHES_EDITORIAL_SOLUTION", "DISAGREES", "NO_EDITORIAL_SOLUTION"],
            }
        alternatives.append(branch)
    report.clear()
    report["anyOf"] = alternatives
    report["description"] = INDEPENDENT_SOURCE_SOLUTION_GUIDANCE


def _project_external_item_learning_codex_contract(
    schema: dict[str, Any], *, result_definition: str = "ExternalItemLearningResult"
) -> None:
    """Expose only Codex-supported syntax; canonical validation remains authoritative."""

    definitions = _mapping(schema, "$defs")
    if result_definition == "ExternalItemLearningResultV2":
        from eom_catalog_contracts.creative_source_draft import (
            creative_source_region_policy_description,
        )

        region_map = _mapping(definitions, "ExternalItemLearningResult_contentRegionMap")
        _append_projection_instruction(region_map, creative_source_region_policy_description())
    result = _mapping(definitions, result_definition)
    properties = _mapping(result, "properties")
    if properties.pop("result_sha256", None) is None:
        raise WorkflowSchemaError("creative learning result hash is not projectable")
    required = result.get("required")
    if not isinstance(required, list) or "result_sha256" not in required:
        raise WorkflowSchemaError("creative learning result hash requirement is invalid")
    required.remove("result_sha256")
    _append_projection_instruction(
        result,
        "Do not output result_sha256; the Orchestrator derives it from the exact submitted "
        "proposal body. Source identity, regions, and Item content remain subject to canonical "
        "JSON Schema and Pydantic validation.",
    )
    safe_text = _mapping(definitions, "ExternalItemLearningResult_safeText")
    for definition, field, maximum in (
        ("ExternalItemLearningResult_region", "observed_text", 6000),
        ("ExternalItemLearningResult_solutionStep", "reasoning_summary", 3000),
        ("ExternalItemLearningResult_conflict", "description", 2000),
    ):
        field_schema = _mapping(_mapping(_mapping(definitions, definition), "properties"), field)
        branches = field_schema.get("allOf")
        if branches != [
            {"$ref": "#/$defs/ExternalItemLearningResult_safeText"},
            {"maxLength": maximum},
        ]:
            raise WorkflowSchemaError("creative learning safe text is not projectable")
        field_schema.clear()
        field_schema.update(copy.deepcopy(safe_text))
        field_schema["maxLength"] = maximum


def _project_knowledge_authoring_content(schema: dict[str, Any]) -> None:
    properties = _mapping(schema, "properties")
    output = _mapping(properties, "output")
    content = _mapping(_mapping(output, "properties"), "content")
    branches = content.get("allOf")
    if not isinstance(branches, list) or len(branches) != 2 or not isinstance(branches[0], dict):
        raise WorkflowSchemaError("knowledge authoring content contract is not projectable")
    item = copy.deepcopy(branches[0])
    item.pop("$schema", None)
    item.pop("$id", None)
    item.pop("title", None)
    item_definitions = item.pop("$defs", None)
    if not isinstance(item_definitions, dict):
        raise WorkflowSchemaError("knowledge authoring item definitions are missing")

    renamed_definitions = {
        f"item_{name}": _rewrite_item_references(value) for name, value in item_definitions.items()
    }
    root_definitions = _mapping(schema, "$defs")
    if set(root_definitions).intersection(renamed_definitions):
        raise WorkflowSchemaError("knowledge authoring item definitions conflict")
    root_definitions.update(renamed_definitions)
    projected = _rewrite_item_references(item)
    if not isinstance(projected, dict):
        raise WorkflowSchemaError("knowledge authoring item projection is invalid")
    content.clear()
    content.update(projected)

    content_properties = _mapping(content, "properties")
    content_properties["locale"] = {"type": "string", "const": "ko-KR"}
    body = _mapping(content_properties, "body")
    body["minItems"] = 6
    body["maxItems"] = 6
    content_properties["interaction"] = {"$ref": "#/$defs/item_singleChoice"}

    table = _mapping(root_definitions, "item_tableBlock")
    table_properties = _mapping(table, "properties")
    table_properties["purpose"] = {"type": "string", "const": "data"}
    table["required"] = list(table_properties)
    headers = _mapping(table_properties, "headers")
    headers["minItems"] = 3
    headers["maxItems"] = 3
    rows = _mapping(table_properties, "rows")
    rows["minItems"] = 1
    rows["maxItems"] = 1
    row = _mapping(rows, "items")
    row["minItems"] = 3
    row["maxItems"] = 3

    image = _mapping(root_definitions, "item_imageBlock")
    image_properties = _mapping(image, "properties")
    image_properties["purpose"] = {"type": "string", "const": "stimulus"}
    image_properties["width_px"] = {"type": "integer", "const": 800}
    image_properties["height_px"] = {"type": "integer", "const": 500}
    artifact_pointer = _mapping(root_definitions, "item_artifactPointer")
    _mapping(artifact_pointer, "properties")["media_type"] = {
        "type": "string",
        "const": "image/png",
    }

    equation = _mapping(root_definitions, "item_equationBlock")
    equation_properties = _mapping(equation, "properties")
    equation_properties["purpose"] = {"type": "string", "const": "stimulus"}
    equation_properties["notation"] = {
        "type": "string",
        "const": "hancom-equation-script",
    }
    equation_properties["source"] = {
        "type": "string",
        "pattern": "^[A-Za-z0-9+\\-*/=() ._^]+$",
    }

    paragraph = _mapping(root_definitions, "item_paragraphBlock")
    _mapping(paragraph, "properties")["purpose"] = {
        "type": "string",
        "enum": ["stem", "prompt"],
    }
    statements = _mapping(root_definitions, "item_statementSetBlock")
    statement_items = _mapping(_mapping(statements, "properties"), "statements")
    statement_items["minItems"] = 3
    statement_items["maxItems"] = 3
    statement = _mapping(root_definitions, "item_statement")
    _mapping(statement, "properties")["label"] = {
        "type": "string",
        "enum": ["ㄱ", "ㄴ", "ㄷ"],
    }

    single_choice = _mapping(root_definitions, "item_singleChoice")
    choices = _mapping(_mapping(single_choice, "properties"), "choices")
    choices["minItems"] = 5
    choices["maxItems"] = 5
    score = _mapping(root_definitions, "item_score")
    _mapping(score, "properties")["points"] = {"type": "integer", "enum": [2, 3]}


def _rewrite_item_references(value: object) -> object:
    if isinstance(value, dict):
        rewritten: dict[str, Any] = {}
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str) and item.startswith("#/$defs/"):
                rewritten[key] = item.replace("#/$defs/", "#/$defs/item_", 1)
            else:
                rewritten[key] = _rewrite_item_references(item)
        return rewritten
    if isinstance(value, list):
        return [_rewrite_item_references(item) for item in value]
    return value


def _normalize_codex_schema(value: object) -> None:
    if not isinstance(value, dict):
        return
    if value.get("pattern") == _CANONICAL_SAFE_ARTIFACT_MEMBER_PATTERN:
        # The canonical contract retains its full traversal guard. Codex's structured-output
        # regex engine does not accept lookaround, so its generation-only projection uses an
        # equivalent regular expression. Canonical JSON Schema and Pydantic validation still run
        # after generation at the application boundary.
        value["pattern"] = _CODEX_SAFE_ARTIFACT_MEMBER_PATTERN
    minimum_length = value.get("minLength")
    if minimum_length is not None:
        if (
            not isinstance(minimum_length, int)
            or isinstance(minimum_length, bool)
            or minimum_length < 0
            or value.get("type") != "string"
        ):
            raise WorkflowSchemaError("Codex result string minimum is not projectable")
        if minimum_length > 0:
            pattern = value.get("pattern")
            if pattern is None:
                value["pattern"] = rf"[\s\S]{{{minimum_length},}}"
            elif pattern == _CANONICAL_SAFE_TEXT_PATTERN and minimum_length == 1:
                value["pattern"] = _CODEX_NONEMPTY_SAFE_TEXT_PATTERN
            elif not isinstance(pattern, str):
                raise WorkflowSchemaError("Codex result string pattern is not projectable")
            else:
                try:
                    accepts_empty = re.search(pattern, "") is not None
                except re.error as exc:
                    raise WorkflowSchemaError(
                        "Codex result string pattern cannot be checked for emptiness"
                    ) from exc
                if accepts_empty:
                    raise WorkflowSchemaError(
                        "Codex result string pattern does not preserve its non-empty contract"
                    )
    maximum_length = value.get("maxLength")
    if maximum_length is not None:
        value_type = value.get("type")
        string_type = value_type == "string" or (
            isinstance(value_type, list)
            and set(value_type) == {"string", "null"}
            and len(value_type) == 2
        )
        if (
            not isinstance(maximum_length, int)
            or isinstance(maximum_length, bool)
            or maximum_length < 0
            or not string_type
        ):
            raise WorkflowSchemaError("Codex result string maximum is not projectable")
        _append_projection_instruction(
            value,
            f"The value MUST contain at most {maximum_length} characters.",
        )
    if value.get("uniqueItems") is True:
        value_type = value.get("type")
        array_type = value_type == "array" or (
            isinstance(value_type, list)
            and set(value_type) == {"array", "null"}
            and len(value_type) == 2
        )
        if not array_type:
            raise WorkflowSchemaError("Codex result uniqueness constraint is not projectable")
        _append_projection_instruction(value, "Every array entry MUST be unique.")
    value.pop("minLength", None)
    value.pop("maxLength", None)
    value.pop("uniqueItems", None)
    if "oneOf" in value:
        value["anyOf"] = value.pop("oneOf")
    prefix_items = value.get("prefixItems")
    if isinstance(prefix_items, list):
        if (
            not prefix_items
            or value.get("minItems") != len(prefix_items)
            or value.get("maxItems") != len(prefix_items)
            or any(item != prefix_items[0] for item in prefix_items[1:])
        ):
            raise WorkflowSchemaError(
                "Codex result projection cannot preserve a heterogeneous fixed tuple"
            )
        value["items"] = prefix_items[0]
        value.pop("prefixItems")
    if "allOf" in value or "prefixItems" in value:
        raise WorkflowSchemaError("Codex result projection retained unsupported composition")

    if "type" not in value:
        if "const" in value:
            constant = value["const"]
            if isinstance(constant, bool):
                value["type"] = "boolean"
            elif isinstance(constant, int):
                value["type"] = "integer"
            elif isinstance(constant, float):
                value["type"] = "number"
            elif isinstance(constant, str):
                value["type"] = "string"
        elif isinstance(value.get("enum"), list) and value["enum"]:
            first = value["enum"][0]
            if all(isinstance(item, str) for item in value["enum"]):
                value["type"] = "string"
            elif all(
                isinstance(item, int) and not isinstance(item, bool) for item in value["enum"]
            ):
                value["type"] = "integer"
            elif isinstance(first, bool) and all(isinstance(item, bool) for item in value["enum"]):
                value["type"] = "boolean"

    properties = value.get("properties")
    if isinstance(properties, dict):
        value["type"] = "object"
        value["additionalProperties"] = False
        value["required"] = list(properties)
        for child in properties.values():
            _normalize_codex_schema(child)
    items = value.get("items")
    if isinstance(items, dict):
        _normalize_codex_schema(items)
    alternatives = value.get("anyOf")
    if isinstance(alternatives, list):
        for child in alternatives:
            _normalize_codex_schema(child)
        array_item_schemas = [
            child["items"]
            for child in alternatives
            if isinstance(child, dict)
            and child.get("type") == "array"
            and isinstance(child.get("items"), dict)
        ]
        if array_item_schemas and all(
            candidate == array_item_schemas[0] for candidate in array_item_schemas[1:]
        ):
            for child in alternatives:
                if (
                    isinstance(child, dict)
                    and child.get("type") == "array"
                    and child.get("maxItems") == 0
                    and "items" not in child
                ):
                    child["items"] = array_item_schemas[0]
    definitions = value.get("$defs")
    if isinstance(definitions, dict):
        for child in definitions.values():
            _normalize_codex_schema(child)


def _append_projection_instruction(value: dict[str, Any], instruction: str) -> None:
    description = value.get("description")
    if description is None:
        value["description"] = instruction
        return
    if not isinstance(description, str):
        raise WorkflowSchemaError("Codex result description is not a string")
    value["description"] = f"{description.rstrip()} {instruction}"


def _resource_error(logical_name: str) -> str:
    try:
        version = metadata.version("eom-platform")
    except metadata.PackageNotFoundError:
        version = "source"
    return (
        f"workflow schema resource unavailable: {logical_name} "
        f"(package=eom_workflow, distribution=eom-platform@{version})"
    )


def _mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise WorkflowSchemaError(f"schema is missing object: {key}")
    return cast(dict[str, Any], value)
