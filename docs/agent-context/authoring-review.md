# 문항 출제와 검토

## 흐름과 승인 의미

요청 초안과 실제 Workflow 시작은 다르다. 시작 시 선택한 released Workflow·Content Pack·
control/preset·Graph 근거를 고정하고, 이후 검토 피드백과 재개도 원래 실행 identity를 따른다.
실행 중 설정에 최신 버전이 생겼다고 기존 실행을 몰래 바꾸지 않는다.

출제자와 검토자는 직접 대화하지 않는다. Runner가 directive와 역할 결과·step attempt를
연결해 최대 3차 개선 경로를 관리한다. 검토 차수와 인프라 retry 횟수는 별개이며,
`WORKER_RESULT_INVALID` 같은 결과 문제를 어떤 correction 경로가 받을 수 있는지는
해당 released definition과 `engine.py`의 실제 분기를 확인한다. 무조건 모든 예외를
같은 모델 재실행으로 해결하지 않는다.

등록·HWPX 확인을 사람 승인보다 먼저 할 수 있다. 사람 승인 대기와 자동 검토 통과,
풀이보고서 accepted, Graph 반영, 임베딩 준비는 서로 다른 상태다. 승인 대기라고 해서
항상 원본/미리보기/HWPX가 불가능하다는 이전 규칙을 복원하지 않는다.

## 먼저 열 파일

- `services/workflow_runner/eom_workflow_runner/engine.py`: step 실행·결과·rework/correction.
- `packages/workflow/eom_workflow/review_rework.py`: source review/history의 typed 규칙.
- `packages/workflow/eom_workflow/review_correction.py`: correction pass와 directive.
- `services/catalog_service/eom_catalog_service/workflow_catalog.py`: Catalog의 역할 준비와 등록 연결.
- `apps/application_api/eom_api/services/item_approval_service.py`: 사람 승인 application.
- `apps/application_api/eom_api/services/hwpx_item_revision_resolver.py`: 출력할 revision 자격.
- `config/workflows`, `config/control-plane`, `content/packs`: 정본 실행 설정·내용 규칙.

## 프롬프트와 문항 구성

콘텐츠팀장 원문과 연동/투영 지침은 구분한다. 원문 참고 파일은 검증된 reference로
materialize하고 실제 실행 authority는 released instruction bundle이다. 원문 두 개를
마음대로 합쳐 수정하거나 staging 경로를 worker에게 직접 전달하지 않는다.

자료는 발문·줄글·표·그림·조건·선지·해설의 의미를 canonical item 구조로 전달한다.
줄글 설명에 무조건 `<자료>` 제목이나 별도 상자를 붙이지 않는다. 비교 수치가 많으면
표도 동등한 선택이며, TABLE-only 문항은 정상이다. 자연스러운 발문 문장 하나를
하드코딩해 모든 문제에 반복하는 방식으로 고치지 않는다.

그림 한 개는 한 개로, 두 개는 독립 PNG 순서로 다룬다. `(가)/(나)`는 필요할 때 HWPX의
편집 가능한 글자이며 PNG에 구워 넣지 않는다. 과학적 label·축·수치와 GPU 소재의
분담은 이미지 계약에서 확인한다. 모델이 만든 이미지 설명을 학생용 본문으로 노출하지 않는다.

## 검증과 근거

- `tests/unit/test_workflow_state_machine.py`: Workflow 전이.
- `tests/unit/test_authoring_reference_boundary.py`: 출제 근거 경계.
- `docs/architecture/CONTENT_TEAM_AUTHORING_PROMPT_V5_DESIGN.md`: 참고 원문과 실행 지침 구분.
- `docs/architecture/HWPX_APPLICATION_API_V0.md`: 출력 application 경계.
