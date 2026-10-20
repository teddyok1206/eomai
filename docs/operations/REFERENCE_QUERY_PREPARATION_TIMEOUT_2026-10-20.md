# Reference QUERY 준비 HTTP 제한시간 진단

2026-10-20 UTC. 기존 등록 REVIEW 증분 목표의 최종 실제 사용자 검증 중 발견한 경계다.
이 문서는 완료 판정이나 새 모델 실행 승인 문서가 아니다.

## 관측과 보존

- 실제 guiadmin 로그인과 동일 단원의 승인 source 확인은 성공했다.
- 02:11:32에 시작한 준비 POST는 30,041ms 뒤503
  `REFERENCE_QUERY_PREPARE_UNAVAILABLE`로 반환됐다.
- 원 key의 유일한 `workflow_0941e1741dd34d3382265fc28a590da7`는
  02:22:37.407423에 COMPLETED였고 원 START command도 SUCCEEDED였다.
  timeout을 서버 미처리로 해석하거나 새 key를 만들지 않는다.
- 원 QUERY의 context SHA는
  `sha256:dd63b688080ca43908572491926fb43fe9dad4bb0d9a95feb47ecd8c832e3cfd`,
  Workflow request SHA는
  `sha256:436391a2181071d0604335af4623c0a18b375a90ab6e186309a56b3015759075`다.
  이는 실제 영속 metadata이며, 자체적으로 사용자 권한이나 HTTP READY reply는 아니다.
- INDEX delta `workflow_235e8836515f438e9fd2b39a074f25d6`도 실제 COMPLETED /
  command SUCCEEDED로 확인했다. 기존 실패 이력과 immutable outputs는 보존한다.
- API client와 owner transport의 제한시간은 각각30초다. owner의 동기 application
  호출 뒤 최종 reply를 보내므로, 실제 준비가 이를 넘기면 caller가 먼저 실패할 수 있다.
  단순 health PASS를 이 사용자 경로의 PASS로 해석하지 않는다.

## 원인 가설과 계측 범위

전체 DOCUMENT vector를 매번 읽는다는 초기 가설은 확인되지 않았다.
`resolve_pinned_read`는 승인된 anchor에 해당하는 binding과 shard만 선택한다.
기존 source/numeric negative tests와 이 실제 검증은 유지한다.

고정 CONTENT index2의521-binding metadata member를 기존 Artifact reader로 검증하고
decoder 하나를 cProfile로 계측했다. 계측 포함9.618초 중 cold schema registry 구성이
6.219초였다. 이는 API 전체의5분 이상 지연을 설명하는 증거가 아니며, warm 실제
application 병목이라고 단정하지 않는다. vector/model read와 DB write는0이었다.

다음 진단은 현재 실행 중인 기존 owner의 함수·파일·행 번호만 대상으로 한다.
`py-spy==0.4.1`을 별도 임시 도구 경로에만 설치했다. 이유는 운영 코드를
수정·재기동하지 않고 호출 위치를 관측하기 위해서다. API/owner Conda prefix, package
dependency, unit, role와 권한은 변경하지 않는다. 공식 출처와 동작 설명은
[py-spy upstream](https://github.com/benfred/py-spy)이다.

로컬 변수·인자·prompt·토큰·세션·process environment·원문은 수집하지 않는다.
`--locals`, memory/core dump, Python 코드 주입과 전역 ptrace 설정 변경은 금지한다.
도구는 고정 버전의 binary wheel만 허용하고, root 실행 파일은 hash를 확인한 별도
root-owned 위치로 materialize한다. 함수 stack 관측은 사용자/source 권한이 아니며
자료 조회를 승인하거나 worker/ADMIN을 가장하지 않는다.

기존 metadata 진단도 unique idempotency key / Workflow PK와 READ ONLY transaction을
사용한다. 세션 주체·현재 DB migration을 확인하고 rollback한다. 기록은 작은 상태·ID·
hash·시간만 포함하며 원 request/result body나 vector bytes는 복사하지 않는다.

## 수정 선택 기준

계측으로 입증된 중복 해석·비용만 기존 소유 경계에서 고친다. 새 검색 엔진, 준비 queue,
전역 authority cache, DTO 위조, 최신 revision 대체, 결과 force-success는 만들지 않는다.
JSON Schema2020-12, 원 source/Graph/policy/index pins, 현재 권한·late fence와 numerical
integrity를 보존한다. 기존 wire 의미가 바뀌어야 한다면 source 수정 전에 별도 설계·
successor를 결정하고, 제한시간 숫자만 무작정 늘려 완료로 보고하지 않는다.

수정·검증 후 최종 실제 조회는 원 key와 exact historical V1 요청을 재사용한다.
완료된 original QUERY를 재계산하지 않으며 새로운 사용자 인증이 실제 필요하면 이를
정직하게 요청한다. client가 종료한 메모리 세션을 복구하거나 인증을 한 것으로 간주하지 않는다.

## 고정 증거와 다음 실제 재조회

기존 checkpoint `/tmp/eom-registered-review-patch.zbfFVg5a/`의 다음 파일을 보존한다.

- `original-query-metadata-202610200225.json`, raw SHA
  `9e5d371c65fc4c5b5f99018af4a2617728e11613ea6097bafdf396c43ac98598`:
  actual READ ONLY / DB0058 / 동일 operator 원 key의 QUERY와 INDEX terminal metadata.
- `mixed-index-metadata-profile-v2-202610200225.json`, raw SHA
  `eca1d303aa7cc5ef131fc8bf41ef866b0842d02c8c3fd14fc8a35cef034f98d5`:
  index decoder의 계측 포함 값이며 실제 HTTP 전체 지연과 구분한다.
- `index21-final-registry-202610200218.json`, raw SHA
  `ade4a8536a6d42cd538a65c743e873c8bdade99630502ff215d94bcab1dd21fc`:
  mixed CONTENT521 / CONCRETE457 / METADATA521, target binding 두 view.

INDEX completion observer의 과거 고정 guard는 이번 후속 전체 관측에서 AssertionError로
중단됐다. 이를 actual INDEX 실패로 간주하거나 guard를 무조건 완화하지 않았다.
대신 exact Workflow PK / 원 QUERY unique key만 확인하는 좁은 metadata read로 두 원
Workflow와 command의 완료를 따로 확인했다.

다음 실제 호출은 새로운 QUERY를 만들지 않고 원 key·Graph·policy·source를 그대로
사용하는 완료 결과 재조회다. 종료된 client의 세션은 폐기되어 새 실제 로그인이 필요하다.
준비한 local diagnostic bootstrap은 검증된 원 client bytes를 hash로 고정하며, 로그인
후 우리 HTTP client만 정상 SIGTSTP job-control 경계에서 잠시 멈춘다. 비밀번호는 이미
삭제됐고 token은 같은 process memory에만 있으며600초 deadline도 계속 흐른다.
짧은 함수-frame 관측을 준비한 뒤 같은 client를 `fg`로 재개한다. worker·서비스·native
실행을 멈추거나 사용자 권한을 shell로 전달하지 않는다. 순수 boundary 테스트4개와
설치 API66의 no-auth plan 검증(HTTP0·로그인 입력0)을 통과했다.

이 시점에는 운영 source·protocol·DB·unit·제한시간을 수정하지 않았다. 실제 VECTOR
검색/read 및 HTTP 같은-key replay는 여전히 PENDING이며 전체 목표를 완료로 표시하지 않는다.
