"""JSON Schema 2020-12 validation backed by package-owned resources."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata
from importlib.resources import files
from importlib.resources.abc import Traversable
from types import MappingProxyType
from typing import Any

from eom_protocol.general_chat_worker_messages import (
    CHAT_WORKER_TICKET_SCHEMA,
    load_chat_worker_ticket_schema,
)
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource


@dataclass(frozen=True)
class CatalogSchemaResource:
    """Immutable identity for one runtime Catalog Contract schema."""

    canonical_path: str
    resource_path: str
    schema_version: str
    sha256: str


CATALOG_SCHEMA_RESOURCES: Mapping[str, CatalogSchemaResource] = MappingProxyType(
    {
        "embedding-gpu-failed-retirement": CatalogSchemaResource(
            "schemas/knowledge/embedding-gpu-failed-retirement-v1.schema.json",
            "resources/knowledge/embedding-gpu-failed-retirement-v1.schema.json",
            "1.0",
            "sha256:4e23e5b8438c5c9389d5061a5598c323e7873f93f02079fa41176377fb74c7ca",
        ),
        "embedding-gpu-allocation-control": CatalogSchemaResource(
            "schemas/knowledge/embedding-gpu-allocation-control-v1.schema.json",
            "resources/knowledge/embedding-gpu-allocation-control-v1.schema.json",
            "1.0",
            "sha256:df9b7d472b337d89c0f06dad49b0ca31c886bdc7b9f63664453dd6330975922b",
        ),
        "embedding-work-batch-result": CatalogSchemaResource(
            "schemas/knowledge/embedding-work-batch-result-v1.schema.json",
            "resources/knowledge/embedding-work-batch-result-v1.schema.json",
            "1.0",
            "sha256:552d31aec38a905623ea608a7b0006d4c706f21a73fad3948abe71c5e4886c18",
        ),
        "embedding-work-batch-input": CatalogSchemaResource(
            "schemas/knowledge/embedding-work-batch-input-v1.schema.json",
            "resources/knowledge/embedding-work-batch-input-v1.schema.json",
            "1.0",
            "sha256:feecd2bebde435773b715c9dc3af0d6a77cb7ef74768165359e13e2f82935005",
        ),
        "embedding-benchmark-failed-attempt": CatalogSchemaResource(
            "schemas/knowledge/embedding-benchmark-failed-attempt-v1.schema.json",
            "resources/knowledge/embedding-benchmark-failed-attempt-v1.schema.json",
            "1.0",
            "sha256:2437de9ac5fafea4b2e3096d918fcdeac396bd529b117aa239138e9fdc287067",
        ),
        "embedding-benchmark-preack-recovery": CatalogSchemaResource(
            "schemas/knowledge/embedding-benchmark-preack-recovery-v1.schema.json",
            "resources/knowledge/embedding-benchmark-preack-recovery-v1.schema.json",
            "1.0",
            "sha256:037849171b58d5cf85d216735b393029e0d326426a3a128eed2afeb829c863ce",
        ),
        "embedding-benchmark-poststart-failure": CatalogSchemaResource(
            "schemas/knowledge/embedding-benchmark-poststart-failure-v1.schema.json",
            "resources/knowledge/embedding-benchmark-poststart-failure-v1.schema.json",
            "1.0",
            "sha256:e8ac0a6b5d06f1376f871ad6c42966f9ae5ffc3ae97381e213a9a1bf950950e0",
        ),
        "embedding-benchmark-poststart-failure-v1.1": CatalogSchemaResource(
            "schemas/knowledge/embedding-benchmark-poststart-failure-v1.1.schema.json",
            "resources/knowledge/embedding-benchmark-poststart-failure-v1.1.schema.json",
            "1.1",
            "sha256:da020334f6a7ad88ea3f12308f0f357e821bb2a04ab6e8ef4f9d55180aedc52a",
        ),
        "embedding-benchmark-poststart-failure-v1.2": CatalogSchemaResource(
            "schemas/knowledge/embedding-benchmark-poststart-failure-v1.2.schema.json",
            "resources/knowledge/embedding-benchmark-poststart-failure-v1.2.schema.json",
            "1.2",
            "sha256:33547b07d145e231cf9acc7ec9eff1ed940069e880dd09ef1b60d5e76eba39c3",
        ),
        "embedding-benchmark-poststart-failure-v1.3": CatalogSchemaResource(
            "schemas/knowledge/embedding-benchmark-poststart-failure-v1.3.schema.json",
            "resources/knowledge/embedding-benchmark-poststart-failure-v1.3.schema.json",
            "1.3",
            "sha256:fbf4f8ca7b80f3d03c297822048289e8c2270164db2987e98cef7de69423343f",
        ),
        "embedding-benchmark-prelaunch-failure": CatalogSchemaResource(
            "schemas/knowledge/embedding-benchmark-prelaunch-failure-v1.schema.json",
            "resources/knowledge/embedding-benchmark-prelaunch-failure-v1.schema.json",
            "1.0",
            "sha256:c339b904046a528d2868c2598049de4e8a6b29036c14ee272176bce3abc459bb",
        ),
        "embedding-registry-v2": CatalogSchemaResource(
            "schemas/knowledge/embedding-registry-v2.schema.json",
            "resources/knowledge/embedding-registry-v2.schema.json",
            "2.0",
            "sha256:088f2981115a8d866e3d720c00c233cba134d3f141c58279b4abcb4f4b348e66",
        ),
        "mixed-embedding-index-v2": CatalogSchemaResource(
            "schemas/knowledge/mixed-embedding-index-v2.schema.json",
            "resources/knowledge/mixed-embedding-index-v2.schema.json",
            "2.0",
            "sha256:3fbd7d4222bab9a4c91080d0015693879615ff09a299076b9233df8733ddc859",
        ),
        "ordinary-item-graph-publication-command": CatalogSchemaResource(
            "schemas/knowledge/ordinary-item-graph-publication-command-v1.schema.json",
            "resources/knowledge/ordinary-item-graph-publication-command-v1.schema.json",
            "1.0",
            "sha256:2b0f8291ebd0fc4939f6b541cef7e048d0e7b2d23a3005fd64ee4ba5bc974555",
        ),
        "ordinary-item-graph-publication-result": CatalogSchemaResource(
            "schemas/knowledge/ordinary-item-graph-publication-result-v1.schema.json",
            "resources/knowledge/ordinary-item-graph-publication-result-v1.schema.json",
            "1.0",
            "sha256:ff1ec3b956f5e797e5d4caf6e764e4b66e641b297cee9a19087fdbf4dfd39e7b",
        ),
        "item-inference-transfer-v2": CatalogSchemaResource(
            "schemas/knowledge/item-inference-transfer-v2.schema.json",
            "resources/knowledge/item-inference-transfer-v2.schema.json",
            "2.0",
            "sha256:0d43afea255a7ecaac1877f2108ca075ef868622e037e81faf2f95c5c4017d54",
        ),
        "registered-item-review-solution-evidence": CatalogSchemaResource(
            "schemas/knowledge/registered-item-review-solution-evidence-v1.schema.json",
            "resources/knowledge/registered-item-review-solution-evidence-v1.schema.json",
            "1.0",
            "sha256:db934703765b4462f3ff4e8bbf9cff27f1f2900e2851b311cd5b2297a5cd24d5",
        ),
        "general-chat-similarity-observation": CatalogSchemaResource(
            "schemas/knowledge/general-chat-similarity-observation-v1.schema.json",
            "resources/knowledge/general-chat-similarity-observation-v1.schema.json",
            "1.0",
            "sha256:34df201d300b9abe70a0e1c389f889ba526c4a6fea6b2b2316c78b3ff702c195",
        ),
        "chat-ranked-candidate-read": CatalogSchemaResource(
            "schemas/knowledge/chat-ranked-candidate-read-v1.schema.json",
            "resources/knowledge/chat-ranked-candidate-read-v1.schema.json",
            "1.0",
            "sha256:100b2f8bdabf426655bad774748a3fd3e2afd593564893c8438810e886e39b40",
        ),
        "general-chat-similarity-provenance": CatalogSchemaResource(
            "schemas/knowledge/general-chat-similarity-provenance-v1.schema.json",
            "resources/knowledge/general-chat-similarity-provenance-v1.schema.json",
            "1.0",
            "sha256:5832a534f919bdb55e75978c46b888295486da31ed026d1c725008e7e76bcd62",
        ),
        "chat-private-query-scope": CatalogSchemaResource(
            "schemas/knowledge/chat-private-query-scope-v1.schema.json",
            "resources/knowledge/chat-private-query-scope-v1.schema.json",
            "1.0",
            "sha256:096505224a270455ecb603e0aed693d00e0d67ebbef8c458a922490edee4862c",
        ),
        "system-rag-private-chat-query-prepare": CatalogSchemaResource(
            "schemas/knowledge/system-rag-private-chat-query-prepare-v1.schema.json",
            "resources/knowledge/system-rag-private-chat-query-prepare-v1.schema.json",
            "1.0",
            "sha256:9af37ac1dab5062183336016d1522a0e167fe165b592abfc244ee8b689487656",
        ),
        "general-chat-private-query-read": CatalogSchemaResource(
            "schemas/knowledge/general-chat-private-query-read-v1.schema.json",
            "resources/knowledge/general-chat-private-query-read-v1.schema.json",
            "1.0",
            "sha256:f0424e012ffcbe663678a83e817a44984a6eae61e8fc18e021421d9a81b116ef",
        ),
        "embedding-native-cuda-index-owner-binding": CatalogSchemaResource(
            "schemas/knowledge/embedding-native-cuda-index-owner-binding-v1.schema.json",
            "resources/knowledge/embedding-native-cuda-index-owner-binding-v1.schema.json",
            "1.0",
            "sha256:67f7be299facf02d9564b214819e86b5be283b116c2b390464b98552efb3a21b",
        ),
        "embedding-native-cuda-index-ready": CatalogSchemaResource(
            "schemas/knowledge/embedding-native-cuda-index-ready-v1.schema.json",
            "resources/knowledge/embedding-native-cuda-index-ready-v1.schema.json",
            "1.0",
            "sha256:f2f33a3e515f5ef4c9e81aebcb940212453cc418c929434b2af3cf77726fae4e",
        ),
        "embedding-benchmark-cuda-ready": CatalogSchemaResource(
            "schemas/knowledge/embedding-benchmark-cuda-ready-v1.schema.json",
            "resources/knowledge/embedding-benchmark-cuda-ready-v1.schema.json",
            "1.0",
            "sha256:c902ead02b103dcff6304cf9fbb9c9e47fcd5db1e23f6e158a7c2660d3913a10",
        ),
        "system-rag-exam-observation-read": CatalogSchemaResource(
            "schemas/knowledge/system-rag-exam-observation-read-v1.schema.json",
            "resources/knowledge/system-rag-exam-observation-read-v1.schema.json",
            "1.0",
            "sha256:78426f9b22d5f6e0b75d4d7fbb36e181265fb890aa1ce29c52db9c9f9bf261b1",
        ),
        "system-rag-exam-observation": CatalogSchemaResource(
            "schemas/knowledge/system-rag-exam-observation-v1.schema.json",
            "resources/knowledge/system-rag-exam-observation-v1.schema.json",
            "1.0",
            "sha256:4eb128c0d2b38f785b00366dc8213f419adb06ae125fa147c29bc4c950db0c46",
        ),
        "embedding-native-runtime-config-v1.3": CatalogSchemaResource(
            "schemas/knowledge/embedding-native-runtime-config-v1.3.schema.json",
            "resources/knowledge/embedding-native-runtime-config-v1.3.schema.json",
            "1.3",
            "sha256:f581d4fdef31dee77a9e9885cb9a009f7658ff3a647b12f867813158cd6dfaae",
        ),
        "embedding-prefix-audit-input-v1.3": CatalogSchemaResource(
            "schemas/knowledge/embedding-prefix-audit-input-v1.3.schema.json",
            "resources/knowledge/embedding-prefix-audit-input-v1.3.schema.json",
            "1.3",
            "sha256:3ed485e0324becea46cfdd88fc3ebd71f8a016b679d10c0a1ca7242b3f959dca",
        ),
        "embedding-native-runtime-config-v1.2": CatalogSchemaResource(
            "schemas/knowledge/embedding-native-runtime-config-v1.2.schema.json",
            "resources/knowledge/embedding-native-runtime-config-v1.2.schema.json",
            "1.2",
            "sha256:d6d837969d4b40deeec8a4e03f4e5597852bc9df3ad71c87fa4fcf7768ac47fb",
        ),
        "embedding-prefix-audit-input-v1.2": CatalogSchemaResource(
            "schemas/knowledge/embedding-prefix-audit-input-v1.2.schema.json",
            "resources/knowledge/embedding-prefix-audit-input-v1.2.schema.json",
            "1.2",
            "sha256:c4b8baa130c032a7ef3513c37df849bf28fd20d500b767bf8eb7bf4e4c89cb9a",
        ),
        "embedding-cuda-host-extension-v1.1": CatalogSchemaResource(
            "schemas/knowledge/embedding-cuda-host-extension-v1.1.schema.json",
            "resources/knowledge/embedding-cuda-host-extension-v1.1.schema.json",
            "1.1",
            "sha256:b6362bdf94c1a7bd32afa252a5acdb3dca04e73b16bdca1ff9937e0a9aa68d0f",
        ),
        "embedding-cuda-host-extension": CatalogSchemaResource(
            "schemas/knowledge/embedding-cuda-host-extension-v1.schema.json",
            "resources/knowledge/embedding-cuda-host-extension-v1.schema.json",
            "1.0",
            "sha256:19aa197a54a7bf8e50164094655522dd8c19dbcebe4dec922912634f9043da0b",
        ),
        "system-rag-private-chat-similarity": CatalogSchemaResource(
            "schemas/knowledge/system-rag-private-chat-similarity-v1.schema.json",
            "resources/knowledge/system-rag-private-chat-similarity-v1.schema.json",
            "1.0",
            "sha256:884bc8b9d873746ffea5cfb5042859a61eaa5942a8f488f4fc3d2d76db14d586",
        ),
        "embedding-private-chat-query": CatalogSchemaResource(
            "schemas/knowledge/embedding-private-chat-query-v1.schema.json",
            "resources/knowledge/embedding-private-chat-query-v1.schema.json",
            "1.0",
            "sha256:50feda7efee0617663def17ab3684afba2580769c1a6454518d042520f75b75b",
        ),
        "system-rag-private-chat-query-basis": CatalogSchemaResource(
            "schemas/knowledge/system-rag-private-chat-query-basis-v1.schema.json",
            "resources/knowledge/system-rag-private-chat-query-basis-v1.schema.json",
            "1.0",
            "sha256:589521cd1ed918569c41f149eb224376172c493a97b00b256c39cbfa5367b145",
        ),
        "embedding-host-configuration-snapshot": CatalogSchemaResource(
            "schemas/knowledge/embedding-host-configuration-snapshot-v1.schema.json",
            "resources/knowledge/embedding-host-configuration-snapshot-v1.schema.json",
            "1.0",
            "sha256:68db10c1af89fbc95ce977e9a6d4c6c1e10fb3fc543d927e04f2f18a73588221",
        ),
        "system-rag-authoring-reference": CatalogSchemaResource(
            "schemas/knowledge/system-rag-authoring-reference-v1.schema.json",
            "resources/knowledge/system-rag-authoring-reference-v1.schema.json",
            "1.0",
            "sha256:fc2bee449016d3fb3de84be22b6a22f1cee55aa88aa2f79f085b661d2a4e9215",
        ),
        "system-rag-reference-query-prepare-v1.1": CatalogSchemaResource(
            "schemas/knowledge/system-rag-reference-query-prepare-v1_1.schema.json",
            "resources/knowledge/system-rag-reference-query-prepare-v1_1.schema.json",
            "1.1",
            "sha256:d6a9e8f99ecd8173497d6283f8a8f58e9124a1890cee00fed795b2fc86d8cb0f",
        ),
        "system-rag-reference-query-prepare": CatalogSchemaResource(
            "schemas/knowledge/system-rag-reference-query-prepare-v1.schema.json",
            "resources/knowledge/system-rag-reference-query-prepare-v1.schema.json",
            "1.0",
            "sha256:ebc804f035eae57c9b4a649316cd63471203218ecb04603454eb08f2bfa15720",
        ),
        "system-rag-item-similarity-publication": CatalogSchemaResource(
            "schemas/knowledge/system-rag-item-similarity-publication-v1.schema.json",
            "resources/knowledge/system-rag-item-similarity-publication-v1.schema.json",
            "1.0",
            "sha256:38eeb30316421482d0770dc5e97cf014738a967277ed5c662dab0fd044ae001a",
        ),
        "system-rag-workflow-similarity-read": CatalogSchemaResource(
            "schemas/knowledge/system-rag-workflow-similarity-read-v1.schema.json",
            "resources/knowledge/system-rag-workflow-similarity-read-v1.schema.json",
            "1.0",
            "sha256:4173690a974ae475f4dcaca9404003a16d644b37b8d970eb798515c72ad6a384",
        ),
        "system-rag-similarity-reader-configuration": CatalogSchemaResource(
            "schemas/knowledge/system-rag-similarity-reader-configuration-v1.schema.json",
            "resources/knowledge/system-rag-similarity-reader-configuration-v1.schema.json",
            "1.0",
            "sha256:56e414955beda6fd1c9abf05e7acc77175c60c0374caf0e615496a5c73cec2a9",
        ),
        "system-rag-similarity-reader-configuration-v2": CatalogSchemaResource(
            "schemas/knowledge/system-rag-similarity-reader-configuration-v2.schema.json",
            "resources/knowledge/system-rag-similarity-reader-configuration-v2.schema.json",
            "2.0",
            "sha256:17df91dd0e3c3437f61479c03a13428c1cf63f09eb2768e04988fe672f18b9b2",
        ),
        "system-rag-reference-query-prepare-v2": CatalogSchemaResource(
            "schemas/knowledge/system-rag-reference-query-prepare-v2.schema.json",
            "resources/knowledge/system-rag-reference-query-prepare-v2.schema.json",
            "2.0",
            "sha256:b1bb18afe2fd0d3b302f38f565ef612d8f27505587e83e2678d6300813e3cf32",
        ),
        "system-rag-similarity-context-v2": CatalogSchemaResource(
            "schemas/knowledge/system-rag-similarity-context-v2.schema.json",
            "resources/knowledge/system-rag-similarity-context-v2.schema.json",
            "2.0",
            "sha256:1d40e17c596afe6a421dd7789728bd6741334874595241cb79dab7f292da79e4",
        ),
        "system-rag-similarity-materials-v2": CatalogSchemaResource(
            "schemas/knowledge/system-rag-similarity-materials-v2.schema.json",
            "resources/knowledge/system-rag-similarity-materials-v2.schema.json",
            "2.0",
            "sha256:c22b5907a5b4d9be22b710da89973e445485a89c858a6758d9c568301daaaf40",
        ),
        "system-rag-similarity-read-v2": CatalogSchemaResource(
            "schemas/knowledge/system-rag-similarity-read-v2.schema.json",
            "resources/knowledge/system-rag-similarity-read-v2.schema.json",
            "2.0",
            "sha256:d7beac0fa677e54e3dd2377c9124547378d141b1be95465d51a6af2995c38665",
        ),
        "system-rag-similarity-read": CatalogSchemaResource(
            "schemas/knowledge/system-rag-similarity-read-v1.schema.json",
            "resources/knowledge/system-rag-similarity-read-v1.schema.json",
            "1.0",
            "sha256:6cdf5bf757b524968f7ffa5fe7dae093f7ca01cf28bd5fc20708c27e4e687dbe",
        ),
        "system-rag-similarity-materials": CatalogSchemaResource(
            "schemas/knowledge/system-rag-similarity-materials-v1.schema.json",
            "resources/knowledge/system-rag-similarity-materials-v1.schema.json",
            "1.0",
            "sha256:a81f556811c74a93faf8635e492ec92a5791948428f9995179b27dea77bc640b",
        ),
        "embedding-native-cuda-probe-lease-ready": CatalogSchemaResource(
            "schemas/knowledge/embedding-native-cuda-probe-lease-ready-v1.schema.json",
            "resources/knowledge/embedding-native-cuda-probe-lease-ready-v1.schema.json",
            "1.0",
            "sha256:f2d741a420707cc5fcf686fd379f089558faf339c36c505ef720cf977f409744",
        ),
        "embedding-native-cuda-probe": CatalogSchemaResource(
            "schemas/knowledge/embedding-native-cuda-probe-v1.schema.json",
            "resources/knowledge/embedding-native-cuda-probe-v1.schema.json",
            "1.0",
            "sha256:ee3b8ad46c92cf88995f351b63072fdccc0283457b49d614626bc3dab633cd8c",
        ),
        "embedding-native-cpu-probe": CatalogSchemaResource(
            "schemas/knowledge/embedding-native-cpu-probe-v1.schema.json",
            "resources/knowledge/embedding-native-cpu-probe-v1.schema.json",
            "1.0",
            "sha256:133d5989acda16ec9f63fc10cbd5f57b114c4c816214c01bcb2e064eab2e14b3",
        ),
        "embedding-reference-query-input-v1.1": CatalogSchemaResource(
            "schemas/knowledge/embedding-reference-query-input-v1_1.schema.json",
            "resources/knowledge/embedding-reference-query-input-v1_1.schema.json",
            "1.1",
            "sha256:03a2d1332fefef201d30baae59597dda49a46f5650c45bf1384cf20a1f08c81d",
        ),
        "system-rag-similarity-context": CatalogSchemaResource(
            "schemas/knowledge/system-rag-similarity-context-v1.schema.json",
            "resources/knowledge/system-rag-similarity-context-v1.schema.json",
            "1.0",
            "sha256:7d1d4bb07964060143acacb32a3dad8ccbc41519d5847742ffe5deb739b57b20",
        ),
        "system-rag-similarity-delivery": CatalogSchemaResource(
            "schemas/knowledge/system-rag-similarity-delivery-v1.schema.json",
            "resources/knowledge/system-rag-similarity-delivery-v1.schema.json",
            "1.0",
            "sha256:c403071c18e44cdad39d96ccb7e6c6454ac27fd76c83d7ac6e98e4b938c3fa65",
        ),
        "embedding-reference-query": CatalogSchemaResource(
            "schemas/knowledge/embedding-reference-query-v1.schema.json",
            "resources/knowledge/embedding-reference-query-v1.schema.json",
            "1.0",
            "sha256:51c563a0b329c3cb81ac3e2a2ca8d53db1019099c10f447c9019f770303daf44",
        ),
        "embedding-native-runtime-config": CatalogSchemaResource(
            "schemas/knowledge/embedding-native-runtime-config-v1.schema.json",
            "resources/knowledge/embedding-native-runtime-config-v1.schema.json",
            "1.0",
            "sha256:f48da8820d2452fe62cfaa8b3401f42abac2f43b94eaf1a18968e5f8492bef5e",
        ),
        "embedding-native-runtime-config-v1.1": CatalogSchemaResource(
            "schemas/knowledge/embedding-native-runtime-config-v1.1.schema.json",
            "resources/knowledge/embedding-native-runtime-config-v1.1.schema.json",
            "1.1",
            "sha256:2dbd806065e6d9d9d852bd4fcc073d7d3bd8851fe7eeeb92d68a3469880b3a1c",
        ),
        "embedding-prefix-audit-input-v1.1": CatalogSchemaResource(
            "schemas/knowledge/embedding-prefix-audit-input-v1.1.schema.json",
            "resources/knowledge/embedding-prefix-audit-input-v1.1.schema.json",
            "1.1",
            "sha256:cddd8cc3911a99a13614c95dde3e5cf697fc11d5b00c6416c82780a23b73d538",
        ),
        "embedding-device-benchmark": CatalogSchemaResource(
            "schemas/knowledge/embedding-device-benchmark-v1.schema.json",
            "resources/knowledge/embedding-device-benchmark-v1.schema.json",
            "1.0",
            "sha256:c8105987d684f6a276fe92361b830663487bdaa5df47c1eb47b6407dd1ee07ad",
        ),
        "embedding-device-benchmark-v1.1": CatalogSchemaResource(
            "schemas/knowledge/embedding-device-benchmark-v1.1.schema.json",
            "resources/knowledge/embedding-device-benchmark-v1.1.schema.json",
            "1.1",
            "sha256:6837c3abe6de51e00e149331422f144223f5b67579ddc41d269d9cdd2f01e690",
        ),
        "embedding-device-benchmark-v1.2": CatalogSchemaResource(
            "schemas/knowledge/embedding-device-benchmark-v1.2.schema.json",
            "resources/knowledge/embedding-device-benchmark-v1.2.schema.json",
            "1.2",
            "sha256:df59b77de1e2dce88431396be3c01d1ac89700f18c899775fcb43de1189334e3",
        ),
        "embedding-installed-runtime-proof": CatalogSchemaResource(
            "schemas/knowledge/embedding-installed-runtime-proof-v1.schema.json",
            "resources/knowledge/embedding-installed-runtime-proof-v1.schema.json",
            "1.0",
            "sha256:303342c0815c0aadb569d90c8f2106587e9bcbb04b1c1cf5d3d50c9a80fbe5c9",
        ),
        "embedding-runtime-bundle": CatalogSchemaResource(
            "schemas/knowledge/embedding-runtime-bundle-v1.schema.json",
            "resources/knowledge/embedding-runtime-bundle-v1.schema.json",
            "1.0",
            "sha256:221d99c694efd24224b69ae8de31df72b21057683cdc4dc05fff072d754da932",
        ),
        "embedding-registry": CatalogSchemaResource(
            "schemas/knowledge/embedding-registry-v1.schema.json",
            "resources/knowledge/embedding-registry-v1.schema.json",
            "1.0",
            "sha256:443d6c2bac150de275c8d69bf7bc3e01bf720002115564fae1002c77e3fb47a5",
        ),
        "item-inference-transfer-embedding": CatalogSchemaResource(
            "schemas/knowledge/item-inference-transfer-embedding-v1.schema.json",
            "resources/knowledge/item-inference-transfer-embedding-v1.schema.json",
            "1.0",
            "sha256:36495b830932ac0f7afdaca7a0909652c61dc16a13d01488651cf84978d83b52",
        ),
        "item-inference-transfer-retry": CatalogSchemaResource(
            "schemas/knowledge/item-inference-transfer-retry-v1.schema.json",
            "resources/knowledge/item-inference-transfer-retry-v1.schema.json",
            "1.0",
            "sha256:1198bbd9071ec67b4e7a0a60f47149b7496ebbaba3686117c4420e58646f7f1b",
        ),
        "item-inference-transfer-invocation-v1.1": CatalogSchemaResource(
            "schemas/knowledge/item-inference-transfer-invocation-v1_1.schema.json",
            "resources/knowledge/item-inference-transfer-invocation-v1_1.schema.json",
            "1.1",
            "sha256:2f42643229b653368415855eaa06121f3f99e28b221f21aca4db8c25eb566e56",
        ),
        "item-inference-transfer-workflow-binding-v1.1": CatalogSchemaResource(
            "schemas/knowledge/item-inference-transfer-workflow-binding-v1_1.schema.json",
            "resources/knowledge/item-inference-transfer-workflow-binding-v1_1.schema.json",
            "1.1",
            "sha256:33aa41423e63ad3d9ba56761029df72c2be9c637c38a784d4b499d4f5930b302",
        ),
        "item-inference-transfer-pair-result-v1.1": CatalogSchemaResource(
            "schemas/knowledge/item-inference-transfer-pair-result-v1_1.schema.json",
            "resources/knowledge/item-inference-transfer-pair-result-v1_1.schema.json",
            "1.1",
            "sha256:5dd12768a41eef7d91edfbeb9effc399f2ad7525306f213bb945c3c7a3ec1451",
        ),
        "item-inference-transfer-human-review": CatalogSchemaResource(
            "schemas/knowledge/item-inference-transfer-human-review-v1.schema.json",
            "resources/knowledge/item-inference-transfer-human-review-v1.schema.json",
            "1.0",
            "sha256:ca7d29dcaa926641e714fe50c08f30819d31ed0c6fd50318161bced08198a975",
        ),
        "item-inference-transfer-metadata": CatalogSchemaResource(
            "schemas/knowledge/item-inference-transfer-metadata-v1.schema.json",
            "resources/knowledge/item-inference-transfer-metadata-v1.schema.json",
            "1.0",
            "sha256:6cbbb35c2b433ac55642eddc9a66adaa3dd2e8320a00260ec621d3a234a5afe1",
        ),
        "item-inference-transfer-invocation": CatalogSchemaResource(
            "schemas/knowledge/item-inference-transfer-invocation-v1.schema.json",
            "resources/knowledge/item-inference-transfer-invocation-v1.schema.json",
            "1.0",
            "sha256:92d3bca3591f54242be1d10d5b467ed6f1734f7417c523ce63d3a24c04e888cd",
        ),
        "item-inference-transfer-workflow-binding": CatalogSchemaResource(
            "schemas/knowledge/item-inference-transfer-workflow-binding-v1.schema.json",
            "resources/knowledge/item-inference-transfer-workflow-binding-v1.schema.json",
            "1.0",
            "sha256:626ff58c2644e46749c0c5e36a36c9ed45f3fc68491e38cfbc24d91843274b96",
        ),
        "item-inference-transfer-snapshot-binding": CatalogSchemaResource(
            "schemas/knowledge/item-inference-transfer-snapshot-binding-v1.schema.json",
            "resources/knowledge/item-inference-transfer-snapshot-binding-v1.schema.json",
            "1.0",
            "sha256:b185c1d186f6aecbaae7bea976311430496e0b2e353aefe5c36e4afd7b8ac204",
        ),
        "item-inference-transfer-snapshot": CatalogSchemaResource(
            "schemas/knowledge/item-inference-transfer-snapshot-v1.schema.json",
            "resources/knowledge/item-inference-transfer-snapshot-v1.schema.json",
            "1.0",
            "sha256:f19f63a5b9b16f3eaebbf6b7ac5296a79f5d97cf535389566194e8b3d8867850",
        ),
        "item-inference-transfer-experiment": CatalogSchemaResource(
            "schemas/knowledge/item-inference-transfer-experiment-v1.schema.json",
            "resources/knowledge/item-inference-transfer-experiment-v1.schema.json",
            "1.0",
            "sha256:becaa7e8281f429267ba9cdcfb03129a5f51ecf53f06b4fcfdf7b9b0789df91b",
        ),
        "item-inference-transfer": CatalogSchemaResource(
            "schemas/knowledge/item-inference-transfer-v1.schema.json",
            "resources/knowledge/item-inference-transfer-v1.schema.json",
            "1.0",
            "sha256:79e197f598d5fadea0ef757208bd01f05783e83499317680ee804f43600fdff2",
        ),
        "mock-exam-assembly-cohort": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-assembly-cohort-v1.schema.json",
            "resources/assessment-assembly/mock-exam-assembly-cohort-v1.schema.json",
            "1.0",
            "sha256:4e6e7b74f44dfe42cf392ebefe07d7ffbdcd6d5bbf2d7a29b9ba7aeda225530b",
        ),
        "mock-exam-item-review-publication-command": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-item-review-publication-command-v1.schema.json",
            "resources/assessment-assembly/"
            "mock-exam-item-review-publication-command-v1.schema.json",
            "1.0",
            "sha256:272512348fd2a8d199d93e0de1fc067dfd761d1387040b9e7fb6e26ca1a1b893",
        ),
        "mock-exam-item-review-publication-result": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-item-review-publication-result-v1.schema.json",
            "resources/assessment-assembly/mock-exam-item-review-publication-result-v1.schema.json",
            "1.0",
            "sha256:7c5925cea23b97b882ed12776c993db611fabac35b5056c41833f727eb989061",
        ),
        "mock-exam-item-review-publication-result-v2": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-item-review-publication-result-v2.schema.json",
            "resources/assessment-assembly/mock-exam-item-review-publication-result-v2.schema.json",
            "2.0",
            "sha256:50dddba5c0167a0edb6993825d7ad62abb6c56bb6c707e2d103e7a2adedaa065",
        ),
        "mock-exam-item-review-publication-result-v3": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-item-review-publication-result-v3.schema.json",
            "resources/assessment-assembly/mock-exam-item-review-publication-result-v3.schema.json",
            "3.0",
            "sha256:b1069f0b2acdd340382cad71ae212117d45525921c61b93c1f2cdb11a29069ee",
        ),
        "mock-exam-item-review-decision": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-item-review-decision-v1.schema.json",
            "resources/assessment-assembly/mock-exam-item-review-decision-v1.schema.json",
            "1.0",
            "sha256:5f0934dfb60d8daf03f32aee080ea0f75b5930553e7bc697a592954552e9fd80",
        ),
        "mock-exam-item-review-decision-v2": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-item-review-decision-v2.schema.json",
            "resources/assessment-assembly/mock-exam-item-review-decision-v2.schema.json",
            "2.0",
            "sha256:7cb83fc19ce124f49bdd9829e3a846c318f85dfa6f3578d69594404fd414bf76",
        ),
        "mock-exam-item-review-decision-v3": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-item-review-decision-v3.schema.json",
            "resources/assessment-assembly/mock-exam-item-review-decision-v3.schema.json",
            "3.0",
            "sha256:e5195f0f76997f8b458ea85e4f3eff1c18aaeb1fbbb023214f6653c3ad5e2ddc",
        ),
        "mock-exam-review-eligibility-query": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-review-eligibility-query-v1.schema.json",
            "resources/assessment-assembly/mock-exam-review-eligibility-query-v1.schema.json",
            "1.0",
            "sha256:92c0a88776f37443c599c298edde768270957e40f0f1135cbd5cc5f519d32715",
        ),
        "mock-exam-review-eligibility-result": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-review-eligibility-result-v1.schema.json",
            "resources/assessment-assembly/mock-exam-review-eligibility-result-v1.schema.json",
            "1.0",
            "sha256:5d8ce21540dbda8f38cda3f008e3379646e06505c6435e95b16095f1a6e8f7c2",
        ),
        "mock-exam-review-eligibility-result-v2": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-review-eligibility-result-v2.schema.json",
            "resources/assessment-assembly/mock-exam-review-eligibility-result-v2.schema.json",
            "2.0",
            "sha256:d1de598f3f8d754df44aff968199eb532eb0bb3ba0c00a72a04ac09a5f5e1557",
        ),
        "mock-exam-review-eligibility-result-v3": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-review-eligibility-result-v3.schema.json",
            "resources/assessment-assembly/mock-exam-review-eligibility-result-v3.schema.json",
            "3.0",
            "sha256:a5023d968ad7346f342bf0f9e79dafb5cd46d2b0d49c06cec673ff5e39f89f27",
        ),
        "mock-exam-production-plan": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-production-plan-v1.schema.json",
            "resources/assessment-assembly/mock-exam-production-plan-v1.schema.json",
            "1.0",
            "sha256:9f0cd769669d7394c59a8683f467bcc93a0846f6e6620a64d374f17802099f41",
        ),
        "mock-exam-production-plan-v2": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-production-plan-v2.schema.json",
            "resources/assessment-assembly/mock-exam-production-plan-v2.schema.json",
            "2.0",
            "sha256:d3bddcbbb236cbfba595587ea373445224de9d02bfa2e975a7dd5010ca48483f",
        ),
        "mock-exam-production-plan-v3": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-production-plan-v3.schema.json",
            "resources/assessment-assembly/mock-exam-production-plan-v3.schema.json",
            "3.0",
            "sha256:687b663f099310209301d1931eb27368cfd8873a38c77b3ee5d3c05b2106523f",
        ),
        "mock-exam-production-plan-v4": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-production-plan-v4.schema.json",
            "resources/assessment-assembly/mock-exam-production-plan-v4.schema.json",
            "4.0",
            "sha256:45d60126e2faaa91f4cd923d4d5230ba53c7bd8f1b4d35c3805728c9ca860094",
        ),
        "mock-exam-production-plan-v5": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-production-plan-v5.schema.json",
            "resources/assessment-assembly/mock-exam-production-plan-v5.schema.json",
            "5.0",
            "sha256:19ac3236bbe655179aec6050353a037985900bd7905e3ce1ad8aa327ab25d30c",
        ),
        "mock-exam-assembly-manifest": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-assembly-manifest-v1.schema.json",
            "resources/assessment-assembly/mock-exam-assembly-manifest-v1.schema.json",
            "1.0",
            "sha256:979d81c600eb8a1242c96bc3c5ade26792f6ac9c89ec22851fe1b10419808ab2",
        ),
        "mock-exam-assembly-manifest-v2": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-assembly-manifest-v2.schema.json",
            "resources/assessment-assembly/mock-exam-assembly-manifest-v2.schema.json",
            "2.0",
            "sha256:4c6e6788af06d6d11e146bc740c81c89659a250207d23257f4f346512752418a",
        ),
        "mock-exam-assembly-manifest-v3": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-assembly-manifest-v3.schema.json",
            "resources/assessment-assembly/mock-exam-assembly-manifest-v3.schema.json",
            "3.0",
            "sha256:fed79f9105f6ea8cd5f2d9bfa53a5c26114c5b880be3ece3befec51f48155c9e",
        ),
        "mock-exam-assembly-plan": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-assembly-plan-v1.schema.json",
            "resources/assessment-assembly/mock-exam-assembly-plan-v1.schema.json",
            "1.0",
            "sha256:b962682195f8b5496fbcce89eed9b4f3daf9a3f27ba07c37307f1a78bce1cd56",
        ),
        "mock-exam-assembly-plan-v2": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-assembly-plan-v2.schema.json",
            "resources/assessment-assembly/mock-exam-assembly-plan-v2.schema.json",
            "2.0",
            "sha256:6b349f47507b2cb81a0e7e8a210efe63df6f55a96fd41d7bd3a86486f50cf891",
        ),
        "mock-exam-layout-policy": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-layout-policy-v1.schema.json",
            "resources/assessment-assembly/mock-exam-layout-policy-v1.schema.json",
            "1.0",
            "sha256:5841b8770b3baab7440c27e39303a1e27fd06513cfcc1093f6fbf73dbcd0428c",
        ),
        "mock-exam-rating-policy": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-rating-policy-v1.schema.json",
            "resources/assessment-assembly/mock-exam-rating-policy-v1.schema.json",
            "1.0",
            "sha256:e5b0bd19c72c85c93a3de83641e255dd61b3ab20b1af49244bdcb206e859be9c",
        ),
        "mock-exam-assembly-policy": CatalogSchemaResource(
            "schemas/assessment-assembly/mock-exam-assembly-policy-v1.schema.json",
            "resources/assessment-assembly/mock-exam-assembly-policy-v1.schema.json",
            "1.0",
            "sha256:85b1ec2e031452d1a514b7eb530c603d2f25fa258adde662dc10b8152d3ba0ba",
        ),
        "assessment-assembly-manifest": CatalogSchemaResource(
            "schemas/legacy-usage/assessment-assembly-manifest-v1.schema.json",
            "resources/legacy-usage/assessment-assembly-manifest-v1.schema.json",
            "1.0",
            "sha256:785d470fceff548e4d6d01a4b5c964bd1193f659d66c4844bce07fb7a3ee62c6",
        ),
        "intake-manifest": CatalogSchemaResource(
            "schemas/content-intake/intake-manifest-v1.schema.json",
            "resources/content-intake/intake-manifest-v1.schema.json",
            "1.0",
            "sha256:5f3b9dcd459988143491557ccf5f220a53c0467d461235ba22de587d0c8b63f0",
        ),
        "pdf-document-review-intake-manifest": CatalogSchemaResource(
            "schemas/document-review/pdf-document-review-intake-manifest-v1.schema.json",
            "resources/document-review/pdf-document-review-intake-manifest-v1.schema.json",
            "1.0",
            "sha256:32c2ccf98930d6e865aaeefe31abbf37e5749f21851bfbf9446d64ecb70683d6",
        ),
        "document-review-evidence-plan": CatalogSchemaResource(
            "schemas/document-review/document-review-evidence-plan-v1.schema.json",
            "resources/document-review/document-review-evidence-plan-v1.schema.json",
            "1.0",
            "sha256:62cc57bec58327da8ab18d83a42307bea34bd8bb09f9a365d35d005d91ccede0",
        ),
        "document-review-evidence-request": CatalogSchemaResource(
            "schemas/catalog-application/document-review-evidence-request-v1.schema.json",
            "resources/catalog-application/document-review-evidence-request-v1.schema.json",
            "1.0",
            "sha256:c9b8d219761ead1f8630809bb29513ee730fae35a947ada0093ae1dd71bc98c1",
        ),
        "document-review-evidence-response": CatalogSchemaResource(
            "schemas/catalog-application/document-review-evidence-response-v1.schema.json",
            "resources/catalog-application/document-review-evidence-response-v1.schema.json",
            "1.0",
            "sha256:b30460358b6c7e83973cb5f85bbd52382f5f07fa05afaf20a35a90a4e45ac793",
        ),
        "pdf-document-review-intake-request": CatalogSchemaResource(
            (
                "schemas/catalog/catalog-application/"
                "pdf-document-review-intake-request-v1.schema.json"
            ),
            ("resources/catalog-application/pdf-document-review-intake-request-v1.schema.json"),
            "1.0",
            "sha256:c9bc0a613b321ad7a4e1b6f5f4deba19f86615841af9de8c6ab28a30b0f5b390",
        ),
        "pdf-document-review-intake-response": CatalogSchemaResource(
            (
                "schemas/catalog/catalog-application/"
                "pdf-document-review-intake-response-v1.schema.json"
            ),
            ("resources/catalog-application/pdf-document-review-intake-response-v1.schema.json"),
            "1.0",
            "sha256:78901a218555b0f9de62f4bf9ac303032cfa7ded812e63c804d33a69775da24a",
        ),
        "document-review-intake-manifest-v2": CatalogSchemaResource(
            "schemas/document-review/document-review-intake-manifest-v2.schema.json",
            "resources/document-review/document-review-intake-manifest-v2.schema.json",
            "2.0",
            "sha256:2db5aec370f13028383de3d68f2713828b84c2107331cd7f520894b5509d3169",
        ),
        "document-review-intake-request-v2": CatalogSchemaResource(
            "schemas/catalog/catalog-application/document-review-intake-request-v2.schema.json",
            "resources/catalog-application/document-review-intake-request-v2.schema.json",
            "2.0",
            "sha256:acf9bc93b25318cf304c85cbb63598a619956f3d7207ab66eb6127128c082977",
        ),
        "document-review-intake-response-v2": CatalogSchemaResource(
            "schemas/catalog/catalog-application/document-review-intake-response-v2.schema.json",
            "resources/catalog-application/document-review-intake-response-v2.schema.json",
            "2.0",
            "sha256:982cbba5d9ce69f95cbda32a5fe5a7dfedf4d828d49b4e0c2228a6a1f4b435e5",
        ),
        "document-review-source-upload-manifest-v1": CatalogSchemaResource(
            "schemas/document-review/document-review-source-upload-manifest-v1.schema.json",
            "resources/document-review/document-review-source-upload-manifest-v1.schema.json",
            "1.0",
            "sha256:3c9c3fed9c98d655e96c4372f6e4f0f68fdde094ff5289ff6985f12e7cbec60f",
        ),
        "document-review-intake-manifest-v3": CatalogSchemaResource(
            "schemas/document-review/document-review-intake-manifest-v3.schema.json",
            "resources/document-review/document-review-intake-manifest-v3.schema.json",
            "3.0",
            "sha256:31a48720f4d1802435c1f59a9b79b30392e230dd8d2311fb35c1542ef5ae1677",
        ),
        "office-document-conversion-outcome-v1": CatalogSchemaResource(
            "schemas/document-review/office-document-conversion-outcome-v1.schema.json",
            "resources/document-review/office-document-conversion-outcome-v1.schema.json",
            "1.0",
            "sha256:f20ee93d89d590b2885b2d19dcd64e6158df3f016611a17cc2d534f244dca007",
        ),
        "document-review-intake-request-v3": CatalogSchemaResource(
            "schemas/catalog/catalog-application/document-review-intake-request-v3.schema.json",
            "resources/catalog-application/document-review-intake-request-v3.schema.json",
            "3.0",
            "sha256:0447ce890ffb482fa967c55e5652a66fe57023fd376fcc54250a2bd92503ae32",
        ),
        "document-review-intake-response-v3": CatalogSchemaResource(
            "schemas/catalog/catalog-application/document-review-intake-response-v3.schema.json",
            "resources/catalog-application/document-review-intake-response-v3.schema.json",
            "3.0",
            "sha256:bda9770d17f7ce31199dab195c37ed3b6242f45f9af834fdaf632eb060e4b859",
        ),
        "document-review-hwpx-correction-request-v2": CatalogSchemaResource(
            "schemas/catalog/catalog-application/document-review-hwpx-correction-request-v2.schema.json",
            "resources/catalog-application/document-review-hwpx-correction-request-v2.schema.json",
            "2.0",
            "sha256:10280c29dd927a3c3b49aa0ff3fb0542c63eabbc6a6a99a72b7fc7522cdc1035",
        ),
        "document-review-pdf-annotation-request-v4": CatalogSchemaResource(
            "schemas/catalog/catalog-application/document-review-pdf-annotation-request-v4.schema.json",
            "resources/catalog-application/document-review-pdf-annotation-request-v4.schema.json",
            "4.0",
            "sha256:074ea17cf18f8360f83e4d1cf2b06a28ae8f8ca4b03761e00f63bd1c30b357c8",
        ),
        "document-review-hwpx-correction-plan-v2": CatalogSchemaResource(
            "schemas/document-review/document-review-hwpx-correction-plan-v2.schema.json",
            "resources/document-review/document-review-hwpx-correction-plan-v2.schema.json",
            "2.0",
            "sha256:528e65ef165c2247e556b5ccd916c5b26f446c8edb78fb3f3f26cce0985aae2a",
        ),
        "document-review-hwpx-correction-request": CatalogSchemaResource(
            (
                "schemas/catalog/catalog-application/"
                "document-review-hwpx-correction-request-v1.schema.json"
            ),
            (
                "resources/catalog-application/"
                "document-review-hwpx-correction-request-v1.schema.json"
            ),
            "1.0",
            "sha256:62212d93d6ce15223a60e775b6eb901cc9c4e228256a6e56ee183f98573c7019",
        ),
        "document-review-hwpx-correction-response": CatalogSchemaResource(
            (
                "schemas/catalog/catalog-application/"
                "document-review-hwpx-correction-response-v1.schema.json"
            ),
            (
                "resources/catalog-application/"
                "document-review-hwpx-correction-response-v1.schema.json"
            ),
            "1.0",
            "sha256:571956d3b6e4f0c34e75f3a5e59603a1df28ec4113e52824b459513ba7af6582",
        ),
        "document-review-hwpx-correction-media-request": CatalogSchemaResource(
            (
                "schemas/catalog/catalog-application/"
                "document-review-hwpx-correction-media-request-v1.schema.json"
            ),
            (
                "resources/catalog-application/"
                "document-review-hwpx-correction-media-request-v1.schema.json"
            ),
            "1.0",
            "sha256:1970162089fc2d5648295c10adc5e51aba58f2929009ef3cefad326617e85bbe",
        ),
        "document-review-hwpx-correction-media-response": CatalogSchemaResource(
            (
                "schemas/catalog/catalog-application/"
                "document-review-hwpx-correction-media-response-v1.schema.json"
            ),
            (
                "resources/catalog-application/"
                "document-review-hwpx-correction-media-response-v1.schema.json"
            ),
            "1.0",
            "sha256:3167d799d8142a1dd0bbeb0f27c9d7471bafee1755aca3a080c4396364ba7cec",
        ),
        "document-review-hwpx-correction-plan": CatalogSchemaResource(
            "schemas/document-review/document-review-hwpx-correction-plan-v1.schema.json",
            "resources/document-review/document-review-hwpx-correction-plan-v1.schema.json",
            "1.0",
            "sha256:26992284f11810a230c6d77b702a41c8064beb38ea7d381ec7f01ea923ec0058",
        ),
        "document-review-hwpx-correction-result": CatalogSchemaResource(
            "schemas/document-review/document-review-hwpx-correction-result-v1.schema.json",
            "resources/document-review/document-review-hwpx-correction-result-v1.schema.json",
            "1.0",
            "sha256:a99384585c6d6d9b42082733bd4a3d482fad15b166582d688366442696ff0dd2",
        ),
        "document-review-pdf-annotation-request": CatalogSchemaResource(
            (
                "schemas/catalog/catalog-application/"
                "document-review-pdf-annotation-request-v1.schema.json"
            ),
            ("resources/catalog-application/document-review-pdf-annotation-request-v1.schema.json"),
            "1.0",
            "sha256:bf4bffe7f5ce2030d7403000fc9f354a25a4d03cc86a211cd5ae80bf941c16d8",
        ),
        "document-review-pdf-annotation-request-v2": CatalogSchemaResource(
            (
                "schemas/catalog/catalog-application/"
                "document-review-pdf-annotation-request-v2.schema.json"
            ),
            ("resources/catalog-application/document-review-pdf-annotation-request-v2.schema.json"),
            "2.0",
            "sha256:7be6dab92977290406b82fed25c597b97f93b5b6606bddccca3b1f81dbc3eed8",
        ),
        "document-review-pdf-annotation-request-v3": CatalogSchemaResource(
            (
                "schemas/catalog/catalog-application/"
                "document-review-pdf-annotation-request-v3.schema.json"
            ),
            ("resources/catalog-application/document-review-pdf-annotation-request-v3.schema.json"),
            "3.0",
            "sha256:f192409e3bfcc8a5eaadda013cf7560abd676e19930780bc060a27f374adec6b",
        ),
        "document-review-pdf-annotation-response": CatalogSchemaResource(
            (
                "schemas/catalog/catalog-application/"
                "document-review-pdf-annotation-response-v1.schema.json"
            ),
            (
                "resources/catalog-application/"
                "document-review-pdf-annotation-response-v1.schema.json"
            ),
            "1.0",
            "sha256:688036a8101999d62414ebee4445f48d4acf8c78f9f46dbaaf38ceba52b662fe",
        ),
        "document-review-pdf-annotation-response-v2": CatalogSchemaResource(
            (
                "schemas/catalog/catalog-application/"
                "document-review-pdf-annotation-response-v2.schema.json"
            ),
            (
                "resources/catalog-application/"
                "document-review-pdf-annotation-response-v2.schema.json"
            ),
            "2.0",
            "sha256:746458392aa78bdfec02d6edc45b4edd51c421743c2816ba219f89bb40be03a4",
        ),
        "document-review-pdf-annotation-media-request": CatalogSchemaResource(
            (
                "schemas/catalog/catalog-application/"
                "document-review-pdf-annotation-media-request-v1.schema.json"
            ),
            (
                "resources/catalog-application/"
                "document-review-pdf-annotation-media-request-v1.schema.json"
            ),
            "1.0",
            "sha256:64ebdb48209bd3021c3f80335cddd811897569ba299b04f12398a2a4c09f9f50",
        ),
        "document-review-pdf-annotation-media-response": CatalogSchemaResource(
            (
                "schemas/catalog/catalog-application/"
                "document-review-pdf-annotation-media-response-v1.schema.json"
            ),
            (
                "resources/catalog-application/"
                "document-review-pdf-annotation-media-response-v1.schema.json"
            ),
            "1.0",
            "sha256:437cbe2367c7e58dff5ee0c695890faefedd5484ad7c8b342f42c394fef48f9f",
        ),
        "document-review-pdf-annotation-manifest": CatalogSchemaResource(
            "schemas/document-review/document-review-pdf-annotation-manifest-v1.schema.json",
            "resources/document-review/document-review-pdf-annotation-manifest-v1.schema.json",
            "1.0",
            "sha256:442e77ce1bcebc0306d020c7cffcf288074799a32bb4798d5a1f212ba815e083",
        ),
        "document-review-pdf-annotation-manifest-v2": CatalogSchemaResource(
            "schemas/document-review/document-review-pdf-annotation-manifest-v2.schema.json",
            "resources/document-review/document-review-pdf-annotation-manifest-v2.schema.json",
            "2.0",
            "sha256:81e1647a71f138424f87d2401527759f197228386862ff8228800f1e6a1b9bd9",
        ),
        "document-review-pdf-annotation-result": CatalogSchemaResource(
            "schemas/document-review/document-review-pdf-annotation-result-v1.schema.json",
            "resources/document-review/document-review-pdf-annotation-result-v1.schema.json",
            "1.0",
            "sha256:426be96da09053ef3b716f19f64e2d87e7ff5c178d63ce39f88cabf710232567",
        ),
        "document-review-pdf-annotation-result-v2": CatalogSchemaResource(
            "schemas/document-review/document-review-pdf-annotation-result-v2.schema.json",
            "resources/document-review/document-review-pdf-annotation-result-v2.schema.json",
            "2.0",
            "sha256:81b4e95d1be0988ffe6f3ef9d72c9b9ed432e868a60615e72e0156edf1fcf983",
        ),
        "mapping-proposal": CatalogSchemaResource(
            "schemas/content-intake/mapping-proposal-v1.schema.json",
            "resources/content-intake/mapping-proposal-v1.schema.json",
            "1.0",
            "sha256:4e2699ca42b8fe0c4ecb0993ce4119110cbebf273eecb135d57414c7e1e40a83",
        ),
        "legacy-usage-import-manifest": CatalogSchemaResource(
            "schemas/legacy-usage/legacy-usage-import-manifest-v1.schema.json",
            "resources/legacy-usage/legacy-usage-import-manifest-v1.schema.json",
            "1.0",
            "sha256:c25893647ebab2969b8f403f409a52c3fa78d169277d1cc00db483f2ee21c3a0",
        ),
        "legacy-usage-mapping-contract": CatalogSchemaResource(
            "schemas/legacy-usage/legacy-usage-mapping-contract-v1.schema.json",
            "resources/legacy-usage/legacy-usage-mapping-contract-v1.schema.json",
            "1.0",
            "sha256:9e697413fe059e3041b6e828d5ec280f27b9cf83466969625a45d1066d9f8548",
        ),
        "legacy-usage-row-proposal": CatalogSchemaResource(
            "schemas/legacy-usage/legacy-usage-row-proposal-v1.schema.json",
            "resources/legacy-usage/legacy-usage-row-proposal-v1.schema.json",
            "1.0",
            "sha256:60824ea6e061eeb56e447af4312e15296d9a88abee42a70ef45808af5049957f",
        ),
        "legacy-source-inventory": CatalogSchemaResource(
            "schemas/legacy-knowledge/legacy-source-inventory-v1.schema.json",
            "resources/legacy-knowledge/legacy-source-inventory-v1.schema.json",
            "1.0",
            "sha256:7fdce3b0bfeab4248c546d3eb6404fc9ddc8a5f340b31d48d3e4f3ac70954411",
        ),
        "legacy-source-inventory-policy": CatalogSchemaResource(
            "schemas/legacy-knowledge/legacy-source-inventory-policy-v1.schema.json",
            "resources/legacy-knowledge/legacy-source-inventory-policy-v1.schema.json",
            "1.0",
            "sha256:a48a917eeeb5460404c58f8ca12bdf6bcf0b70a15cbec88fa7398442bd79c742",
        ),
        "legacy-source-inventory-v2": CatalogSchemaResource(
            "schemas/legacy-knowledge/legacy-source-inventory-v2.schema.json",
            "resources/legacy-knowledge/legacy-source-inventory-v2.schema.json",
            "2.0",
            "sha256:ecb02a261d523e640cda1d11118b988c1d5038e020429e959856eb08c65979e7",
        ),
        "legacy-source-relation-manifest": CatalogSchemaResource(
            "schemas/legacy-knowledge/legacy-source-relation-manifest-v1.schema.json",
            "resources/legacy-knowledge/legacy-source-relation-manifest-v1.schema.json",
            "1.0",
            "sha256:0f4c5b0e67243e5b6686d1d7bff8871a0f31f895a3b8e8ecfd888294a8605c26",
        ),
        "legacy-source-rights-review": CatalogSchemaResource(
            "schemas/legacy-knowledge/legacy-source-rights-review-v1.schema.json",
            "resources/legacy-knowledge/legacy-source-rights-review-v1.schema.json",
            "1.0",
            "sha256:0ab0b051ca3bb4830fbc0d8c35af38bd809e617e6edc3e270e8103e23487c7c7",
        ),
        "legacy-source-rights-review-v2": CatalogSchemaResource(
            "schemas/legacy-knowledge/legacy-source-rights-review-v2.schema.json",
            "resources/legacy-knowledge/legacy-source-rights-review-v2.schema.json",
            "2.0",
            "sha256:de8a98565ffb8b6d326cd716ff8245778a0ea11702838bf6dd5475b7fecef3f5",
        ),
        "legacy-source-selection": CatalogSchemaResource(
            "schemas/legacy-knowledge/legacy-source-selection-v1.schema.json",
            "resources/legacy-knowledge/legacy-source-selection-v1.schema.json",
            "1.0",
            "sha256:89acd96ec4f08ec7aa11da34370db02666fdccb289e0574b5c21065f43940111",
        ),
        "legacy-source-selection-v2": CatalogSchemaResource(
            "schemas/legacy-knowledge/legacy-source-selection-v2.schema.json",
            "resources/legacy-knowledge/legacy-source-selection-v2.schema.json",
            "2.0",
            "sha256:0c25bfa3c8732f85306b7077199e0f222aab65203c468a8ecb813f6092407775",
        ),
        "pdf-page-range-materialization-manifest": CatalogSchemaResource(
            "schemas/legacy-knowledge/pdf-page-range-materialization-manifest-v1.schema.json",
            "resources/legacy-knowledge/pdf-page-range-materialization-manifest-v1.schema.json",
            "1.0",
            "sha256:08bf76c009dadebce705bf667cee8364a23b378ee57427aa754fdb968876d6aa",
        ),
        "textbook-analysis-bundle-manifest": CatalogSchemaResource(
            "schemas/legacy-knowledge/textbook-analysis-bundle-manifest-v1.schema.json",
            "resources/legacy-knowledge/textbook-analysis-bundle-manifest-v1.schema.json",
            "1.0",
            "sha256:9c53d4f99b37d229899f367351bb50433d1bb67a4eb79c9a0c50706cabad0133",
        ),
        "textbook-analysis-bundle-manifest-v2": CatalogSchemaResource(
            "schemas/legacy-knowledge/textbook-analysis-bundle-manifest-v2.schema.json",
            "resources/legacy-knowledge/textbook-analysis-bundle-manifest-v2.schema.json",
            "2.0",
            "sha256:250d76be4267a1dbf92884811af7b6e616bd4978a0b2c2fbd593c92e4f1e541a",
        ),
        "item-origin-types": CatalogSchemaResource(
            "schemas/item-origin/item-origin-types-v1.schema.json",
            "resources/item-origin/item-origin-types-v1.schema.json",
            "1.0",
            "sha256:51f25418d08cbc2c26848a6db129fee3e7b88e19dc9228ee149cfea05d040b0c",
        ),
        "organization-revision": CatalogSchemaResource(
            "schemas/item-origin/organization-revision-v1.schema.json",
            "resources/item-origin/organization-revision-v1.schema.json",
            "1.0",
            "sha256:62cabab12bac346efef23c352c8eaeb95e0ca012682e802f8a43e83d15178a8b",
        ),
        "assessment-occurrence-revision": CatalogSchemaResource(
            "schemas/item-origin/assessment-occurrence-revision-v1.schema.json",
            "resources/item-origin/assessment-occurrence-revision-v1.schema.json",
            "1.0",
            "sha256:0ae2cdc2ddce804dbdec22a175847061ed096be561f07a5ffda0ac0167e1f722",
        ),
        "assessment-occurrence-revision-v2": CatalogSchemaResource(
            "schemas/item-origin/assessment-occurrence-revision-v2.schema.json",
            "resources/item-origin/assessment-occurrence-revision-v2.schema.json",
            "2.0",
            "sha256:169ed9def9fa8500abee2b23a99824bcb00cffe79ad3420294d3af5480dadb4d",
        ),
        "item-origin-profile": CatalogSchemaResource(
            "schemas/item-origin/item-origin-profile-v1.schema.json",
            "resources/item-origin/item-origin-profile-v1.schema.json",
            "1.0",
            "sha256:38059059f8b2d95854ac14c969a2661d83dea3de9529e282386a3faaff2dd9e6",
        ),
        "legacy-assessment-types": CatalogSchemaResource(
            "schemas/legacy-assessment/legacy-assessment-types-v1.schema.json",
            "resources/legacy-assessment/legacy-assessment-types-v1.schema.json",
            "1.0",
            "sha256:6bfa999200ba29d50a7da4aa1daecabe7bedd0c0adcb7b48beac0bb8b5c963b5",
        ),
        "assessment-source-bundle-proposal": CatalogSchemaResource(
            "schemas/legacy-assessment/assessment-source-bundle-proposal-v1.schema.json",
            "resources/legacy-assessment/assessment-source-bundle-proposal-v1.schema.json",
            "1.0",
            "sha256:84308332c21aeef93ffec4e17c7ffb23dbd41634bf0357d632aa1a18311825e6",
        ),
        "assessment-source-bundle": CatalogSchemaResource(
            "schemas/legacy-assessment/assessment-source-bundle-v1.schema.json",
            "resources/legacy-assessment/assessment-source-bundle-v1.schema.json",
            "1.0",
            "sha256:9fc91febb16de433b077ba61fd6f52015e7ff5dcac9cd85b5a08fcc89bab5592",
        ),
        "assessment-layout-observation": CatalogSchemaResource(
            "schemas/legacy-assessment/assessment-layout-observation-v1.schema.json",
            "resources/legacy-assessment/assessment-layout-observation-v1.schema.json",
            "1.0",
            "sha256:ce10b60ff6ca4e94191ac9d23a512af94f364df82e713c171433b038ba51396c",
        ),
        "legacy-item-extraction-request": CatalogSchemaResource(
            "schemas/legacy-assessment/legacy-item-extraction-request-v1.schema.json",
            "resources/legacy-assessment/legacy-item-extraction-request-v1.schema.json",
            "1.0",
            "sha256:c7345e533aa51b0cf6dece535d89b4848a5b6452fc29b2f31ec96cd77b0c4bf0",
        ),
        "legacy-item-extraction-batch": CatalogSchemaResource(
            "schemas/legacy-assessment/legacy-item-extraction-batch-v1.schema.json",
            "resources/legacy-assessment/legacy-item-extraction-batch-v1.schema.json",
            "1.0",
            "sha256:f3507d450aa77c8f90d8d500de185b9091e92ae556d1f3b4b075c13f75245180",
        ),
        "science-assessment-web-acquisition": CatalogSchemaResource(
            "schemas/legacy-assessment/science-assessment-web-acquisition-v1.schema.json",
            "resources/legacy-assessment/science-assessment-web-acquisition-v1.schema.json",
            "1.0",
            "sha256:28493d454739761c352c3459c3a09adc4f1786b63e6e72eb3d5b5b0a89ddeec5",
        ),
        "science-assessment-metadata-resolution": CatalogSchemaResource(
            ("schemas/legacy-assessment/science-assessment-metadata-resolution-v1.schema.json"),
            ("resources/legacy-assessment/science-assessment-metadata-resolution-v1.schema.json"),
            "1.0",
            "sha256:71cbe3b3233d09be184568a6468fc72dcd76922ac152445b4cbdd0ff9768e4e4",
        ),
        "science-assessment-web-corpus-plan": CatalogSchemaResource(
            "schemas/legacy-assessment/science-assessment-web-corpus-plan-v1.schema.json",
            "resources/legacy-assessment/science-assessment-web-corpus-plan-v1.schema.json",
            "1.0",
            "sha256:2ad0dc68ec23e27d7bab4f4b097370b6bfe1c35c4c8539e34213a8f100b77e18",
        ),
        "science-assessment-web-corpus-manifest": CatalogSchemaResource(
            "schemas/legacy-assessment/science-assessment-web-corpus-manifest-v1.schema.json",
            "resources/legacy-assessment/science-assessment-web-corpus-manifest-v1.schema.json",
            "1.0",
            "sha256:50bfa4ece78b249ff2fc2da7c187a97a116c6689710c05d5068f427abd98d54d",
        ),
        "science-assessment-web-corpus-manifest-v2": CatalogSchemaResource(
            ("schemas/legacy-assessment/science-assessment-web-corpus-manifest-v2.schema.json"),
            ("resources/legacy-assessment/science-assessment-web-corpus-manifest-v2.schema.json"),
            "2.0",
            "sha256:dd57a020106016a54a08712f065fb80231697abc9c0a03464117d227560dab64",
        ),
        "legacy-item-extraction-batch-v2": CatalogSchemaResource(
            "schemas/legacy-assessment/legacy-item-extraction-batch-v2.schema.json",
            "resources/legacy-assessment/legacy-item-extraction-batch-v2.schema.json",
            "1.1",
            "sha256:712855481c549fd52432282e92880cfd387fb9709f8123cc3a4b78756aafc500",
        ),
        "legacy-item-extraction-validation-recovery": CatalogSchemaResource(
            ("schemas/legacy-assessment/legacy-item-extraction-validation-recovery-v1.schema.json"),
            (
                "resources/legacy-assessment/"
                "legacy-item-extraction-validation-recovery-v1.schema.json"
            ),
            "1.0",
            "sha256:9cdbbc056f0919bc84e73040986d913c5ecbf664760c7ecc2f7a7398138a77f0",
        ),
        "legacy-extraction-result-identity-collisions": CatalogSchemaResource(
            (
                "schemas/legacy-assessment/"
                "legacy-extraction-result-identity-collisions-v1.schema.json"
            ),
            (
                "resources/legacy-assessment/"
                "legacy-extraction-result-identity-collisions-v1.schema.json"
            ),
            "1.0",
            "sha256:aa5434934b2c14e0517f7cf3bda65b58a691d28a5f672dcaab1778c798a2119b",
        ),
        "legacy-item-corpus-completion-command": CatalogSchemaResource(
            "schemas/legacy-assessment/legacy-item-corpus-completion-command-v1.schema.json",
            "resources/legacy-assessment/legacy-item-corpus-completion-command-v1.schema.json",
            "1.0",
            "sha256:44aa4e6b1c7a77d932de1806e34f783e014e427755aac99318fed7d1726c8169",
        ),
        "legacy-item-corpus-completion-command-v2": CatalogSchemaResource(
            "schemas/legacy-assessment/legacy-item-corpus-completion-command-v2.schema.json",
            "resources/legacy-assessment/legacy-item-corpus-completion-command-v2.schema.json",
            "1.1",
            "sha256:a1e6ac8f54119f68f7664098103a0356e6fbac1070c926af7d1551be712c05b1",
        ),
        "legacy-item-corpus-completion-receipt": CatalogSchemaResource(
            "schemas/legacy-assessment/legacy-item-corpus-completion-receipt-v1.schema.json",
            "resources/legacy-assessment/legacy-item-corpus-completion-receipt-v1.schema.json",
            "1.0",
            "sha256:9851152632eccb1b3176616e24284e6c066df752f1ede84c67ba31778b22e84a",
        ),
        "legacy-item-corpus-completion-receipt-v2": CatalogSchemaResource(
            "schemas/legacy-assessment/legacy-item-corpus-completion-receipt-v2.schema.json",
            "resources/legacy-assessment/legacy-item-corpus-completion-receipt-v2.schema.json",
            "1.1",
            "sha256:3ea010b251237a60c184548e9e6391d55a74707c262bc71c7898bc47260cbd68",
        ),
        "pdf-learning-completion": CatalogSchemaResource(
            "schemas/legacy-assessment/pdf-learning-completion-v1.schema.json",
            "resources/legacy-assessment/pdf-learning-completion-v1.schema.json",
            "1.0",
            "sha256:1652de61ff752ea8e21f79c819b16b214a8896b90bcde2a4d44cc0f5060e10a4",
        ),
        "pdf-learning-completion-v2": CatalogSchemaResource(
            "schemas/legacy-assessment/pdf-learning-completion-v2.schema.json",
            "resources/legacy-assessment/pdf-learning-completion-v2.schema.json",
            "1.1",
            "sha256:890281dfe762d3a643e39f573592cafd22dcf4687e8637aa638b64266122e6da",
        ),
        "pdf-learning-completion-v3": CatalogSchemaResource(
            "schemas/legacy-assessment/pdf-learning-completion-v3.schema.json",
            "resources/legacy-assessment/pdf-learning-completion-v3.schema.json",
            "1.2",
            "sha256:f2092ffff5c646ca06af87097d14033fee815d0d5d628f54bfb27115a03c3b0d",
        ),
        "pdf-learning-item-completion-shard": CatalogSchemaResource(
            "schemas/legacy-assessment/pdf-learning-item-completion-shard-v1.schema.json",
            "resources/legacy-assessment/pdf-learning-item-completion-shard-v1.schema.json",
            "1.0",
            "sha256:ad4b16e687343513ae47e38f85c5386ca58e786f3186c37bbb253381b1f25874",
        ),
        "legacy-item-extraction-receipt": CatalogSchemaResource(
            "schemas/legacy-assessment/legacy-item-extraction-receipt-v1.schema.json",
            "resources/legacy-assessment/legacy-item-extraction-receipt-v1.schema.json",
            "1.0",
            "sha256:0a4650e2c38fc31270db8ba5874643730da12f60f4715613528e128244d79b1a",
        ),
        "legacy-item-extraction-result": CatalogSchemaResource(
            "schemas/legacy-assessment/legacy-item-extraction-result-v1.schema.json",
            "resources/legacy-assessment/legacy-item-extraction-result-v1.schema.json",
            "1.0",
            "sha256:2c81a578eebdbfd450af0e386196a7d3892cb7083b061dce97f9b86c8d16b2e5",
        ),
        "legacy-item-media-pointer-compatibility-policy": CatalogSchemaResource(
            "schemas/legacy-assessment/"
            "legacy-item-media-pointer-compatibility-policy-v1.schema.json",
            "resources/legacy-assessment/"
            "legacy-item-media-pointer-compatibility-policy-v1.schema.json",
            "1.0",
            "sha256:96afd0d95efe77b9a4367977c5629c79d6598429c15cbea0418eee03be779c6f",
        ),
        "legacy-item-extraction-acceptance": CatalogSchemaResource(
            "schemas/legacy-assessment/legacy-item-extraction-acceptance-v1.schema.json",
            "resources/legacy-assessment/legacy-item-extraction-acceptance-v1.schema.json",
            "1.0",
            "sha256:cc998174aaccc487c8449f91c4156c8caaf23ec294d06fa905b39bad7d8a11a6",
        ),
        "legacy-item-promotion-request": CatalogSchemaResource(
            "schemas/legacy-assessment/legacy-item-promotion-request-v1.schema.json",
            "resources/legacy-assessment/legacy-item-promotion-request-v1.schema.json",
            "1.0",
            "sha256:d0273a9367abff2d2fa5ed5f7af6b4424521c97fb4a615c18156e6c584585fce",
        ),
        "legacy-item-editorial-compatibility-request": CatalogSchemaResource(
            "schemas/legacy-assessment/legacy-item-editorial-compatibility-request-v1.schema.json",
            "resources/legacy-assessment/legacy-item-editorial-compatibility-request-v1.schema.json",
            "1.0",
            "sha256:0d9809e4faf8b06f5c17d6db3d2ad54dfb505367d2346839ea69670141f57bea",
        ),
        "legacy-item-editorial-compatibility-policy": CatalogSchemaResource(
            "schemas/legacy-assessment/legacy-item-editorial-compatibility-policy-v1.schema.json",
            "resources/legacy-assessment/legacy-item-editorial-compatibility-policy-v1.schema.json",
            "1.0",
            "sha256:2c61e37fa9f2087ae52f552d7f40d6a36207680d111f6dd89b695c3128443a0d",
        ),
        "legacy-item-editorial-compatibility-result": CatalogSchemaResource(
            "schemas/legacy-assessment/legacy-item-editorial-compatibility-result-v1.schema.json",
            "resources/legacy-assessment/legacy-item-editorial-compatibility-result-v1.schema.json",
            "1.0",
            "sha256:5d64ac1e1d3210cb5541502794c5e9f1293a589a011cb7af744ba5fe53110260",
        ),
        "legacy-item-editorial-compatibility-proposal": CatalogSchemaResource(
            "schemas/legacy-assessment/legacy-item-editorial-compatibility-proposal-v1.schema.json",
            "resources/legacy-assessment/legacy-item-editorial-compatibility-proposal-v1.schema.json",
            "1.0",
            "sha256:f4fc79d5ce7986f06a84fd8246561aff0599da95b527ade592c15bebfd91055e",
        ),
        "legacy-item-corpus-coverage": CatalogSchemaResource(
            "schemas/legacy-assessment/legacy-item-corpus-coverage-v1.schema.json",
            "resources/legacy-assessment/legacy-item-corpus-coverage-v1.schema.json",
            "1.0",
            "sha256:b739132cabd2c2cafb246942e5b6d8fe05e6195aefdc09594182555869004021",
        ),
        "product-usage-graph-projection": CatalogSchemaResource(
            "schemas/legacy-usage/product-usage-graph-projection-v1.schema.json",
            "resources/legacy-usage/product-usage-graph-projection-v1.schema.json",
            "1.0",
            "sha256:ac5a3d66d83769a523e2dd8331c9562650a04de3e2368a3f9d91968fa8076820",
        ),
        "uncertainties": CatalogSchemaResource(
            "schemas/content-intake/uncertainties-v1.schema.json",
            "resources/content-intake/uncertainties-v1.schema.json",
            "1.0",
            "sha256:6cbe845ff766076ce64d76c7c9483f164a454fac92f8e5ba6dc374c89d79bebf",
        ),
        "human-decision": CatalogSchemaResource(
            "schemas/content-intake/human-decision-v1.schema.json",
            "resources/content-intake/human-decision-v1.schema.json",
            "1.0",
            "sha256:7d8c6f988229f0f6036d586716b228f1c1082ead7bccf02dc2ba66d25f2f8f26",
        ),
        "content-pack": CatalogSchemaResource(
            "schemas/content-pack/content-pack-v1.schema.json",
            "resources/content-pack/content-pack-v1.schema.json",
            "1.0",
            "sha256:8d121d187885a9c1c2b588493d9d7337856614db6d5011306d63b16a9219fb8b",
        ),
        "content-pack-v2": CatalogSchemaResource(
            "schemas/content-pack/content-pack-v2.schema.json",
            "resources/content-pack/content-pack-v2.schema.json",
            "1.1",
            "sha256:c1d2576b5cf8e52e4590dedb2f8950d8c1bf62450062d2ef7a9f7b0e3a7e51d3",
        ),
        "integrated-science-editorial-outline": CatalogSchemaResource(
            "schemas/curriculum/integrated-science-editorial-outline-v1.schema.json",
            "resources/curriculum/integrated-science-editorial-outline-v1.schema.json",
            "1.0",
            "sha256:6b3e0bff6435827b322337f5c8a48e920c3fffc149e4e047e71374ededb28745",
        ),
        "eom-guidance-markdown-control": CatalogSchemaResource(
            "schemas/guidance/eom-guidance-markdown-control-v1.schema.json",
            "resources/guidance/eom-guidance-markdown-control-v1.schema.json",
            "1.0",
            "sha256:9d34f2c8ff6c5c6d7f58593d0c25ac0b47584efb7cc735151498d2284d1725ac",
        ),
        "educational-document-types": CatalogSchemaResource(
            "schemas/educational-document/educational-document-types-v1.schema.json",
            "resources/educational-document/educational-document-types-v1.schema.json",
            "1.0",
            "sha256:395fe3dcbbc300678d4e251fb92cb8c437a59dad2d8f80fdfeda7f54f12c9cb5",
        ),
        "educational-document-rights-attestation": CatalogSchemaResource(
            "schemas/educational-document/educational-document-rights-attestation-v1.schema.json",
            "resources/educational-document/educational-document-rights-attestation-v1.schema.json",
            "1.0",
            "sha256:70a7620748a7547fbc8270b35113cdcd1b997e3bbc2a33a46cea143aa6f8e65c",
        ),
        "educational-document-registration-request": CatalogSchemaResource(
            "schemas/educational-document/educational-document-registration-request-v1.schema.json",
            "resources/educational-document/educational-document-registration-request-v1.schema.json",
            "1.0",
            "sha256:f32c5164ab16fd770d2381e4c031f535850608070fa548f7f9ef9eb9cd09ce2d",
        ),
        "educational-document-registration-request-v2": CatalogSchemaResource(
            "schemas/educational-document/educational-document-registration-request-v2.schema.json",
            "resources/educational-document/educational-document-registration-request-v2.schema.json",
            "2.0",
            "sha256:95daf98c15ab2cdb4157c81bbd80471a8593f67b199d0f153a9c47f13448a367",
        ),
        "educational-document-revision-manifest": CatalogSchemaResource(
            "schemas/educational-document/educational-document-revision-manifest-v1.schema.json",
            "resources/educational-document/educational-document-revision-manifest-v1.schema.json",
            "1.0",
            "sha256:cd63c557b4166984500e1ad5fb3c0d2ec9fb6f4b6b5bdc17e1999d4db2d807a0",
        ),
        "educational-document-revision-manifest-v2": CatalogSchemaResource(
            "schemas/educational-document/educational-document-revision-manifest-v2.schema.json",
            "resources/educational-document/educational-document-revision-manifest-v2.schema.json",
            "2.0",
            "sha256:8eedef05745b406e91fe6394b29e1314d26293a084c46d7412da0d0b54062eb2",
        ),
        "educational-document-registration-receipt": CatalogSchemaResource(
            "schemas/educational-document/educational-document-registration-receipt-v1.schema.json",
            "resources/educational-document/educational-document-registration-receipt-v1.schema.json",
            "1.0",
            "sha256:8f4d0c05c27a7b79a51206fac4dc904cc7c5db186d25ef98bea32aec53e845f5",
        ),
        "educational-document-registration-receipt-v2": CatalogSchemaResource(
            "schemas/educational-document/educational-document-registration-receipt-v2.schema.json",
            "resources/educational-document/educational-document-registration-receipt-v2.schema.json",
            "2.0",
            "sha256:eb6e5e853d967e58f325217d80d8d5828dfe287c9c17539a973230004b4d5d85",
        ),
        "content-pack-profile": CatalogSchemaResource(
            "schemas/content-pack/profile-v1.schema.json",
            "resources/content-pack/profile-v1.schema.json",
            "1.0",
            "sha256:d8af117b56737b3e9355284665be0d4775f39f6a9230974255c540725f44fcfb",
        ),
        "prompt-envelope": CatalogSchemaResource(
            "schemas/content-pack/prompt-envelope-v1.schema.json",
            "resources/content-pack/prompt-envelope-v1.schema.json",
            "1.0",
            "sha256:ac60d0750780f5b13149e40163823f39773376322bf4f7b7173bb2c9282210dc",
        ),
        "item-revision-manifest": CatalogSchemaResource(
            "schemas/item-registry/item-revision-manifest-v1.schema.json",
            "resources/item-registry/item-revision-manifest-v1.schema.json",
            "1.0",
            "sha256:9c6be99f5331d72fa43d3112f37bda45c0337829d44e8f91a05e145030a2c399",
        ),
        "item-revision-manifest-v2": CatalogSchemaResource(
            "schemas/item-registry/item-revision-manifest-v2.schema.json",
            "resources/item-registry/item-revision-manifest-v2.schema.json",
            "2.0",
            "sha256:b37d4683eced80a8bcb0eef8c669c991fdb556882dbf120a8c0fdab278b86c3e",
        ),
        "item-revision-approval-receipt": CatalogSchemaResource(
            "schemas/item-registry/item-revision-approval-receipt-v1.schema.json",
            "resources/item-registry/item-revision-approval-receipt-v1.schema.json",
            "1.0",
            "sha256:f388cca728cf7df1b6d0b74f258a49870b99c7e6fb45ef840ed015dbd652ba0c",
        ),
        "item-revision-hwpx-eligibility": CatalogSchemaResource(
            "schemas/item-registry/item-revision-hwpx-eligibility-v1.schema.json",
            "resources/item-registry/item-revision-hwpx-eligibility-v1.schema.json",
            "1.0",
            "sha256:bcbe2f90b8b5012d1c60ebe04cf35e956d417d832f7328e26c83426ca8cefda2",
        ),
        "assessment-item-content": CatalogSchemaResource(
            "schemas/item-registry/assessment-item-content-v1.schema.json",
            "resources/item-registry/assessment-item-content-v1.schema.json",
            "1.0",
            "sha256:ca0d360c209d26cce7e9283d42509204ccd8e50f519a85be871a2bbfc625a4bd",
        ),
        "assessment-item-content-v2": CatalogSchemaResource(
            "schemas/item-registry/assessment-item-content-v2.schema.json",
            "resources/item-registry/assessment-item-content-v2.schema.json",
            "2.0",
            "sha256:2136413f5059905be0c066c8fd657cbfc5238ba47e36ac3502be669ae130b9a8",
        ),
        "assessment-item-content-v3": CatalogSchemaResource(
            "schemas/item-registry/assessment-item-content-v3.schema.json",
            "resources/item-registry/assessment-item-content-v3.schema.json",
            "3.0",
            "sha256:3e9eada3374173119a74ddc7da1b21b6cf30d688d9a561c424120e77801a3596",
        ),
        "catalog-application-request": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-request-v1.schema.json",
            "resources/catalog-application/catalog-application-request-v1.schema.json",
            "1.0",
            "sha256:ab395b09afc99bbee7a25b0c15d9f8f63eb22b73b2a5e62586f0f8d80f8d3855",
        ),
        "catalog-application-response": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-response-v1.schema.json",
            "resources/catalog-application/catalog-application-response-v1.schema.json",
            "1.0",
            "sha256:ad549c7b25c1e620e7cf54fa46cb4891f322d69f65bd5c5104bf9e50f4582ff8",
        ),
        "catalog-application-request-v2": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-request-v2.schema.json",
            "resources/catalog-application/catalog-application-request-v2.schema.json",
            "2.0",
            "sha256:316ca9bbeed50fb84f97cadb9be23cc62e528f43a39473afad4899f7fc75a250",
        ),
        "catalog-application-response-v2": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-response-v2.schema.json",
            "resources/catalog-application/catalog-application-response-v2.schema.json",
            "2.0",
            "sha256:209edc85877d14d1b4b8ae99ac6b33b479761e9ed0cb89890b2ec6baf3f70c7f",
        ),
        "catalog-application-request-v3": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-request-v3.schema.json",
            "resources/catalog-application/catalog-application-request-v3.schema.json",
            "3.0",
            "sha256:f94dcef9b685d830cfe4518ef1f7937e2e1cc14877cdea1c2b3a18064f049494",
        ),
        "catalog-application-response-v3": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-response-v3.schema.json",
            "resources/catalog-application/catalog-application-response-v3.schema.json",
            "3.0",
            "sha256:197bdc748aeeee9835e37ce49f6ca350f4c261af12f664e5d7b2ed5749dc40ea",
        ),
        "catalog-application-request-v4": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-request-v4.schema.json",
            "resources/catalog-application/catalog-application-request-v4.schema.json",
            "4.0",
            "sha256:a8296f2cb3bc9a03365087d282d14c989248635fa72832bce387a3e719274c76",
        ),
        "catalog-application-response-v4": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-response-v4.schema.json",
            "resources/catalog-application/catalog-application-response-v4.schema.json",
            "4.0",
            "sha256:41d5d126c0759538861f493010567fef87e4468c925c0892592567bebf5a9c30",
        ),
        "catalog-application-response-v5": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-response-v5.schema.json",
            "resources/catalog-application/catalog-application-response-v5.schema.json",
            "5.0",
            "sha256:1155fa976a1dc1913cbd51c97084bb17824211fe9ecd32c65e5d6f74ceec16a9",
        ),
        "catalog-application-response-v6": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-response-v6.schema.json",
            "resources/catalog-application/catalog-application-response-v6.schema.json",
            "6.0",
            "sha256:cc85a5642643693717b63c952061ad90e7a6b681c1c1e2940c447679c1a69dab",
        ),
        "catalog-application-request-v5": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-request-v5.schema.json",
            "resources/catalog-application/catalog-application-request-v5.schema.json",
            "5.0",
            "sha256:614599a6e49e160c2090be55b8039811bd610776c6a7d485fccc2a447d8503e2",
        ),
        "catalog-application-request-v6": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-request-v6.schema.json",
            "resources/catalog-application/catalog-application-request-v6.schema.json",
            "6.0",
            "sha256:24e7f04eadb60f631f61be10ef5a492ae80387191205ea7cbb4d91daf9505e9d",
        ),
        "catalog-application-request-v7": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-request-v7.schema.json",
            "resources/catalog-application/catalog-application-request-v7.schema.json",
            "7.0",
            "sha256:3015df5c9edb1fbf47cc36e039cbab692ad08175e87ad1a9a58ebf89fbfa3a37",
        ),
        "catalog-application-request-v8": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-request-v8.schema.json",
            "resources/catalog-application/catalog-application-request-v8.schema.json",
            "8.0",
            "sha256:eb2466090929b29bf4f24d1a6ab3d00652ffef4ff69657416c8331e1f2295aa5",
        ),
        "catalog-application-request-v9": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-request-v9.schema.json",
            "resources/catalog-application/catalog-application-request-v9.schema.json",
            "9.0",
            "sha256:cc94fe85f5f508771dfc930f580516664e70038921d69c18022d778c263785a7",
        ),
        "catalog-application-request-v10": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-request-v10.schema.json",
            "resources/catalog-application/catalog-application-request-v10.schema.json",
            "10.0",
            "sha256:fc89d31db0aa51d97c991187b5553f82954b497d5cbebc8edc54b908b1484366",
        ),
        "catalog-application-request-v11": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-request-v11.schema.json",
            "resources/catalog-application/catalog-application-request-v11.schema.json",
            "11.0",
            "sha256:a832103de53ed2a258ea0e016677495d4818ed2c763dcb191153512f6350c5b4",
        ),
        "catalog-application-request-v12": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-request-v12.schema.json",
            "resources/catalog-application/catalog-application-request-v12.schema.json",
            "12.0",
            "sha256:1fa2c37672bfadfa1947b4a19634726d2550d3d8c4c3a3cc614a6070e105a243",
        ),
        "catalog-application-request-v13": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-request-v13.schema.json",
            "resources/catalog-application/catalog-application-request-v13.schema.json",
            "13.0",
            "sha256:331b531c6ef3ba721f95946f7a1c25f1b58f7963a8aa9053154f7df72b29d082",
        ),
        "catalog-application-request-v14": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-request-v14.schema.json",
            "resources/catalog-application/catalog-application-request-v14.schema.json",
            "14.0",
            "sha256:4146339d31147505a4795c8f720469846e1c5f175617d38d4ac1722d464003d2",
        ),
        "catalog-application-request-v15": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-request-v15.schema.json",
            "resources/catalog-application/catalog-application-request-v15.schema.json",
            "15.0",
            "sha256:f6f6a6ea8404fe9b54687e515a32adb1ab1ae24be1082542ad9dd9213f85fa2b",
        ),
        "catalog-application-request-v16": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-request-v16.schema.json",
            "resources/catalog-application/catalog-application-request-v16.schema.json",
            "16.0",
            "sha256:90c849ae999dfa367d6cb725e7aa58a3670beb255400da9f281a41609bba59de",
        ),
        "catalog-application-request-v17": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-request-v17.schema.json",
            "resources/catalog-application/catalog-application-request-v17.schema.json",
            "17.0",
            "sha256:f7876161668b985d4929a231eec8337a666a1fd9816dba903139ba45bd18306a",
        ),
        "catalog-application-request-v18": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-request-v18.schema.json",
            "resources/catalog-application/catalog-application-request-v18.schema.json",
            "18.0",
            "sha256:a42dc7754170545ae4f7d34d950204ce0ecb1262bc72dab52017cb17de312554",
        ),
        "catalog-application-request-v19": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-request-v19.schema.json",
            "resources/catalog-application/catalog-application-request-v19.schema.json",
            "19.0",
            "sha256:1dc59dcae45f521dd7c39e2d7e5ebbdbfe89580e9c2173abf5e98cae9ad7610b",
        ),
        "catalog-application-response-v7": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-response-v7.schema.json",
            "resources/catalog-application/catalog-application-response-v7.schema.json",
            "7.0",
            "sha256:786bb14244347078fbd4b1a610cadfa72df33a0eb5f5d9ccbc7ce554d570e5d5",
        ),
        "catalog-application-response-v8": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-response-v8.schema.json",
            "resources/catalog-application/catalog-application-response-v8.schema.json",
            "8.0",
            "sha256:1b4918df65852a378301b886ea4e5e53e515fd2caae5ea165b73e709ecc95aae",
        ),
        "catalog-application-response-v9": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-response-v9.schema.json",
            "resources/catalog-application/catalog-application-response-v9.schema.json",
            "9.0",
            "sha256:a603c5023b3343faa66723e8c88736a6ea6515427cedb9747ba089a4f40519ea",
        ),
        "catalog-application-response-v10": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-response-v10.schema.json",
            "resources/catalog-application/catalog-application-response-v10.schema.json",
            "10.0",
            "sha256:d24f2d2ca3fb3fd593f087c3658d17be45d00863df94ff8b6ada867ba0d92308",
        ),
        "catalog-application-response-v11": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-response-v11.schema.json",
            "resources/catalog-application/catalog-application-response-v11.schema.json",
            "11.0",
            "sha256:19f0d075aadbe36cb8e32ed6d98216340e944c02dd27c003e4abb13c0478c5e7",
        ),
        "catalog-application-response-v12": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-response-v12.schema.json",
            "resources/catalog-application/catalog-application-response-v12.schema.json",
            "12.0",
            "sha256:81d158d1f74da6ca3150c2d44a4cb91eb9785575a3d508688df6c537ad93d800",
        ),
        "catalog-application-response-v13": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-response-v13.schema.json",
            "resources/catalog-application/catalog-application-response-v13.schema.json",
            "13.0",
            "sha256:691f8828f01a909581aa4a4a73357e6b364d4539a4a7363e338e914970eaa5ae",
        ),
        "catalog-application-response-v14": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-response-v14.schema.json",
            "resources/catalog-application/catalog-application-response-v14.schema.json",
            "14.0",
            "sha256:a49f11043ce4991c0ef1498f51037a5d16d7e9cf68b8439f4e471a8fc0c3339d",
        ),
        "catalog-application-response-v15": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-response-v15.schema.json",
            "resources/catalog-application/catalog-application-response-v15.schema.json",
            "15.0",
            "sha256:31ff01702ac930245a96972585e3c46b8ecb77192e4051ec116ab7c92cda7dc0",
        ),
        "catalog-application-response-v16": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-response-v16.schema.json",
            "resources/catalog-application/catalog-application-response-v16.schema.json",
            "16.0",
            "sha256:3749d78f9b1f0804cc8454ed6e1aac628fbf5eaceb49f865b1690f9b1c587b41",
        ),
        "catalog-application-response-v17": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-response-v17.schema.json",
            "resources/catalog-application/catalog-application-response-v17.schema.json",
            "17.0",
            "sha256:bb60cc10fecdaca25cadd91b9c878fc3f1cf07a043c5f20d01c9a0a41c1811ac",
        ),
        "catalog-application-response-v18": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-response-v18.schema.json",
            "resources/catalog-application/catalog-application-response-v18.schema.json",
            "18.0",
            "sha256:b4290c8a0942035246179d5d828d51724069f1843ee223e7cc837f42811f9fe5",
        ),
        "catalog-item-media-request": CatalogSchemaResource(
            "schemas/catalog-application/catalog-item-media-request-v1.schema.json",
            "resources/catalog-application/catalog-item-media-request-v1.schema.json",
            "1.0",
            "sha256:4e69c87208e641917fb6ce4655219767fce33ec9b32261d076b48c151f352385",
        ),
        "catalog-item-media-response": CatalogSchemaResource(
            "schemas/catalog-application/catalog-item-media-response-v1.schema.json",
            "resources/catalog-application/catalog-item-media-response-v1.schema.json",
            "1.0",
            "sha256:e40e2f407ca6a124ed091dbc8e7b06e4eee78783d5855b6e8c17e24294f9928f",
        ),
        "catalog-item-component-media-request": CatalogSchemaResource(
            "schemas/catalog-application/catalog-item-component-media-request-v1.schema.json",
            "resources/catalog-application/catalog-item-component-media-request-v1.schema.json",
            "1.0",
            "sha256:7f9e937b19ef14231094d57d984bea2f8a33cf7eef6010e69598b64638752ca4",
        ),
        "catalog-item-component-media-response": CatalogSchemaResource(
            "schemas/catalog-application/catalog-item-component-media-response-v1.schema.json",
            "resources/catalog-application/catalog-item-component-media-response-v1.schema.json",
            "1.0",
            "sha256:5d350c7808c93066c361193c9bf1badbbc798b8e3401a5087c4f400d5f4751b8",
        ),
        "catalog-assessment-page-list-request": CatalogSchemaResource(
            "schemas/catalog-application/catalog-assessment-page-list-request-v1.schema.json",
            "resources/catalog-application/catalog-assessment-page-list-request-v1.schema.json",
            "1.0",
            "sha256:a2bd18c2ae6a3280e1d66ada150ed664b04d5583b6569401b11cc2b589abec8d",
        ),
        "catalog-assessment-page-list-response": CatalogSchemaResource(
            "schemas/catalog-application/catalog-assessment-page-list-response-v1.schema.json",
            "resources/catalog-application/catalog-assessment-page-list-response-v1.schema.json",
            "1.0",
            "sha256:2ec9dfb16b22b028f68b2778d08b2697abe2b9701a428de21a3bbbf806f7c3a1",
        ),
        "catalog-assessment-page-media-request": CatalogSchemaResource(
            "schemas/catalog-application/catalog-assessment-page-media-request-v1.schema.json",
            "resources/catalog-application/catalog-assessment-page-media-request-v1.schema.json",
            "1.0",
            "sha256:ab72da0aa488478e7e918053ec0771e3e1c006acee2c4489604970e744f1d536",
        ),
        "catalog-assessment-page-media-response": CatalogSchemaResource(
            "schemas/catalog-application/catalog-assessment-page-media-response-v1.schema.json",
            "resources/catalog-application/catalog-assessment-page-media-response-v1.schema.json",
            "1.0",
            "sha256:6a1e60af2d8d5fca8ff0c58014bfed2cb1121fb4e2346068f4db30f8f59b3021",
        ),
        "pdf-document-review-page-media-request": CatalogSchemaResource(
            (
                "schemas/catalog/catalog-application/"
                "pdf-document-review-page-media-request-v1.schema.json"
            ),
            ("resources/catalog-application/pdf-document-review-page-media-request-v1.schema.json"),
            "1.0",
            "sha256:a3397524644b13fd0271c86bb7acb51a60570a260363d051ff4732390a5bc051",
        ),
        "pdf-document-review-page-media-response": CatalogSchemaResource(
            (
                "schemas/catalog/catalog-application/"
                "pdf-document-review-page-media-response-v1.schema.json"
            ),
            (
                "resources/catalog-application/"
                "pdf-document-review-page-media-response-v1.schema.json"
            ),
            "1.0",
            "sha256:535e7f96436bc7da31d0070b292d8c4b2a4f0f29e6ebdec887095e42415f3a43",
        ),
        "knowledge-types": CatalogSchemaResource(
            "schemas/knowledge/knowledge-types-v1.schema.json",
            "resources/knowledge/knowledge-types-v1.schema.json",
            "1.0",
            "sha256:d1d0e842b75a263470ef7403f3117a3c23f52f3c5f5f181477f0f2b422312456",
        ),
        "knowledge-types-v2": CatalogSchemaResource(
            "schemas/knowledge/knowledge-types-v2.schema.json",
            "resources/knowledge/knowledge-types-v2.schema.json",
            "2.0",
            "sha256:9a40420c613c3913dd35f5ada3072197a70362127fa033f5ad5ee7805b512a3c",
        ),
        "knowledge-analysis-request": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-request-v1.schema.json",
            "resources/knowledge/knowledge-analysis-request-v1.schema.json",
            "1.0",
            "sha256:1e4b982fc6bd91448ce014e4b7160a5bfd5008b1985e7318e1e102e29b4ce233",
        ),
        "knowledge-analysis-result": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-result-v1.schema.json",
            "resources/knowledge/knowledge-analysis-result-v1.schema.json",
            "1.0",
            "sha256:fc496fe1f9d8b663b33677e24cf0e2158b0f20bb815f69dfd9551a625820c3f3",
        ),
        "knowledge-analysis-types-v2": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-types-v2.schema.json",
            "resources/knowledge/knowledge-analysis-types-v2.schema.json",
            "2.0",
            "sha256:74cf5efc429b70e0e500283a356da742a8c7beb50fccb1f1a46c07523599fa3f",
        ),
        "knowledge-analysis-request-v2": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-request-v2.schema.json",
            "resources/knowledge/knowledge-analysis-request-v2.schema.json",
            "2.0",
            "sha256:bf77196f281dc8c2c22e850e576a9137acb7bc1fea3681400f8855dc1f63414f",
        ),
        "knowledge-analysis-types-v3": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-types-v3.schema.json",
            "resources/knowledge/knowledge-analysis-types-v3.schema.json",
            "3.0",
            "sha256:7270e1f7fa9154e5a5f00f4e48bea2d49399ea9570ed1d81a1fc566eecdcea76",
        ),
        "knowledge-analysis-types-v4": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-types-v4.schema.json",
            "resources/knowledge/knowledge-analysis-types-v4.schema.json",
            "4.0",
            "sha256:02584fb9edb61c32a904c5ec5878f9f96ffe300f32796fab3cfe730ae531935f",
        ),
        "knowledge-analysis-types-v5": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-types-v5.schema.json",
            "resources/knowledge/knowledge-analysis-types-v5.schema.json",
            "5.0",
            "sha256:6ebd7a574a8c202bf6994eee8a42965a18a65f23bce38da50ae7ae81084132bf",
        ),
        "knowledge-analysis-request-v3": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-request-v3.schema.json",
            "resources/knowledge/knowledge-analysis-request-v3.schema.json",
            "3.0",
            "sha256:314c70a742970aa8a586a034269d8bc262860bd478042c6c46ebfc86bc8780d8",
        ),
        "knowledge-analysis-request-v4": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-request-v4.schema.json",
            "resources/knowledge/knowledge-analysis-request-v4.schema.json",
            "4.0",
            "sha256:d519beeb77aaf2c12fe1c137dfe715619ece99a42c964944ccf6e8658c638c7f",
        ),
        "knowledge-analysis-request-v5": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-request-v5.schema.json",
            "resources/knowledge/knowledge-analysis-request-v5.schema.json",
            "5.0",
            "sha256:b5354e230d8c93061c6854ce8c74ab5b7fa289bb9c595f205c44f6edecdbbf70",
        ),
        "knowledge-analysis-request-v6": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-request-v6.schema.json",
            "resources/knowledge/knowledge-analysis-request-v6.schema.json",
            "6.0",
            "sha256:8107f1e55d46901fb7ff6619872fbc5600b27c6e068cffb486155e627728e9d0",
        ),
        "knowledge-analysis-request-v7": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-request-v7.schema.json",
            "resources/knowledge/knowledge-analysis-request-v7.schema.json",
            "7.0",
            "sha256:fbbdb51000a710c279fccfba990ac700d64993ccf538b4c7bc3739dcbefddcf7",
        ),
        "knowledge-analysis-request-v8": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-request-v8.schema.json",
            "resources/knowledge/knowledge-analysis-request-v8.schema.json",
            "8.0",
            "sha256:21629d4417eced251d8596e9d87d94444cc3fe906b50644395c332faea6c50fc",
        ),
        "knowledge-analysis-request-v9": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-request-v9.schema.json",
            "resources/knowledge/knowledge-analysis-request-v9.schema.json",
            "9.0",
            "sha256:0aa8708c9952d47bac35e3a7921a03deacff64688dc880258cac0595d9a4e56d",
        ),
        "knowledge-analysis-request-v10": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-request-v10.schema.json",
            "resources/knowledge/knowledge-analysis-request-v10.schema.json",
            "10.0",
            "sha256:bd8c32b905729735b0513b699ef01661d3df719c403048c04ed5e658ea97b7fc",
        ),
        "knowledge-analysis-batch-request": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-batch-request-v1.schema.json",
            "resources/knowledge/knowledge-analysis-batch-request-v1.schema.json",
            "1.0",
            "sha256:6050ea59b635cb50e718e76dd92967ddb88f55dede0e67fed3b55376ec65ce7e",
        ),
        "knowledge-analysis-batch-request-v2": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-batch-request-v2.schema.json",
            "resources/knowledge/knowledge-analysis-batch-request-v2.schema.json",
            "1.1",
            "sha256:f64c59baa793738cc09dcc264dd0cae0f9d6da702367af4437ef5be0417892dd",
        ),
        "knowledge-analysis-batch-request-v3": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-batch-request-v3.schema.json",
            "resources/knowledge/knowledge-analysis-batch-request-v3.schema.json",
            "1.2",
            "sha256:d81bdd2cc14b6a8277ef80d7c64184861ba63a98cf6a75426de0a8f2726a13b4",
        ),
        "knowledge-analysis-batch-request-v4": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-batch-request-v4.schema.json",
            "resources/knowledge/knowledge-analysis-batch-request-v4.schema.json",
            "1.3",
            "sha256:31d8eeba953cceff26fe6552fee6833c4424fa856efeb93561b1f2a9f52bf00f",
        ),
        "knowledge-analysis-worker-proposal": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-worker-proposal-v1.schema.json",
            "resources/knowledge/knowledge-analysis-worker-proposal-v1.schema.json",
            "1.0",
            "sha256:18447391cb82171e32d1c95f4fd040a23bfdf21b0eaba56d2d48b97f92ad1c00",
        ),
        "knowledge-analysis-worker-proposal-v2": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-worker-proposal-v2.schema.json",
            "resources/knowledge/knowledge-analysis-worker-proposal-v2.schema.json",
            "2.0",
            "sha256:b2605e937e7431a7e0b5203f876c032fc5eb61f547fdf620a4a756b2715bf43e",
        ),
        "knowledge-analysis-worker-proposal-v3": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-worker-proposal-v3.schema.json",
            "resources/knowledge/knowledge-analysis-worker-proposal-v3.schema.json",
            "3.0",
            "sha256:48353e07147aa97aff2b27c503a9c626d640a70bf728d77f1d7e166e88b07cf3",
        ),
        "knowledge-analysis-worker-proposal-v4": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-worker-proposal-v4.schema.json",
            "resources/knowledge/knowledge-analysis-worker-proposal-v4.schema.json",
            "4.0",
            "sha256:1fd771c15c02d675bab6a8c73d7385814749633d02f12f7662c7cdd5f5851d79",
        ),
        "knowledge-analysis-worker-proposal-v5": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-worker-proposal-v5.schema.json",
            "resources/knowledge/knowledge-analysis-worker-proposal-v5.schema.json",
            "5.0",
            "sha256:3067ea18275478c07f8adb3792a7e99897252506379fd4f4ba0c9a05d9a9a878",
        ),
        "knowledge-analysis-worker-proposal-v6": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-worker-proposal-v6.schema.json",
            "resources/knowledge/knowledge-analysis-worker-proposal-v6.schema.json",
            "6.0",
            "sha256:a5b0815acd211ce43d0be25ff886c8b2a7c39fa225916da034b8e7ad03b2f01c",
        ),
        "knowledge-analysis-worker-proposal-v7": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-worker-proposal-v7.schema.json",
            "resources/knowledge/knowledge-analysis-worker-proposal-v7.schema.json",
            "7.0",
            "sha256:8be2932a12408c4f52e453ff4e40a1a4973a8776e3f39fb55189c4b67e5bad9b",
        ),
        "knowledge-analysis-worker-proposal-v8": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-worker-proposal-v8.schema.json",
            "resources/knowledge/knowledge-analysis-worker-proposal-v8.schema.json",
            "8.0",
            "sha256:cdae8e9e3f45bb7be7e21905efe84c20f6495d38a2a39f96dccf57c0364e953f",
        ),
        "knowledge-analysis-solution-types-v1": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-solution-types-v1.schema.json",
            "resources/knowledge/knowledge-analysis-solution-types-v1.schema.json",
            "1.0",
            "sha256:2c8f271a8ceeec22de0fb164edb6f475f70219b36cdc4d0101e84a0aa69ac3a1",
        ),
        "knowledge-analysis-solution-report-v1": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-solution-report-v1.schema.json",
            "resources/knowledge/knowledge-analysis-solution-report-v1.schema.json",
            "1.0",
            "sha256:f66a69b23f7f6cabaf15fa3fb6acf85e00665e3c5782cdd414ca5905cdacbf8e",
        ),
        "knowledge-assessment-page-image-observation-v2": CatalogSchemaResource(
            "schemas/knowledge/knowledge-assessment-page-image-observation-v2.schema.json",
            "resources/knowledge/knowledge-assessment-page-image-observation-v2.schema.json",
            "2.0",
            "sha256:ace304a0acd7c864a97e8bc1be8e886732270b07b98a49c970e89449427bbc9c",
        ),
        "knowledge-analysis-proposed-node-v3": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-proposed-node-v3.schema.json",
            "resources/knowledge/knowledge-analysis-proposed-node-v3.schema.json",
            "3.0",
            "sha256:e08650c9fc853f130814c778073db50d396d1a0239ce3638d18ba8bda30916b4",
        ),
        "knowledge-analysis-proposed-node-v4": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-proposed-node-v4.schema.json",
            "resources/knowledge/knowledge-analysis-proposed-node-v4.schema.json",
            "4.0",
            "sha256:33a6ba163cce388671c85756b78d99234c6a92ec877711b4f3164e871779542c",
        ),
        "knowledge-analysis-proposed-edge-v4": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-proposed-edge-v4.schema.json",
            "resources/knowledge/knowledge-analysis-proposed-edge-v4.schema.json",
            "4.0",
            "sha256:521582690b2098e3366453a630da52d9828be81220aed42556f78531a8e7fb4e",
        ),
        "knowledge-analysis-proposal-receipt": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-proposal-receipt-v1.schema.json",
            "resources/knowledge/knowledge-analysis-proposal-receipt-v1.schema.json",
            "1.0",
            "sha256:9159e7ef26da33825052f6704d13b1ff80bb2c68afdbc0a9474fab19912e69a7",
        ),
        "knowledge-analysis-proposal-receipt-v2": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-proposal-receipt-v2.schema.json",
            "resources/knowledge/knowledge-analysis-proposal-receipt-v2.schema.json",
            "2.0",
            "sha256:5af94d49dc656f4833182cd554a4e1ae1faea795927253a5577572e54fc31c98",
        ),
        "knowledge-analysis-proposal-receipt-v3": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-proposal-receipt-v3.schema.json",
            "resources/knowledge/knowledge-analysis-proposal-receipt-v3.schema.json",
            "3.0",
            "sha256:36e361597b71170821e96cde9786349834048cc5606e1390e3ade08a7b70aac3",
        ),
        "knowledge-analysis-proposal-receipt-v4": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-proposal-receipt-v4.schema.json",
            "resources/knowledge/knowledge-analysis-proposal-receipt-v4.schema.json",
            "4.0",
            "sha256:e760b89bf97fcfa90c099b60b6bfa1c19628deaf950bd7a1a8dbaacdd055312d",
        ),
        "knowledge-analysis-proposal-receipt-v5": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-proposal-receipt-v5.schema.json",
            "resources/knowledge/knowledge-analysis-proposal-receipt-v5.schema.json",
            "5.0",
            "sha256:e9a57008f855db5425651bafa98347f9868f7941f56e706dac46b6cf69da754f",
        ),
        "knowledge-analysis-proposal-receipt-v6": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-proposal-receipt-v6.schema.json",
            "resources/knowledge/knowledge-analysis-proposal-receipt-v6.schema.json",
            "6.0",
            "sha256:2e324fe040cb8c48e4549c56d654c6a690d40ae699fed7195460e9646037e30f",
        ),
        "knowledge-analysis-proposal-receipt-v7": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-proposal-receipt-v7.schema.json",
            "resources/knowledge/knowledge-analysis-proposal-receipt-v7.schema.json",
            "7.0",
            "sha256:c2aa46be06de9a001d504d7a75750fe6b57a8c148be22211f1e34834aff3fadb",
        ),
        "knowledge-analysis-proposal-receipt-v8": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-proposal-receipt-v8.schema.json",
            "resources/knowledge/knowledge-analysis-proposal-receipt-v8.schema.json",
            "8.0",
            "sha256:a8789f95a3472c5ab0ef3dc2e632bb4fee9832e1affab6472ef351736dde4810",
        ),
        "knowledge-analysis-proposal-receipt-v9": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-proposal-receipt-v9.schema.json",
            "resources/knowledge/knowledge-analysis-proposal-receipt-v9.schema.json",
            "9.0",
            "sha256:2ff63cbad5db4fe92980b02ca977ec961f3d3686012ccfcaa91a08008232b8cb",
        ),
        "knowledge-analysis-risk-policy": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-risk-policy-v1.schema.json",
            "resources/knowledge/knowledge-analysis-risk-policy-v1.schema.json",
            "1.0",
            "sha256:75fba0cfa467fc99622adcff4fbb8c140e38995c2dd8e669486d650587cb5fa0",
        ),
        "knowledge-analysis-review-decision": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-review-decision-v1.schema.json",
            "resources/knowledge/knowledge-analysis-review-decision-v1.schema.json",
            "1.0",
            "sha256:0344869edb7bade14c94f187ac4af25d0efa80efbbe10a96d9afeb4c13eba9cf",
        ),
        "knowledge-analysis-result-v2": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-result-v2.schema.json",
            "resources/knowledge/knowledge-analysis-result-v2.schema.json",
            "2.0",
            "sha256:e017752dc52ca32cb18d5e671525d1415c76ce19df023ac33fd3a43e811c3d48",
        ),
        "knowledge-analysis-result-v3": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-result-v3.schema.json",
            "resources/knowledge/knowledge-analysis-result-v3.schema.json",
            "3.0",
            "sha256:e32b715cfdded7e18631f0d4979a5a5125e450a3d13d238359d1231d24703f32",
        ),
        "knowledge-analysis-result-v4": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-result-v4.schema.json",
            "resources/knowledge/knowledge-analysis-result-v4.schema.json",
            "4.0",
            "sha256:6ed3f31a8ba5f1679c94fd93e6b3d8e68e5611b25d088933459455fda2c5ea50",
        ),
        "knowledge-analysis-result-v5": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-result-v5.schema.json",
            "resources/knowledge/knowledge-analysis-result-v5.schema.json",
            "5.0",
            "sha256:bebe839c267ebb7e82bec5c21059e27e3b96135b8e68815beb49b42377c7fb44",
        ),
        "knowledge-analysis-result-v6": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-result-v6.schema.json",
            "resources/knowledge/knowledge-analysis-result-v6.schema.json",
            "6.0",
            "sha256:6d019621da271e3ed286e113b277346475b2a166afa103b2b6fe85bbf101d9c5",
        ),
        "knowledge-analysis-result-v7": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-result-v7.schema.json",
            "resources/knowledge/knowledge-analysis-result-v7.schema.json",
            "7.0",
            "sha256:1725be6c3a9b01643f23df351c002a8816df839b7f6c61a4db8d7f4f0a426282",
        ),
        "knowledge-analysis-result-v8": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-result-v8.schema.json",
            "resources/knowledge/knowledge-analysis-result-v8.schema.json",
            "8.0",
            "sha256:8067c3e1d4907e65aa54f75f82a23f74f227c9c7834d6767a70bd48c1fa1a9e8",
        ),
        "knowledge-analysis-result-v9": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-result-v9.schema.json",
            "resources/knowledge/knowledge-analysis-result-v9.schema.json",
            "9.0",
            "sha256:f52f7a1d4c7ec742fda337be9a6ea671b3911af1f519b7a4913e9266d63904d6",
        ),
        "knowledge-analysis-result-v10": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-result-v10.schema.json",
            "resources/knowledge/knowledge-analysis-result-v10.schema.json",
            "10.0",
            "sha256:123028744f3f545a3a3b60869425bf242df33a77110726c459fc7f153b4b33bf",
        ),
        "knowledge-graph-snapshot-manifest": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-snapshot-manifest-v1.schema.json",
            "resources/knowledge/knowledge-graph-snapshot-manifest-v1.schema.json",
            "1.0",
            "sha256:daaf1dffca162018bead549399927e6429a7dac34775fb969c675207d9920f9a",
        ),
        "knowledge-graph-publication": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-publication-v1.schema.json",
            "resources/knowledge/knowledge-graph-publication-v1.schema.json",
            "1.0",
            "sha256:4594e9f479744d3ecf266d8e68367d5a207f82cc1001602864249bb9c471fd6d",
        ),
        "knowledge-graph-publication-v2": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-publication-v2.schema.json",
            "resources/knowledge/knowledge-graph-publication-v2.schema.json",
            "2.0",
            "sha256:58c3b6b0e671614ae6a88c27f3706f46d80b771edef35cadda5de13141c024a1",
        ),
        "knowledge-graph-publication-v3": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-publication-v3.schema.json",
            "resources/knowledge/knowledge-graph-publication-v3.schema.json",
            "3.0",
            "sha256:0508d4a90ac59f932dfccbcff5c208f53c782e5c64daddc6f35c95a983c209e3",
        ),
        "knowledge-graph-publication-v4": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-publication-v4.schema.json",
            "resources/knowledge/knowledge-graph-publication-v4.schema.json",
            "4.0",
            "sha256:c663a5bde522891a04d9ffbee6ea7231e8e156b2ade305d5a16cd316716f02d6",
        ),
        "knowledge-graph-publication-v5": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-publication-v5.schema.json",
            "resources/knowledge/knowledge-graph-publication-v5.schema.json",
            "5.0",
            "sha256:c87350c2f40fc225962bd86e4a2172c03c4c5b726437735ffe0e7d6e4a30f8ab",
        ),
        "knowledge-graph-publication-v6": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-publication-v6.schema.json",
            "resources/knowledge/knowledge-graph-publication-v6.schema.json",
            "6.0",
            "sha256:42664c7dae7c5d22169fff4a86b7f7c225556e751da7f702c8e862a6d88762f8",
        ),
        "approved-item-graph-publication-command": CatalogSchemaResource(
            "schemas/knowledge/approved-item-graph-publication-command-v1.schema.json",
            "resources/knowledge/approved-item-graph-publication-command-v1.schema.json",
            "1.0",
            "sha256:3b33ee6a94e1b805dba01aa6c32eabc6dc5fc283d0aef817a97e4eb4d9d6f165",
        ),
        "approved-item-graph-publication-result": CatalogSchemaResource(
            "schemas/knowledge/approved-item-graph-publication-result-v1.schema.json",
            "resources/knowledge/approved-item-graph-publication-result-v1.schema.json",
            "1.0",
            "sha256:003b79ea82307e9a8515c2f0fe23df81d46dfd588832a09af6933c194d85489e",
        ),
        "knowledge-graph-publication-result": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-publication-result-v1.schema.json",
            "resources/knowledge/knowledge-graph-publication-result-v1.schema.json",
            "1.0",
            "sha256:c0d81175e94434888c84832e8edb64257370e998b7ebe41f5c382672638f657d",
        ),
        "knowledge-graph-projection": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-projection-v1.schema.json",
            "resources/knowledge/knowledge-graph-projection-v1.schema.json",
            "1.0",
            "sha256:b3a78a44dab9cb3a5525e5e1bfe5bc195044221867c92df2a98b08b358701102",
        ),
        "knowledge-graph-projection-v2": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-projection-v2.schema.json",
            "resources/knowledge/knowledge-graph-projection-v2.schema.json",
            "2.0",
            "sha256:fd820117c31c746bf5a8f525bc5b71367f4020318be79bb06ae2eeb1bbda2a9a",
        ),
        "knowledge-graph-projection-v3": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-projection-v3.schema.json",
            "resources/knowledge/knowledge-graph-projection-v3.schema.json",
            "3.0",
            "sha256:e033d2df5f4a6f181a2d2de28fd52a3fd1c1a1651ecb4a8d2377616ac6432ff3",
        ),
        "knowledge-graph-projection-v4": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-projection-v4.schema.json",
            "resources/knowledge/knowledge-graph-projection-v4.schema.json",
            "4.0",
            "sha256:73876b357bae57c6b66f24bcce39d632194edde507a8132664bb371b9878db17",
        ),
        "knowledge-graph-structure-manifest": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-structure-manifest-v1.schema.json",
            "resources/knowledge/knowledge-graph-structure-manifest-v1.schema.json",
            "1.0",
            "sha256:818ecc197f3d5fdcd24b18ec73c4de5a76ca6db85fb5f01672e7067a3dde4cf9",
        ),
        "knowledge-graph-structure-manifest-v2": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-structure-manifest-v2.schema.json",
            "resources/knowledge/knowledge-graph-structure-manifest-v2.schema.json",
            "2.0",
            "sha256:eec6563f952c8bc4cc03a57179910b47f04eccba83e3154b3bf8f13b151f72e3",
        ),
        "knowledge-graph-structure-manifest-v3": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-structure-manifest-v3.schema.json",
            "resources/knowledge/knowledge-graph-structure-manifest-v3.schema.json",
            "3.0",
            "sha256:7754599edffd9f71c7aec38c4457da321edce5787290da5e50b481a64eebf773",
        ),
        "knowledge-graph-structure-manifest-v4": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-structure-manifest-v4.schema.json",
            "resources/knowledge/knowledge-graph-structure-manifest-v4.schema.json",
            "4.0",
            "sha256:fbb4aad03dd8d18fda098b7a1312a80a85933066babadaeef0113124713114dd",
        ),
        "knowledge-graph-structure-manifest-v5": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-structure-manifest-v5.schema.json",
            "resources/knowledge/knowledge-graph-structure-manifest-v5.schema.json",
            "5.0",
            "sha256:1ba3811bb993aef736f7d31cd79a311f2168e076844866299e3952e2d19df911",
        ),
        "knowledge-graph-structure-manifest-v6": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-structure-manifest-v6.schema.json",
            "resources/knowledge/knowledge-graph-structure-manifest-v6.schema.json",
            "6.0",
            "sha256:ffa269d11d5997e4d4649a0435b32ee5f53281dee85a06d5f77a7fdf215edd88",
        ),
        "knowledge-graph-snapshot-manifest-v2": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-snapshot-manifest-v2.schema.json",
            "resources/knowledge/knowledge-graph-snapshot-manifest-v2.schema.json",
            "2.0",
            "sha256:2fe24ad351ca7dcd10a9ba7909bf0fe0fe6fb2bf7715ca3dac02d1697cf60d09",
        ),
        "knowledge-graph-snapshot-manifest-v3": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-snapshot-manifest-v3.schema.json",
            "resources/knowledge/knowledge-graph-snapshot-manifest-v3.schema.json",
            "3.0",
            "sha256:a8a8fbd41022ce0200b1979a4c2d24ca95a27cd5571b143dab61cab84344b50d",
        ),
        "knowledge-graph-snapshot-manifest-v4": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-snapshot-manifest-v4.schema.json",
            "resources/knowledge/knowledge-graph-snapshot-manifest-v4.schema.json",
            "4.0",
            "sha256:cfd175b616352a765d661c71e488e4d5e0c88cfa9ab7b1b01f75cb8986cb9cd6",
        ),
        "knowledge-graph-snapshot-manifest-v5": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-snapshot-manifest-v5.schema.json",
            "resources/knowledge/knowledge-graph-snapshot-manifest-v5.schema.json",
            "5.0",
            "sha256:c26c886601748fa6fb20849241837ac22c67d80f2fd2069c7f256d4132072a6b",
        ),
        "knowledge-graph-snapshot-manifest-v6": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-snapshot-manifest-v6.schema.json",
            "resources/knowledge/knowledge-graph-snapshot-manifest-v6.schema.json",
            "6.0",
            "sha256:5b8cd0666e066fb1b1ae515117c9130c862ade8df0edbd5567bade8fa9d993cc",
        ),
        "knowledge-graph-snapshot-manifest-v7": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-snapshot-manifest-v7.schema.json",
            "resources/knowledge/knowledge-graph-snapshot-manifest-v7.schema.json",
            "7.0",
            "sha256:ba98bbc7ebb823f4826368a38e986a14f00a0618bfa03b115b67a5563472b3a2",
        ),
        "knowledge-graph-snapshot-manifest-v8": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-snapshot-manifest-v8.schema.json",
            "resources/knowledge/knowledge-graph-snapshot-manifest-v8.schema.json",
            "8.0",
            "sha256:1e19e4ff2b15e60a36bbd1c4206c7a77278460506df5eb3a74e3f5f0491f131c",
        ),
        "knowledge-graph-snapshot-manifest-v9": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-snapshot-manifest-v9.schema.json",
            "resources/knowledge/knowledge-graph-snapshot-manifest-v9.schema.json",
            "9.0",
            "sha256:7bbc5958d6b5a490979b9a73914f22e53eed4e292f744f1fc4dd7b9454255377",
        ),
        "automatic-item-curriculum-alignment-v2": CatalogSchemaResource(
            "schemas/knowledge/automatic-item-curriculum-alignment-v2.schema.json",
            "resources/knowledge/automatic-item-curriculum-alignment-v2.schema.json",
            "2.0",
            "sha256:07e5f5f8a46aa555a989614e650c19f89dc83bf39b2b78c171a83648a3f4dd08",
        ),
        "education-retrieval-access-policy": CatalogSchemaResource(
            "schemas/knowledge/education-retrieval-access-policy-v1.schema.json",
            "resources/knowledge/education-retrieval-access-policy-v1.schema.json",
            "1.0",
            "sha256:83e7fd1dc6cc78e74f3b35556a1eaf3039745e9d52fce04e46ad254490219afe",
        ),
        "education-retrieval-access-policy-v1.1": CatalogSchemaResource(
            "schemas/knowledge/education-retrieval-access-policy-v1_1.schema.json",
            "resources/knowledge/education-retrieval-access-policy-v1_1.schema.json",
            "1.1",
            "sha256:2ba2fc1fd906fef5a17acb3a7ba7d7e3351aa9a2e863a4386f0913b4bf7f7152",
        ),
        "education-retrieval-access-policy-v1.2": CatalogSchemaResource(
            "schemas/knowledge/education-retrieval-access-policy-v1_2.schema.json",
            "resources/knowledge/education-retrieval-access-policy-v1_2.schema.json",
            "1.2",
            "sha256:9f723f43e17df7ddead0d1fcfae0008d61230b841a25fb682d62ec850bae5811",
        ),
        "educational-retrieval-requirement": CatalogSchemaResource(
            "schemas/knowledge/educational-retrieval-requirement-v1.schema.json",
            "resources/knowledge/educational-retrieval-requirement-v1.schema.json",
            "1.0",
            "sha256:378cb7997cdb2167156fe95bb30ab8f23e3924a6a5a4b3b2c7fc1bbaa8cb2ba3",
        ),
        "past-exam-variation-request": CatalogSchemaResource(
            "schemas/knowledge/past-exam-variation-request-v1.schema.json",
            "resources/knowledge/past-exam-variation-request-v1.schema.json",
            "1.0",
            "sha256:db804cde755161366446e17405c4fa99aa479b3e9e87e8861038c181eef2589b",
        ),
        "educational-retrieval-requirement-v2": CatalogSchemaResource(
            "schemas/knowledge/educational-retrieval-requirement-v2.schema.json",
            "resources/knowledge/educational-retrieval-requirement-v2.schema.json",
            "2.0",
            "sha256:887f77a30e2076a836d5353525de6de5285f14cf7f7c38a0594844f88b0e5e77",
        ),
        "education-retrieval-request": CatalogSchemaResource(
            "schemas/knowledge/education-retrieval-request-v1.schema.json",
            "resources/knowledge/education-retrieval-request-v1.schema.json",
            "1.0",
            "sha256:92bb7b8aa224a00eb7c2eb6f95d4c94465d8ccc19e4be2de010fc0512a800043",
        ),
        "education-retrieval-request-v2": CatalogSchemaResource(
            "schemas/knowledge/education-retrieval-request-v2.schema.json",
            "resources/knowledge/education-retrieval-request-v2.schema.json",
            "2.0",
            "sha256:d73d33141c3df357dc8508630931092d5b4d2f948cc1cd212766d5650caa9062",
        ),
        "evidence-bundle-manifest": CatalogSchemaResource(
            "schemas/knowledge/evidence-bundle-manifest-v1.schema.json",
            "resources/knowledge/evidence-bundle-manifest-v1.schema.json",
            "1.0",
            "sha256:5a575aa08788eb5a4ec6961c214872b4e6ed103fa0c9db78edcf47b791d9539e",
        ),
        "evidence-bundle-manifest-v2": CatalogSchemaResource(
            "schemas/knowledge/evidence-bundle-manifest-v2.schema.json",
            "resources/knowledge/evidence-bundle-manifest-v2.schema.json",
            "2.0",
            "sha256:a908f3dffd665292e5b171d799e8e1e95faa0ed5a4df3cfdc426c8f4f4bfcdaa",
        ),
        "evidence-bundle-manifest-v3": CatalogSchemaResource(
            "schemas/knowledge/evidence-bundle-manifest-v3.schema.json",
            "resources/knowledge/evidence-bundle-manifest-v3.schema.json",
            "3.0",
            "sha256:22d326637c08e00089b0fc0af2ca0a14eeb68c452f5cf822a2cbd91902dbae23",
        ),
        "evidence-bundle-manifest-v4": CatalogSchemaResource(
            "schemas/knowledge/evidence-bundle-manifest-v4.schema.json",
            "resources/knowledge/evidence-bundle-manifest-v4.schema.json",
            "4.0",
            "sha256:9dbf2b90ece9dae7a5963e504c1fb8dede32d09e9b6cb1f7b5beb6eb75162781",
        ),
        "evidence-bundle-manifest-v5": CatalogSchemaResource(
            "schemas/knowledge/evidence-bundle-manifest-v5.schema.json",
            "resources/knowledge/evidence-bundle-manifest-v5.schema.json",
            "5.0",
            "sha256:a72c0235d96b10e3bb032c183bdbb86349e1d2245ed3a2a8b478b432d48389bd",
        ),
        "evidence-bundle-publication-result": CatalogSchemaResource(
            "schemas/knowledge/evidence-bundle-publication-result-v1.schema.json",
            "resources/knowledge/evidence-bundle-publication-result-v1.schema.json",
            "1.0",
            "sha256:2f511f842bea023a3c430e0e40d12e02861c1d39b9cfb7de2691ace32415c654",
        ),
        "evidence-bundle-publication-result-v2": CatalogSchemaResource(
            "schemas/knowledge/evidence-bundle-publication-result-v2.schema.json",
            "resources/knowledge/evidence-bundle-publication-result-v2.schema.json",
            "2.0",
            "sha256:af55e991a17dbc56f43f75d3c6fb245efea64e0668149e96cad69b59f6305770",
        ),
        "evidence-bundle-publication-result-v3": CatalogSchemaResource(
            "schemas/knowledge/evidence-bundle-publication-result-v3.schema.json",
            "resources/knowledge/evidence-bundle-publication-result-v3.schema.json",
            "3.0",
            "sha256:c490617299d48da76552eee36c12e33268d915ca02167c629ea74b741cdc7f21",
        ),
        "evidence-bundle-publication-result-v4": CatalogSchemaResource(
            "schemas/knowledge/evidence-bundle-publication-result-v4.schema.json",
            "resources/knowledge/evidence-bundle-publication-result-v4.schema.json",
            "4.0",
            "sha256:2c4c60b94661042880b85d961dc210ecf73af1441dab2a421573cab4689277fb",
        ),
        "evidence-bundle-publication-result-v5": CatalogSchemaResource(
            "schemas/knowledge/evidence-bundle-publication-result-v5.schema.json",
            "resources/knowledge/evidence-bundle-publication-result-v5.schema.json",
            "5.0",
            "sha256:2d0d1e15e3844d72d9958cc3644a6ab97654c7ba9107fd9f080f6a4ad151e1b2",
        ),
    }
)

_RESOURCE_ROOT = files("eom_catalog_contracts").joinpath("resources")


class CatalogSchemaError(ValueError):
    """Raised when a Catalog Contract schema is unknown, missing, or invalid."""


def _distribution_version() -> str:
    try:
        return metadata.version("eom-platform")
    except metadata.PackageNotFoundError:
        return "source"


def _resource_error(name: str, reason: str) -> CatalogSchemaError:
    return CatalogSchemaError(
        f"catalog schema resource unavailable: {name} ({reason}; "
        f"package=eom_catalog_contracts, distribution=eom-platform@{_distribution_version()})"
    )


def _schema_resource(name: str) -> tuple[CatalogSchemaResource, Traversable]:
    try:
        entry = CATALOG_SCHEMA_RESOURCES[name]
    except KeyError as exc:
        raise CatalogSchemaError(f"unknown catalog contract schema: {name}") from exc
    parts = entry.resource_path.split("/")
    if parts[0] != "resources" or any(part in {"", ".", ".."} for part in parts):
        raise CatalogSchemaError(f"catalog schema resource path is unsafe: {name}")
    resource: Traversable = _RESOURCE_ROOT
    for part in parts[1:]:
        resource = resource.joinpath(part)
    return entry, resource


@lru_cache(maxsize=len(CATALOG_SCHEMA_RESOURCES))
def load_schema(name: str) -> dict[str, Any]:
    entry, resource = _schema_resource(name)
    try:
        raw = resource.read_bytes()
    except (OSError, UnicodeError) as exc:
        raise _resource_error(name, "package resource is missing or unreadable") from exc
    actual_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
    if actual_hash != entry.sha256:
        raise _resource_error(name, "package resource hash mismatch")
    try:
        value: object = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise CatalogSchemaError(f"catalog schema is not an object: {name}")
        Draft202012Validator.check_schema(value)
    except (UnicodeError, json.JSONDecodeError, SchemaError) as exc:
        raise _resource_error(name, "package resource is malformed") from exc
    return value


def catalog_schema_inventory() -> tuple[tuple[str, CatalogSchemaResource], ...]:
    """Return the deterministic logical schema inventory for release checks."""

    return tuple(sorted(CATALOG_SCHEMA_RESOURCES.items()))


@lru_cache(maxsize=1)
def _catalog_schema_registry() -> Registry[Any]:
    resources: list[tuple[str, Resource[Any]]] = []
    # Reuse the protocol owner's exact ticket. It identifies existing work and
    # never supplies an actor, private-source grant or execution capability.
    ticket = load_chat_worker_ticket_schema()
    if ticket.get("$id") != CHAT_WORKER_TICKET_SCHEMA:
        raise CatalogSchemaError("private query worker-ticket schema differs")
    resources.append((ticket["$id"], Resource.from_contents(ticket)))
    for name in CATALOG_SCHEMA_RESOURCES:
        schema = load_schema(name)
        identifier = schema.get("$id")
        if not isinstance(identifier, str):
            raise _resource_error(name, "schema identifier is missing")
        resources.append((identifier, Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def catalog_schema_registry() -> Registry[Any]:
    """Return the immutable installed Catalog schema registry for composed contracts."""

    return _catalog_schema_registry()


def validate_contract(name: str, value: dict[str, Any]) -> None:
    Draft202012Validator(
        load_schema(name),
        format_checker=FormatChecker(),
        registry=_catalog_schema_registry(),
    ).validate(value)
