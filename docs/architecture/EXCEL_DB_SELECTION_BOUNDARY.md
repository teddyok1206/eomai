# DB → Excel 문항 선택 경계

`EXCEL_CONTENT_PLACEMENT_DESIGN.md`의 반복 자리·200개 초과 배치를 DB 선택 단계에서도
막지 않는다. 기존 개인 조립 V1/V2 계약과 저장본을 변경하는 작업은 아니다.

- `item-db-assembly.js`는 Excel의 선택 대상이 활성화된 동안만 별도 메모리 선택 목록을
  표시한다. 저장·출력 정본은 여전히 Catalog의 콘텐츠 편성 application이다.
- 선택 목록은 기존 `createPlanningDraft`의 ordered occurrence/placement ID를 재사용한다.
  문항 pointer가 같아도 별도 자리이며 이동·교체·삭제는 placement ID를 따른다.
  메모리의 section key는 UI collection key일 뿐 저장할 콘텐츠 identity가 아니다.
- 작은 typed target pointer와 표시 label만 보관한다. 원본 문항·파일 bytes·권한을 복사하거나
  새 registry를 만들지 않는다. 실제 handoff는 기존 `acceptSelections`와 `SAVE_SECTIONS`의
  pointer·권한·revision 검증에 다시 들어간다.
- 화면은 100행씩 표시하고 전체 목록을 순서대로 한 번에 넘긴다. 최대 100,000자리의 기존
  방어 한계를 사용한다. 보관 공간은 O(n), 전달·목록 읽기는 O(n), DOM은 최대 100행이다.
  모델의 기존 선형 이동·재번호 정책은 그대로 사용한다.
- 개인 조립 초안·제목·멱등 저장 key는 별도로 유지한다. Excel 선택 중에는 개인 조립 저장을
  비활성화하고 handler도 차단한다. 기존 개인 초안이나 저장본을 선택 목록으로 가져와도
  개인 초안을 덮어쓰지 않는다.
- handoff 실패 시 선택 목록을 유지하고, 성공 시 전달한 선택 목록만 비운다. 화면 전환은
  기존 개인 초안을 복원하며 사용자 변경은 두 메모리 상태를 모두 지운다. 늦은 저장본 읽기는
  owner/화면 generation 및 선택 모드가 바뀌면 적용하지 않는다.

별도 editor/schema/DB를 만드는 대신 기존 두 draft의 서로 다른 의미를 UI에서 명확히
구분한다. 기존 개인 조립을 모두 새 계약으로 재해석하는 방식은 이미 저장된 이력과 출력에
영향을 주므로 선택하지 않는다. 이 변경에는 migration이나 새로운 API가 없다.

검증: `tests/web_gui/item_db_browser_checks.mjs`는 실제 HTML/controller에서 301회 반복 선택,
100행 paging, occurrence 교체·이동·삭제, 일괄 handoff, 실패 후 재전달, 개인 초안 보존,
구 SAVE 호출 부재와 owner 변경 정리를 확인한다. 기존 private draft 회귀도 유지한다.
