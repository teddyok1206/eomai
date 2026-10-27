# DB 혼합 문항 조립 초안 운영 릴리스

확인 시각: 2026-10-27 15:57 UTC. 이 기록은 조립 **선택·순서 저장/재열기**의 기술 릴리스다. 편집 가능한 합본 HWPX 생성이나 원본 전용 문항의 정본 Item/Graph 승격 완료를 뜻하지 않는다.

## 고정 릴리스와 검증

- Source/API/Web commit: `834f81ea290c59f2319031b6fb501ba30a912622`; Git tree: `fe70aebb04b1f55b835c580c685337f032324f88`.
- 운영 DB: `20261027_0060 → 0061 → 0062`를 각 exact protected callback으로 순서대로 적용하고, read-only 조회에서 `production_migration_head=20261027_0062` 확인.
- `0062` 보호 release admission: `ADMIT_PASS`. 설치 전 build-only API wheel RECORD·Web installed simulation PASS. `scripts/api/deploy_release.sh --install`의 PDF runtime, mock-exam admission, migration verify, 역할 reconcile, API isolation, 설치 메타데이터가 PASS.
- API rollback record: `/var/lib/eom-api/deployments/834f81ea290c59f2319031b6fb501ba30a912622.json`. Web wheel SHA-256: `fa71bff47da3fdfbc4ee00e8472129f27bc28231f9a2483be0ec6f54d7ad449b`; 설치 Web build-info source commit이 동일함.
- 설치 후 `scripts/api/deploy_release.sh --verify` PASS, API `/api/v1/health/ready=READY`, HTTPS `/studio/`는 비로그인 사용자에게 정상 로그인 리다이렉트 `303`. API/Catalog/workflow runner/HWPX/Web 및 격리된 embedding INDEX/QUERY 서비스 모두 active.
- Disposable PostgreSQL `0062` upgrade→downgrade→upgrade 및 external-item 저장/검색/게시 통합 테스트 9개 PASS, 테스트 DB 제거. source의 관련 focused tests 332개 PASS는 이전 커밋 `ecc7ba50`에서 기록된 범위이고, 뒤의 두 커밋은 HWP 변환 조사 문서만 변경했다.

## 남은 확인과 기능 경계

- 인증된 사용자 화면에서 `데이터 → DB`의 새 조립 초안 저장→목록→재열기는 아직 live 수동 smoke 기록이 없다. HTTPS 비로그인 상태와 소스/격리 DB PASS를 그 증거로 확대하지 않는다.
- `EXTERNAL_SOURCE_DOCUMENT` placement는 정확한 원본 파일 포인터이지 승인된 `AssessmentItemContent`가 아니다. 저장된 초안을 곧바로 출판 가능한 HWPX나 Graph 근거로 표시하지 않는다.
- 이 서버의 LibreOffice/H2Orestart는 HWP를 읽지만 HWPX export 필터가 없다. 실제 U `12109` HWP→HWPX 시도는 출력이 없었다. [임포트·합본 설계의 변환 게이트](../architecture/NOTION_ITEM_ARCHIVE_IMPORT_PLAN_2026-10-27.md)를 통과하기 전에는 편집 가능한 HWP 원본 합본을 성공 처리하지 않는다.
- 창작 문항의 Codex 구조화 추출·풀이보고서·Graph 게시 슬롯은 아직 비활성 경계다. [후속 계약](../architecture/CREATED_ITEM_GRAPH_AND_SOLUTION_REPORT_SUCCESSOR.md)의 source 재인가/영속 claim/result admission이 필요하며 source-only import 1,297행을 승인 Item으로 재해석하지 않는다.

릴리스 준비용 일회성 `/tmp/eom-source-clean.*`, `/tmp/eom-release-payload.*`, 임시 context 파일은 exact path 확인 후 제거했다. 보호 admission stage와 API rollback record, build-only wheel 결과는 검증·복구 증거로 보존했다. 기존 실패·INDEX 이력은 수정하지 않았다.
