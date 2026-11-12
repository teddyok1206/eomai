# 기존 구조 정비 검증 — 2026-11-12

상태: **소스 구현·검증 완료, 운영 미배포**. 출발 commit `13f95be8`.
계획: [S1–S5 설계](../architecture/MAINTENANCE_CONSOLIDATION_2026-11-12.md).
이 기록은 새로운 운영 배포·학습·문항 생성 승인이나 실제 서비스 복구 결과가 아니다.

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

## 보존 및 남은 운영 경계

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
