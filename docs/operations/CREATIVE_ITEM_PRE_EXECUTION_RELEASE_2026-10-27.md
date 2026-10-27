# 창작 문항 슬롯 실행 전 준비 릴리스

확인 시각: 2026-10-27 21:02 UTC.

사용자가 이번 목표의 종료선을 **실제 Codex 풀이보고서 작성 직전까지의 준비**로 변경했다.
주간 한도를 추론으로 재검사하지 않는다. 모델 호출, START, 풀이보고서 수락과 Graph 게시를
이번 준비 릴리스의 성공으로 가장하지 않는다.

## 설치 및 무실행 검증

| 경계 | 확인 결과 |
| --- | --- |
| 소스 | `85ed2c93` 준비 application/CLI, `03caebae631e936261012b41926baa5d9e38f8fe` 설치본 검사 보강; 모두 main에 push |
| 설치 platform/API | `03caebae631e936261012b41926baa5d9e38f8fe`, tree `2606add55adac675d334bb4948b94beaef25bbed` |
| 기존 Web | `590625b2e2d17109840601a34e22be4598d56c58` 유지; 이번에 재배포하지 않음 |
| DB migration | 기존 `20261027_0062` 확인, 새 migration 없음 |
| source 검증 | focused unit 168 PASS, 배포/API 계약 54 PASS, 변경 source 9개 mypy·Ruff/format PASS |
| disposable DB | migration 왕복 및 외부 문항/조립/준비 검사 17 PASS, 공식 cleanup 완료 |
| wheel | platform/API/계약 3개 RECORD, 비편집 설치 simulation, 창작 definition admission·role/result schema·PREPARE-only CLI 검사 PASS |
| 운영 설치 | protected source/wheel admission, migration verify, API/Catalog/HWPX 역할 reconcile, API isolation, 설치 metadata PASS |
| HTTPS | `/studio/api/v1/health/ready`: READY / Application API ACTIVE |
| rollback | `/var/lib/eom-api/deployments/03caebae631e936261012b41926baa5d9e38f8fe.json` |
| GPU INDEX | PID 734655, active/running, 시작 시각 2026-10-26 00:32:30 UTC 유지; 변경·재시작 0 |

빌드 전용 wheel은
`/tmp/eom-api-build/03caebae631e936261012b41926baa5d9e38f8fe.mpJLsw/dist`,
실제 설치 실행의 wheel은
`/tmp/eom-api-build/03caebae631e936261012b41926baa5d9e38f8fe.QnOsDI/dist`다.
동일 커밋이라도 각 실제 설치 인자는 기존 배포 스크립트의 inspection identity로 확인한다.
보호 context는 `/var/lib/eom-release-operator-stage.6b3cb636-vnfvza4c`이며
context SHA는 `sha256:baa9fa9473892d9b4f855940993971306b58c278fe88b703cdb4ee081b8be80b`다.
폴더 접두사 `6b3cb636`은 기존 staging 절차의 이름일 뿐, 실제 source identity는 context의
위 `03caebae…` commit/tree/archive hash다.

첫 `85ed2c93` build는 새 Workflow가 설치 검증 목록에 빠져 admission 비교에서 실패했다.
운영 적용 없이 `03caebae`에서 목록·회귀 검사를 보강하고 새 build가 통과했다.
첫 install 시도는 이전 커밋의 protected context가 남아 source mismatch로 거부됐다.
기존 상태를 우회하지 않고 새 exact context를 ADMIT한 뒤 정상 설치했다. 실패 기록은 보존한다.

## 원본 등록 재대조

새 설치본의 공식 `ExternalItemImportAuditService.verify`로 NAS의 정본 엑셀과 저장된
관찰값·검색 facet·교정본 포인터를 다시 대조했다. source-only 등록이며 정본 Item 수가 아니다.

- import: `extimport_d2019be75aa943636bfa8b7fb7f4a92e`.
- workbook SHA: `sha256:2e04e7c0b6b3d507a846bb0a25b75e3313110595d8f399806fcbc087ad4be8fe`.
- 원본 A:AF 관찰값 1,297행, 1/2/3교 연결 관찰 3,042개, 선택된 최종 파일 1,053건.
- MATCHED 1,042, 내용이 HWPX인 `.hwp` 1, 같은 바이트의 중복 위치 10.
- 초안 225, 반려 5, 파일 없음 6, 이름 불일치 7, 미지원 링크 1.
- 연결 예외 14건의 검수표:
  `staging/item-db-import-20261027/connection-exceptions.md`.

## 실제 원본 준비 gate

운영의 지원된 Catalog target projection으로 U `10310`의 정확한 3교 selection을 조회했다.
source revision은 `extitemrev_5dfa745e71d74a15aa69b2928f81fca6`,
관찰 SHA는 `sha256:1320fc1fc17aeaa15146b4dbc86445a4d6615c8599af2dc2bde3b6fb725a264a`다.
기존 released 분석 policy의 candidate는 `gpt-5.6-terra / xhigh`였으며 availability는
재검사하지 않았다. 기존 fixed-host support slot05·상한 1만 사용하고 새 capacity를 만들지 않는다.

검토된 definition·fallback prompt와 두 instruction 파일을 새로운 exact 대상에만 설치했다.
전체 runner 설정 설치를 재실행하거나 human actors·capability policy·기존 슬롯 인증을 바꾸지 않았다.
명령은 `eomctl content external-items learning prepare`이며 `--start` 옵션이 없다.
설치된 API build source와 runtime commit, root 보호 입력 파일, 실제 Studio 인증을 먼저 검사한다.
현재 operator/session/권한을 재확인하고 원본→페이지 Artifact→control→Workflow/plan/READY→
임시 staging까지 검사한다. 정상/실패 종료 시 자신이 만든 검증 session만 로그아웃한다.

현재 **REAL_SOURCE_PREPARE=PENDING_AUTHENTICATION**이다. tmux `EOM`의 6번
`item-db-ready`에 실제 `guiadmin` 숨김 입력을 띄웠다. 비밀번호·token은 인자/파일/로그에
저장하지 않는다. 이 gate가 끝나기 전에는 전체 목표 완료를 선언하지 않는다.

## 유지하는 한계

- 실제 Codex 호출·추출/풀이 결과·정본 Item 승격·Graph 게시·임베딩 추가는 실행하지 않았다.
- DB 조립의 선택/순서 저장·재열기는 실사용 확인됐지만 원본 HWP의 편집 가능한 합본은
  변환 중 그림 소실 때문에 미지원이다. 페이지 그림으로 대체하거나 성공 파일을 꾸미지 않는다.
- 위 준비/자동 검증은 한글 편집 품질, 교육적 품질 또는 계정 주간 quota의 PASS가 아니다.
- 상세 경계와 후속 계약은
  [창작 문항 풀이보고서·Graph 설계](../architecture/CREATED_ITEM_GRAPH_AND_SOLUTION_REPORT_SUCCESSOR.md),
  기존 GUI·합본 조사 결과는 [DB 조립 릴리스](ITEM_DB_CURATED_ASSEMBLY_RELEASE_2026-10-27.md)를 따른다.
