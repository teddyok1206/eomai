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
reconcile을 통과했다. 실제 native stage/replay/concurrency suite241 PASS /266.06초,
공식 cleanup PASS(임시 DB·전용 역할·임시 credential 제거)다. 운영0058이나 기존 history를
pytest 대상으로 사용하지 않았다. 테스트 XML/로그는 별도 checkpoint에 보존한다.

### 호환 배포 범위

수정은 `92cf9b4e757ac3977d8282483421966e96a11e9f`로 commit/push했다. 공식
build-only·wheel RECORD가 통과했다. 우선 실제 느린 준비 호출을 소유하는 QUERY의
cold SDK만 새 source로 선택한다. API/Catalog66과 INDEX e013은 유지한다. wire/schema,
API provider의 실제 source/wheel/code/config pin, source/Graph/policy/index, 수치
runtime/model과 원 완료 Workflow는 바꾸지 않는다. 따라서 이 선택은 모든 component를
최신 source로 배포했다는 뜻이 아니며, 뒤의 실제 public READ는 별도 검증 대상이다.

기존 protected owner installer로 새 platform/API-contracts 두 wheel을 별도 cold release에
설치했다. 실행 권한 없는 기존 installer의 최초 직접 호출은 command-not-found로 실행
전에 중단됐고, 실제 target 없음 확인 뒤 명시적 Bash로 실행했다. 실패 output은 보존한다.

QUERY source 선택은 기존 owner configuration schema를 그대로 사용한다. 원 API66
file-only provider observer를 다시 실행하고 정확히 대조한다. primary/mixed의
`owner_source_commit`과 owner environment hash만 바꾸고, private의 참조 config hash 및
관련 systemd config hash/entrypoint를 함께 갱신하는 정확히5개 파일이다. 현재 namespace,
권한, corpus, policy, model, socket, source classes와 provider는 동일하다. 일회성 pure
transformation/negative tests6 PASS다.

PREPARE는 root-owned 별도 stage에 원본과 successor·파일 epoch·hash를 보관한다.
SELECT 전에는 QUERY만 정상 drain하고 PID0/empty cgroup 및 관련 active native QUERY
없음을 확인한다. 각 파일의 원 epoch/hash CAS, exclusive intent와 fsync/원자 교체를
사용한다. 새 queue/자동 재시도/DB 쓰기/모델 실행은 없다. 부분 상태가 불명확하면 추가
교체·시작을 멈춘다. rollback은 QUERY inactive 상태에서 보존한 원66의 정확한5개 bytes를
동일 CAS로 복원하는 것이며 다른 service나 immutable 결과를 되돌리지 않는다.

### 정상 drain 중 발견한 별도 종료 결함

03:05:01 UTC에 원66 QUERY만 정상 stop했다. SELECT는 실행하지 않았다. 이후 frame은
request worker가 유휴 `_worker`에서 대기하고, main thread의 중첩된 두
`stop_child → Event.set → Condition.__enter__`를 보였다. unit의 control-group 신호와
parent의 child 전달이 중복되면서 비재진입 잠금에 갇힌 것이다. 처리 중 모델·native QUERY
unit은 없었으며 이 현상을 현재 원 QUERY의 처리 실패나 DB 손상으로 해석하지 않았다.

신호 handler는 이제 lock/IO 호출 없이 local bool만 설정한다. 기존 socket loop는
0.25초마다 그 flag를 확인하고 normal cleanup/ThreadPool drain은 handler 밖에서
실행한다. 기존 Event·단일 thread pool·원 socket ownership와 KillMode는 유지한다.
새 queue, DB/schema/protocol, 권한 변경은 없다. RED1 FAIL 후 entry/server/transport/runtime
63 PASS /8.28초, strict type2 files와 Ruff/format을 통과했다. 수치·worker 검증이 아니라
control-plane 신호 처리의 회귀다.

잠긴 원66 controller는 frame·고정 PID/parent/UID/cgroup/InvocationID와 관련 active native
QUERY0을 확인한 뒤 해당 child PID4174473만 SIGKILL로 복구 종료했다. parent는 원 child를
회수했다. 이는 정상 drain PASS가 아니며 실패 journal을 보존한다. **native 모델/worker를
강제 종료하지 않았고**, DB/status/history를 수정하지 않았다. source92의5파일 PREPARE와
cold SDK는 선택하지 않은 채 보존하며, 신호 수정까지 포함한 새 candidate로만 재기동한다.
API/Catalog/INDEX는 여전히 동일 PID/Invocation이며 API LIVE/READY다.

신호 수정까지 포함한 candidate는 `2eef9b20bbd9f1394efc8d1566fada8d37769f66`이며
공식 build/RECORD와 별도 cold two-wheel 설치, 동일5파일 변환6 PASS 뒤 선택했다.
QUERY API provider는 원66을 유지한다. 새 SELECT receipt의 raw SHA는
`3b17031a659e0288385736a6d5916b7f7cd2672ba72dc80b84a12c03724b75e7`다.

첫 새 기동은 기존 socket pathname이 남아 있어 fail-closed `ChatTransportError`로
종료됐다. 자동 unlink를 허용하지 않았다. controller PID0/failed 상태, 정확한 두 socket의
종류·UID/GID/mode·inode와 ECONNREFUSED를 확인한 후 같은 디렉터리의
`.stale-108bcc8d` 이름으로 이동해 보존했다. 데이터/DB/Artifact 삭제0이며 이 endpoint
metadata는 복구 가능하다. 새 기동은 이 명시적 정리 이후 별도로 수행한다. 기존 실패
journal을 성공으로 바꾸지 않는다.

03:14:11.963544 UTC 실제 `REFERENCE_QUERY_OWNER_READY`를 확인했다. QUERY owner는
root parent330733 / child330795(uid990), invocation `c2e67715235e44069793d79e0929d652`였다.
신호 수정의 실제 검증으로 이 유휴 owner만 normal stop했고3.7초 이내 PID0 / inactive /
Result=success 및 `Deactivated successfully`를 확인했다. 두 번째 강제 종료는 없었고
native/model/DB 작업은0이다. 이후 같은5파일 선택 그대로 재기동했다.

API4172613·Catalog4172610·INDEX89255와 각 InvocationID는 그대로 유지됐고 API
`/api/v1/health/live`, `/api/v1/health/ready`는 정상이다. 잘못된 prefix `/health/...`의
초기404를 서비스 장애로 해석하지 않았으며 정식 API_PREFIX 경로로 재확인했다.
설치API66의 원 최종 HTTP client/plan no-auth 검사도 PASS(HTTP0/login0)다.

기존 사용자 로그인은 실제 성공했지만30초503 뒤 원 client finally에서 메모리 세션을
종료했다. 새 실제 로그인 전에는 source·서비스 검증을 HTTP 사용자 검증이나 전체 목표
완료로 확대하지 않는다. 실제 준비·검색·두 번 read·원 key replay 및 V1 역사 요청만 남는다.

두 번째 기동도03:16:19.788691 UTC READY다. 현재 parent332030,
invocation `0fac6053d0a947909d19ed71dffe14d0`, source2eef, NRestarts0 / Result=success다.
API/provider66·Catalog66·INDEX e013을 유지하는 compatible set이며 새 Graph/model 실행은
없다. Slack RECOVERED `devreport_82eb83b8e0e04d38a988fd6d3b742fb5`로 실제 복구 및
남은 사용자 HTTP gate를 보고했다. 선행 report에서 cleanup PASS 표기가 실제 확인보다
앞섰던 항목은 후속 공식 cleanup receipt(`fead9c55…`)로 확인해 정정한다.

tmux `EOM:2 rag-incremental`에서 원 client SHA22ca49…와 plan SHAfb3f3e…를 그대로
실행했다. 초기 진단용 self-pause bootstrap 대신 원 검증 client를 사용한다. 로그인 입력
전 no-auth gate는 성공했고, 실제 로그인은 원600초/인증 freshness를 바꾸지 않는다.

## 03:36 실제 HTTP: 준비 replay 성공, Catalog read 별도 지연

다음 실제 사용자 로그인은 성공했다. 원 mixed QUERY prepare가 두 번 모두200/READY이며
동일 reply를 반환했다. 원 key/Workflow/context/hash는 유지됐다. 다음 full context READ는
Catalog66의30초 제한에서503 `SIMILARITY_CONTEXT_UNAVAILABLE`였다. client는 이를
성공으로 바꾸거나 새 key로 우회하지 않았으며 finally에서 메모리 세션을 닫았다.

이 실제 READ의 Catalog stage에는 completed-query before7.476초, full population의
admit5.390초·solution profiles7.984초·materialize3.237초 등이 기록됐다. 이는 전체 source
읽기의 실제 비용이며 이전 QUERY 준비 병목과 구분한다. Catalog66에서는 이미 수정한
index 재검증 경로도 아직 그대로다. 결과 VECTOR/read/replay는 여전히 PENDING이다.

### Catalog 한정 compatible SDK 연결 설계

1. 책임/경계: 이미 설치·검증한 root-owned cold SDK2eef를 Catalog 프로세스의 명시적
   package 경로로 선택한다. API/provider66·QUERY2eef·INDEX e013은 유지한다.
2. 정본: 원 published Artifact/Graph/registry/DB0058과 immutable release wheel이다.
3. entity/revision/hash, V1/V2 schema/wire, 원 QUERY/INDEX 및 기존520개는 바꾸지 않는다.
4. 실행 전 실제 Catalog UID로 module/distribution source closure와 wheel RECORD를
   확인한다. 원 source/Graph/policy/access/member/numeric 검증은 새 SDK에서도 동일하다.
5. 주요 접근은 동일 root의 pin/decoder map lookup과 bounded population 읽기다.
6. 기존 reader의 root-local cache를 재사용하며 전역 권한/result cache를 추가하지 않는다.
7. 시간/공간 한도는 위 수정과 동일하다. 전체 HTTP30초 안의 성공은 실제 호출로 확인한다.
8. application transaction/unique/claim/lease/idempotency 경계는 변경하지 않는다.
9. 기존 service의 명시적 Conda console entry에 protected installed SDK PYTHONPATH를
   선택한다. checkout/runtime Git, 외부 API, 별도 service/queue/framework는 추가하지 않는다.
10. 기존 source/reader 설정을 소유하는40-drop-in 한 파일만 epoch/hash CAS로 변경한다.
    원본을 별도 보존하고 정상 Catalog stop/PID0 뒤 선택한다. 실패하면 원 파일 복원이며
    API/worker/DB/history는 되돌리지 않는다. secret/env credential은 읽거나 옮기지 않는다.
11. 전체 shared-prefix 재설치는 변경하지 않은 API/provider까지 교체한다. 이번에는 이미
    검증한 같은 SDK를 Catalog에만 연결해 변경 경계를 제한한다. 새 wire successor는 없다.

선택은 기존40-drop-in의 source pin, 명시적 installed SDK PYTHONPATH와 bytecode-off
설정만 변경하며 reader/operation opt-in/hash는 보존한다. 추가 drop-in을 누적하지 않는다.
이 component 선택은 API prefix 자체를 새 버전으로 설치했다는 뜻이 아니다. 다음 공용
platform 배포에서는 이 override를 반드시 inventory하고, 동일/후속 수정이 포함된 공용
release로 정렬한 뒤 PYTHONPATH 선택을 제거한다. 이전 component 선택을 묵시적으로
남겨 최신 공용 source인 것처럼 주장하지 않는다.

### Catalog SDK 선택과 제한 검증

실제 Catalog 계정으로 import한 EOM module487개가 모두 설치 SDK2eef 아래에서
해석됐고 eom-platform distribution도 같은 위치였다. DB/model 호출0, torch/transformers
미수입이다. 관련 runtime/registry/pinned-read 소스68 PASS /9.13초 및 순수 설정 변환과
predecessor drift 거부4 PASS다. 운영 데이터에 pytest를 실행하지 않았다.

기존40-drop-in raw188f2960…를 정상 stop/PID0 후 epoch/hash CAS로
raw `b2e5573a672fa9a62491e862ed35295ea573f263dd0dc2decec2d493ece79c94`로 선택했다.
원본·successor·manifest·rollback을 root-owned `/var/lib/eom-catalog-sdk-2eef9b20/`에
보존했다. 추가 drop-in이나 새 service를 만들지 않았다. Catalog 새 PID353401 /
invocation `af236f6b12774b6eb5a7d4c44f1236dc`, Result=success / NRestarts0이고 API
LIVE/READY다. API4172613·QUERY332030·INDEX89255와 각 InvocationID는 그대로다.

최종 검증 도구는 원 client bytes22ca49…와 plan fb3f3e…를 hash로 고정한 local wrapper다.
로그인 직후 우리 client만 잠시 job-control pause하여 실제 Catalog 함수-frame 진단을
준비한다. 지정 transport-unavailable 한정으로 같은 메모리 세션·같은 계획을 보존하고
명시적 재개를 최대1회 허용한다. 권한 철회/hash/결과 불일치/목표 후보 부재/freshness는
즉시 실패한다. 원600초는 계속 흐르며 남은60초 미만에는 pause하지 않는다. 두 번째
실패를 반복하지 않는다. 순수 경계11 PASS와 설치API66 no-auth plan(HTTP0/login0)을
통과했다. 토큰·password 파일/전달, 새 key/model/DB 쓰기, 인증 만료 연장은 없다.
