from eom_workflow_runner.engine import (
    CONTENT_TEAM_IMAGE_RESULT_SCHEMAS,
    _is_content_team_image_result_schema,
)


def test_runner_routes_v10_image_result_without_reinterpreting_prior_families() -> None:
    assert (
        frozenset({"image-result@8.0", "image-result@9.0", "image-result@10.0"})
        == CONTENT_TEAM_IMAGE_RESULT_SCHEMAS
    )
    assert _is_content_team_image_result_schema("image-result@10.0")
    assert not _is_content_team_image_result_schema("image-result@7.0")
    assert not _is_content_team_image_result_schema("image-result@11.0")
