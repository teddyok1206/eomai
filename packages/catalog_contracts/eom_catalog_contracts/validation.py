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
            "sha256:c2f7e5456ac15eaa2526a33ba9de8bef81e9640925a05b1531e9abf80744a664",
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
        "educational-document-revision-manifest": CatalogSchemaResource(
            "schemas/educational-document/educational-document-revision-manifest-v1.schema.json",
            "resources/educational-document/educational-document-revision-manifest-v1.schema.json",
            "1.0",
            "sha256:cd63c557b4166984500e1ad5fb3c0d2ec9fb6f4b6b5bdc17e1999d4db2d807a0",
        ),
        "educational-document-registration-receipt": CatalogSchemaResource(
            "schemas/educational-document/educational-document-registration-receipt-v1.schema.json",
            "resources/educational-document/educational-document-registration-receipt-v1.schema.json",
            "1.0",
            "sha256:8f4d0c05c27a7b79a51206fac4dc904cc7c5db186d25ef98bea32aec53e845f5",
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
        "assessment-item-content": CatalogSchemaResource(
            "schemas/item-registry/assessment-item-content-v1.schema.json",
            "resources/item-registry/assessment-item-content-v1.schema.json",
            "1.0",
            "sha256:ca0d360c209d26cce7e9283d42509204ccd8e50f519a85be871a2bbfc625a4bd",
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
        "catalog-application-response-v7": CatalogSchemaResource(
            "schemas/catalog-application/catalog-application-response-v7.schema.json",
            "resources/catalog-application/catalog-application-response-v7.schema.json",
            "7.0",
            "sha256:786bb14244347078fbd4b1a610cadfa72df33a0eb5f5d9ccbc7ce554d570e5d5",
        ),
        "knowledge-types": CatalogSchemaResource(
            "schemas/knowledge/knowledge-types-v1.schema.json",
            "resources/knowledge/knowledge-types-v1.schema.json",
            "1.0",
            "sha256:d1d0e842b75a263470ef7403f3117a3c23f52f3c5f5f181477f0f2b422312456",
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
        "knowledge-graph-structure-manifest": CatalogSchemaResource(
            "schemas/knowledge/knowledge-graph-structure-manifest-v1.schema.json",
            "resources/knowledge/knowledge-graph-structure-manifest-v1.schema.json",
            "1.0",
            "sha256:818ecc197f3d5fdcd24b18ec73c4de5a76ca6db85fb5f01672e7067a3dde4cf9",
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
        "education-retrieval-access-policy": CatalogSchemaResource(
            "schemas/knowledge/education-retrieval-access-policy-v1.schema.json",
            "resources/knowledge/education-retrieval-access-policy-v1.schema.json",
            "1.0",
            "sha256:83e7fd1dc6cc78e74f3b35556a1eaf3039745e9d52fce04e46ad254490219afe",
        ),
        "educational-retrieval-requirement": CatalogSchemaResource(
            "schemas/knowledge/educational-retrieval-requirement-v1.schema.json",
            "resources/knowledge/educational-retrieval-requirement-v1.schema.json",
            "1.0",
            "sha256:378cb7997cdb2167156fe95bb30ab8f23e3924a6a5a4b3b2c7fc1bbaa8cb2ba3",
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
    for name in CATALOG_SCHEMA_RESOURCES:
        schema = load_schema(name)
        identifier = schema.get("$id")
        if not isinstance(identifier, str):
            raise _resource_error(name, "schema identifier is missing")
        resources.append((identifier, Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def validate_contract(name: str, value: dict[str, Any]) -> None:
    Draft202012Validator(
        load_schema(name),
        format_checker=FormatChecker(),
        registry=_catalog_schema_registry(),
    ).validate(value)
