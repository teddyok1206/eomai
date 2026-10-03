"""Fail before inference when either pinned CLIP tokenizer would discard prompt instructions."""

from __future__ import annotations

from typing import Any

from eom_image_provider.provider import ProviderError


def require_prompt_capacity(
    pipeline: Any,
    prompts: tuple[str, ...],
    *,
    model_error: str,
    overflow_error: str,
) -> None:
    for name in ("tokenizer", "tokenizer_2"):
        tokenizer = getattr(pipeline, name, None)
        maximum = getattr(tokenizer, "model_max_length", None)
        if tokenizer is None or not isinstance(maximum, int) or not 1 <= maximum <= 512:
            raise ProviderError(model_error)
        for prompt in prompts:
            try:
                encoded = tokenizer(
                    prompt,
                    add_special_tokens=True,
                    padding=False,
                    truncation=False,
                    return_attention_mask=False,
                )
                input_ids = encoded["input_ids"]
            except Exception as exc:
                raise ProviderError(model_error) from exc
            if (
                not isinstance(input_ids, list)
                or not input_ids
                or isinstance(input_ids[0], list)
                or len(input_ids) > maximum
            ):
                raise ProviderError(overflow_error)
