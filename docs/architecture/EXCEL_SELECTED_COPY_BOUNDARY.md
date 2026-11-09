# Excel 선택 구간·자리 복사 경계

2026-11-09. 기존 Excel 설계 §2.2, §15.2, §18.4의 부분 복사를 구현한다.

- 책임: 화면은 사용자가 고른 불변 저장본의 구간/자리를 읽어 새 편집 배열을 만든다.
  저장·인가·원본 검증·transaction은 기존 Catalog `SAVE_SECTIONS`가 소유한다.
- 정본: 기존 edition revision과 Form/Assembly revision. 원문·그림·풀이·벡터를 복사하지 않는다.
  새 자리만 새 logical placement ID이며 `copied_from`에 원래 assembly ID/revision/hash/자리 ID를 둔다.
- 읽기: 기존 `READ_SECTION`으로 source edition revision/hash와 Form pointer를 pin한다.
  선택 그룹은 원래 트리 순서의 leaf로 확장하고, 체크한 순서와 관계없이 원래 문항 순서를 유지한다.
- 쓰기: INSERT는 명시 위치, REPLACE는 명시한 기존 placement ID 집합만 교체한다.
  새 최종 배열은 기존 expected edition revision/hash와 before Form revision/hash를 가진다.
- 검증: 기존 `validate_slot_origins`가 공유 Form 소속, 원본 revision/hash, 원래 자리와
  실제 target 일치를 검증한다. 기존 자리의 provenance 변경은 계속 금지한다.
  원본 읽기 오류·누락·stale 응답은 초안을 변경하지 않는다.
- 자료구조: section/placement membership은 set, 제목은 map, 출력은 ordered array/tuple이다.
  선택된 원본과 대상 배열 길이에 선형이며 조회는 기존 200행 pagination을 사용한다.
- 동시성/재전송: 대상 edition CAS와 기존 command receipt를 재사용한다. source는 불변 revision이라
  원판 head 변경으로 재해석하지 않는다. copy clipboard 재사용 때마다 새 자리 ID를 만들지만
  이미 제출한 저장 요청의 재전송에서는 기존 body/key를 보존한다.
- 경계/대안: 새로운 queue, registry, DB schema, cross-service message가 필요 없다.
  브라우저에 새 복사 명령을 영속화하는 대신 이미 출시된 CuratedSlot/copied_from와 SAVE_SECTIONS
  계약을 재사용한다. 제목이나 고유번호만 복사하는 대안은 exact source provenance를 보존하지 못한다.

`content-planning-copy.js`는 편집 준비만 담당하며 실행 권한을 부여하지 않는다.
서버의 기존 `copy_assembly_slots`는 whole-edition과 선택 복사 테스트에서 같은 origin 규칙을 쓴다.
