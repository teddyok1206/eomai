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

## 목표 완료 — 2026-10-30 03:51:56 UTC

`CREATIVE_RECOVERY_FIVE=PASS`. 공식 복구로 멈춘 10369를 다시 추출·등록했고,
그 뒤 원래 대상 순서의 다섯 문항을 정본 기준으로 별도 대조했다. 운영 진행률은
**54 → 59/1053**이다. 이후 10375의
`workflow_f8bea8a152d4416b943ce089cd189b90`가 자동 시작돼 연속 처리가 유지된다.
이 목표의 종료선은 추가 5건 검증이며 전체 1053건 완료가 아니다. 이 시점 잔여는
10375를 포함한 994건이다.

| 고유번호 | 정본 Item Revision | ACCEPTED 분석 | 공개 풀이 단계 |
| --- | --- | --- | ---: |
| 10369 | `itemrev_529ced1919c84ab5ae352d96dfba6328` | `analysisrun_060df2fb6d8545769c2a1a972b4cc894` | 5 |
| 10370 | `itemrev_e809f0e338964edeb67fa82d868db95a` | `analysisrun_3c1320a280714eb2a35fada7f2cd0426` | 4 |
| 10371 | `itemrev_7f7d159930224a00897b05464d87d0c4` | `analysisrun_f28b91d472fc4aaea84fa1b9e519b8b1` | 3 |
| 10372 | `itemrev_829460f4788c462a986ef0ea5dc73d5b` | `analysisrun_8804a7b669864e0ca7e9559f0938abda` | 4 |
| 10374 | `itemrev_3976067a748a4c59864b0a3a615a8b32` | `analysisrun_85e3c4f53629442bbda991a2a6c59318` | 3 |

최종 대조에 사용한 exact Graph는 `graphrev_4d298fd8d363146a3b75e9fb48f9ad32`,
SHA-256은 `21fff21d6719f346de1320ea7555898020245ad066843fb3ad9363ae102fb6c2`다.
다섯 문항의 정본 역할 Artifact/revision/member/schema/media/hash는 실제 등록 계보와
검증됐고, 각 accepted 분석이 이 Graph에 연결됐다. 공식 Catalog materialize를 통해
공개 풀이 전체·원문/독립 답안·모든 issue/warning·원래 proposal status가 정본과
일치함을 확인했다. 원문 미인쇄 배점 주의사항 5건과 10370의 `OTHER_OBSERVED`도
그대로 조회된다. 이것은 등록·조회 및 기술 검증이지 사람의 과학적 품질 승인 대체가 아니다.

### 보존·중복·실행 경계의 실제 확인

- 추출 5개 + 후속 분석 5개 Job 모두 slot05에서 SUCCEEDED였다. 각 pair의 protocol은
  `workflow-role/1.34.0` / `workflow-role/1.4.0`이다. 선택된 10개 Job의 lease는 모두
  RELEASED이며 시간 구간 중복 0, 원문당 APPROVED canonical 중복 0이다.
- 재개 전 Graph의 **1069개** source/accepted-result identity·revision·hash 참조가
  모두 보존됐다. 최종 Graph membership은 1074개다. 기존 54개를 포함하는 재개 전의
  노드 17964개와 edge 42555개도 전부 보존됐고, 최종 18055/42726개에서 기존 identity의
  누락·재발급은 0이다. 교과서·기출의 1015개 기준선, 기출 base 520개 및 accepted
  풀이 successor 520개도 별도 대조에서 유지됐다. 서로 다른 분모를 문항 수로 합산하지 않는다.
- 원래 실패 Workflow/Job은 FAILED / `WORKER_RESULT_INVALID`를 유지한다. 원래 stdout의
  SHA `d517941b11e11a730fbaa31b7e78ad920022c972fdf6fda22986d999bc799790`도 같다.
  완료 후 같은 공식 recovery 요청을 실제 재전송하자 최초 준비한 exact selection을
  반환했고 `workers_started=0`이었다. 실패를 성공으로 바꾸거나 새 identity로 우회하지 않았다.
- cohort revision과 1053개 target-set SHA, 원래 owner·preset·policy pin은 유지한다.
  새 DB migration·새 queue·계정/인증 변경·운영 DB pytest는 없었다.
- GPU INDEX는 기존 b3c8a4c0의 PID2113256 /
  `8b9b5ed1ec1a4c67bc9ec7c44f9debff`, QUERY는 기존 07ec7b32의 PID1708497 /
  `9c60629b423547fc832a91b7e9f180e3`다. 보호된 공유 설정 9개 hash가 기존 기준선과
  같고 INDEX runtime/owner JSON도 해당 release 기록과 byte-identical이다. 이후 최종
  12개 hash 관측 역시 중간 관측과 동일했다. GPU 실행을 중단하거나 pin을 교체하지 않았다.
- API READY 및 기존 30분 creative/embedding observer timer가 활성 상태다. 관측 timer는
  상태를 읽을 뿐 자동 retry·등록·Slack 전송을 수행하지 않는다.

### 증거와 의도적으로 남겨 둔 별도 범위

- `/tmp/eom-creative-recovery-five-acceptance-20261030.json`: 다섯 건의 정본 포인터·hash,
  원문/공개 풀이/주의사항의 공식 조회 대조, 10개 Job과 lease, 기존 source 참조 보존.
- `/tmp/eom-creative-five-graph-preservation-reviewed-20261030.json`: 원래 54개를 포함한
  재개 전 전체 Graph 노드·edge identity의 보존. bounded read-only DB 조회다.
- `/tmp/eom-creative-10369-recovery-replay-0303.log`: 기존 recovery selection의 실제 멱등 재전송.
- `/tmp/eom-creative-goal-final-gpu-pins-20261030.json`: hash-only GPU 설정 확인.

위 파일은 작은 개발 검증 read model이며 정본을 대체하지 않는다. 실제 Worker 결과·Item·
accepted 분석·Graph는 이미 등록된 immutable Artifact/pointer에서 재구성할 수 있다.

운영 복구와 추가 5건 검증은 **기존 설치본의 supported recovery/정상 처리 경로**로
성공했다. 생성 지침을 보강한 `c6dabde8`는 소스·wheel 검증 후보로 보존했으나 이번
목표에서 공유 API/Runner에 배포하지 않았다. 이를 재발 방지 지침의 live 활성화로
보고하지 않는다. 기존 공개 풀이 임베딩 successor/production migration 0063도
이번 목표와 별도 미활성 범위로 유지한다. 목표를 전체 1053건 완료나 교육 품질,
새 embedding/query family의 성공으로 확대하지 않는다.
