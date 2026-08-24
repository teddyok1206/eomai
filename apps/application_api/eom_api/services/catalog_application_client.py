"""Application API adapter for the private Catalog application socket."""

from __future__ import annotations

import grp
import json
import pwd
import socket
import stat
from pathlib import Path
from typing import Any

from eom_catalog_contracts import (
    CATALOG_APPLICATION_MAX_MESSAGE_BYTES,
    CATALOG_APPLICATION_SOCKET_MODE,
    CATALOG_APPLICATION_SOCKET_PATH,
    AssessmentItemContent,
    CatalogApplicationErrorCode,
    CatalogApplicationRequest,
    CatalogApplicationResponse,
    CreateEvidenceBundleCommand,
    CreateItemProductionEvidenceCommand,
    CreateKnowledgeAnalysisCommand,
    EvidenceBundlePublicationResult,
    EvidenceBundlePublicationResultV2,
    ItemContentQuery,
    KnowledgeAnalysisApplicationResult,
    ReconcileKnowledgeAnalysisCommand,
    ReviewedItemContentImportCommand,
    ReviewedItemContentImportResult,
    ReviewKnowledgeAnalysisCommand,
    validate_contract,
)
from eom_item_registry import RegistryError, RegistryErrorCode
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

CONNECT_TIMEOUT_SECONDS = 5.0
RESPONSE_TIMEOUT_SECONDS = 30.0


class CatalogApplicationClientError(RuntimeError):
    def __init__(self, code: str | CatalogApplicationErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = str(code)


class CatalogApplicationClient:
    def __init__(
        self,
        socket_path: Path = Path(CATALOG_APPLICATION_SOCKET_PATH),
        *,
        expected_uid: int | None = None,
        expected_gid: int | None = None,
    ) -> None:
        self.socket_path = socket_path
        self.expected_uid = expected_uid
        self.expected_gid = grp.getgrnam("eom-api").gr_gid if expected_gid is None else expected_gid

    def import_reviewed(
        self,
        command: ReviewedItemContentImportCommand,
    ) -> ReviewedItemContentImportResult:
        response = self._request(command)
        if response.operation != command.operation or response.result is None:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog application import response is invalid",
            )
        return response.result

    def load_item_content(self, item_revision_id: str) -> AssessmentItemContent:
        command = ItemContentQuery(item_revision_id=item_revision_id)
        response = self._request(command)
        if response.operation != command.operation or response.content is None:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog application content response is invalid",
            )
        return response.content

    def create_knowledge_analysis(
        self, command: CreateKnowledgeAnalysisCommand
    ) -> KnowledgeAnalysisApplicationResult:
        return self._analysis_request(command)

    def reconcile_knowledge_analysis(
        self, command: ReconcileKnowledgeAnalysisCommand
    ) -> KnowledgeAnalysisApplicationResult:
        return self._analysis_request(command)

    def review_knowledge_analysis(
        self, command: ReviewKnowledgeAnalysisCommand
    ) -> KnowledgeAnalysisApplicationResult:
        return self._analysis_request(command)

    def create_evidence_bundle(
        self, command: CreateEvidenceBundleCommand
    ) -> EvidenceBundlePublicationResult:
        response = self._request(command)
        if response.operation != command.operation or response.evidence is None:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog Evidence Bundle response is invalid",
            )
        return response.evidence

    def create_item_production_evidence(
        self, command: CreateItemProductionEvidenceCommand
    ) -> EvidenceBundlePublicationResultV2:
        response = self._request(command)
        if response.operation != command.operation or response.item_production_evidence is None:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog item production Evidence Bundle response is invalid",
            )
        return response.item_production_evidence

    def _analysis_request(
        self,
        command: CreateKnowledgeAnalysisCommand
        | ReconcileKnowledgeAnalysisCommand
        | ReviewKnowledgeAnalysisCommand,
    ) -> KnowledgeAnalysisApplicationResult:
        response = self._request(command)
        if response.operation != command.operation or response.analysis is None:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog knowledge analysis response is invalid",
            )
        return response.analysis

    def _request(
        self,
        command: ReviewedItemContentImportCommand
        | ItemContentQuery
        | CreateKnowledgeAnalysisCommand
        | ReconcileKnowledgeAnalysisCommand
        | ReviewKnowledgeAnalysisCommand
        | CreateEvidenceBundleCommand
        | CreateItemProductionEvidenceCommand,
    ) -> CatalogApplicationResponse:
        payload = CatalogApplicationRequest(root=command).model_dump(mode="json")
        request_schema = (
            "catalog-application-request-v4"
            if command.operation == "CREATE_ITEM_PRODUCTION_EVIDENCE"
            else "catalog-application-request-v3"
        )
        response_schema = (
            "catalog-application-response-v4"
            if command.operation == "CREATE_ITEM_PRODUCTION_EVIDENCE"
            else "catalog-application-response-v3"
        )
        validate_contract(request_schema, payload)
        self._validate_socket()
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(CONNECT_TIMEOUT_SECONDS)
            connection.connect(str(self.socket_path))
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            if len(encoded) + 1 > CATALOG_APPLICATION_MAX_MESSAGE_BYTES:
                raise ValueError("Catalog application request exceeds its fixed bound")
            connection.sendall(encoded + b"\n")
            connection.settimeout(RESPONSE_TIMEOUT_SECONDS)
            raw = self._read_response(connection)
            value: Any = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            validate_contract(response_schema, value)
            response = CatalogApplicationResponse.model_validate(value)
        except CatalogApplicationClientError:
            raise
        except (
            OSError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
            JsonSchemaValidationError,
            ValidationError,
        ) as exc:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog application boundary is unavailable",
            ) from exc
        finally:
            connection.close()
        if response.status == "ERROR":
            self._raise_remote_error(response.error_code)
        return response

    def _validate_socket(self) -> None:
        try:
            metadata = self.socket_path.lstat()
            expected_uid = (
                pwd.getpwnam("eom-catalog-manager").pw_uid
                if self.expected_uid is None
                else self.expected_uid
            )
        except (KeyError, OSError) as exc:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog application socket is unavailable",
            ) from exc
        if (
            not stat.S_ISSOCK(metadata.st_mode)
            or self.socket_path.is_symlink()
            or metadata.st_uid != expected_uid
            or metadata.st_gid != self.expected_gid
            or stat.S_IMODE(metadata.st_mode) != CATALOG_APPLICATION_SOCKET_MODE
        ):
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog application socket metadata is invalid",
            )

    @staticmethod
    def _read_response(connection: socket.socket) -> bytes:
        value = bytearray()
        while len(value) <= CATALOG_APPLICATION_MAX_MESSAGE_BYTES:
            chunk = connection.recv(
                min(64 * 1024, CATALOG_APPLICATION_MAX_MESSAGE_BYTES + 1 - len(value))
            )
            if not chunk:
                break
            newline = chunk.find(b"\n")
            if newline >= 0:
                value.extend(chunk[:newline])
                if newline != len(chunk) - 1:
                    raise ValueError("Catalog application response has trailing bytes")
                return bytes(value)
            value.extend(chunk)
        raise ValueError("Catalog application response is absent or exceeds its fixed bound")

    @staticmethod
    def _raise_remote_error(error_code: str | None) -> None:
        if error_code is None:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog application response omitted its error code",
            )
        try:
            registry_code = RegistryErrorCode(error_code)
        except ValueError:
            try:
                catalog_code = CatalogApplicationErrorCode(error_code)
            except ValueError as exc:
                if error_code.startswith("KNOWLEDGE_ANALYSIS_"):
                    raise CatalogApplicationClientError(
                        error_code,
                        "Catalog knowledge analysis operation failed",
                    ) from None
                if error_code.startswith("KNOWLEDGE_RETRIEVAL_"):
                    raise CatalogApplicationClientError(
                        error_code,
                        "Catalog knowledge retrieval operation failed",
                    ) from None
                raise CatalogApplicationClientError(
                    CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                    "Catalog application returned an unknown error code",
                ) from exc
            raise CatalogApplicationClientError(
                catalog_code,
                "Catalog application operation failed",
            ) from None
        raise RegistryError(registry_code, "Catalog application operation failed")
