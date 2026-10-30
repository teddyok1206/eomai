# 창작 문항 10369 추출 복구

## 원인과 수정 범위

2026-10-30 00:02 UTC, 완료 54/1053 다음 고유번호 10369의 추출이
`WORKER_RESULT_INVALID`로 실패했다. 원본 조건 5개와 판단용 보기 3개를 모두
`statement_set`으로 제안했지만 해설 참조는 보기 3개만 존재했다. 기존 canonical
reference 검증이 정확히 거부했다. 원래 stdout SHA-256은
`d517941b11e11a730fbaa31b7e78ad920022c972fdf6fda22986d999bc799790`다.

수정 책임은 기존 창작 V2 생성 schema projection과 core prompt다. 조건·절차 목록과
판단 대상 보기를 구분하고 statement ID의 정확한 해설 coverage를 안내한다.
등록/검증 규칙, released JSON Schema bytes, 과거 결과와 hash는 변경하지 않는다.
새 schema/DB migration/queue/의존성/자동 무한 retry는 없다.

정본은 기존 cohort/source/work/plan, 실패 Workflow/Job과 결과 파일이다. 생성 지침은
권한이나 source evidence가 아니다. 기존 map/set 검증과 indexed Workflow/Job lookup,
명시적 invalid-result recovery의 predecessor lock/고유 successor를 재사용한다.
관측 status는 캐시이며 완료 증거를 대체하지 않는다. 실패 이력을 성공으로 바꾸거나
응답에 해설을 합성하지 않는다. 원본 조건을 삭제하는 단순 우회도 사용하지 않는다.

운영 복구는 기존 application의 후속 Workflow 준비와 멱등 재전송 확인 후 같은
1053개 대상·slot05·동시1·고정 정책으로 순차 owner를 재개한다. GPU INDEX/QUERY의
실행 pin과 기출/교과서 정본은 보존한다. 완료 기준은 기존 54개를 보존하고 추가
5문항의 정본 Item/accepted 분석/공유 Graph/공식 보고서 조회까지 확인하는 것이다.

## 검증 및 운영 결과

V2 생성 projection/core prompt의 지침 후보와 참조 검증 회귀를 포함해 창작/기존 추출
unit 523개 PASS, core 3개 mypy 및 Ruff/format PASS다. 새 테스트 fixture는 최소 보기
개수와 정규화 후 self-hash를 맞춘 뒤 재검증했다. 후보를 운영 지침 반영 완료로
표현하지 않는다. 현재 GPU 작업을 위해 공유 API/Runner/DB를 교체하지 않았다.

기존 guarded disposable DB의 external-item suite는 25 PASS, 1개는 이전 실험의
고정 capacity key가 남아 `CONTROL_LOGICAL_CONFLICT`로 거부됐다. 운영 DB 테스트나
복구 application 실패가 아니며, 이 결과를 전체 PASS로 합산하지 않는다. 동시 복구,
실패 보존과 늦은 거부 검사를 포함한 workflow 저장소 검사는 통과했다.

기존 설치본 007e3f44의 공식 invalid-result recovery application으로 후속
`workflow_0512192c4e504c43991aa3b06bf5519e`를 준비했다. 준비 단계 worker 실행은 0이며,
원래 work input SHA `717b72e5361ab22b1b15b22919c36618dd357114f95f6f506c94c45be22f2cab`
를 보존한다. 기존 실패 Workflow/Job은 변경하지 않았다. 같은 cohort의 원래 순차
owner를 재개했으며 현재는 기존 완료 문항의 정본 검증으로 cursor를 복원 중이다.
이는 새 지침 후보의 운영 배포 증거가 아니며, 원래 거부된 결과를 승격하지 않는
명시적 재추출이다. 추가 5건의 끝단 증거는 완료 후 기록한다.
