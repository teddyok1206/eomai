# 기능별 모델 설정 정리

2026-11-12 UTC. 관리자에게 문항 제작·자료 검토·자료 학습·기존 문항 등록·유사도 정밀
비교·고객지원·ChatGPT의 7개 기능만 제공한다. 기능 내부의 서로 다른 작업 단계와
프롬프트를 하나의 실행 규약으로 억지로 합치지 않는다.

## 책임과 정본

Orchestrator가 기능 → 단계 → 실제 ExecutionPreset의 고정 대응을 소유한다. API는
해당 대응과 현재 발행 revision 및 그 이후의 미적용 draft만 읽어 제공하고 Web은 기능/단계를 선택하여 기존
모델 편집·검증·발행 use case를 호출한다. 별도 모델 설정 DB·범용 프리셋 프레임워크를
추가하지 않는다. ChatGPT는 같은 기능 선택 안의 별도 기존 설정 owner를 사용한다.

관리자 메뉴의 기능 하나는 여러 작업 단계를 포함할 수 있다. 단계의 모델 변경은 그
단계의 실제 current pointer를 바꾼다. 화면에만 다른 이름을 붙인 복사본을 만들지 않는다.
프롬프트·retrieval·timeout·권한·결과 schema는 기존 model-only 검증으로 유지한다.

## 모델 및 조회 경계

- 논리 기능·단계 키는 코드에 정의한 작은 불변 값이다. 동적 registry나 추가 table은 없다.
- 실행 정본은 기존 preset logical ID → immutable revision → policy/bundle pointers다.
- 단계별 현행 preset만 indexed lookup으로 일괄 조회한다. 동일 key가 여러 단계에 소속되거나
  current revision이 없고 잘못된 경우는 명시적으로 거부한다. 임의 최신/다른 기능 fallback 금지.
- UI 선택은 기능 → 단계 → 모델/생각하는 깊이다. 문항 제작은 기존 역할별 선택을 그대로 쓴다.
- ChatGPT는07번째 기능으로 제공하되 일반 Workflow preset을 만들거나06 예약을 변경하지 않는다.
- 초기 조회와 설정 갱신은 O(P+S), P는 현행 단계 수, S는 반환된 current revision 수다.
  과거 revision 전체 조회나 단계별 N+1은 필요 없다. 조회 결과 캐시는 추가하지 않는다.
- 변경은 기존 preset row lock·expected version·idempotency·검증 receipt 경계다.
  기능/단계 전환 시 이전 응답과 편집 상태를 무효화하여 다른 설정에 반영하지 않는다.

## 제거 범위

구 슬롯별 중복 및 과거 프리셋을 유지할 필요가 없다는 사용자 지시를 따른다. 단,
프리셋 삭제는 기출·문항·풀이보고서·과거 실행 기록 삭제 권한이 아니다. 먼저 read-only
inventory로 현재 installed pin, 실행 및 FK/문서 참조를 확인한다. 참조 없는 과거 설정은
검토된 정확한 ID를 기존 owner의 트랜잭션에서 제거하고 감사용 소형 결과를 남긴다.
공유 bundle·원문·NAS 산출물은 프리셋 정리의 삭제 대상이 아니다.

기존 실행/분석이 참조하는 프리셋의 물리 삭제에 별도 데이터 삭제가 필요하면 그 범위를
보고하고 사용자 결정을 받는다. FK를 끄거나 history의 pin/hash를 다른 값으로 바꿔
삭제하지 않는다. 신형 소비 경로 전환을 과거 실행의 재해석으로 처리하지 않는다.

사용자 확인: 과거 풀이·실행 이력 연결에 필요한 최소 기록만 예외적으로 보존한다.
관측 시점의 직접 참조에는 예전 창작 분석 프리셋2개에 대한 분석488건이 있었다.
이를 삭제 대상 문항 수로 해석하거나 데이터 정리 권한으로 확대하지 않는다.

미사용 과거 revision의 물리 삭제는 기존 DB-owner `MetadataResetTransaction.owner_mutations`
경계를 재사용한다. 정확한 두 설정 테이블의 불변 trigger만 트랜잭션 안에서 잠시
해제·복원하며 FK는 항상 유지한다. 참조·hash·실행 중 여부를 먼저 확인한다.
API/worker 역할에는 이 권한을 부여하지 않고 schema migration도 추가하지 않는다.
실패 시 삭제와 trigger DDL 모두 함께 rollback한다. 공유 bundle/artifact는 삭제하지 않는다.

## 검증과 배포

JSON Schema 2020-12 → Pydantic/단계 catalog → API/BFF → UI 순서로 구현한다.
기능 7개, 단계 중복/누락, current/hash/owner 오류, 관리자 권한, 늦은 응답, 기능 전환,
모델 저장/재조회와 기존 발행 절차를 검사한다. 삭제/동시성 검사는 disposable DB만
사용한다. 운영 API/Web 호환 배포와 현행 실행 pin 검증 후 기능별 화면을 확인한다.

더 단순한 UI 문자열 필터만으로는 모델을 바꾼 실제 대상과 현재 실행 경로의 일치를
보장하기 어려우므로 작은 서버 소유 대응표를 쓴다. 일반 설정 엔진이나 모델 설정을
중복 저장하는 대안은 현재 요구에 불필요하다.
