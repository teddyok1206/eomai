# 원본 그림 입력을 이용한 4슬롯 창작 등록 계속 처리

2026-11-03 UTC 사용자 추가 승인. 기존 그림 입력 구현을 마친 뒤 4개 슬롯으로
풀이·Graph 등록을 계속하고 공통 임베딩까지 연결한다. 새 queue/Graph layer는 만들지 않는다.

1. **경계/책임:** 현재 creative cohort owner가 준비·등록·Graph publication을,
   Orchestrator가 실제 worker claim/lease와 Artifact commit을 맡는다. INDEX는 기존 owner다.
2. **정본:** 이미 사용자가 접수한 원본 source revisions, 기존 모집단과 seed의 승인된
   owner/target pins. 과거 보고서·등록 문항은 재생성하지 않는다.
3. **식별:** 기존 immutable 모집단의 별도 실행 continuation을 발행한다. 원본/문항 ID와
   history를 유지하고 새 Workflow3/Pack1.2/4슬롯 설정만 후속 실행에 pin한다.
4. **포인터:** parent cohort와 정확한 기존 parallel continuation, 원본 revision/hash,
   preset/capacity/policy/Graph/분석 Artifact를 기존 resolver로 확인한다. latest 대체는 없다.
5. **접근 패턴:** indexed pending membership, unique concurrent claim, bounded ordered
   source window, 한 번의 Graph batch commit, incremental embedding 대상 추가다.
6. **구조/인덱스:** 기존 queue·held-slot/job unique index·host advisory lock·source registration
   business-key fence를 재사용한다. source/window는 map, 중복은 set, history는 bounded chain이다.
7. **규모/복잡도:** 현재 1,053 eligible source 중 이미 등록된 것은 재사용한다. source당
   indexed lookup + 실제 문서 크기에 선형인 추출, 창은 최대 8 source, worker는 최대 4다.
8. **트랜잭션/동시성:** 새 capacity `worker-capacity-policy/1.5`는 정확히 slot03/04/05/06만
   support로 실행한다. 03(image)·04(item_management)의 물리 역할은 바꾸지 않는다.
   host/knowledge ceiling은 이 목적만 4, 슬롯당 1, GPU 1을 유지한다. 과거 정책 ceiling은 3이다.
   필요한 DB 변경은 기존 capacity CHECK에 이 정확한 successor 분기만 추가하는 migration이다.
   pool child CHECK의 상한도 4로 넓히되, 과거 parent의 host/knowledge 상한과 기존
   typed pool 상한 3은 유지한다. 과거 정책으로 네 번째 claim을 얻을 수 없다.
   실제 command runner도 기존 scale-out 관리자의 고정 accelerator3 하나를 추가해
   4 process로 맞춘다. 같은 queue/claim/lease이고 새 scheduler나 worker protocol은 없다.
   향후 shared release는 기존 active-unit glob과 staged accelerator3 검사로 차단된다.
9. **의존 방향:** contracts → domain capacity/continuation → 기존 application owners →
   PostgreSQL/systemd/파일 adapter. worker의 DB/NAS 권한은 추가하지 않는다.
10. **실패/재개/멱등:** 진행 중 문항은 기존 핀으로 완료한다. 이후 신규 source만 native
    그림 입력을 사용한다. 실패·content-unavailable 기록은 보존하고 다른 문항은 계속한다.
    재시작은 같은 source/selection/Artifact를 조회한다. 새 등록은 기존 INDEX가 incrementally
    받는 accepted report 경계에 연결하며 전체 INDEX 재시작/벡터 삭제는 하지 않는다.
11. **단순 대안:** 기존 3슬롯 policy의 숫자를 덮어쓰거나 Orchestrator 밖에서 네 번째
    worker를 띄우면 과거 계약과 중복 실행 방지가 깨진다. 새 purpose-limited capacity와
    기존 continuation/parallel driver 확장이 가장 작은 안전한 변경이다.

## 완료 기준

원본 그림 신규 입력의 실제 등록·Preview/media·HWPX 검증을 먼저 닫는다. 이후 새
continuation의 실제 4개 slot claim/진행을 확인하고, 새 문항의 풀이·Graph 등록 및
공통 임베딩 대상 수록/처리를 관측한다. 기존 성공·실패와 GPU INDEX pin/PID를 보존한다.
전체 잔여 corpus가 며칠 걸리더라도 서비스를 계속 돌도록 남기며, 단순 READY나 unit
개수만으로 실제 4슬롯/Graph/임베딩 성공을 주장하지 않는다.

### 사용자 확정 범위 (2026-11-03)

사용자가 `그림 등록·4슬롯·임베딩 우선`을 선택했다. 가져온 canonical1 문항의 가변 구조를
새 HWPX로 재출력하는 renderer 확장은 후속 과제로 분리한다. 기존 실패 build를 보존하며
현재 목표의 완료 조건에 이 확장을 다시 추가하지 않는다.

### 원본 그림 보고서의 증분 임베딩 출처 연결

실제 INDEX는 외부 분석 result@3의 출처 포인터를 구 Entry1의 @1/@2 허용 목록에서
거부했다. 내부 풀이보고서 V2와 `public-solution-text/1.0`, recipe2, encoding identity,
기존 모델·CPU/GPU 수치 실행환경·shard는 변경하지 않는다. 수치 입력은 계속 검증된
`EmbeddingTextInput`이며 원본 그림 bytes를 임베딩에 섞지 않는다.

새 provenance에는 Entry3 및 metadata5 successor를 사용한다. 공개한 predecessor schema
bytes는 보존하며, 기존 담당 계약 parser가 각 명시적 버전의 JSON Schema와 hash를 검증한다.
기존 버전의 tag로 새 포인터를 위장하지 않는다. INDEX2 application DAG·queue·claim,
DB table/열·권한 정책은 그대로이며 읽기/저장/재전송 경계만 새 출처 형식을 지원한다.

정본은 승인된 source/lineage/result Artifact다. logical Item과 revision·Artifact·content hash는
분리한다. map/set 및 indexed revision lookup으로 source/demand를 연결하고 정렬된 immutable
manifest를 만든다 (N개에 O(N log N), 공간 O(N)). 기존 source lock·CAS head·unique encoding
key가 동시성/재전송을 보호한다. 새 table/index/queue/모델 의존성은 없다. 실제 disposable
저장에서 발견한 기존 manifest schema allow-list 3개 CHECK만 migration71로 확장한다.
rollback은 새5 metadata가 있으면 거부하며, 데이터 삭제나 과거 vector 재계산은 없다. 실패한 owner 실행과
벡터는 보존하고, 인계 시 실행 중 numerical child가 없는지 확인한다. 단순히 old enum을
넓히는 대안은 released bytes와 실제 출처를 바꾸므로 사용하지 않는다.

## 관측된 과거 실패의 처리

새 입력 파일럿의 모집단 조회에서 과거 COMPLETED 및 FAILED Workflow가 함께 확인됐다.
`1.2` 병렬 driver에 한해, application이 정확한 target/selection의 terminal source failure를
확인하면 기존 `blocked_sources`에 기록하고 다른 문항을 처리한다. 과거 serial/3슬롯
driver의 중단 의미는 유지한다. 권한·hash·정책·Graph publication 오류나 분류되지 않은
예외는 계속 전체 중단한다. source별 실패는 등록/검증 완료 수에 포함하지 않고, 새
identity를 만들어 자동 재실행하거나 과거 FAILED를 성공으로 바꾸지 않는다.

## 네 번째 슬롯의 고정 실행 시간 경계

실제 신규 작업에서 slot03의 기본 image unit(1,800초)과 source/report 실행(7,200초)이
맞지 않아 모델 호출 전에 WORKER_UNAVAILABLE가 발생했다. slot04에서 이미 사용하던
purpose-specific fixed unit을 같은 방식으로 03에 확장한다. 기본 image unit·물리 role·
worker 실행 helper·인증·프로토콜은 바꾸지 않는다. 정확한 (03,image,7200) 조합만 새
root-owned `eom-worker-analysis-03@job_<ID>.service`를 선택한다. 기존 Orchestrator의
capacity/claim이 용도 권한을 확인하며, 새 unit 자체는 동일 user/group/파일 격리다.

readiness는 새 unit의 SHA/ownership을 확인하고, 중단 후 실행 조회는 기본/분석 unit을
모두 본다. 동시에 둘 다 있으면 UNKNOWN으로 둔다. Polkit은 workflow runner의 정확한
03/04 분석 unit StartUnit만 허용하며 restart·다른 slot·임의 unit은 허용하지 않는다.
03 grant는 `48-eom-native-office-report-worker.rules`에 한정한다. GPU/CPU 수치
실행환경이 pin한 기존 `50-eom-worker-units.rules` bytes와 그 검증 hash는 바꾸지 않는다.
호환 설치 때 진행 중 worker가 없음을 확인한다. 이 오류의 기존 FAILED source/job는
보존하고 supported preexecution recovery 경계에서만 재개 가능 여부를 판단한다.

이 실패는 Job가 이미 있으므로 기존 `NO_PLATFORM_JOB_CREATED` 복구로 가장하지 않는다.
기존 명시적 successor 복구 owner에 `creative-launch-recovery/1.0` 한 종류를 추가한다.
Workflow3/Office Work2·slot03·정확한 trusted timeout-contract 오류·terminal Job·출력/commit
없음·활성 command/lease 없음이 모두 확인된 경우만 새 실행을 준비한다. 원래 제출자의
현재 권한·원본/plan/preset pins를 재검증하고 기존 parent lock·unique workflow key·
append-only event로 동시 요청과 재전송을 수렴한다. parent/Job의 FAILED는 보존한다.
새 성공은 같은 source 등록 business key에 연결하며 Item/Graph를 중복 만들지 않는다.
단순 대안인 FAILED row 변경이나 다른 namespace의 무관한 새 작업은 사용하지 않는다.

## 실제 원본에서 확인한 일반 회색조

### 4건 Graph publication의 실제 중단 수정

새 continuation은 4건 publication을 요청하지만 기존 application의 내부 batch guard가
3건까지만 허용해 실제 등록 후 중단됐다. 이 guard를 4로 정렬한다. 기존 3슬롯 계약의
batch 크기는 그대로이며 새 queue/Graph/preset 재선택은 없다. publication은 분석 preset을
선택하지 않고 각 accepted analysis의 정본·권한·source hash를 검증하므로 과거·신규
분석을 같은 기존 Graph publisher로 묶어도 된다. 4건을 한 번에 publish하고 5건은 I/O 전에
거부하는 회귀 검증을 추가한다. 과거 FAILED와 미등록 상태를 성공으로 덮어쓰지 않는다.

새 파일럿 11763(HWPX)·11743(HWP)의 본문 그림은 특수 효과가 아니라 각각
`GRAY_SCALE`, picture-info byte70=1을 사용했다. [한컴 공식 5.0 revision1.3 표32](https://cdn.hancom.com/link/docs/%ED%95%9C%EA%B8%80%EB%AC%B8%EC%84%9C%ED%8C%8C%EC%9D%BC%ED%98%95%EC%8B%9D_5.0_revision1.3.pdf)의
일반 회색조 모드다. decoder가 이를 모든 특수 효과와 함께 거부했던 범위를 보완한다.

기존 Catalog1.0의 `rendered_uses`는 실제 원본 사용 개체의 PNG를 가리키는 계약이며
consumer가 색 변환을 다시 수행하지 않는다. schema/role bytes와 과거 manifest는 바꾸지
않고, 새 CPU tool release의 source-native 해석만 확장한다. 원본 RGB PNG는 `images/`에
보존하고, 회색조는 기존 `uses/<SHA>.png`로 별도 식별한다. 원본 hash·native object
hash·locator·tool release와 output hash가 재현 경계다. JSON wire에 임시 renderer recipe를
새 필드로 퍼뜨리지 않는다.

내부 set으로 정확한 회색조 use ID만 renderer에 전달하고, 같은 바이너리를 원색/회색으로
두 번 쓴 경우도 별도 view/cache key로 구분한다. Pillow의 결정적 luma 변환과 원래 alpha를
사용하며, 크기·좌표·모서리·라벨을 바꾸거나 이진화/dither/자동 대비 보정을 하지 않는다.
밝기·대비·다른 효과·그룹 합성은 여전히 명시적 unresolved다. CPU sandbox 밖에서 원본을
해석하지 않는다. 기존 두 완료 보고서는 보존하고 성공으로 재해석하지 않는다.
