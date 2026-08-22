Workflow {{ workflow.id }} / {{ workflow.step_key }}, Content Pack {{ pack.release_id }}.
아래 authoring result를 검토하고, 문항의 image block이 고정 stimulus revision
{{ stimulus.artifact_revision_id }}을 정확히 가리키는지 확인하라. 새 이미지를 만들거나 포인터를 변경하지
마라. JSON Schema에 맞춰 decision=asset_approved와 해당 artifact_revision_id, 간단한 한국어 요약을
반환하라. 불일치가 있으면 임의로 고치지 말고 worker 실행을 실패시켜라.

AUTHORING_RESULT_JSON:
{{ upstream.authoring.result_json }}
