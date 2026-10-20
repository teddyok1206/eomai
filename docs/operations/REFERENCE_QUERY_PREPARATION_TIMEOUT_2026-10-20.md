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

## 02:49 실제 frame 관측과 수정 설계

같은 실제 로그인 process를 재개한 뒤 원 key를 재조회했다. 5초 sample은
`for_pinned_similarity_request_in_session → _validate_similarity_manifest →
validate_similarity_index_pin_v2 → MixedEmbeddingIndexManifest.model_validate` 안의
기존 binding hash 재계산이었다. 다음 sample은 JSON Schema 검증이었다. Catalog는
이 sample에서 대기 중이었다. 동일 POST는 다시30초503으로 종료됐다. 이는 전체 지연의
정밀 비율은 아니지만, canonical member를 이미 decode한 직후 다시 전체 index를
파싱하는 실제 중복 경로의 증거다. 실패한 세션은 종료됐으며 복구하거나 재사용하지 않는다.

수정 범위는 다음과 같다.

1. 책임: 기존 Catalog Artifact reader의 root-local immutable 해석 재사용과 순수 index-pin
   일치 규칙. API, worker, 새 검색 엔진이나 queue를 추가하지 않는다.
2. 정본: 승인된 canonical Artifact bytes와 기존 JSON Schema2020-12/Pydantic decoder다.
3. 논리 entity/revision/hash 및 V1/V2 wire/schema bytes는 변경하지 않는다.
4. 초기 decode는 모든 raw scalar/extra/hash를 검증한다. 이후 이미 decode된 값의 pin
   비교는 작은 순수 규칙을 공유한다. 외부 공개 validator는 full raw 검증을 계속 수행한다.
5. 주요 접근은 동일 transaction root에서 동일 immutable pointer/decoder의 반복 lookup이다.
6. 기존 bounded reader를 Session.info의 명시적 root-local factory로 재사용한다. 새 root,
   다른 settings/thread/Session에는 이전 reader를 전달하지 않는다. 전역 cache는 없다.
7. lookup은 O(1), 각 root의 retained bytes/decoded entries는 기존128/32MiB·2048 한도다.
   중복 O(index bytes) parse/hash를 없애며 공개 입력 검증 비용은 그대로 남는다.
8. 트랜잭션·권한·원본·numeric·late provenance fence는 매번 기존 owner에서 실행한다.
   reader 재사용은 권한 또는 성공 결과 cache가 아니다.
9. 의존 방향은 application/adapter → 기존 Catalog reader/contracts다. domain에 DB/IO를
   추가하지 않는다. 중복 pin 규칙은 V1/V2 공개 validator와 owner가 함께 사용한다.
10. 실패/replay/key/deadline/원 Workflow는 바꾸지 않는다. 변경은 호환 package 배포로만
    반영하고 실행 중 source를 hotpatch하지 않는다.
11. 더 단순한 제한시간 증가만으로는 반복 parse 비용이 남는다. 반대로 validation을
    생략하면 forged pointer/input을 허용하므로, raw 검증과 이미 해석된 값 비교를 분리한다.

검증은 reader의 root/settings/thread 경계, provenance 변경·파일 손상 거부, V1/V2 raw
forged/extra/hash negatives와 pin mismatch, decode 횟수 및 합성 최대 규모 benchmark를
포함한다. 실제 HTTP PASS는 이후 같은 원 key·진짜 사용자 인증으로 별도로 확인한다.

### 소스 검증

- 기존/추가 집중8 suites342 PASS /64.32초. reader와 현재 provenance, index/index2,
  V1/V2 raw negatives, 실제 임시 파일·수치 참조, original completed replay를 포함한다.
- 별도6 suites145 PASS /117.28초(위 묶음과 reader suite가 겹치므로 합산하지 않는다).
- 원 실제 pin read를 두 번 실행하는 새 검사는 decoder1회이면서 current source capture는
  다시 발생하고, 그 뒤 Artifact 승인 철회는 거부함을 확인했다.
- 최대1024-binding 합성 index의3회 공개 raw 재검증은3.577087초,
  canonical decode 후 동일3회 pin 비교는0.000035초였다. 순수 연산의 중복 제거
  측정이며 HTTP 전체 지연·실제 source 권한·검색 품질 개선 수치가 아니다.
- Ruff/format, strict mypy6 source files, 의존 방향6 checks PASS다. 새 dependency,
  migration, schema bytes, source/Graph/policy/index pins, numerical runtime 변경은 없다.
- 최초 신규 factory tests2개는 구현 전 AttributeError로 실패했다. settings fixture명과
  completed-reader test seam 보정 뒤 최종342 PASS였으며 중간 실패를 숨기지 않는다.
  별도 suite 호출의 존재하지 않는 파일 경로 오류도 수정 후145 PASS로 재실행했다.

공식 disposable DB `20261020025629_f20dc47a`의0058 migrate/down/up 및 runtime role
reconcile을 통과했다. 실제 native stage/replay/concurrency suite는 별도 실행 중이다.
운영0058이나 기존 history를 pytest 대상으로 사용하지 않는다.
