# 선택적 native HWP 변환기

`NativeHwpConverter.java`는 EOM의 file-only adapter다. HWP→HWPX의 문서 모형 변환은
[hwp2hwpx](https://github.com/neolord0/hwp2hwpx)와 저자의
[hwplib](https://github.com/neolord0/hwplib),
[hwpxlib](https://github.com/neolord0/hwpxlib)를 사용한다. 세 프로젝트는 Apache-2.0이다.
배포 bundle은 upstream license와 출처를 포함하고 Git에는 binary를 넣지 않는다.

추가 이유는 HWP의 글·표·수식·그림·중첩 도형을 raster fallback 없이 native HWPX로
변환하기 위해서다. 기존 Rust 후보에서 누락되던 grouped drawing과 source-proven picture
placement를 실제 문서에서 비교했다. 고정 source commit과 JAR SHA를 검증해 빌드하며
Maven/plugin/build hook이나 runtime download는 실행하지 않는다.

이 의존성은 격리 Builder의 선택적 로컬 도구에만 설치한다. API·Catalog·Codex·임베딩
환경에는 Java library나 새 Python dependency를 추가하지 않는다. 원본과 변환 결과는
다른 identity이며 실제 내용 fingerprint와 package 보존 검증을 통과해야 한다.

## Bounded native reader V2

`NativeHwpReaderV2.java`와 `NativeHwpConverterV2.java`는 별도 entrypoint·bundle/2.0·
evidence/2.0으로 선택한다. 기존 V1 bundle과 실행 핀은 덮어쓰지 않는다. 새 dependency나
upstream source patch는 없으며 동일 SHA의 public reader/model API만 조합한다.

hwplib 1.1.10의 `HWPReader.memo`는 마지막 section의 남은 record가 MEMO_LIST가 아니면
전진하지 않을 수 있다. V2는 직속 본문과 뒤따르는 master-page/memo record를 구분하고
진행·개수·bytes를 제한하며 알 수 없는 tail을 건너뛰지 않고 실패한다. 지원된 MEMO 필드도
정확한 명령 구조와 실제 메모 본문을 대조하고 native MEMO로 보존한다.

바탕쪽의 오래된 파일명 필드에는 begin 하나에 end 둘인 잘못된 편집 장식이 있을 수 있다.
V2는 본문 문항에는 예외를 적용하지 않는다. 명시적으로 미적용인 보조 바탕쪽만 별도로
변환하고, 이 오류가 나면 원본 HWP와 decompressed source record의 정확한 범위/hash,
단락·수식·표·도형 증거를 auxiliary exception으로 남긴다. 변환 가능한 보조 바탕쪽은
native XML로 보존하지만 적용 위치를 발명하지 않는다. 이 경우 원시험지 전체 pagination과
바탕쪽 적용은 NOT_VERIFIED이며, 문항 본문의 native 보존 PASS와 구분한다.
