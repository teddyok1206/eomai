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
        "item-origin-profile": CatalogSchemaResource(
            "schemas/item-origin/item-origin-profile-v1.schema.json",
            "resources/item-origin/item-origin-profile-v1.schema.json",
            "1.0",
            "sha256:1a428b3ce8d0a09460cbefcb23384c2222e0fd3aa4c84a71ae76490cfff12d8d",
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
        "knowledge-analysis-types-v4": CatalogSchemaResource(
            "schemas/knowledge/knowledge-analysis-types-v4.schema.json",
            "resources/knowledge/knowledge-analysis-types-v4.schema.json",
            "4.0",
            "sha256:02584fb9edb61c32a904c5ec5878f9f96ffe300f32796fab3cfe730ae531935f",
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
        "evidence-bundle-manifest-v4": CatalogSchemaResource(
            "schemas/knowledge/evidence-bundle-manifest-v4.schema.json",
            "resources/knowledge/evidence-bundle-manifest-v4.schema.json",
            "4.0",
            "sha256:9dbf2b90ece9dae7a5963e504c1fb8dede32d09e9b6cb1f7b5beb6eb75162781",
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
