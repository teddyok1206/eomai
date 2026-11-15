# Native 자료의 원본 배점 보존

2026-11-15 UTC. 김병훈450문항 목표를 축소하지 않는 실제 입력 호환 보완이다.

## 확인한 사실과 중단 범위

450개의 분리된 원문 HWPX에는 모두 정확히 하나의 `[배점점]` 표시가 있다.
1.5점144개·2.5점146개·2점160개다.16회·18회의 인쇄 배점 합계는50.5점이며 임의로50점으로
보정하지 않는다. 본문·원 해설·그림·Excel 원문·고유번호는 별도 정본이다.

첫 회차의 공식 Native bundle question pointer와 등록 content를 실제 Artifact owner로 읽어
25개를 비교했다.16개가 불일치했다.1.5가15로, 또는 소수 배점이0/2로 저장된 사례가 있다.
기존 '25개 완료'는 기술 상태였으며 배점 충실도 PASS가 아니었다.
`staging/native-registered-score-audit-20261115.json`이 읽기 전용 증거다.

3회차1번은 같은 정수 전용 계약에 대해 proposal을 거부해 `UNSUPPORTED_STRUCTURE`를
기록했다. 파일을 못 읽은 것이 아니다.2번의 공개 풀이 실패는 별개인 앞으로 향한
solution-step dependency이며 그 검증을 완화하지 않는다.

Material owner에는 지원된 main-only SIGINT drain을 요청했다. 기존 작업/실패/원문을
지우지 않았고 INDEX/QUERY는 교체·중단하지 않았다. goal은 계속 active다.

## 소유자와 최소 설계

1. 책임: HWPX 형식 계층은 이미 선택된 문항 XML에서 배점 표시만 읽는다. Catalog가 exact
   Native question pointer·actor 권한·schema/media/hash/lifecycle를 해석하고, 학습 입력 준비와
   등록 직전 같은 원본 배점을 대조한다. worker가 권한이나 기대값을 정하지 않는다.
2. 정본은 approved Native bundle의 문항별 HWPX다. 모델 proposal이나 Excel의 편성용 배점이
   원문 인쇄 배점을 대체하지 않는다. Excel 원문/추후 고유번호 갱신은 그대로 보존한다.
3. parser 결과는 작은 frozen value다. 별도 logical ID/DB/registry/queue/cache를 만들지 않는다.
   문항·revision·Artifact identity와 hash는 기존 포인터를 유지한다.
4. parser는 UTF-8 bounded section XML의 실제 paragraph text만 읽는다. DTD/entity/NUL·과도한
   depth/size를 거부한다. 여러 표시를 하나로 추측하거나 참고 그림/타 문항의 배점을 고르지 않는다.
   MATCHED/ABSENT/AMBIGUOUS를 구분하고 값은 Decimal로 비교하며 float 반올림/배율 변환은 없다.
   `material_native_score.py`는 이미 original/split lineage를 확인한 question descriptor만
   연다. 문서32MiB·ZIP member2048·section32·section별16MiB·XML합계32MiB로 제한하며,
   중복 member·암호화·지원하지 않는 압축을 거부하고 FD를 항상 닫는다. hash/lifecycle와
   권한은 기존 Artifact owner 및 전후 authorize에서 확인한다. 정기 상태 조회는 원문을 읽지 않는다.
5. 새 `source-score/2.0`은 기존 정수/미인쇄 의미를 보존하면서 정확한 반점 문자열을 추가한다.
   실제290개에 필요한 `1.5`/`2.5`는 문자열로 전달해 binary-float·15점 대체를 막는다.
   기존 Preview4가 이미 지원하는 integer/positive half-point 표시 범위만 이번에 약속한다.
   0.5/0.25 같은 미지원 표시를 정수로 바꾸지 않으며 별도 successor가 필요함을 기록한다.
6. `creative-source-item-draft/2.0`과 Native extraction/result successor가 새 score를 사용한다.
   기존 V1 draft/result·ROLE1.37/1.39·Workflow1/2·released Pack bytes는 바꾸지 않는다.
   새 wire/schema와 Pydantic을 먼저 정의하고 실제 필요한 새 ROLE/definition/Pack만 묶어 활성화한다.
   번호는 현재 등록된 family와 대조해 확정하며 임의 latest 재선택을 하지 않는다.
7. canonical block content의 successor `1.1`은 기존 body/interaction/solution 배치를 그대로
   쓰고 소수 배점만 정확한 문자열로 보존한다. 정수/미인쇄 입력의 기존 canonical1.0 경로는
   유지한다. content-team2/3로 억지 재배치하지 않는다. `BLOCKS_V1`은 같은 block-layout
   renderer를 뜻하며 source schema URI/version은1.0/1.1로 정확히 구분한다. Preview4의
   score_display는 이미1.5/2.5를 허용하므로 wire 의미/화면 구조를 바꿀 이유가 없다.
8. Catalog canonical reader·approved Item knowledge source·Preview·공통 풀이/임베딩 projection을
   같은1.1 pointer로 연결한다. imported Native 합본은 기존 원문 HWPX를 그대로 사용한다.
   지원하지 않는 template 재출력을 가능하다고 표시하지 않으며 별도 renderer를 만들지 않는다.
9. dominant operation은 문항 pointer별 bounded XML 선형 읽기와 task/Item PK lookup이다.
   parser O(XML bytes), space O(bounded text/depth/candidates); 기존 set/map·indexed joins를
   사용한다. 새 index/DB migration은 현재 필요가 입증되지 않았다.
10. 새 기대값은 검증한 Native question pointer와 기존 request/plan/receipt hash에 묶는다.
    등록 전 원본 배점과 proposal/canonical을 비교한다. 불일치는 stable source-score 오류로
    거절하고 원본이 '안 읽힘'으로 오인하지 않는다. model output을 제자리 고치지 않는다.
11. 복구는 기존 terminal/lease/retry 경계를 사용한다. source-score 때문에 proposal이 없는
    예외는 exact source·기술 원인·새 계약 지원을 증명한 후 새 linked task에서 다시 추출한다.
    이미 등록된 배점 오류는 원본 근거의 reviewed successor Item Revision·정확한 lineage로
    수정한다. 기존 task/accepted result/Graph/벡터를 성공으로 재해석하거나 덮어쓰지 않는다.
    기존 image correction에서 재사용 가능한 owner/transaction을 우선하고 새 수정 framework는 만들지 않는다.
12. 더 단순해 보이는 대안인 old schema의 integer→number 변경,0/15/반올림 저장,정상 자료를
    UNPRINTED라 부르기, metadata만 고쳐 canonical 오류를 숨기기는 원본 의미/immutable
    계약을 깨므로 사용하지 않는다. 공통 Graph·INDEX 숫자 recipe를 이 문제 때문에 바꾸지 않는다.

## 구현 후보와 활성 경계

score2·draft2·extraction2·block content1.1의 schema/Pydantic과 순수 compiler/reader를
추가했다. shared region/reference/answer 검증은 두 실제 형식이 같은 기반을 사용하며
archive/result1은 새 draft를 수용하지 않는다. block1.1의 Preview는 exact source URI와
schema_version을 확인하고 template 재생성 가능 여부는 false다. 실제 원문 전달/합본은 별개다.
같은 문항에서 배점만 바뀌어도 question embedding text/hash는 동일하다는 회귀를 추가했다.

후속 source에서는 ROLE1.40/request3/result3/plan41과 receipt3, 등록·HTTP 응답까지 연결했다.
설치·활성화와 실제 Native canary, 기존 등록의 reviewed correction은 별도 gate다.
source 후보의 통과만으로 운영 지원을 선언하거나 Material owner를 다시 켜지 않는다.

### 등록·조회 및 현재 실행 설정의 연결

- `item-lineage/3.0`은 result@3의 exact Artifact와 별도 learning-result hash를 pin한다.
  기존1/2 lineage bytes와 replay 의미를 바꾸지 않는다. 공통 필드 검증만 공유한다.
- 일반 Pack1.4 / Native Pack1.5는 ROLE1.40·Workflow3 전용이다. metadata와 item-type은
  각각1.2/1.3과 byte-identical하다. Native 문제·해설·Excel의 기존6 component 구조를 유지한다.
  Runtime에는 두 explicit release ID를 추가하고 누락 시 구 Pack/latest로 대체하지 않는다.
- 등록은 기존 advisory key·Registry transaction 안에서 완료 task/source를 재인가하고,
  result3 Native의 원문 question descriptor 배점을 다시 읽어 비교한다. 같은 요청의 replay도
  이 경계를 통과한다. integer/UNPRINTED content1.0과 exact half content1.1을 실제 compiler
  결과대로 구분하며 Artifact protocol1.28은1.1에만 사용한다. old protocol hash는 바꾸지 않는다.
- GET_ITEM_CONTENT의 request10·권한은 그대로이고 content1.1 응답만 response19로 읽는다.
  visual presentation response2는 기존 응답 전체와 새1.1 표시만 수용한다. API/SDK 양쪽을
  호환 배포해야 한다. 수동 reviewed import와 구형 template renderer 지원을 묵시적으로 넓히지 않는다.
  `ReviewedItemContentContract`는 기존 수동 입력1/2/3만 유지하고 read family와 분리한다.
  새1.1 읽기 추가가 미지원 수동 import까지 OpenAPI에 허용된다고 표시되게 하지 않는다.
- 기존 Office picture-use publisher는 두 실제 draft family를 같은 image pointer로 처리한다.
  일반 PDF의 visual-set2는 result2/3 pointer를 pin하며 기존1은 유지한다. 이는 PDF 원본의
  기존 렌더 경계만 잇는 것이고 Native HWPX 그림을 PDF crop으로 바꾸는 경로가 아니다.
- 실행 설정은 기존 protocol-only upgrade owner를 재사용해1.39→1.40의 명시적 후속 release를
  만든다. 실제 관리자의 현재 모델 순서·추론 깊이·instruction·capacity·권한·표시명은 동일해야 한다.
  같은 logical preset/row lock과 evaluation/publication/release를 사용하고 source hash/CAS가
  달라지면 거절한다. 새 preset family/queue/DB migration은 없다.

새 등록과 조회 자체의 검증이 기존 오류 문항의 복구 완료를 뜻하지는 않는다. 운영 전환 전에는
아직 제출된 구 Native extraction·lease를 따로 확인하고, 소수 배점을 표현할 수 없는 결과를
그대로 신규 등록하지 않도록 supported linked reanalysis 대상으로 분리한다. 기존16개 오류는
후속 Item Revision과 그에 맞는 공개 풀이/Graph 처리까지 확인해야 한다.

### 실행 연결의 최소 successor

현재 family의 점유를 확인한 뒤 새 Workflow3/ROLE1.40/result3/plan41을 사용한다.
work1의 문항/페이지/해설 선택은 그대로 둔다. request3와 plan41에는 nullable
`native_printed_score`라는 작은 값만 추가한다. Native scope가 있으면 Catalog가 그 scope의
exact question document를 읽어 얻은 PRINTED 값을 필수로 넣으며, scope가 없으면 null이다.
이 값은 이미 존재하는 question pointer와 request/plan hash에 묶이고 별도 정본이 아니다.
모델은 expected value를 고르거나 권한으로 사용할 수 없다.

새 result3은 discovery1 또는 extraction2만 받는다. Native 추출 결과의 score는 입력의
정확한 기대값으로 제한하고 등록 owner도 원문을 다시 대조한다. 구 ROLE/result/plan은
새 draft를 허용하도록 바꾸지 않는다. 공개 풀이의 source/step 검증과 숫자 임베딩 recipe는
유지한다. 새 task만 새 실행 family로 제출하며 기존 제출된 task/result는 새 의미로 읽지 않는다.
기존 Pack1.3의 실제 compatibility는 ROLE<1.40 / Workflow2로 닫혀 있다. metadata와
component 종류가 같다는 이유로 이 Pack을 새 실행에 재사용하지 않는다. 일반/Native의
필요한 Pack successor를 추가하되 기존 metadata 의미와 원문 file pointers는 유지한다.

기등록 오류의 복구도 새 일반 framework보다 기존 학습/Registry revision 경계를 우선한다.
원본과 배점이 다른 exact target만 후속 추출 대상으로 선정하고, source1.1을 지원하는
새 result에서 정본을 만들며 기존 logical Item의 새 Revision으로 등록하는 방식을 우선 검증한다.
정상 target은 상속한다. 모델이 반환하지 않은 올바른 소수 배점을 old accepted result에
끼워 넣거나, old 풀이의 source revision/hash만 교체해 새 분석인 것처럼 만들지 않는다.
새 Revision의 base/공개 풀이는 기존 분석 파이프라인이 처리하도록 한다. 실제 선택 retry·
same-source successor의 transaction/멱등 경계를 구현·검증하기 전 운영 보정으로 선언하지 않는다.

## 구현·검증 순서

### 후속 추출의 최소 저장·동시성 경계

새 explicit Native score reanalysis는 원본 run이 terminal이고 실제 Workflow/Job/lease가
quiescent일 때만 만든다. ordinary retry의 FAILED 의미를 넓히지 않는다. 원문 question을 읽은
동일 source owner가 등록 배점 불일치 또는 구 계약의 배점 표현 거부를 확인한 target만 고른다.
기등록 target은 그 준비 시점의 mutable current를 한 번 선택해 exact Item/revision/manifest/
content hash로 고정한다. 특히 앞선22번 그림 보정 revision을 원래 revision으로 되돌리지 않는다.

target마다 작은 immutable proof를 기존 ControlFileSetPublisher로 게시한다. 조회는 새 run ID와
predecessor task ID에서 정해지는 explicit idempotency key의 indexed owner lookup이며,
반환된 pointer를 Catalog Artifact owner로 해석한다. path/implicit latest나 작업 결과 복제,
새 DB table/queue/cache가 아니다. 단일 문항 등록이 시험지 전체 proof를 다시 파싱하지 않도록
proof는 문항별 Artifact이며 work/result/native question/기등록 content의 작은 pointer만 가진다.

원본 revision→run lock, source task checksum, pinned Artifact metadata와 현재 Item CAS를
최종 확인한 한 transaction에서 기존 linked run/task를 만든다. first event는 명시적
MATERIAL_NATIVE_SCORE_REANALYSIS_STARTED이며 기존 predecessor FK가 대상 관계를 고정한다.
선정 target의 새 task만 PENDING이고 입력/출력/분석/Item pin을 상속하지 않는다. 정상 완료
target은 원래 Item/Graph checkpoint와 predecessor 이력으로 base/public 참조를 유지한다.
분석 run FK는 child task의 unique 소유 관계이므로 새 task에 복사하지 않는다. 기존
`MaterialTaskHistory.analysis_owner`와 공식 읽기 projection이 정확한 원래 분석을 찾는다.
게시 뒤 transaction 실패 시 proof는 원래 publication key로 조회·hash/내용을 검증하여
재사용하며, SDK가 갱신돼도 최초 source provenance를 바꾸지 않는다. old task/result/Graph는 수정하지 않는다.
초기 command의 run/timestamp/idempotency key hash가 동일하면 새 작업을 만들지 않고 같은 successor를 읽는다.

새 target의 result3 등록은 같은 source key advisory lock 안에서 proof의 기존 Item에 대해
Registry REVISE_ITEM/base_revision_id를 사용한다. 새 logical Item을 만들지 않는다.
후속 Lineage4는 문항별 보정 proof Artifact를 명시적으로 pin한다. 일반 result3의 Lineage3와
기존 Lineage1/2는 바꾸지 않는다. proof의 원문·구 result·구 current revision 및 새 result가
한 등록 이력에서 추적되며, 숨은 latest 또는 filesystem 경로로 근거를 복원하지 않는다.
fresh canonical/proposal/receipt는 새 source-faithful 추출에서 만들고 old accepted result에 값을
끼워 넣지 않는다. Registry commit 직후 응답이 사라져도 exact revision key로 회복한다.
source·Item·권한·hash가 달라지면 새 current로 대체하지 않고 explicit stale/error다.

접근 패턴은 run/task PK·source-current 준비·revision hash·publication key lookup과 bounded
문항 순회다. 전체 선정은 O(q × 기존 source-resolution 비용 + question XML bytes)다.
task/history는 bulk keyed query이며 각 원본/Item의 권한·Artifact 확인은 기존 owner의
indexed resolution을 그대로 쓴다. 문항별 등록 proof 조회는 O(1) indexed lookup + bounded
JSON/XML이다. 이 일회성 보정에 별도 영속 cache나 전체 source 정본 사본을 만들지 않는다.
모델·추론·capacity와 기존 control release owner는 유지한다. 새 Indexed tracker/단순 현재 row
수정이나 전체25개 재생성은 source fidelity·이력 또는 재사용 범위를 깨므로 선택하지 않는다.

- 원본290개/기존 등록16개 불일치를 보존하고 새 등록을 안전하게 drain한다.
- pure bounded parser, 새 score schema/value, source/canonical successor와 단위 검사.
- 기존 worker/등록 owner에 연결하고 원본 배점 대조를 강제한다. 원문/그림/해설은 바꾸지 않는다.
- 역사적 schema replay·Native2/3·정수/미인쇄·반점·위조/모호 XML·pointer/권한/hash 검증.
- disposable DB에서 linked correction/retry·동시 생성·중단/replay·immutability를 검증한다.
- 호환 private runtime과 Web에 반영하고 실제1.5/2.5/2점 문항을 각각 확인한다.
- 전체450 및 현재/후속 Item Revision의 배점을 원문과 대조하고 Graph/공개 풀이/INDEX를
  끝까지 연결한다. 기술 완료와 source fidelity를 분리해 최종 판정한다.

이 문서/개발 후보는 운영 활성화나450개 완료 증거가 아니다. 실제 gate는 자료 학습 운영
checkpoint에 append한다. 원문 파일과 과거 실행은 계속 보존한다.
