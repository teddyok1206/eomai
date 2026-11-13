# 자료 검토 화면의 응답 소유권과 업로드 재개

기존 API upload intent/set과 멱등 key를 브라우저에서 이어 사용하는 변경이다.
새 작업 queue, DB 테이블, worker protocol, 실행 권한은 추가하지 않는다.

## 책임과 정본

API의 인증된 exact intent/set 조회가 상태·workflow의 정본이다. 화면은 owner별 작은
재개 참조만 tab storage에 보관한다. 논리 workflow, intent/set ID, 파일 hash는 바꾸지
않는다. 상태를 캐시해 API의 현재 상태를 대신하지 않는다.

보관 값은 version, SINGLE/PAIRED, SHA-256 request fingerprint, 원래 5개 멱등 key,
확인한 intent/set ID뿐이다. 원본 파일명/bytes, 자연어 지시, session/CSRF/비밀번호를
저장하지 않는다. fingerprint는 원래 business input과 파일 lastModified의 digest다.

## 접근과 자료구조

owner ID를 key로 단일 pending record를 읽고 갱신한다. 최대 4KiB, O(1) 접근이다.
record shape와 ID/key/hash를 검증하며 잘못된 record나 저장 실패 때 새 POST를 차단한다.
재진입 GET도 실제 로그인 권한으로 확인한다. 다른 owner의 record를 재사용하지 않는다.

주석/교정 변경은 선택 sequence·workflow ID·operator ID를 함께 확인한다. 늦은 성공,
오류, finally는 새 선택을 바꾸지 않는다. 같은 요청의 중복 클릭과 A→B→A 전환은 원래
key를 재사용한다. 이 transient cache는 최대 32개이며 성공 결과만 용량 확보를 위해
퇴역할 수 있다. 처리 여부가 불명확한 요청의 key를 버리고 새 요청으로 바꾸지 않는다.

## 부작용과 복구

record를 저장한 뒤에만 intent/set 생성·content 전송을 한다. 생성 응답을 받으면 exact
ID를 저장한 뒤 upload한다. timeout/401/새로고침은 record를 지우지 않는다.
기존 ID가 있으면 GET 상태를 먼저 읽고 PROCESSING/STARTING은 poll만 한다. STARTED는
원래 workflow를 연다. 아직 필요한 파일만 같은 key로 전송하며 파일을 잃은 새 페이지에서는
동일 파일·지시를 다시 선택하도록 안내한다. fingerprint가 달라지면 자동으로 새 key를 만들지 않는다.

자동 상태 조회는 5초 간격 최대 60회다. 이후 원래 참조를 유지하고 명시적 새로고침에서
동일 ID 조회를 이어간다. FAILED_RETRYABLE은 같은 원본/key로 명시적 재시도만 허용하고,
FAILED_FINAL은 사용자가 실패 내역을 확인한 뒤 서버의 terminal 상태를 다시 확인해야
브라우저 재개 참조만 닫을 수 있다. 서버 실패 이력은 변경하지 않는다.

새 submit은 첫 비동기 파일 판별 전에 기존 상태 조회 epoch를 무효화한다. 그렇지 않으면
이전 GET의 STARTED 응답이 pending을 지운 직후, digest 대기 중이던 submit이 새 UUID로
같은 자료를 다시 제출할 수 있다. owner 검사만으로 해결되지 않는 같은 owner의 race다.

브라우저를 떠난다고 서버 작업을 취소하지 않으며, 모델 호출이나 실패 이력을 재해석하지
않는다. 상태 조회를 못 하면 불명확한 요청으로 남기고 조회를 재시도한다. 임의 최신 문서나
관리자 authority로 대체하지 않는다.

Web UI→기존 BFF GET/PUT→API application 방향을 유지한다. 서버는 기존 긴 intake를
소유하고, Web timeout 이후 GET 결과가 처리 중이면 성공처럼 표시하지 않는다.
단순히 timeout을 늘리는 대안은 재로그인/응답 유실 후 identity 손실을 해결하지 못한다.

## HWP 확장자의 HWPX 입력

새 입력의 `.hwp` 파일 앞 8바이트만 읽어 PK container면 HWPX 후보로 선언한다.
그 bytes를 browser에서 ZIP으로 풀거나 신뢰하지 않으며 기존 Catalog가 전체 package를
검증한다. frozen 계약의 HWPX suffix 규칙을 유지하기 위해 제출명만
`원래이름.hwp.hwpx`로 정규화하고 원래 이름과 제출명을 함께 안내한다.
원래 File의 이름·bytes는 바꾸지 않는다. 정본의 `original_filename`이 byte-for-byte 원래
이름과 같다고 주장하지 않는다. 240자 한도 초과는 업로드 전에 명확히 거절한다.

## 검증

격리 Node 검사로 선택 A→B→A, 늦은 성공/오류/finally, 중복 클릭, wrong workflow 결과,
owner 교체, storage 실패/변조, reload 재개, terminal 결과와 paired member 처리 상태를
검증한다. 실제 브라우저·운영 활성화는 소스 검사와 구분한다.
