# Prelaunch AI Item 정리: 소유자 운영 경계

이 명령은 `AI_PRELAUNCH_20261028` 승인 집합 110 Item/111 Revision에만 적용한다. 일반 문항 삭제 API가 아니며, 임의 문항·기출·교과서·창작 자료를 전달할 수 없다. 일반 삭제는 기존 Registry lifecycle/retirement 경계와 별도 사용자 화면으로 다룬다. 과거 Graph·시험지·근거를 함께 물리 삭제하는 일을 평소 삭제 버튼에 연결하지 않는다.

## 설치와 사전 조건

- source commit을 고정해 만든 non-editable `eom-platform` wheel과 표준 RECORD를 검증한다.
- 기존 실행환경을 덮어쓰지 않고 root 소유 `/opt/eom/maintenance-releases/<commit>/site-packages`에 설치한다.
- 실제 local `eom` 운영자만 실행할 수 있다. 요청 JSON의 권한·DB 주소·환경의 `EOM_DATABASE_URL`은 관리 권한이 아니다. 고정된 root 소유 PostgreSQL owner 설정을 사용하고, 각 adapter가 실제 DB owner 권한을 확인한다.
- INDEX/QUERY·Workflow/maintenance·Catalog/HWPX runner·chat owner의 진행 작업을 확인하고 정상 정지한다. Codex 인증·worker 설정·모델·GPU runtime pin을 바꾸지 않는다. 실제 native 실행이 남아 있으면 명령은 거부된다.
- 서비스 정지 후 공식 PostgreSQL 백업과 manifest를 새로 만든다. 백업 bytes/hash/대상 DB와 2시간 이내 생성 여부를 확인한다.

## 공식 인터페이스

설치된 관리 wheel의 `eomctl prelaunch-reset`을 사용한다. CWD/Git 소스를 runtime으로 import하지 않는다.

```text
prelaunch-reset plan --backup-manifest <공식 backup manifest> --output <새 local plan.json>
prelaunch-reset apply --plan-file <그 plan.json> --expected-plan-sha256 <plan_sha256>
```

`plan`은 JSON Schema/Pydantic frozen plan을 만들고, Orchestrator가 NAS에 정본 계획을 커밋한다. local 파일은 실행 입력 사본이다. `apply`는 게시된 정본 계획의 hash, 실제 owner/서비스 정지, source revision/Graph hash, 전체 대상과 보호 metadata fingerprint를 재확인한다.

## 책임과 원자성

- Orchestrator application: root transaction, 동시 운영 잠금, 계획 재검증, 보호 fingerprint, Artifact/Job/분석·lease 정리, NAS 계획/영수증 커밋.
- Catalog application: Item/Revision/metadata, Graph·검색·index·전용 Assembly·자료 검토 관계. 이미 API가 소유한 upload intent가 발견되면 자동 삭제하지 않고 중단.
- Workflow application: 승인 범위의 실행 계획/명령/step/event 관계.
- HWPX application: 승인 범위의 single/whole-exam build 관계.

각 소유자는 자신의 명명된 불변 트리거만 transaction 안에서 해제·복구한다. FK/unique 제약이나 모든 트리거를 일괄 해제하지 않는다. 성능 보조 인덱스 두 개도 같은 transaction 안에서 생성하고 제거한다. 실패/중단 시 데이터·트리거·보조 인덱스가 함께 rollback된다. DB migration head는 변경하지 않는다.

공유 producer metadata는 생존 FK/JSON 참조와 의존 관계의 전이 폐쇄로 보존한다. NAS 기존 파일을 unlink/이동/덮어쓰지 않는다. 원래 FAILED/RUNNING 기록을 성공으로 바꾸지 않으며, 승인된 과거 기록만 삭제한다.

## 완료와 복구

- 삭제 대상 110개, 원래 revision 111개, 구 Graph 68/69와 관련 실행이 없어야 한다.
- 기출 520 source·교과서 10 source, 외부 source 1,297개, legacy Item 757개와 보존 샘플 1개를 확인한다. 다른 문항/교과서/창작 metadata·벡터 encoding·비대상 HWPX의 fingerprint는 변경되면 안 된다.
- Orchestrator가 완료 영수증을 NAS에 커밋한다. 같은 계획 재전송은 기존 영수증을 읽으며 새 삭제나 새 실행을 만들지 않는다.
- DB commit 뒤 영수증 커밋 전에 중단된 경우에도 같은 계획의 정확한 사후 조건을 검사해 영수증만 복구한다. 다른 계획/latest로 대체하지 않는다.
- 원래 active였던 서비스만 다시 시작하고 Graph 67의 새 검색 index 준비 및 API/GUI·보존 샘플 읽기를 확인한다. 구 index revision을 새 Graph로 재해석하지 않는다.
- 검증 실패 시 추가 side effect를 멈추고 실제 DB/영수증 상태를 먼저 조사한다. transaction 안의 실패는 rollback, commit 이후 복구는 승인된 백업/같은 계획의 복구 경계로 수행한다.

## 검증 증거

`tests/integration/test_prelaunch_item_reset_application.py`는 disposable marker가 있는 복원 DB에서만 실행한다. 계획 변경 차단, component owner 경계, 동시 write 차단, 중단 rollback, 실제 정리와 동일 계획 재전송을 포함한다. `EOM_PRELAUNCH_RESET_TEST_STATE`를 설정하지 않으면 실행하지 않는다. 운영 DB를 pytest 대상으로 사용하지 않는다.

## 2026-10-28 운영 실행 결과

정리와 동일 계획 재전송을 완료했다. 실행한 설치본 source는 `3a8692641d917f0285b1773bf029588ee9b04b57`이며 API/Web/INDEX/QUERY pin을 교체하는 배포가 아니다. 영구 migration이나 DB privilege 변경도 없다.

- 삭제: Item 110개, Item Revision 111개, 승인된 과거 workflow 921개, 전용 producer Job 918개.
- 보존: AI 샘플 1개와 기존 HWPX, 기출 source 520개, 교과서 source 10개, 외부 원천 source 1,297개, legacy Item 757개, 공유 producer Job 1,216개.
- 기존 NAS 파일 삭제 0개. 적용 직전 PostgreSQL 백업·manifest와 정본 계획/완료 영수증을 보존했다.
- 동일 계획 재전송은 기존 영수증을 반환했으며 추가 삭제/Job/Artifact를 만들지 않았다.
- 서비스 7개 재개, HTTPS/API readiness 및 보존 샘플 내용·HWPX secure read/hash 확인 완료. Graph 67 `CONTENT_ONLY` current index는 520/520이며 다른 view/device의 준비는 기존 owner에서 계속한다.
- disposable DB 동시성/중단/재전송 검사 6개 PASS 후 해당 DB·전용 role·local state만 공식 cleanup으로 제거했다.

계획·영수증의 immutable ID/hash, 백업 경로와 조사 이력은 [실행 기록](../architecture/AI_ITEM_PURGE_BOUNDARY_2026-10-28.md#현재-판정-운영-적용-완료)에 있다. 이미 완료한 계획을 새 승인처럼 재생성하거나, 이 고정 범위 명령을 일반 문항 삭제 API로 재사용하지 않는다.
