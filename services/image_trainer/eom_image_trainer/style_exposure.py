"""Derive the closed native 4:2:4 schedule without copying targets or global RNG state."""

from __future__ import annotations

import random
from collections import deque

from eom_image_contracts.sdxl_native_lora import LocalImageSdxlNativeLoraCommandV3


def native_style_exposure_schedule(command: LocalImageSdxlNativeLoraCommandV3) -> tuple[int, ...]:
    """All targets once, then quota-shuffled, within-expression shuffle cycles.

    O(N + updates * accumulation) time/space; at most 200 targets/4,000 indices.
    Counts describe scheduled exposure, not a recovered per-step execution journal.
    """
    weights = command.exposure_policy.expression_weights
    samples = command.training_samples
    count = len(samples)
    microsteps = (
        command.hyperparameters.max_train_steps
        * command.hyperparameters.gradient_accumulation_steps
    )
    if type(command.seed) is not int or microsteps < count:
        raise ValueError("SDXL_NATIVE_LORA_STYLE_EXPOSURE_SCHEDULE_INVALID")
    buckets: dict[str, list[int]] = {expression: [] for expression, _ in weights}
    for index, sample in enumerate(samples):
        buckets[sample.conditioning.expression].append(index)
    if any(not bucket for bucket in buckets.values()):
        raise ValueError("SDXL_NATIVE_LORA_STYLE_EXPOSURE_COVERAGE_INVALID")

    schedule = list(range(count))
    random.Random(command.seed).shuffle(schedule)
    remaining = microsteps - count
    total_weight = sum(weight for _, weight in weights)
    quotas = [remaining * weight // total_weight for _, weight in weights]
    remainders = [remaining * weight % total_weight for _, weight in weights]
    for position in sorted(range(len(weights)), key=lambda i: (-remainders[i], i))[
        : remaining - sum(quotas)
    ]:
        quotas[position] += 1
    expressions = [
        expression
        for (expression, _), quota in zip(weights, quotas, strict=True)
        for _ in range(quota)
    ]
    random.Random(command.seed).shuffle(expressions)
    generators = {
        expression: random.Random(command.seed + position + 1)
        for position, (expression, _) in enumerate(weights)
    }
    queues: dict[str, deque[int]] = {expression: deque() for expression in buckets}
    for expression in expressions:
        queue = queues[expression]
        if not queue:
            cycle = list(buckets[expression])
            generators[expression].shuffle(cycle)
            queue.extend(cycle)
        schedule.append(queue.popleft())
    return tuple(schedule)
