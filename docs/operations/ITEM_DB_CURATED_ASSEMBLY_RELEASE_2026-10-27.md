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

- 최초 `834f81ea` 운영 배포의 사용자 저장 smoke는 `CATALOG_APPLICATION_INTERNAL_ERROR`로 실패했다. 아래 후속 수정/실사용 검증이 이 경계를 닫는다.
- `EXTERNAL_SOURCE_DOCUMENT` placement는 정확한 원본 파일 포인터이지 승인된 `AssessmentItemContent`가 아니다. 저장된 초안을 곧바로 출판 가능한 HWPX나 Graph 근거로 표시하지 않는다.
- 이 서버의 LibreOffice/H2Orestart는 HWP를 읽지만 HWPX export 필터가 없다. 실제 U `12109` HWP→HWPX 시도는 출력이 없었다. [임포트·합본 설계의 변환 게이트](../architecture/NOTION_ITEM_ARCHIVE_IMPORT_PLAN_2026-10-27.md)를 통과하기 전에는 편집 가능한 HWP 원본 합본을 성공 처리하지 않는다.
- 창작 문항의 Codex 구조화 추출·풀이보고서·Graph 게시 슬롯은 아직 비활성 경계다. [후속 계약](../architecture/CREATED_ITEM_GRAPH_AND_SOLUTION_REPORT_SUCCESSOR.md)의 source 재인가/영속 claim/result admission이 필요하며 source-only import 1,297행을 승인 Item으로 재해석하지 않는다.

릴리스 준비용 일회성 `/tmp/eom-source-clean.*`, `/tmp/eom-release-payload.*`, 임시 context 파일은 exact path 확인 후 제거했다. 보호 admission stage와 API rollback record, build-only wheel 결과는 검증·복구 증거로 보존했다. 기존 실패·INDEX 이력은 수정하지 않았다.

## 후속 저장 오류 수정과 실제 사용자 검증

2026-10-27 16:43–16:44 UTC. 사용자 U `10310`·`10318`은 둘 다 정확한 3교 원본 연결과 Artifact/member/hash가 유효했다. 최초 저장 실패의 원인은 Catalog 런타임에 의도적으로 없는 `UPDATE` 권한을 `SELECT ... FOR SHARE`가 요구한 점이다. 읽기 전용 원본·불변 revision 잠금만 제거하고, 권한을 확대하지 않았다. 정확한 source revision과 source 관찰 hash를 pin하며, 중복 저장은 actor/idempotency unique 제약으로 막고, 실제 출력 전 재인가한다.

- 수정 source commit `6b3cb636b3a9e086378378a123f0da69e61b4022` (`fix(item-db): avoid privileged locks for curated draft save`)을 푸시했다. Catalog 경계 29개, 관련 unit/API/Web 49개, Ruff 및 수정 파일 mypy가 통과했다. owner-role disposable 테스트는 런타임 role 권한과 같지 않으므로 이것만으로 live 성공이라 판정하지 않았다.
- 해당 commit의 build-only wheel RECORD 검증, 보호된 `release-operator-context/1.11` source/wheel admission, `MIGRATION_VERIFY_0062`, Catalog/HWPX role reconcile, API isolation 및 설치를 통과했다. 운영 rollback record는 `/var/lib/eom-api/deployments/6b3cb636b3a9e086378378a123f0da69e61b4022.json`이다. API `/api/v1/health/ready=READY`; Catalog/API active다. 격리 GPU INDEX owner의 서비스 시작 시각은 2026-10-26 00:32:30 UTC로 유지되어 이번 설치에서 재시작되지 않았다.
- 사용자는 `데이터 → DB`에서 두 문항의 저장 성공을 보고했고, `다시 열기`를 눌렀다. 서버의 같은 운영 배포에서 `POST /item-db/assemblies` 1회와 뒤이은 목록 `GET`, 저장본 상세 `GET` 요청이 완료됐다. 다시 열기의 결과는 파일 생성이 아니라 상단 `조립 순서 초안`에 두 문항을 저장 순서대로 복원하는 기능임을 안내했고, 사용자는 이후 정상 동작을 확인했다. 따라서 **저장/목록/상세/화면 재열기의 실제 사용자 경로는 확인**됐지만, 이 기록만으로 편집 가능한 HWPX 합본이나 Graph 게시가 완료됐다고 주장하지 않는다.

## U 10310·10318 편집 가능한 합본의 격리 변환 조사

2026-10-27 17:35 UTC. 사용자가 실제 저장한 순서의 두 원본은 ZIP 안에서 확장자와 내용이 모두 **HWP 5.0**이다. 임시 폴더에 두 정확한 ZIP member만 추출해 네트워크·장치·홈 접근이 제한된 일회성 사용자 서비스에서 `hwp` 1.3.1로 조사했다. 원본 Artifact와 운영 DB는 변경하지 않았다.

- 각 원본의 `HWP → HWPX --strict`는 모두 발행 거부됐다. 각각 `control_removed=1`, `metadata_value_removed=2`의 보존 손실이 보고됐다. 두 손실 항목의 의미를 실제 문항 내용과 대조하기 전에는 변환 성공이라고 판정할 수 없다.
- 비엄격 단일 변환 후보와 원본의 추출 본문 텍스트는 두 문항 모두 byte-for-byte 동일했다. 이는 문자 손실이 없다는 제한된 증거일 뿐, 제거된 control이나 화면 배치·그림 보존을 입증하지 않는다.
- 같은 격리 조건에서 LibreOffice로 원본 HWP와 비엄격 HWPX를 각각 PDF/PNG로 렌더링해 직접 대조했다. 두 문항 모두 1페이지로 열리지만 표·텍스트의 위치가 달라졌고, **U 10318의 원본 기출 그림은 변환본에서 보이지 않는다**. LibreOffice 자체의 원본 HWP 배치도 완전하지 않아 Hancom 기준의 정밀 일치 판정은 아니지만, 이미지 소실이라는 명백한 음성 증거가 있으므로 비엄격 변환본의 발행을 차단한다.
- U 10318 후보 ZIP에는 `BinData/image1.bmp`, `image2.bmp`가 실제로 포함되고 section XML에도 두 `binaryItemIDRef`가 있다. 즉 파일 안에 그림 bytes가 아예 없는 문제로 단정할 수 없고, HWP→HWPX의 개체/배치 참조와 독립 renderer 해석을 함께 조사해야 한다. 앞서 확인한 서로 다른 원본 HWPX 병합 시 ID 충돌 문제와도 구분한다.
- 두 원본을 순서대로 합친 **비엄격 조사 후보**는 구조 검증을 통과했지만, `control_removed=2`, `document_metadata_superseded=1`, `gso_object_id_renumbered=6`, `metadata_value_removed=2`가 기록됐다. ZIP/HWPX 구조 유효성은 서식·개체 보존이나 한글 편집 품질의 증거가 아니다. 이 후보는 `/tmp/eom-assembly-10310-10318.K22gDu/merged.nonstrict.hwpx`에만 있고 정식 Artifact로 등록·배포하지 않았다.
- 기존 EOM content-team 시험지 병합기는 서로 다른 원본 문서의 style을 안전하게 재매핑하지 못하면 `content-team cross-style remapping is unsupported`로 중단한다. 따라서 두 원본을 그 병합기에 강제로 넣지 않는다.

현재 결정: 이 저장 초안은 **선택·순서 저장/재열기까지 PASS**, **편집 가능한 HWPX 합본은 아직 미지원**이다. 다음 구현은 원본 HWP 변환 손실의 실제 영향과 binary/style 참조를 독립 검증하고, 허용 가능한 보존 정책과 사람의 한글 육안 확인을 명시한 별도 출력 계약으로 진행한다. 비엄격 후보를 조용히 성공 파일로 제공하거나 페이지 그림으로 대체하지 않는다.
