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

추가로 같은 guarded DB의 recovery 저장소 사례만 별도 실행해 **6 PASS**를 확인했다.
이전 전체 suite의 capacity key fixture 충돌은 그대로 기록하며 운영 오류로 해석하지
않는다. 지침 후보 `c6dabde85233938758470399e4f5c8fdbeede85d`는 main에 push했고,
정식 build-only의 wheel RECORD와 비편집 설치본 검증도 PASS다. 공유 API/Runner,
production migration 0063 또는 공개 풀이 임베딩 successor를 이 복구 때문에
묵시적으로 활성화하지 않는다.

02:22 UTC 기존 완료 54개가 같은 Item/분석으로 재검증된 후, 10369의 후속 추출이
slot05에서 시작됐다. Job `job_26b8f7e4386f4b9da0a1d4c6b7379e4f`는 RUNNING이며 실제
ACTIVE lease 1개를 확인했다. 아직 등록 성공 증거가 아니다. 재개 owner invocation은
`f5ce519df5d44d44b531a0296631b152`다.

추가 5개는 부모 cohort의 기존 순서에서 **10369, 10370, 10371, 10372, 10374**다.
10373을 실패 후 임의로 건너뛴 것이 아니라 원래 frozen target set의 다음 5개다.
고정 대상 집합·원래 owner·source/정책 pin은 유지한다. 완료 시 이 다섯의 source/
canonical/accepted analysis/Graph/공식 공개 풀이 pointer와 hash를 대조하고,
재개 전 Graph `graphrev_a7a5f84bf68b2b860748797d868a1ffb`의 모든 source/accepted-result
참조가 보존됨을 추가 확인한다. 기존 readonly acceptance를 재사용하는 bounded helper는
검증되지 않은 status 숫자만으로 PASS를 만들지 않는다.

### 02:57 UTC — 추가 2건 운영 진행, 5건 최종 대조는 대기

10369의 새 추출 Job은 02:26:43 UTC SUCCEEDED, 분석 Job
`job_a8df1e06ef474d85801e116b31ad704d`는 02:29:40 UTC SUCCEEDED였다.
각각 role 1.34.0과 기출 분석과 같은 role 1.4.0을 사용했고 slot05였다.
Item `itemrev_529ced1919c84ab5ae352d96dfba6328`, accepted 분석
`analysisrun_060df2fb6d8545769c2a1a972b4cc894`, 공유 Graph
`graphrev_669c50401bd6471f0bb33129bc9c48f1`과 연결됐다.

기존 readonly acceptance로 10369를 별도 검증했다. 공식 보고서의 공개 풀이 5단계·
원문/독립 답안·모든 주의사항이 원래 결과와 일치했다. 원문당 canonical 중복 0,
두 Job의 slot lease 중복 0이었다. 기존 1015개 교과서·기출 source/accepted-result
참조와 노드/edge identity, 기출 520개 및 accepted 풀이 successor 520개도 보존됐다.
증거는 `/tmp/eom-creative-10369-e2e-0240.json`이며 immutable pointer에서 재구성할 수 있다.

같은 공식 Catalog report resolver로 추출 구조도 대조했다. 새로운 source draft는
`paragraph` + `statement_set`이고 판단 statement/해설은 ㄱ·ㄴ·ㄷ의 동일한 3개 ID다.
조건을 보기로 잘못 모델링한 이전 결과를 제자리 고치거나 검증을 완화하지 않았다.
정본 role Artifact는 `artifact_49393a60cb6346c386530be23e52840e` /
`rev_d4a2a2808c704fca806c989c42cec9b5`의 `result.json`, SHA는
`bb8a6cd117d0d089c0f375787728593083ca642338284cc1d9f19cd9f3dfa5e9`다.
이는 현재 설치본의 명시적 재추출 성공이며 새 지침 후보의 운영 활성화 증거는 아니다.

02:57 UTC 운영 owner는 10370의 `itemrev_e809f0e338964edeb67fa82d868db95a` /
`analysisrun_3c1320a280714eb2a35fada7f2cd0426`을 Graph
`graphrev_cd2239c7f0a85b4570c5423f40b2d88c`까지 검증해 56/1053이 됐다.
다음 10371의 `workflow_eb873569938a48c9802f307793cc08fe`가 자동 시작됐다.
목표 5건 중 운영 진행은 2건이며, 다섯 문항의 별도 정본 대조 및 목표 완료는 아직 아니다.
GPU INDEX/QUERY의 기존 PID·invocation과 재개 owner invocation은 모두 유지된다.
