# 기존 구조 정비 검증 — 2026-11-12

상태: **소스 검증 및 사용자 후속 승인에 따른 운영 배포 완료**.
출발 commit `13f95be8`, 운영 source `a7fc195d607bdca917cce0d48a4897b1db313c9b`.
계획: [S1–S5 설계](../architecture/MAINTENANCE_CONSOLIDATION_2026-11-12.md).
아래 소스 검증 기록과 후속 운영 반영 기록을 구분한다. 이 문서 자체는 새 모델 실행 승인이 아니다.

## 최근 문항 제작 시간

운영 DB의 workflow/step/event를 read-only로 조회했다. 문항 내용·prompt·인증값은 수집하지 않았다.

- Workflow: `workflow_51eb5300e8f14dc7bdddb3846ef8a738`, `COMPLETED`.
- UTC 시작: `2026-11-12T15:56:16.493247Z`; 완료: `2026-11-12T16:16:35.922609Z`.
- 사용자 표시: 한국 시간 11월 13일 00:56:16 → 01:16:35.
- **시작부터 DB 등록 완료까지 20분 19초**. 버튼 클릭 이전 시간·HWPX 제작 시간은 제외한다.

| 단계 | 소요 시간 |
| --- | ---: |
| 출제 | 5분 48초 |
| 1차 검토 | 7분 49초 |
| 추가 심화 검토 | 5분 57초 |
| 등록 | 38초 |

단계별 반올림과 전환 대기 때문에 합계에 소폭 차이가 있다. image 단계는 SKIPPED,
출제 재작성 횟수는 0이다. 첫 검토의 SUPERSEDED는 `REVIEW_ESCALATION_SCHEDULED`에
따른 교체이며 실패로 분류하지 않는다. 이 한 실행으로 전체 평균 속도를 주장하지 않는다.

## 변경 및 확인된 원인

1. **Pack 호환성:** Catalog와 Runner가 동일한 기존 workflow 계층의 유한 집합을 사용한다.
   실제 1.20.17/18/19 Pack과 binding을 검증했다. 미래 버전을 자동 허용하지 않는다.
2. **퇴역 설정과 재시작:** 현재 scope의 두 preset은 ACTIVE이고 모든 핀이 일치했지만,
   과거 세 scope의 preset 여섯 참조가 RETIRED여서 시작이 막혔다. 과거 scope 읽기에만
   RETIRED를 허용한다. 현재 scope는 ACTIVE 필수이며 신규 제출·재시도 권한은 기존 owner가
   계속 검사한다. released revision/hash/capacity/key 검사는 완화하지 않았다.
3. **시작 완료 신호:** creative owner는 scope/fence/pin 초기화 후 systemd에 READY를 보낸다.
   단순한 프로세스 생성 성공과 준비 완료를 구분한다. unit과 wheel을 함께 배포해야 한다.
4. **요청 종류:** Catalog 두 reader 및 Runner의 요청 union 처리 오류 9개를 실제 타입
   검사로 수정했다. material-learning 요청을 item 요청으로 임의 해석하지 않는다.
5. **배포 판정:** 기존 release operator의 네 중복 분기를 하나의 불변 대응표로 정리했다.
   25개 역사적 schema/hash/migration/receipt 의미를 보존했다. 새 framework는 없다.

## 검증

- 연결 회귀: **745 PASS**. 실제 Pack binding, cohort 중단/복구, 병렬 실행,
  release context, 의존 방향, 개발 context navigation을 포함한다.
- disposable PostgreSQL: **22 PASS**. 프리셋 퇴역 후 exact revision 읽기,
  현재 퇴역 설정 거부, 기존 동시성·replay·rollback 검증을 포함한다.
  migration 왕복 후 공식 cleanup 완료. 운영 DB에는 pytest를 실행하지 않았다.
- Ruff lint/format, mypy(변경 경계), `git diff --check`: PASS.
- 새 wheel 설치 후 별도 프로세스 **4개**에서 API/Catalog/Runner/HWPX import,
  SQLAlchemy FK/DDL 및 source 경로 격리를 확인했다. wheel RECORD 검사 PASS.
- 회귀 확인 중 임시 DB restricted-role 준비 누락으로 첫 실행이 1건 실패했다.
  공식 reconcile 후 동일 suite 22개가 통과했다. 실패 이력은 보존했다.
- 임시 wheel 파일이 0664로 생성돼 최초 RECORD identity 검사가 거부했다.
  해당 실험 파일만 0600으로 바꾸고 재검증했다. 운영 권한을 완화하지 않았다.

검증용 wheel SHA-256:
`73aab0db99bd9b24e21a9bf15717067832bdec8a1b88c1ca3fb2725f836028de`.
이 wheel은 작업 트리 설치 시뮬레이션이며 운영용 clean-commit release로 간주하지 않는다.

## 소스 검증 시점의 보존 및 남은 운영 경계

- 팀장 프롬프트, released contract/Pack bytes, 문항·Graph·풀이보고서·임베딩,
  현재 모델 설정, 완료 산출물과 실패 이력을 변경하지 않았다.
- 모델/GPU 신규 실행 0, 새 문항 생성 0, 운영 서비스 재시작 0, 운영 migration 0.
- read-only 진단 시 `eom-creative-learning.service`는 기존 `failed/exit 78` 상태였다.
  **소스 수정으로 실제 서비스를 복구했다고 보고하지 않는다.**
- 후속 운영 반영 시 clean commit으로 공유 platform/API와 해당 pinned owner의 호환성을
  확인하고, creative wheel+notify unit을 함께 적용한다. 다른 실행의 runtime pin을
  임의 변경하거나 과거 실패를 성공으로 고치지 않는다.
- 전체 시스템 무결함·실서비스 PASS·출제 속도 개선을 이번 검증으로 주장하지 않는다.

일시적인 검사 자료는 Git에 넣지 않고 별도 증거로 관리한다. 반복 suite는 중복 합산하지 않는다.

## 후속 승인에 따른 운영 반영 — 2026-11-12 UTC

사용자의 “푸시, 운영 배포” 승인 후 `main`을 GitHub에 푸시하고 clean commit에서
공식 build-only 경로로 세 wheel을 다시 만들었다. 위 작업 트리 검증 wheel을 배포하지 않았다.

| 구성요소 | 운영 선택 |
| --- | --- |
| 공유 platform / API / API contracts / Catalog / Workflow Runner | `a7fc195d607bdca917cce0d48a4897b1db313c9b` |
| creative 등록 owner 및 notify unit | 같은 `a7fc195d`의 설치본·템플릿 |
| Web | 기존 `858680cfaaa3e091b6e98b220e50ccb8d70e3735` 보존 |
| QUERY owner | 기존 `11d826d29587c48a2416fb26825c5748cb737d22` 보존, API provider pin만 호환 갱신 |
| INDEX·GPU 수치 환경 / 자료 학습 | 설치 파일 및 실행 identity 보존 |
| migration | `20261112_0079` 유지, DDL 없음 |

실제 배포 wheel SHA-256:

- platform: `6c4e55b3785445c6fe8c8d8da25aa508f2452fd985e2f02e262aac9a231d6ff2`
- API: `ef649f1f98fa3113d56443996d333f6bc3a5add17dc8fa7206d6bf8e13dc7660`
- API contracts: `bf7bfb5525ea47a84999e143916429513f38cec11b70d7f9cf105c31f72e67bb`

### 실행 경계 및 확인

- 실제 worker lease·실행 command·HWPX·채팅·QUERY/GPU transient work가 모두 없는
  창을 확인한 뒤 기존 owner installer와 typed configuration codec으로 호환 전환했다.
- API/Web의 짧은 중단 후 Catalog/API → 채팅 worker/owner → QUERY → HWPX/Web/Runner
  순서로 복구했다. Web 패키지·모델 선택·슬롯 인증·원본 및 실패 이력은 변경하지 않았다.
- API `READY`, HTTPS 로그인 화면 200, 배포 Web wheel과 정적 파일 5개 bytes 일치,
  익명 관리자 설정 접근 401을 확인했다. 관련 서비스 14개가 active이며 PID가 있다.
- creative owner는 기존 exit 78에서 새 `Type=notify`로 scope/pin 초기화를 통과했다.
  이후 `PROCESSING` 및 기존 등록 대상의 `PUBLISHING` 진행을 관찰했다.
  시작 시점의 `verified_count=0`은 복원 중인 owner의 진행 projection이며 전체 등록 수가 아니다.
- 첫 후속 검사에서 READY 직후의 read model `STARTING`을 잘못 실패로 취급했다.
  이는 서비스 실패가 아니라 검증 스크립트의 판정 오류였다. 실패 로그를 보존하고,
  readiness와 첫 source scan을 구분한 재검사에서 `PROCESSING` 및 전체 checks PASS를 확인했다.
- 별도 로그인·문항 생성·채팅 응답·GPU canary는 요청하지 않았다. 인증된 사용자 화면의
  실제 업무 검증까지 PASS로 확대 해석하지 않는다.

운영 기록: `/var/lib/eom-maintenance-release-20261112/`의 `prepared.json`,
`rollback.json`, `installed.json`, `activated.json`, `postdeploy.json`.
이전 wheel·설정·unit bytes는 복구용으로 보존한다. 자동 rollback이나 과거 실패 재해석은 없다.
배포 operator의 소스 정리 때문에 이전 context/admission 기록을 다시 쓰지 않았고,
이번 무 migration 배포에서는 privileged migration callback을 호출하지 않았다.

별도 기존 장애: `eom-embedding-index-owner.service`는 배포 전부터 failed였으며
이번에도 동일 invocation을 보존했다. 이번 배포로 GPU INDEX가 복구됐다고 주장하지 않는다.
기존 원본 보류 항목도 그대로 남겨 두며, 등록 전체 완료를 이번 배포의 완료 조건으로 삼지 않는다.
