# 설계 오류 경계 수정 릴리스

설계 기준과 수정 대상: [전체 검토·구현 판정](../architecture/DESIGN_ERROR_REMEDIATION_REVIEW_2026-11-08.md).
사용자 승인 범위는 R01–R05 수정·검증·호환 운영 배포다. 추측성 Q 항목을 이유로 기능이나
새 프레임워크를 추가하지 않는다.

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
- 실제 API mount/UID 격리 16개 allowed/denied probe PASS.
- 실제 HTTPS 로그인 페이지 200, Web readiness 200, 비인증 session 조회 401.
- installed pip dependency check PASS.
- 사용자 인증 브라우저 재검토는 이번 배포에서 실행하지 않았다. 이전 GUI 성공을 새
  브라우저 검증으로 재사용하지 않는다. 운영 검사 중 비밀번호·세션 캡처 없음.

보호된 설치·rollback·원본 설정·검증 기록:
`/var/lib/eom-architecture-release-20261108`.
현재 INDEX 인계 기록: `/var/lib/eom-architecture-index-release-20261108`.
전체 goal은 INDEX 수정본 활성화·재개 검증과 최종 증거 보관까지 완료해야 닫는다.
