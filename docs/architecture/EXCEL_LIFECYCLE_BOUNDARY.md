# Excel 콘텐츠·판 보관 경계

2026-11-09. 설계 T26의 사용자 보관/복원 경로이며 실제 삭제는 제공하지 않는다.

- 책임/정본: Catalog의 기존 Deliverable/ContentEdition lifecycle 열만 변경한다.
  Form/Assembly/Item/Graph/벡터와 출력·인쇄 기록은 수정하지 않는다.
- identity: 논리 콘텐츠 또는 판의 표시 상태다. 불변 composition revision/hash는 변경하지 않는다.
  Edition CAS는 기존 lock_version, Product CAS는 기존 deliverable_events의 마지막 sequence다.
- 원본: Product 복원은 그 대상의 마지막 보관 event의 prior_state로 돌아간다.
  PLANNED/IN_PRODUCTION/RELEASED를 모두 임의 PLANNED로 바꾸지 않는다.
- 접근 패턴: 대상 PK lookup, owner별 lifecycle 목록, sequence 역순 event 이력이다.
  기존 PK/owner index/event unique sequence를 사용하며 목록은 최대100, 이력은 최근50개다.
  product event version은 correlated indexed MAX, 목록은 단일 bounded SQL이다.
- transaction: Product 공유 잠금 → Edition 편집 잠금의 순서를 기존 편집에도 적용한다.
  서로 다른 판 편집은 Product 공유 잠금으로 병렬이다. 보관/복원은 Product 배타 잠금 뒤
  해당 Edition을 잠근다. 새 판 생성/편집과 보관이 서로 추월하지 않는다.
- 이력: 기존 deliverable_events에 대상·전후 상태·사유를 append한다.
  content_planning_events의 revision-number sequence는 바꾸지 않는다.
  작은 command receipt는 기존 content_planning_command_receipts를 사용한다.
- 실패/재전송: actual actor의 권한을 재검증한다. 같은 key/body는 원래 결과,
  다른 body는 conflict, 다른 expected state/version은 stale이다. 보관은 읽기·현재 사용/인쇄 사용을
  삭제한 것으로 해석하지 않는다. 일반 active 편집 화면에서만 숨기고 보관 목록에서 복원한다.
- 계약: 새 lifecycle action/result 및 기존 private RPC successor만 추가한다.
  기존 출시 JSON Schema bytes와 DB schema는 변경하지 않는다.
- 단순 대안: 행 삭제는 참조/사용 이력을 손상시키며, UI에서만 숨기는 것은 다른 사용자가
  계속 편집하게 만든다. 새 registry/soft-delete framework/queue 대신 기존 상태 열을 사용한다.
