from scripts.image_trainer.publish_science_subject_refinement_plan import CANDIDATE_PROMPTS


def test_refinement_candidate_prompts_close_expected_subject_population() -> None:
    assert set(CANDIDATE_PROMPTS) == {
        "AIR_CUSHION_PACKAGING",
        "APPLE_TREE",
        "BIODIVERSITY",
        "BURR_FRUIT",
        "CLOUD_WEATHER",
        "CONSUMER_SCIENCE_PRODUCT",
        "FOSSIL",
        "GEOLOGIC_ROCK",
        "MICROSCOPIC_TISSUE",
        "NON_HUMAN_ANIMAL",
        "OCEAN_WATER",
        "SAFETY_EQUIPMENT",
        "SPACECRAFT",
        "STAR_FIELD",
    }
    assert all(
        prompt == prompt.strip() and prompt.isascii() for prompt in CANDIDATE_PROMPTS.values()
    )
    assert all(20 <= len(prompt) <= 2000 for prompt in CANDIDATE_PROMPTS.values())
