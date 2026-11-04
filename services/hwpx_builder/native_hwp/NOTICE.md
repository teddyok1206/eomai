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
