# 설계 오류 경계 수정 릴리스

설계 기준과 수정 대상: [전체 검토·구현 판정](../architecture/DESIGN_ERROR_REMEDIATION_REVIEW_2026-11-08.md).
사용자 승인 범위는 R01–R05 수정·검증·호환 운영 배포다. 추측성 Q 항목을 이유로 기능이나
새 프레임워크를 추가하지 않는다.

최종 운영 확인: **2026-11-08 18:01 UTC, R01–R05 반영 완료**.
runtime source는 `b9007cbd`이며 후속 test/doc commit을 위해 이미 확인한 운영 패키지를
다시 빌드·재시작하지 않는다. 아래 17:08 표는 당시의 인계 중간 기록이다.

## 고정 후보와 검증

- source commit: `b9007cbd6b3d70fa8b53190f2fa0e1fc552a4ae9`, main에 커밋·push 완료.
- API contracts wheel SHA-256:
  `67fb91526c39e4603c8b8cc4c6adbf2327d35279362953101a1799492fdc3a64`.
- API wheel SHA-256:
  `61f71755e900a47272c71717dc582cb21b5a2d4257641ff50b84b2571b358860`.
- platform wheel SHA-256:
  `61d7a077fb8b6a570052d74c7dac23f2516757304d836b27f7fe6507a087d248`.
- focused source 158 PASS; 문맥 index 13 PASS; Ruff·focused mypy PASS.
- disposable PostgreSQL: migration 왕복·role PASS, Graph 10, 검색 6,
  INDEX 258, HWPX 30 PASS. 별도 Builder E2E 1건 opt-in SKIP: renderer 미변경.
- wheel RECORD·별도 설치 Runner/HWPX fresh-process FK 해석 PASS.

## 17:08 UTC까지의 운영 반영

| 구성 요소 | 상태 |
| --- | --- |
| API/platform/Catalog/HWPX Manager/일반 Runner | `b9007cbd` 호환 설치 완료 |
| Web | 기존 `9810efd6` 유지; 화면 파일 변경 없음 |
| QUERY | 기존 `c915281e` owner 유지; API provider wheel/code-member·관련 wrapper pin 갱신 |
| creative owner | `6272329a` → `b9007cbd`, 원 cohort·환경·worker 설정 유지 |
| INDEX | 기존 `1083b89f` 실행 보존; 새 `b9007cbd` 준비 및 인계 진행 중 |
| numerical CPU/CUDA·모델·vector space | 변경 없음 |
| DB head | `20261105_0074` 유지, migration 없음 |

기존 creative producer에 SIGINT drain을 먼저 요청했고 exit 0·유효 worker/command 0을
확인한 뒤 공유 패키지를 교체했다. SIGKILL·진행 중 worker 취소·DB row 수동 수정은 없다.
공유 배포 전후 INDEX PID `774682`와 invocation
`bae83e900f544d4e99976b8a54f7cc41`, 자료 학습 PID/invocation과 보호 설정은 동일했다.
QUERY 재시작은 새로운 provider pin을 검증하고 listener가 준비된 뒤 Web을 다시 열었다.

creative 전용 설치본도 별도 graceful drain·exit 0 후 교체하고 원래 cohort를 재개했다.
systemd timeout은 새 template과 동일한 1,800초이며 close 이전 fence 해제는 없다.
현재 조회된 원본 보류 목록은 기존 source 입력 문제다. 재시작 직후 traversal count 0을
DB의 Graph 등록 총수 0으로 해석하지 않는다.

## 실제 운영 검사

- 설치된 API의 기존 Graph 조회에서 승인 문항 3개를 선택하고, canonical analysis source로
  새 exact-navigation 경계를 두 번 읽었다. revision과 요청 순서 동일, 새 검색·모델 요청 0.
- 해당 **문항 navigation만** 0.008초 / 0.007초. 전체 ranking 조회·GUI end-to-end 속도가 아니다.
- 후속 전후 비교(17:36 UTC): 원 기준 메서드와 설치된 메서드의 결과·순서·SQL statement
  동일, 요청당 SQL 7회. 전 8.8/7.0ms, 후 7.1/7.0ms. 새 N+1 조회 없음.
- 실제 API mount/UID 격리 16개 allowed/denied probe PASS.
- 실제 HTTPS 로그인 페이지 200, Web readiness 200, 비인증 session 조회 401.
- installed pip dependency check PASS.
- 사용자 인증 브라우저 재검토는 이번 배포에서 실행하지 않았다. 이전 GUI 성공을 새
  브라우저 검증으로 재사용하지 않는다. 운영 검사 중 비밀번호·세션 캡처 없음.

보호된 설치·rollback·원본 설정·검증 기록:
`/var/lib/eom-architecture-release-20261108`.
현재 INDEX 인계 기록: `/var/lib/eom-architecture-index-release-20261108`.
전체 goal은 INDEX 수정본 활성화·재개 검증과 최종 증거 보관까지 완료해야 닫는다.

## 완료 기준 재검토

`03dda7e8`은 production 변경 없는 보강 테스트 commit이다. Graph Artifact 작성 전·후,
DB commit 직전·직후 interruption과 동일 요청 복구를 추가해 disposable suite 14개가
통과했다. 최초 fixture/harness 오류와 후속 PASS를 구분해 로그를 보존한다.
두 disposable DB 모두 공식 cleanup으로 제거했고 운영 DB에 pytest를 실행하지 않았다.

## INDEX 최종 인계

- 기존 CPU `workflow_e576f6b4969744dda41998a9e4b8aa27`, CUDA
  `workflow_53b8d14c380d468f85f7788c558303c7` 모두 `COMPLETED`와 실패 코드 없음 확인.
  원 owner는 17:57:52 UTC 정상 종료했고 SIGKILL/진행 계산 취소는 없었다.
- 첫 활성화 점검은 **정상적으로 거부**됐다. 완료 중인 CUDA가 CPU standby 요청 1건을
  17:57:46에 추가했기 때문이다. 서비스 exit 0만으로 queue가 비었다고 간주하지 않았다.
- 해당 `workflow_bf4c03afda134859a0e80ffc74b3c33e`만 기존 공식
  `cancel_unstarted_indexing_workflow`로 취소했다. REQUESTED/PENDING, attempts=0,
  lease·step 없음, 정확한 request/service hash를 확인하고 동일 취소 replay도 통과했다.
  `late-standby-cancelled.json`에 receipt와 원래 두 요청의 성공을 보존했다.
  새 queue·새 retry 정책·수동 DB UPDATE를 도입하지 않았다.
- 같은 준비 계획으로 활성화를 이어갔고 18:01:30 UTC 새 owner가 verifier를 통과해
  `LOCAL_INDEXING_SERVICE_STARTED`, `LOCAL_INDEXING_CPU_OVERLAP_ENABLED`,
  `LOCAL_INDEXING_RECONCILIATION_STARTED`를 기록했다. PID `931727`, invocation
  `38e2a423497849dd88f010dacc8ff383`.
- 설치 파일과 등록된 ACTIVE identity가 `b9007cbd`로 일치한다. 이전 service의 미완료
  workflow 0, CPU/GPU 환경 bytes·모델/space/runtime profile·routing·controller 동일.
- API/Web/Catalog/QUERY/creative/material 서비스 active. INDEX 교체 중 API/Web/QUERY/
  material invocation은 유지됐고 기존 10분 관측 timer도 active다.
- 새 owner의 source 준비 재개까지 확인한 것이며, 새로운 전체 INDEX iteration 완료나
  GPU 모델 계산을 이미 완료했다는 뜻은 아니다. corpus 배경 처리는 계속한다.

최종 근거는 보호된 root의 `verified.json`, `resumed.json`,
`late-standby-cancelled.json`, 공유 root의 `navigation-comparison.json`이다.
첫 활성화 거부와 fixture/harness 실패 로그도 최종 감사 산출물에 포함한다.

## 최종 감사 보관

기존 Catalog → Orchestrator Artifact commit 경계로 선택한 기록 37개를 NAS에 보관하고
모든 member의 SHA-256·내용 재읽기를 확인했다. 비밀번호·인증·환경 파일과 rollback
설정 원문은 이 감사 묶음에 넣지 않았다.

- Artifact: `artifact_a7e49d9d400c4b6384a7d86511cdd5e7`
- Revision: `rev_6ecef40c934545229b97f1ce5e372282`
- primary `note.md` SHA-256:
  `7aa91cb9106afc49d46f2e83a0184344b86b3fbef3a4f2b2dfe34baf73477d26`
- 위 primary는 이 감사 포인터 절을 덧붙이기 전의 완료 기록 snapshot이다.

판정: **구조 수정·검증·운영 반영 완료**. Q01–Q05의 명시된 후속 한계, 기존 source 보류,
corpus 전체 배경 처리, 새 브라우저/콘텐츠 품질 평가는 이 완료 판정으로 대신하지 않는다.
