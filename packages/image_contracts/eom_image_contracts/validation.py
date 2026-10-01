"""JSON Schema 2020-12 validation backed by wheel-owned resources."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

SCHEMA_FILES = {
    "composite-receipt": "local-image-composite-receipt-v1.schema.json",
    "composite-request": "local-image-composite-request-v1.schema.json",
    "model-manifest": "local-image-model-manifest-v1.schema.json",
    "provider-binding": "local-image-provider-binding-v1.schema.json",
    "provider-binding-v2": "local-image-provider-binding-v2.schema.json",
    "provider-binding-v3": "local-image-provider-binding-v3.schema.json",
    "provider-binding-v4": "local-image-provider-binding-v4.schema.json",
    "provider-binding-v5": "local-image-provider-binding-v5.schema.json",
    "provider-binding-v6": "local-image-provider-binding-v6.schema.json",
    "generation-request": "local-image-generation-request-v1.schema.json",
    "generation-receipt": "local-image-generation-receipt-v1.schema.json",
    "visual-reference-intent": "local-image-visual-reference-intent-v1.schema.json",
    "visual-reference-bundle": "local-image-visual-reference-bundle-v1.schema.json",
    "visual-reference-discovery-command": (
        "local-image-visual-reference-discovery-command-v1.schema.json"
    ),
    "visual-reference-discovery-result": (
        "local-image-visual-reference-discovery-result-v1.schema.json"
    ),
    "visual-reference-acquisition-command": (
        "local-image-visual-reference-acquisition-command-v1.schema.json"
    ),
    "visual-reference-acquisition-result": (
        "local-image-visual-reference-acquisition-result-v1.schema.json"
    ),
    "reference-conditioned-composite-request": (
        "local-image-reference-conditioned-composite-request-v1.schema.json"
    ),
    "reference-conditioned-composite-receipt": (
        "local-image-reference-conditioned-composite-receipt-v1.schema.json"
    ),
    "style-adapter-release": "local-image-style-adapter-release-v1.schema.json",
    "style-adapter-release-v2": "local-image-style-adapter-release-v2.schema.json",
    "reference-conditioned-composite-request-v2": (
        "local-image-reference-conditioned-composite-request-v2.schema.json"
    ),
    "reference-conditioned-composite-receipt-v2": (
        "local-image-reference-conditioned-composite-receipt-v2.schema.json"
    ),
    "reference-conditioned-composite-request-v3": (
        "local-image-reference-conditioned-composite-request-v3.schema.json"
    ),
    "reference-conditioned-composite-receipt-v3": (
        "local-image-reference-conditioned-composite-receipt-v3.schema.json"
    ),
    "reference-conditioned-composite-request-v4": (
        "local-image-reference-conditioned-composite-request-v4.schema.json"
    ),
    "reference-conditioned-composite-receipt-v4": (
        "local-image-reference-conditioned-composite-receipt-v4.schema.json"
    ),
    "reference-conditioned-composite-request-v5": (
        "local-image-reference-conditioned-composite-request-v5.schema.json"
    ),
    "reference-conditioned-composite-receipt-v5": (
        "local-image-reference-conditioned-composite-receipt-v5.schema.json"
    ),
    "reference-conditioned-composite-request-v6": (
        "local-image-reference-conditioned-composite-request-v6.schema.json"
    ),
    "reference-conditioned-composite-receipt-v6": (
        "local-image-reference-conditioned-composite-receipt-v6.schema.json"
    ),
    "reference-composition-evaluation": (
        "local-image-reference-composition-evaluation-v1.schema.json"
    ),
    "visual-reference-publication-receipt": (
        "local-image-visual-reference-publication-receipt-v1.schema.json"
    ),
    "quality-evaluation-plan": "local-image-quality-evaluation-plan-v1.schema.json",
    "quality-evaluation-result": "local-image-quality-evaluation-result-v1.schema.json",
    "training-authorization": "local-image-training-authorization-v1.schema.json",
    "crop-locator-command": "local-image-crop-locator-command-v1.schema.json",
    "crop-locator-result": "local-image-crop-locator-result-v1.schema.json",
    "training-crop-proposal-set": ("local-image-training-crop-proposal-set-v1.schema.json"),
    "training-crop-review": "local-image-training-crop-review-v1.schema.json",
    "training-candidate-inventory": ("local-image-training-candidate-inventory-v1.schema.json"),
    "training-dataset-manifest": "local-image-training-dataset-manifest-v1.schema.json",
    "training-eligibility-review": ("local-image-training-eligibility-review-v1.schema.json"),
    "lora-training-plan": "local-image-lora-training-plan-v1.schema.json",
    "lora-adapter-manifest": "local-image-lora-adapter-manifest-v1.schema.json",
    "lora-checkpoint-manifest": "local-image-lora-checkpoint-manifest-v1.schema.json",
    "lora-training-receipt": "local-image-lora-training-receipt-v1.schema.json",
    "lora-training-command": "local-image-lora-training-command-v1.schema.json",
    "lora-training-worker-result": ("local-image-lora-training-worker-result-v1.schema.json"),
    "lora-micro-probe-plan": "local-image-lora-micro-probe-plan-v1.schema.json",
    "lora-micro-probe-command": "local-image-lora-micro-probe-command-v1.schema.json",
    "lora-micro-adapter-manifest": "local-image-lora-micro-adapter-manifest-v1.schema.json",
    "lora-micro-probe-worker-result": ("local-image-lora-micro-probe-worker-result-v1.schema.json"),
    "lora-micro-evaluation-command": ("local-image-lora-micro-evaluation-command-v1.schema.json"),
    "lora-micro-evaluation-result": ("local-image-lora-micro-evaluation-result-v1.schema.json"),
    "science-corpus-training-authorization": (
        "local-image-science-corpus-training-authorization-v1.schema.json"
    ),
    "science-corpus-visual-pilot-plan": (
        "local-image-science-corpus-visual-pilot-plan-v1.schema.json"
    ),
    "science-corpus-visual-pilot-plan-v2": (
        "local-image-science-corpus-visual-pilot-plan-v2.schema.json"
    ),
    "science-corpus-visual-pilot-plan-v3": (
        "local-image-science-corpus-visual-pilot-plan-v3.schema.json"
    ),
    "science-corpus-visual-pilot-command": (
        "local-image-science-corpus-visual-pilot-command-v1.schema.json"
    ),
    "science-corpus-visual-pilot-command-v2": (
        "local-image-science-corpus-visual-pilot-command-v2.schema.json"
    ),
    "science-corpus-visual-pilot-command-v3": (
        "local-image-science-corpus-visual-pilot-command-v3.schema.json"
    ),
    "science-corpus-visual-pilot-result": (
        "local-image-science-corpus-visual-pilot-result-v1.schema.json"
    ),
    "science-visual-pattern-inventory": (
        "local-image-science-visual-pattern-inventory-v1.schema.json"
    ),
    "science-visual-pattern-inventory-v2": (
        "local-image-science-visual-pattern-inventory-v2.schema.json"
    ),
    "science-visual-campaign-pattern-inventory": (
        "local-image-science-visual-campaign-pattern-inventory-v1.schema.json"
    ),
    "science-visual-campaign-review-batch-command": (
        "local-image-science-visual-campaign-review-batch-command-v1.schema.json"
    ),
    "science-visual-campaign-review-batch-result": (
        "local-image-science-visual-campaign-review-batch-result-v1.schema.json"
    ),
    "science-visual-crop-set": "local-image-science-visual-crop-set-v1.schema.json",
    "science-visual-crop-set-v2": "local-image-science-visual-crop-set-v2.schema.json",
    "science-raster-suitability-review": (
        "local-image-science-raster-suitability-review-v1.schema.json"
    ),
    "science-campaign-raster-suitability-review": (
        "local-image-science-campaign-raster-suitability-review-v1.schema.json"
    ),
    "science-raster-refinement-plan": ("local-image-science-raster-refinement-plan-v1.schema.json"),
    "science-campaign-raster-refinement-plan": (
        "local-image-science-campaign-raster-refinement-plan-v1.schema.json"
    ),
    "science-visual-campaign-crop-set": (
        "local-image-science-visual-campaign-crop-set-v1.schema.json"
    ),
    "science-visual-campaign-crop-set-v2": (
        "local-image-science-visual-campaign-crop-set-v2.schema.json"
    ),
    "science-object-line-art-suitability-review": (
        "local-image-science-object-line-art-suitability-review-v1.schema.json"
    ),
    "science-object-line-art-crop-set": (
        "local-image-science-object-line-art-crop-set-v1.schema.json"
    ),
    "science-lora-micro-probe-plan": ("local-image-science-lora-micro-probe-plan-v1.schema.json"),
    "science-lora-micro-probe-command": (
        "local-image-science-lora-micro-probe-command-v1.schema.json"
    ),
    "science-lora-micro-adapter-manifest": (
        "local-image-science-lora-micro-adapter-manifest-v1.schema.json"
    ),
    "science-lora-micro-probe-worker-result": (
        "local-image-science-lora-micro-probe-worker-result-v1.schema.json"
    ),
    "science-campaign-lora-micro-probe-plan": (
        "local-image-science-campaign-lora-micro-probe-plan-v1.schema.json"
    ),
    "science-campaign-lora-micro-probe-command": (
        "local-image-science-campaign-lora-micro-probe-command-v1.schema.json"
    ),
    "science-campaign-lora-micro-adapter-manifest": (
        "local-image-science-campaign-lora-micro-adapter-manifest-v1.schema.json"
    ),
    "science-campaign-lora-micro-probe-worker-result": (
        "local-image-science-campaign-lora-micro-probe-worker-result-v1.schema.json"
    ),
    "science-campaign-lora-micro-evaluation-command": (
        "local-image-science-campaign-lora-micro-evaluation-command-v1.schema.json"
    ),
    "science-campaign-lora-micro-evaluation-result": (
        "local-image-science-campaign-lora-micro-evaluation-result-v1.schema.json"
    ),
    "science-campaign-lora-micro-probe-plan-v2": (
        "local-image-science-campaign-lora-micro-probe-plan-v2.schema.json"
    ),
    "science-campaign-lora-micro-probe-command-v2": (
        "local-image-science-campaign-lora-micro-probe-command-v2.schema.json"
    ),
    "science-campaign-lora-micro-adapter-manifest-v2": (
        "local-image-science-campaign-lora-micro-adapter-manifest-v2.schema.json"
    ),
    "science-campaign-lora-micro-probe-worker-result-v2": (
        "local-image-science-campaign-lora-micro-probe-worker-result-v2.schema.json"
    ),
    "science-campaign-lora-micro-evaluation-command-v2": (
        "local-image-science-campaign-lora-micro-evaluation-command-v2.schema.json"
    ),
    "science-campaign-lora-micro-evaluation-result-v2": (
        "local-image-science-campaign-lora-micro-evaluation-result-v2.schema.json"
    ),
    "science-campaign-lora-micro-probe-plan-v3": (
        "local-image-science-campaign-lora-micro-probe-plan-v3.schema.json"
    ),
    "science-campaign-lora-micro-probe-command-v3": (
        "local-image-science-campaign-lora-micro-probe-command-v3.schema.json"
    ),
    "science-campaign-lora-micro-adapter-manifest-v3": (
        "local-image-science-campaign-lora-micro-adapter-manifest-v3.schema.json"
    ),
    "science-campaign-lora-micro-probe-worker-result-v3": (
        "local-image-science-campaign-lora-micro-probe-worker-result-v3.schema.json"
    ),
    "science-campaign-lora-micro-evaluation-command-v3": (
        "local-image-science-campaign-lora-micro-evaluation-command-v3.schema.json"
    ),
    "science-campaign-lora-micro-evaluation-result-v3": (
        "local-image-science-campaign-lora-micro-evaluation-result-v3.schema.json"
    ),
    "science-lora-micro-evaluation-command": (
        "local-image-science-lora-micro-evaluation-command-v1.schema.json"
    ),
    "science-lora-micro-evaluation-result": (
        "local-image-science-lora-micro-evaluation-result-v1.schema.json"
    ),
    "science-visual-subject-inventory": (
        "local-image-science-visual-subject-inventory-v1.schema.json"
    ),
    "science-visual-subject-benchmark-plan": (
        "local-image-science-visual-subject-benchmark-plan-v1.schema.json"
    ),
    "science-visual-subject-benchmark-command": (
        "local-image-science-visual-subject-benchmark-command-v1.schema.json"
    ),
    "science-visual-subject-benchmark-result": (
        "local-image-science-visual-subject-benchmark-result-v1.schema.json"
    ),
    "science-visual-subject-benchmark-review": (
        "local-image-science-visual-subject-benchmark-review-v1.schema.json"
    ),
    "science-visual-subject-multiseed-plan": (
        "local-image-science-visual-subject-multiseed-plan-v1.schema.json"
    ),
    "science-visual-subject-multiseed-command": (
        "local-image-science-visual-subject-multiseed-command-v1.schema.json"
    ),
    "science-visual-subject-multiseed-result": (
        "local-image-science-visual-subject-multiseed-result-v1.schema.json"
    ),
    "science-visual-subject-multiseed-review": (
        "local-image-science-visual-subject-multiseed-review-v1.schema.json"
    ),
    "science-visual-subject-refinement-plan": (
        "local-image-science-visual-subject-refinement-plan-v1.schema.json"
    ),
    "model-candidate-manifest": "local-image-model-candidate-manifest-v1.schema.json",
    "flux2-reference-probe-plan": "local-image-flux2-reference-probe-plan-v1.schema.json",
    "flux2-reference-probe-command": ("local-image-flux2-reference-probe-command-v1.schema.json"),
    "flux2-reference-probe-result": "local-image-flux2-reference-probe-result-v1.schema.json",
    "flux2-reference-probe-plan-v2": "local-image-flux2-reference-probe-plan-v2.schema.json",
    "flux2-reference-probe-command-v2": (
        "local-image-flux2-reference-probe-command-v2.schema.json"
    ),
    "flux2-reference-probe-result-v2": "local-image-flux2-reference-probe-result-v2.schema.json",
    "svg-label-layout-validation-receipt": ("svg-label-layout-validation-receipt-v1.schema.json"),
}
SCHEMA_SHA256 = {
    "composite-receipt": "sha256:5a2c87fac79464d4e0fcc8a0ed2bf5a2b1be309c5da867eaeb757e2c23784256",
    "composite-request": "sha256:a238142416462d0dd597d06973ebc180e57c57acf61dc089c79209f6f1a8f4d9",
    "model-manifest": "sha256:f3c0d55b27e16785c14f04a52be0c84cfc23cb7fe10f9e40654891f907804fd3",
    "provider-binding": "sha256:5669a9e9d47b0e681b165dd7a8d71500d7f0552c968759273d4107eb488f00be",
    "provider-binding-v2": (
        "sha256:c9a7c6a2ba772f44108193be85d8b354ec89e26e1003affbe634f8327399ad78"
    ),
    "provider-binding-v3": (
        "sha256:51f22a71964507fbeeb1f800fcdd61551dc4f382e3cc28ec76c1f687ee620020"
    ),
    "provider-binding-v4": (
        "sha256:9e1c367abeee7276d3f4e390cdc61a117f9f49dd6b4341d0904542657a2fabdc"
    ),
    "provider-binding-v5": (
        "sha256:64094135c4dbf1c9f3d7a34cdf03cbd008744315c77263734fc8c770a4a3bb00"
    ),
    "provider-binding-v6": (
        "sha256:d2440059f71246c9e6de2dfa41648a4baa91027c072f1d1107ab255c9e26362a"
    ),
    "generation-request": "sha256:8107b01c9f088bbf0b9d3c63e58c29252a5125acf5f5fb157be74f02cdb3839e",
    "generation-receipt": "sha256:eccd1c2b335ee6709c3962e3649784f16db120cc68eed7faf2e491db6efc3982",
    "visual-reference-intent": (
        "sha256:5040cb4700ba514d580b87fb6616e47b60066af4a73aa33564561e355ac4a05c"
    ),
    "visual-reference-bundle": (
        "sha256:d1c41b0b7ebd6f0f459f01920066e4b40481e8f7d5574506d4a44fd5bcb9bd24"
    ),
    "visual-reference-discovery-command": (
        "sha256:0e0fb830e8083cd3c21f38de3fb190a5fa864e1b8a765b7c81ada4ed6dfcc266"
    ),
    "visual-reference-discovery-result": (
        "sha256:ff8bb116d1ae808a59795fbc32ac0ac95974bb25cd51d7bb98ca4f40f31e3a64"
    ),
    "visual-reference-acquisition-command": (
        "sha256:40677d44357c4c3b6767f6b7654589d41ae9fd1b85e9928c0ca134320c185fff"
    ),
    "visual-reference-acquisition-result": (
        "sha256:ac8c083fd573108d46534798d12d090ef33adbf06667dc68a8c56f3351074ea9"
    ),
    "reference-conditioned-composite-request": (
        "sha256:f23558ed1d352e41d800e35bde0fd090a0d33f6d5cafb213bb7593c26b13f40e"
    ),
    "reference-conditioned-composite-receipt": (
        "sha256:50863b0953358d7b71f3aa909748bf4ac9306418894c34b58c34f1800573568e"
    ),
    "style-adapter-release": (
        "sha256:22f632254b0b72236d4d8a1e80597dfdca7982fe028259b0bcb1ee630d251018"
    ),
    "style-adapter-release-v2": (
        "sha256:e009d0496edb573840cebfef8f6112244fda9aeaaf67ca100546d87bec6e067f"
    ),
    "reference-conditioned-composite-request-v2": (
        "sha256:6b538a3b968b728c6f2c51e882e3e3626220a0778bf43dabae9c38ff1dc24c96"
    ),
    "reference-conditioned-composite-receipt-v2": (
        "sha256:ce8986fd687998cfef67ff3df72fa98dd45cc5def52e056ab8e2e4ec7dc59961"
    ),
    "reference-conditioned-composite-request-v3": (
        "sha256:02ed5dfe0b946ae068dec703605c618d8d038acba5d2f871695b1b7f56f5d05b"
    ),
    "reference-conditioned-composite-receipt-v3": (
        "sha256:30d516b0c5b36ce9cfd9a4d3c2f0c59217cdc201aaa36d89972ac08c8f9404a4"
    ),
    "reference-conditioned-composite-request-v4": (
        "sha256:8a201067f093c76f7923b6920e064c885565480ba960e371b711a693e3448dc3"
    ),
    "reference-conditioned-composite-receipt-v4": (
        "sha256:88d1c70fd2a7b599c93162388fb54885055337e7b1f777c14f8ed3877b44335a"
    ),
    "reference-conditioned-composite-request-v5": (
        "sha256:88892bc7a35ce27106467f778a5661664b8f2d6ca55057ce2ff4c610b34b3ad6"
    ),
    "reference-conditioned-composite-receipt-v5": (
        "sha256:61e0c6338609564e12eb1034ef48af7c467260c13c41ba9d1bbf206f7b17d2f5"
    ),
    "reference-conditioned-composite-request-v6": (
        "sha256:6b9dad92a0e262b826d94cdc95c40bca8d2db54de92d65dabb9d551e0094220e"
    ),
    "reference-conditioned-composite-receipt-v6": (
        "sha256:1499a4019e8a50d6ba9987ef223a30a0df33c196d5d0f66692f118e1c5c8f33d"
    ),
    "reference-composition-evaluation": (
        "sha256:2bf2747b6d2458880c7fa26409b96377756a022bc13f4a75ee1de19340ef1120"
    ),
    "visual-reference-publication-receipt": (
        "sha256:79446191e079598884186344efbbb5a6cfc150a021ba3b929011c6ad707ba2ed"
    ),
    "quality-evaluation-plan": (
        "sha256:d0968b5e3237cef4edd5581f8e72e768c0e9c4c64efd4008d1bdeaed2c1497ca"
    ),
    "quality-evaluation-result": (
        "sha256:58ec74c1d1485fdaa5847bdfa8adb8603743d68db7f6c612ac36cf2f524a3335"
    ),
    "training-authorization": (
        "sha256:766c4f1facc36e59b0a12a3d1403bc98b6c00cf8a0206e894c5f42877c361c88"
    ),
    "crop-locator-command": (
        "sha256:6b3181bcd98de43a46110056ee0ca58fe3c91ed43d691d35d9f9f526c7d2d159"
    ),
    "crop-locator-result": (
        "sha256:a532cff048956c0ca52b7ba175aeba0860bb844d4f2a2777bfcf8f3f8fb75cd3"
    ),
    "training-crop-proposal-set": (
        "sha256:c461eedb36d4ad631964a483dbbc14a0dfb6f26bb27cd90326a01839c79cb12f"
    ),
    "training-crop-review": (
        "sha256:eb907f8ad4b92553a2401b750b446f9479394a4208810535569b1fff154a2f1a"
    ),
    "training-dataset-manifest": (
        "sha256:ecb43e5ed58af59b40056a2afa0f541b12caffb71dee733aaa2681aef694c81c"
    ),
    "training-eligibility-review": (
        "sha256:28568f2e83c23e9d4d94cb8c9e967a193082dbbc35c332148b1e9ccf3bcbd4b9"
    ),
    "training-candidate-inventory": (
        "sha256:c9908e54437663d1044822c61ff1c7ada6e1de09be8f08b72d2932b1849a9ee2"
    ),
    "lora-training-plan": (
        "sha256:f55bb6a9f5560764aa21174a91d5f187d430aed20a8c0cbcbfe24e430f49fdf5"
    ),
    "lora-adapter-manifest": (
        "sha256:6ff652980b8b3599d0843395820d0e468270cfd17e9ab733a6b7ee28d6acb546"
    ),
    "lora-checkpoint-manifest": (
        "sha256:ceaafc8068624e4ff460b852b636ce8d468c203480c9ed94d0d1337620e62f6b"
    ),
    "lora-training-receipt": (
        "sha256:4fa7cb556139374b6964baa8aa028350843d2f7d85ff680a66f673e24f127089"
    ),
    "lora-training-command": (
        "sha256:6b7c6eb7acf0253b37cd627309bc8c1633f71da8becae2b760ba19cdb3ab4aa4"
    ),
    "lora-training-worker-result": (
        "sha256:310500458a4496105816c55b207bd39daa842dcfd3fa02a820f462484441f6d7"
    ),
    "lora-micro-probe-plan": (
        "sha256:32c0c1ef0098a46a143f83a4e58292ff31254a69d89a87163d655474ac93bf20"
    ),
    "lora-micro-probe-command": (
        "sha256:149e08b0792eaea80b1e66eb0f8abcf836d66c71c863462723eeb6557b0d9cf3"
    ),
    "lora-micro-adapter-manifest": (
        "sha256:1221dcd0213a912bcd20b487ae2895e5256dda6a927adb89dab77754365e0cd3"
    ),
    "lora-micro-probe-worker-result": (
        "sha256:f6f1a795dcc433428b5b4a8a4597870c22243e0fee7ead8c947e4eaf19743d5b"
    ),
    "lora-micro-evaluation-command": (
        "sha256:bb4ec8dbaceaa8c89044a857963408678f7a08e29cd0c8244d1e9b3e21578faf"
    ),
    "lora-micro-evaluation-result": (
        "sha256:06fe871bafaa1a6cd1a8195836692ec2169d1ec6cdedc8d77282f19b85b04857"
    ),
    "science-corpus-training-authorization": (
        "sha256:8f84ee0e5485e01a04dd1746a2baa2210aaeb9e0f5182755a198402149d895e2"
    ),
    "science-corpus-visual-pilot-plan": (
        "sha256:76a48e59f9d9fb9777467bf8466f915a7cface0d04a0383bdb68ec4dea2f4708"
    ),
    "science-corpus-visual-pilot-plan-v2": (
        "sha256:90b6e463e31978d63d95ea045cec6a5b6ca7b4bb5c91e6f417eea83203af4057"
    ),
    "science-corpus-visual-pilot-plan-v3": (
        "sha256:cf3e1ad771eba8ffb32a62f367970955f3aea74109dd519debc01504b77add4b"
    ),
    "science-corpus-visual-pilot-command": (
        "sha256:9093b8e0c621cd12e978570eb1e5582097a8a70a73628b6fe182dfdaed3b8090"
    ),
    "science-corpus-visual-pilot-command-v2": (
        "sha256:5dae2e101d539b2eabbe40abaa96d91e0e850eab08cf437d51f696b6f424b4cc"
    ),
    "science-corpus-visual-pilot-command-v3": (
        "sha256:953143fe884c4ff39c7a3cfe9c66d1337c153433dc5ce9d2c9deeac755e706c6"
    ),
    "science-corpus-visual-pilot-result": (
        "sha256:8b2dccc1f567922917912eb5025e1fbf9256f2361e4ac6918602c504749246a1"
    ),
    "science-visual-pattern-inventory": (
        "sha256:191235a93c0b53830cb54e34341f2f893b570510624ac1486e76be16270a3fb4"
    ),
    "science-visual-pattern-inventory-v2": (
        "sha256:e2c89de1a67b461a7eb0c6e59a7fdcb9d9dae95e597fa80c6b989e02021ba646"
    ),
    "science-visual-campaign-pattern-inventory": (
        "sha256:912839c7fa1cdda4701c1a1aecf865f1fc94368510863de64a1b3e7b1b538b1b"
    ),
    "science-visual-campaign-review-batch-command": (
        "sha256:f62d1ee93dcd4125634ac4ddd1d89edb1b11c3f6f19fd197b94b13164bd375fd"
    ),
    "science-visual-campaign-review-batch-result": (
        "sha256:c81561b3de9fc99fc198a3bae61ffe5d4423263804d07440aa7195973722652d"
    ),
    "science-visual-crop-set": (
        "sha256:bc3f82e49d96dc6fe467d659c700c6a9bd12d044873b806d4b6017a8bde4d574"
    ),
    "science-visual-crop-set-v2": (
        "sha256:2b4f1865270c1c50c33ed6aedb56f239679accccf15ce49b9575418715bc12b7"
    ),
    "science-object-line-art-suitability-review": (
        "sha256:0f92daa6ab3441e8e8af765e0422491a4bbd1a3377967feea8edb86911313f0d"
    ),
    "science-object-line-art-crop-set": (
        "sha256:5982a6486aa98fae1dd3a56fd2e116f1a025ee20fb8d3fbd4280dcea407c8013"
    ),
    "science-raster-suitability-review": (
        "sha256:b386137ac8f1188aa01b12a075f8e1ba3696621d299cbf599bce8760f92b3713"
    ),
    "science-campaign-raster-suitability-review": (
        "sha256:e8ec84c1cb790b07f24fe033875f105fcac2ecce10529384adec7843aaa8dfaa"
    ),
    "science-raster-refinement-plan": (
        "sha256:419679adabbb30229386bf63bb2221dc1d599a7681b2e9de56f8ce5f15c6072b"
    ),
    "science-campaign-raster-refinement-plan": (
        "sha256:d3949a1d6d9ea0120ef691f420a6486afdaa38d1090eeb9a49548c2c6f5eeb90"
    ),
    "science-visual-campaign-crop-set": (
        "sha256:efc18963369f2622be8abd3cac4cf427017501fc83e1b55e22bf0bdfa3f29b40"
    ),
    "science-visual-campaign-crop-set-v2": (
        "sha256:b055484d6111aadd0dc9ea6d5d1606784392e3dc0af1c187231689d9428d5953"
    ),
    "science-lora-micro-probe-plan": (
        "sha256:70629fa7c1c2d427ace089cdfd0089c0f110e28a10627499da2ed1d1c5f5e1f8"
    ),
    "science-lora-micro-probe-command": (
        "sha256:d4ab0f2f962f84c18422b32030ac13feb5fd82e5036e0e8f8348b2fad5f7aae6"
    ),
    "science-lora-micro-adapter-manifest": (
        "sha256:fab3939a63f27123811c129335841e2a927bc88757828708775de599a84d1d8e"
    ),
    "science-lora-micro-probe-worker-result": (
        "sha256:4dc0aa5f491448d27f24c652250bdb3eed7098a9d590fa7bc262dd3215876080"
    ),
    "science-campaign-lora-micro-probe-plan": (
        "sha256:ab99e4ea978c40bd0caf0175570082eff7ddbec300594b306f7a30eb5da07566"
    ),
    "science-campaign-lora-micro-probe-command": (
        "sha256:35eb988dc82e34342f98dafc6485d4ca77c2ed58050c104b896de6500de689e5"
    ),
    "science-campaign-lora-micro-adapter-manifest": (
        "sha256:06370c3246b1d376ac569fd597d60404102e468f42dbf6fa96319e2297daacb3"
    ),
    "science-campaign-lora-micro-probe-worker-result": (
        "sha256:9d8a70a25346b427e15860197dd61ca1746c93a0ef6d257e50077f40dffa809f"
    ),
    "science-campaign-lora-micro-evaluation-command": (
        "sha256:6bf9e50a74310b32bae17c2494ce83ad3b4b35a2ceeccee528522f7ff649f6b8"
    ),
    "science-campaign-lora-micro-evaluation-result": (
        "sha256:e4b3cbaae122fbe058da01c3101073c2d38e75f285c35f61cc8912154f9a92ba"
    ),
    "science-campaign-lora-micro-probe-plan-v2": (
        "sha256:24d09a30abbc2552c1017d8583a80c60b159c1f12e3d73d18c506690d2ba5f68"
    ),
    "science-campaign-lora-micro-probe-command-v2": (
        "sha256:aa66b73f16e9348ae82efd909f3ebc62f2e14e784f2af1e5edec5f627a190e5d"
    ),
    "science-campaign-lora-micro-adapter-manifest-v2": (
        "sha256:7c727f9d4bfa12e74f56a44c0ffeab1c5fb2cfd0ac2ede84614f848a268a6478"
    ),
    "science-campaign-lora-micro-probe-worker-result-v2": (
        "sha256:63386217674168aff4f3f2af25de3d0f2337dab9e7c237159c8c5f74538e639b"
    ),
    "science-campaign-lora-micro-evaluation-command-v2": (
        "sha256:1ee16a52ebba2b7bb42ced31cadcdf7a16125112df2ff7b00aa9faea97471b0e"
    ),
    "science-campaign-lora-micro-evaluation-result-v2": (
        "sha256:b7db6670fa4b41d81d83a3100d364032f9f32b1855f92cbcdeda01fccd018f4d"
    ),
    "science-campaign-lora-micro-probe-plan-v3": (
        "sha256:06e7e9f091c92c8c3355a6832364b36325ff0ba473cb0c5976eb99f7baac6849"
    ),
    "science-campaign-lora-micro-probe-command-v3": (
        "sha256:fbacfa10fe6063311b65fb555e89e20af3a7c793614b5f95e7bbc2af4def898f"
    ),
    "science-campaign-lora-micro-adapter-manifest-v3": (
        "sha256:91e88a5b8fce6b74dffbf2c2adb7dd4eda7cbbc83d45d34075adfa8ca5f7d31d"
    ),
    "science-campaign-lora-micro-probe-worker-result-v3": (
        "sha256:5c563dab6452285735b6e7cc96720d2025083fd3b11bcc4ff7e9a05f47ad35a6"
    ),
    "science-campaign-lora-micro-evaluation-command-v3": (
        "sha256:a72636bb5a6db707de4860b6aef60cc63e8864d9e2026c0801fad9e69f6bf85d"
    ),
    "science-campaign-lora-micro-evaluation-result-v3": (
        "sha256:4dae3349885dd47488eeb45f3196ad1b7f4bc21c950aa8936120677efc987f1f"
    ),
    "science-lora-micro-evaluation-command": (
        "sha256:715e3f8495698b9e3db7601ec954a38774011ab67a649c19190e9bfe6774b019"
    ),
    "science-lora-micro-evaluation-result": (
        "sha256:2477a3f12e6396b3224d1812ce84d513eec607a768cb69f3f66d78ceafe76399"
    ),
    "science-visual-subject-inventory": (
        "sha256:5b5d5aed3224e601cfe7353f2eea693ef0eae79f6529db16409698a5a9028f6b"
    ),
    "science-visual-subject-benchmark-plan": (
        "sha256:088ae1612b80d5f28b5cce730a41bf81281e0ad180977713d41a38cd2dafc63b"
    ),
    "science-visual-subject-benchmark-command": (
        "sha256:1769922358a9c2bc1aa558a853d992996f6322d3edc9d085d22b5f6098851d7f"
    ),
    "science-visual-subject-benchmark-result": (
        "sha256:471516e78fd47eec687bb276ef95c1e6a2614f50a41bf9efde45a9b8cddf9533"
    ),
    "science-visual-subject-benchmark-review": (
        "sha256:309d059b24f07ca0a6a6c8e088a5e57e03c0569a06dfa5c283aa0ff408513740"
    ),
    "science-visual-subject-multiseed-plan": (
        "sha256:b17c5c8294e79ab9fa8161f6a9d070fefd96e922a9d4835a8a819a48a6b26726"
    ),
    "science-visual-subject-multiseed-command": (
        "sha256:a98220ae623410160ece500f7a2551e73c7c6738a0e6c28e40e0979a852c24be"
    ),
    "science-visual-subject-multiseed-result": (
        "sha256:24809d3cb85b8a166c7555af1e8fbfb722a6c36f37c2c72dcdfe0e40592a288e"
    ),
    "science-visual-subject-multiseed-review": (
        "sha256:a84ac26745df3e56c22cc288ba8c555fda8411868aaf0f49f2e790227e92a882"
    ),
    "science-visual-subject-refinement-plan": (
        "sha256:85f158a9fd84919e6eb3cee09dbb5a2e142f456044792dd11bb6218607ab701d"
    ),
    "model-candidate-manifest": (
        "sha256:cb13c20fc5f88b025c14e15990582c0762df85a9576de41fa2db2bd7958c7658"
    ),
    "flux2-reference-probe-plan": (
        "sha256:80ffbe051f3d4db74d475c9463f650de7cc70efd3ae2a15412ac1f2ab85542cf"
    ),
    "flux2-reference-probe-command": (
        "sha256:beb6cb5e88ab230458bdd3e868f06e17d0805a00a4ab3c6e542dfeb857f56a91"
    ),
    "flux2-reference-probe-result": (
        "sha256:179051d6e4f685b199aa0cc95a74e8e815ba5b2e0a941aa163f3735a97356181"
    ),
    "flux2-reference-probe-plan-v2": (
        "sha256:522c04c5e11063c6e56beafc36d79c72f1361c5136aaa7ef701bed7ce88a37b9"
    ),
    "flux2-reference-probe-command-v2": (
        "sha256:2135e4a7cd9374d06f58154b91762bc68831c1bee607239d5476a9464a4153bd"
    ),
    "flux2-reference-probe-result-v2": (
        "sha256:a808adb23481ec00399db1f91879455c72b9e136d8c9dbff7e782c37942a3d26"
    ),
    "svg-label-layout-validation-receipt": (
        "sha256:97fd5aeac833ada2883dfef2f1f033f0c66a59aeb977630b0707af200d23f569"
    ),
}


@lru_cache(maxsize=len(SCHEMA_FILES))
def load_schema(name: str) -> dict[str, Any]:
    try:
        filename = SCHEMA_FILES[name]
    except KeyError as exc:
        raise ValueError(f"unknown local image contract: {name}") from exc
    resource = files("eom_image_contracts").joinpath("schemas", filename)
    raw = resource.read_bytes()
    if "sha256:" + hashlib.sha256(raw).hexdigest() != SCHEMA_SHA256[name]:
        raise ValueError(f"local image contract hash mismatch: {name}")
    value: dict[str, Any] = json.loads(raw.decode("utf-8"))
    Draft202012Validator.check_schema(value)
    return value


def validate_contract(name: str, value: dict[str, Any]) -> None:
    Draft202012Validator(
        load_schema(name),
        registry=_schema_registry(),
        format_checker=FormatChecker(),
    ).validate(value)


@lru_cache(maxsize=1)
def _schema_registry() -> Registry[Any]:
    resources = []
    for name in sorted(SCHEMA_FILES):
        schema = load_schema(name)
        identifier = schema.get("$id")
        if not isinstance(identifier, str):
            raise ValueError(f"local image contract lacks an identifier: {name}")
        resources.append((identifier, Resource.from_contents(schema)))
    return Registry().with_resources(resources)
