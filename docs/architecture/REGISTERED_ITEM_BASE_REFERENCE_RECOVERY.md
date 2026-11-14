# Registered Item 기초 분석 근거 검증과 복구

상태: 승인 전 검증과 내부 후속 복구 구현 후보. 운영 활성 여부는 별도 릴리스 증거로 확인한다.

## 책임과 불변식

1. **경계**: Catalog KnowledgeAnalysis application이 등록 Item 기초 분석의 승인 전에
   source JSON pointer와 발췌 해시를 검증한다. Worker가 쓴 해시를 원본 Artifact의 무결성
   해시와 혼동하지 않는다. 원본/권한/Artifact/receipt 오류를 모델 데이터 오류로 숨기지 않는다.
2. **정본**: 승인된 Item JSON, 원본 proposal members/receipt와 accepted-result는 그대로
   보존한다. 모델이 제출한 잘못된 digest를 고쳐 쓴 뒤 과거 승인을 유효하다고 주장하지 않는다.
3. **식별자**: 기존 Item/ItemRevision은 재사용한다. 복구 분석과 Material run/task는 새 ID와
   predecessor 연결을 갖는다. 기존 task의 non-null analysis pin은 DB에서 불변이다.
4. **포인터 검증**: 실제 actor의 source 권한, exact Item Revision/Artifact/hash/schema,
   receipt/member hashes, preset/risk policy revision/hash를 다시 확인한다. JSON pointer의
   존재·비어 있지 않은 값·canonical JSON SHA·문제/해설 역할을 동일 owner 규칙으로 검증한다.
5. **접근 패턴**: 분석 ID/멱등 키 조회, revision→run/task 잠금, bounded predecessor 순회와
   source anchor 순회다. 대형 본문을 DB나 event에 복제하지 않는다.
6. **구조와 인덱스**: 기존 PK, analysis idempotency UNIQUE, task/run predecessor FK,
   revision/attempt UNIQUE와 append-only event를 재사용한다. 별도 queue/table은 만들지 않는다.
7. **비용**: source 한 번 materialize 후 anchor 수×bounded pointer depth에 선형이다.
   현재 한 문항 크기와 기존 계약 상한을 따른다. 기출/문서 분석의 다른 family는 바꾸지 않는다.
8. **동시성**: 승인 전 오류로 실패 전이할 때 해당 분석 row를 잠그고 읽었던 version/pins와
   상태를 재확인한다. 복구는 기존 revision→run 잠금 순서와 멱등 키를 사용한다.
9. **의존 방향**: application은 기존 Artifact reader와 pure reference-index owner를 호출한다.
   계약/domain은 DB/NAS/worker adapter를 참조하지 않는다. HTTP/신규 worker protocol은 없다.
10. **실패/재실행**: 잘못된 locator/빈 target/excerpt digest/근거 역할은 typed 데이터 오류다.
    새 분석은 ACCEPTED 전에 실제 FAILED가 되며 기존 실패 retry가 처리한다. 이미 승인된
    잘못된 분석 때문에 공개 풀이 생성이 막히면 기존 Material claim fence로 해당 task만 FAILED로
    남긴다. 다른 task는 계속 진행한다. 승인/실패 이력은 성공으로 덮지 않는다.
11. **더 단순한 대안**: 해시·개념 역할을 완화하거나 기존 task pin/accepted proposal을 덮는
    방법은 근거와 이력을 손상시킨다. 유효 anchor 부분집합도 필요한 개념 역할이 남지 않으면
    복구로 사용할 수 없다. 이 경우 같은 Item의 기초 분석만 명시적으로 다시 만든다.

## 승인된 invalid base의 명시적 후속 복구

- 먼저 기존 Material run이 정상 terminal에 도달하도록 한다. 특정 reference-data 오류만
  해당 task의 실제 FAILED로 기록하며, 성공/진행 이력이나 원본 입력을 변경하지 않는다.
- 이후 기존 linked Material successor의 새 task에 정확한 extraction input/output과 Item을
  상속한다. 재추출·Registry 재등록·성공한 보고서/Graph 재생성을 하지 않는다.
- visual 실패 task와 base-reference 실패 task의 복구 근거는 구분한다. 전자는 검증된
  Prepared3와 해당 native scope, 후자는 exact accepted base/receipt/source/preset/risk pins와
  owner가 재현한 reference-data 실패를 요구한다. 단순 boolean으로 승인 범위를 넓히지 않는다.
- accepted-base 복구에만 쓰는 내부 typed command/application entrypoint를 둔다. 기존 일반
  retry의 ACCEPTED predecessor 거절은 유지한다. 새 분석은 기존 request2/proposal1/workflow를
  사용하고 predecessor를 원래 accepted base에 핀하며, 복구 이유를 기존 event에 남긴다.
- 새 task가 새 분석을 소유하도록 `_create`의 기존 생성·enqueue transaction 경계를 재사용한다.
  원래 task의 analysis pin을 바꾸거나 implicit latest/effective 분석을 몰래 선택하지 않는다.
- `recover_native_material_references`가 만드는 run의 sequence-1 event는
  `MATERIAL_NATIVE_REFERENCE_RETRY_STARTED`다. `CreateMaterialBaseRecoveryCommand`와
  `validate_material_base_recovery`는 이 범위의 새 task에만 기존 `_create`를 열고, 같은
  transaction에서 새 analysis pin을 최초 설정한다. `_pin_analysis`의 accepted 상속 규칙은
  완화하지 않는다. 일반 retry의 event만으로 accepted-base 복구 권한을 얻지 못한다.
- source/accepted-result/receipt/preset/risk 중 하나라도 달라지거나 public solution/Graph가
  이미 연결됐거나 live workflow/lease가 있으면 복구를 거절한다. 동일 command는 같은 새
  run/task/analysis로 재조회되며, 다른 복구와 동시 실행은 revision lock/UNIQUE로 하나만 허용한다.
  새 분석이 이미 해당 task에 핀된 재조회는 새 task의 완료/공개 풀이/Graph 상태 때문에
  거절하지 않되, 실제 actor와 원 source/accepted predecessor 및 정확한 멱등 생성 결과를
  다시 확인한다. 원 task의 공개 풀이/Graph 존재를 금지하는 최초 복구 조건과 혼동하지 않는다.
- Prepared3로 실패한 그림 2건과 invalid-base 1건을 한 successor에 넣는 확장은 이 검증들을
  task별로 적용할 수 있을 때만 한다. 기존 visual-only 및 ordinary retry의 의미를 바꾸지 않는다.
- 필요 검증: 승인 전 invalid SHA/locator 거절, 원본 Artifact hash/권한 오류 전파, Material의
  단일 task 실패 후 다음 task 진행, accepted/Item 불변, 새 분석만 생성, 동일 요청 재전송,
  concurrent 복구/ordinary retry와 잘못된 pins의 disposable PostgreSQL 회귀다.
