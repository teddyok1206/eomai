# Excel 인쇄 기록의 완료 출력 연결

기존 `EXCEL_CONTENT_PLACEMENT_DESIGN.md` §4.2/18.5의 선택적 완료 HWPX 연결을 닫는다.
인쇄 사실은 사용자 기록이며, 다운로드/출력이 인쇄 사실을 자동 생성하지 않는다.

- 책임: Catalog 인쇄 application은 exact 편성 scope를 확인하고 기존 Artifact owner가
  검증한 curated 출력만 불변 인쇄 기록에 연결한다. 파일 복사·renderer 실행은 없다.
- 정본: 편성 revision/선택 scope, 이미 성공한 Job/Artifact Revision이다. 출력 build ID와
  expected output SHA만 명령에 더하며 browser가 경로·권한·Artifact 상태를 선언하지 않는다.
- 모델: 기존 print-record/1.0의 `output` pointer를 채운다. released command/1.0은 그대로
  두고 `RECORD_PRINT_WITH_OUTPUT`을 명시한 command/2.0과 RPC request/2.0을 추가한다.
  DB migration이나 새 registry는 필요 없다.
- 검증: edition/revision/scope → prepared assembly → committed Job/Artifact/result의
  revision/hash/profile/schema/media/lifecycle를 대조한다. 다른 구간·다른 저장본·실패·미완료·
  hash 불일치를 거부하고 latest로 대체하지 않는다. 현재 문항 읽기 권한도 기존 경계에서 검사한다.
- 접근: unique `jobs.idempotency_key`와 Artifact/Revision primary/FK lookup, indexed
  delivery scope lookup이다. 반복 파일 hash/대용량 재물질화 없이 작은 metadata를 사용한다.
  판의 출력 개수에 대한 full scan은 없으며 한 출력의 이미 저장된 입력/결과 검증은 O(n)이다.
- 동시성: 기존 edition lock/command receipt transaction 안에서 기록한다. 같은 key는
  같은 결과, 다른 내용은 충돌이다. 기존 초기 인쇄가 있으면 자동 덮어쓰기 대신 기존 기록을
  반환하고 새 연결이 필요하면 명시적 정정을 사용한다.
- 의존성: Manager가 사용하던 committed-output validation을 Catalog Artifact adapter의
  공개 함수로 공유한다. Catalog → Manager 역의존이나 새 권한/SQL 우회는 만들지 않는다.
- 실패/복구: 기존 출력·실패 이력은 수정하지 않는다. 조회는 출력 재실행이 아니며 인쇄
  취소/정정은 기존 append-only event를 그대로 따른다.
- 더 단순한 대안: build ID만 그대로 저장하면 다른 구간의 파일을 인쇄 근거로 붙일 수 있어
  불충분하다. 별도 파일 검증/복사 대신 기존 committed publication 검증을 재사용한다.
