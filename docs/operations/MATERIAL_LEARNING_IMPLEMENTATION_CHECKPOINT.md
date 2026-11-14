# 자료 학습 구현 checkpoint

2026-11-06 UTC. 사용자의 최종 범위는 운영 배포·제한된 실제 업로드 처리 확인까지다.
goal 카드의 초기 배포 금지 문구는 후속 사용자 지시로 대체됐다. 구현 중간 기록은 보존하며,
최종 운영 결과와 검증 한계는 [운영 반영 기록](MATERIAL_LEARNING_RELEASE_2026-11-06.md)을
우선한다. 전 corpus의 임베딩 완료를 뜻하지 않는다.

## 2026-11-14 22:49 UTC — 완료19개 보존·실패6개 후속 실행과 INDEX 복구

run4는 QUESTION COMPLETED19/FAILED6으로 정상 terminal 처리됐다. 공개 풀이19개와
문항19개의 Graph 연결을 확인했다. Graph revision은6개이며, 이를 연결 문항6개로
세면 안 된다. 등록된23개 전체의 실제 actor 권한·원본/Native lineage·본문·그림 hash
감사는23 PASS/불일치0이다. 그림 없는 정상 문항도 포함한다. source-catalog의 과거42b2
생성 증거는 그대로 검증했고70 생성본으로 바꿔 부르지 않았다. 감사의 DB/NAS 쓰기와
모델/GPU 호출은0이다.

공식 `recover_native_material_references`로 run5
`materialrun_5657a103ccc4526088ec722ae3abf0e2`를 생성했다. 완료19개의 Item/분석/공개 풀이/
Graph pin은 그대로 상속했고, 원 run4의 state·task pin·기존 accepted-invalid 분석도
바꾸지 않았음을 재대조했다. 새 Prepared3은
artifact_d0f34322fa604d5da7930a4f3c4908f8 / rev_22ef5690195d466ab2b8fc9758bf8c56,
SHA `176c14ecf395e89d07f5aa2da7706cb716d2a05846473eabf8a538fe5afaa2d1`다.
복구 생성 자체의 모델 호출은0이다. Material을 다시 시작했고 실제 슬롯03이 실패분의
새 추출을 실행 중이다. 공식 `MaterialLearningReadService.inspect`의 read-only 조회는
COMPLETED19/REGISTERED4/RUNNING1/PENDING1, Graph 연결19개를 확인했다.

INDEX의19a8 문제도 새 계약이나 직접 row 수정 없이 기존 복구 owner로 처리했다.
원래 READY 기록의 numerical Invocation9b87d014ed4c456e9b9647df639a273d와 실제 grant/input
연결을 검증하고, 그 invocation의 **기존 FAILED retirement**를 찾았다. 현재 unit의 빈
Invocation은 미실행 증거가 아니었다. `recover_retired_indexing_workflow`로 정확한
기존 Workflow/encoding4개의 실제 실패를 기록했고 동일 명령 재전송도 검증했다.
planning SUCCEEDED와 기존 벡터/이력은 불변이다. 명령 SHA는
`241660f998ccb604d2b00a2e5ae48ab3d3972b26acc3306fa519ff8a8131458d`이며 새 계산/서비스
효과는 복구 transaction에서0이다. 같은 INDEX 설정으로 다시 시작해 PID4111864 /
Invocation1186ee5ff1424504bca03dc911cb9f09의 active 상태를 확인했다. 새 수치 완료·인덱스
게시까지 끝났다고 주장하지 않고 계속 관찰한다. QUERY는 원 PID/Invocation을 유지한다.

현재 전체450개 목표는 계속 ACTIVE다. 다음은 run5의6개 완료와 첫 회차25개 실제
조회/Graph 검증, 원래 HTTP 배치 driver의 정확한6실패 successor 채택 후 나머지17회차
입력, 전체450개 및 증분 임베딩 연결이다. 번호250개와 미기입200개 정책도 유지한다.
실패5개를 가정한 이전 초안은 실행하지 않았다.

근거: staging의 `native-reference-recovery-terminal19-20261114.json`,
`native-approved-visual-audit-r3-20261114.jsonl`, `native-reference-recovery-apply-r3-20261114.log`,
`native-reference-run5-public-status-20261114.json`,
`native-gpu19a-original-retirement-probe-20261114.json`,
`native-gpu19a-bound-failure-recovery-{prepare,record}-20261114.log`,
`native-index-post19a-resume-progress-20261114.json`이다. 원본/900분할 파일과 이 검증 기록은
계속 보존하며, 전체450개 등록 완료로 보고하지 않는다.

## 2026-11-14 22:10 UTC — private 실행 모듈 반영·자료 학습 재개

`70bebfb3`의 Catalog/Material과 ROLE Runner4개를 실제로 반영했다. 최종 postdeploy와
resume는 PASS다. Runner별 실제 PID의 source/PYTHONPATH와 immutable import 경로, 정확한
EnvFile 순서 및 설치 파일을 확인했다. 공유 API/Web51과 QUERY pin851·PID3528016은 그대로다.
Catalog PID4082139, Runner PID4082309/4082308/4082307/4082310, 재개한 Material PID4085873이다.
기존 풀이 worker는 강제 중단하지 않았고, 수치 자식 unit의 자연 종료 이후에만 파일을 바꿨다.

도중 GPU busy guard는 파일 교체 전에 기존 서비스를 복구했고, 재시도에서는 수치 공백을
먼저 기다렸다. 빌드 이후 추가된 정확한 문서-only commit3feffe80만 별도로 검증했으며,
runtime source를 최신 HEAD로 대체하지 않았다. systemctl의 EnvFile 값은 실제 줄바꿈 형식으로
검증하도록 도구를 바로잡았다. 실패 로그는 보존했다. 실제 반영은 release_r5.py, 후속 확인·
재개는 release_r6.py(SHA `9c6ad7e38c7da44db64bfa6620bb0a07ea8c794c9066db6e7e55f1a924d3ea76`)다.

22:10 run4는 등록23/base ACCEPTED19/공개 풀이18/Graph5,
QUESTION COMPLETED5/PUBLISHING13/ANALYZING1/FAILED6이다. 새 source의 분석 worker도 실제로
실행 중이다. 22번의 기존 실패는 원 receipt를 해석해 ITEM_ELEMENT13개가 모두
`knode_item_...` alias여서 typed reference에서 제외된 경우임을 확인했다. 새 후보의
타입별 prefix 제약이 정확히 다루는 문제이며, 기존 결과를 rename/성공 처리하지 않았다.
남은 한 문항의 분석·공개 풀이와 batch Graph 게시, 이후 실패6개 공식 복구가 남는다.

INDEX는22:09:57에 다시 종료돼 **현재 GPU 인덱싱 복구가 추가로 필요하다.** 이번 원인은
앞선 systemctl timeout과 달리 `EMBEDDING_BENCHMARK_CHANNEL_EOF`다. 원 CUDA parent19a8의
planning SUCCEEDED를 수치 완료로 읽지 않는다. canonical completion receipt는 없고,
연결된 encoding4개가 RUNNING이며 실제 input-grant 파일도 존재한다. 따라서 숫자 unit이
현재 fresh/inactive라는 사실만으로 NOT_GRANTED/미실행을 단정하지 않는다. 기존 공식
grant·handoff/retirement 경계로 판정한 뒤 복구해야 하며, 무조건 재시작하거나 FAILED/성공을
위조하지 않는다. 앞선 CPU encoding4개는 재계산 없이 저장 단계가 복구되어 해당 head가
1292→1296으로 증가했다. 저장 벡터와 기존 모든 실패 이력은 유지한다.

이 상태는 전체450개 목표 완료가 아니다. 자료 학습을 계속 진행하면서 GPU의 정확한
중단 경계를 별도로 확인한다. 증거는 staging의 `native-picture-completion-release-*r5*`,
`*postdeploy-r6*`, `*resume-r6*`, `native-reference-recovery-progress-installed70-20261114.json`,
`native-new-base-node-diagnostic-r2-20261114.json` 및
`native-index-post-release-invocation-diagnostic-20261114.json`이다.

## 2026-11-14 21:59 UTC — 450문항 그림 전수 검사와 실행 모듈 인계

후보 `70bebfb36738db365a0dcad60c5ca0b8c5f771f9`(tree
`627433425baec57914053177daad4772f495aad9`)를 커밋·푸시하고 별도 immutable SDK와
CPU 그림 도구로 설치했다. 기존 입력 manifest와 18개 MAIN 원본·450개 Native 문항,
분할 receipt를 그대로 사용한 재검사는 **450 PASS / 0 FAIL / BODY picture use373개**다.
04회2번의 BLACK_WHITE 두 사용본과 12회14번의 동일 HWPX 그림 개체5개도 통과했다.
원본 변경·모델/GPU 호출·DB/NAS 쓰기는 이 검사에서 모두0이다. 이것은 등록450개나
한글 육안 검수/교육 품질의 완료가 아니라, 실제 원본 파일·그림 대응의 offline 증거다.

같은 후보는 알려진 그림 해석 예외를 단일 자료의 terminal 실패로 격리하며, 일반 FAILED와
accepted-invalid base가 섞인 공식 복구를 지원한다. 등록 base의 출력 schema와 수신 검증은
기존 public node-type별 ID prefix 및 shared suffix 규칙을 함께 사용한다. v21 원문 지침과
historical proposal/schema bytes는 바꾸지 않았다. disposable PostgreSQL106개 회귀 후
전용 DB/계정을 정리했다. 소스·그림·최종 contextual 검사와 Ruff/format/mypy·wire audit 및
wheel RECORD/import 검사도 통과했다. 실제 보호 Pillow11.3에서는4101색상의 정수식/alpha와
원본 불변을 별도로 확인했다. 소스 gate들에는 중복 검증이 있어 단순 합산하지 않는다.

호환 인계 범위는 private Catalog/Material과 실제 ROLE Runner4개다. API/Web51과 공개
QUERY pin851은 그대로 유지한다. Runner는 공유 runtime.env를 수정하지 않고 마지막의
전용 비밀 없는 EnvFile로 새 immutable prefix를 선택한다. ADMIT 및 migration0079 VERIFY는
PASS다. 이 시각에는 Material이 SIGINT로 정상 종료됐고, 기존 분석 worker1개의 자연 완료를
기다리고 있다. **아직 이 checkpoint를 운영 활성화·새 보고서/Graph 성공으로 읽으면 안 된다.**
첫 helper의 module-file 문맥 오류와 다음 numeric 상태 guard 거절은 파일 교체 전 발생했고
실패 로그를 보존했다. 최종 동결 helper는 release_r3.py, SHA
`79911a0d517410b485f31775a5992777f5a3a6286ca9f388bd3c2166c355ae7f`다.

그 guard에서 확인한 INDEX는 이 배포의 변경 전에21:19 UTC에 별도 종료돼 있었다.
원인은 설치된 e99의 systemctl 상태 관측2/5/10초 timeout 소진
(`LOCAL_INDEXING_RUNTIME_UNAVAILABLE`, local_indexing_runtime:218)이다. 설정/hash/GPU 추론
실패로 확대 해석하지 않는다. manager 정상 응답을 확인하고 같은 설정·같은 서비스로만
재기동했다. 새 PID4017862/Invocation5da1a41838074533a79d088404624fb7은 active이며,
QUERY PID3528016/Invocationd8261930e63649f0bcf1c4e35c2f8fba는 보존했다. 구 실패Invocation과
완료 벡터/원래 CPU 명령은 보존하며, 성공한 계산을 새 계산으로 우회하지 않는다.

21:47 실제 run4 관측은 등록21/accepted base18/공개 풀이17/Graph5, 실패6개다.
기존 실패5개 외에22번의 분석 실패가 추가됐으므로, 실패5개/완료20개로 고정한 복구 초안은
**실행하지 않는다.** 새 원인과 최종 terminal 집합을 확인한 뒤 지원된 successor를 적용한다.
전체450개 등록·공개 풀이·공통 Graph·증분 임베딩과 실제 조회의 목표는 계속 ACTIVE다.

근거: staging의 `native-body-picture-450-r2-qualification-20261114.log`,
`native-picture-completion-release-{prepare,admit,activate}-r3-20261114.log`,
`native-index-current-invocation-diagnostic-r2-20261114.json` 및 같은 시각의 운영 기록.
전수 summary SHA는 `3f8815db22cbca628a7403aafa19d54306bafafdc65285f3acd4b18f11b1ecd3`다.
이 로그·원본·생성 파일·대기 중인 인증 입력은 Git에 넣지 않는다.

## 2026-11-14 19:38 UTC — 좁은 호환 배포와 실제 처리 재개

Catalog private receiver와 Material owner를 `9c5b4bb790eae9db472357217b0d5afb9a4b37dc`
(tree `b7f4e3a748e0a3c7e1c44fbcb24d309ec3f04e5b`)로 반영했다. CPU 그림 도구는 별도
고정 설치 `2e5e585db7bbf5ac9572d4aed993637e32c89661`이며, signed resize-box의 부호와
명시 bitmap flip을 구분한다. context1.24 ADMIT와 migration0079 VERIFY는 실제 PASS다.
패키지 검사는 immutable0444 설치 파일을 변경하지 않고 private0600 검증 입력으로만
일시 materialize했다. 첫 사전 검사 실패와 GPU batch 경계 대기는 보존했으며, 그때는
운영 파일 교체 전이었다. 실제 반영은 자연스러운 수치 작업 공백에서 수행했다.

API/Web·global runner, INDEX/QUERY 설정과 프로세스는 보존했다. 반영 후 실제
INDEX PID3532049/Invocation1d8e6e31400940d6b09dae42fdf94236 및 QUERY
PID3528016/Invocationd8261930e63649f0bcf1c4e35c2f8fba가 동일함을 확인했다.
Material은 active이며 원래 run4의 다음 QUESTION 추출 workflow가 실제 RUNNING이다.
문제의 기존 accepted base는 수정하지 않고 typed 근거 오류로 해당 task만 FAILED가 됐다.

19:38 관측: QUESTION COMPLETED5/PUBLISHING8/RUNNING1/PENDING8/FAILED3,
등록14/accepted base14/공개 풀이13/Graph5다. 실패3에는 원래 그림 실패2와 근거 오류1이
포함된다. PREPARE/DISCOVER 완료7을 문항 완료 수에 더하지 않는다. 다음은 run4의
자연스러운 terminal 상태 후 공식 Prepared3/reference successor로 실패3만 복구하는 것이다.
전체450개 처리·임베딩 완료나 첫25개 완주를 아직 주장하지 않는다. 권한/수식/편집 가능한
원본 보존과 실제 DB/native 읽기 검증은 계속한다. disposable DB103개 검증 후 임시 DB와
그 전용 계정을 공식 guarded cleanup으로 제거했으며 운영 데이터는 삭제하지 않았다.

근거: staging의 `native-reference-recovery-release-{prepare-r2,admit,activate-r4,postdeploy}`
로그 및 `native-reference-recovery-progress-20261114T1940.json`(실제 관측19:38 UTC).
최종 동결 배포 helper SHA는 `32d4eedb736e415181a875a019e03ea4508b6aba993198d420872f8afe1087e8`다.
이 파일들은 로컬 검증 산출물이며 Git에는 넣지 않는다.

## 2026-11-14 19:18 UTC — 그림 검증 완료, 근거 복구 후보 검증

`2e5e585d`의 별도 CPU 설치본은 실제 첫25개 BODY 그림 범위 대응을 통과했다.
9번·13번 최종 PNG를 직접 열어 원본의 글자·축·방향이 뒤집히지 않았음을 확인했다.
source와 Native 두 decoder의 일치뿐 아니라 원 embedded PNG와 실제 출력의 방향을
대조했으며, 기존 승인14개의 그림·내용·lineage 감사도 모두 PASS다. 한글에서 직접
열어 본 사용자 육안 검수나 전체450개 등록·임베딩 완료를 뜻하지 않는다.

승인 전 locator/excerpt 검증, 같은 Item의 accepted-invalid base 전용 후속 분석과
visual/reference 복합 successor를 기존 Catalog/Material owner에 추가했다. 기존 accepted
결과·task pin·일반 retry는 그대로다. 새 schema/HTTP/worker protocol/migration은 없다.
source 관련925 PASS, 별도 그림237 PASS, 공식 disposable PostgreSQL의 Material 저장·
동시성·재전송103 PASS, core5개 mypy·Ruff/format·wire mirror 검사가 PASS다.
DB 검사는 운영 DB에서 하지 않았고, 실제 모델/등록/Graph 실행의 증거로 대체하지 않는다.

아직 이 후보의 Catalog/Material 운영 활성화와 기존 run4 재개는 하지 않았다.
현재 Material은 앞선 오류 반복을 멈춘 상태이며 API/Web/INDEX/QUERY는 보존 중이다.
다음은 호환 설치·실제 기존 작업 재개 후 새 보고서/Graph와 명시적 후속 run을 검증하는 것이다.
전체450개 목표는 ACTIVE다.

## 2026-11-14 18:48 UTC — Native 원본 검증과 현재 처리 중단 원인

목표는 계속 ACTIVE이며 전체450문항 완료를 주장하지 않는다. 첫 회차에서 등록14개,
accepted base14개, 공개 풀이13개, Graph 연결5개를18:25 UTC에 관측했다. 9번·13번의
과거 추출 실패와 나머지9개 QUESTION 대기는 보존한다. Native 문제/해설900개와
Excel18개의 준비가 운영 Item450개 완료를 뜻하지 않는다.

- 실제 첫25개 BODY 그림을 원본 raster의 pixel·viewport·use와 대조한다. EMF 제목 장식이나
  ZIP의 미참조 member는 본문 그림이 아니다. scope/Prepared3 및 per-book index를 커밋했다.
  CPU tool/SDK의 `2b66d109` 후보는 구조상25개 대응은 통과했지만 직접 PNG를 열어보니
  음수 scale의 과도한 반사 해석이 글자를 뒤집었다. **운영 비활성 상태로 보존**하고
  signed resize-box와 명시 bitmap flip을 구분하는 최종 수정을 검증 중이다.
- 기존 승인14개는 실제 actor 권한과 공식 Native/Registry/accepted-result 읽기로
  본문 use 범위·등록 이미지·원 content hash·lineage를 대조해 모두 PASS다. 첫 감사의
  Role envelope/learning-result hash 혼동은 도구에서만 수정하고 첫 로그와 Item은 보존했다.
  Graph/교육 품질 검수까지 했다고 주장하지 않는다.
- 14번째 등록 문항(원문16번)은 기본 분석 ACCEPTED 뒤 공개 풀이 준비에서
  `KNOWLEDGE_ANALYSIS_BASE_INVALID`로 자동 재시작을 반복했다.18:30 UTC경 Material만
  정상 정지했다. read-only 진단은 원본/Artifact/receipt 해시가 아니라 모델이 선언한
  13개 anchor 중 `solution` 발췌 해시1개의 불일치를 확인했다. 개념 노드가 모두 그
  anchor만 참조하므로 해시/역할 검증을 완화해 우회하지 않고 공식 후속 분석을 준비한다.
- API/Web·global runner와 Catalog는51, private Material은0f282 설치를 유지한다.
  새 CPU tool/SDK는 별도 prefix에만 준비했다. INDEX/QUERY의 PID·Invocation·수치
  runtime은 보존한다.18:26 UTC에 CPU/CUDA 실행과 이전 CUDA 완료를 확인했으며
  bounded window의 encoding 수를450개 전체 coverage로 합산하지 않는다.

다음은 원본 그림 방향의 실제 픽셀 검증, 승인 전 발췌 검증 및 사용불가 accepted base의
공식 복구, Catalog·Material만의 호환 반영과 원래 작업 재개다. 성공 task·정본·실패 이력은
유지하며 전체450개·실제 자료 조회·공통 Graph·증분 INDEX 검증까지 계속한다.

## 사용자 지정 후속 순서

현재 자료 학습의 구현·검증·운영 배포와 실제 동작 확인을 먼저 완료한다. 그 뒤에 Map에서
DB의 출처 Layer(교과서·기출·창작·AI·외부)를 쉽게 볼 수 있도록 개선한다. Map 작업은
아직 시작하지 않았다. 기존 source layer/색/필터 기반과 클라이언트에 이미 불러온 일부
노드에만 적용되는 현재 필터의 한계를 확인했으며, 새 독립 Graph나 가짜 등록 노드를
만들지 않는 기존 read 경계를 유지한다. Graph 미등록 원본과 실제 Graph membership을
구분한다. 이 후속 작업을 현재 운영 배포보다 먼저 수행하지 않는다.

## 최신 운영 checkpoint

09:08 UTC: 새 CUDA 요청 `workflow_322c3516a2b448dfaa0bfd243aaf801f`와 command
`wfcmd_bd16d3b306f6447ea614383985cefd5f`가 실제 RUNNING/PROCESSING이고 error는 없다.
자료 학습 구현·호환 운영 배포·제한된 실제 canary·INDEX handoff 검증을 완료한다.
전체 임베딩과 원본 보류 재확인은 기존 서비스/10분 timer로 계속하며 Map은 별도 후속이다.

09:01 UTC: 실제 작은 PDF의 전체 run·문항/설명 task가 COMPLETED이고, 문항 Registry·
accepted base/V11 풀이·공유 Graph·DB 외부 목록·공식 문항/설명 RAG 및 동일 요청
replay를 확인했다. V11 metadata bulk prefetch 결함도 수정해 같은 운영 문항의 strict
public capture·공통 GPU encoding 입력 준비가 PASS다. API/platform/Catalog/QUERY
provider의 fedb9750 호환 배포와 INDEX의 공식 source successor 인계를 완료했다.
Web은 공개 계약/asset이 같은 e1df5c8f를 재사용했으며 material/창작 process는 보존했다.
INDEX는 active로 다음 source 준비를 진행 중이고10분 관측·Slack 정상 전송을 확인했다.
전체 corpus vector 완료나 인증 브라우저/교육 품질 수동 확인을 주장하지 않는다.
최종 실제 실행 상태는 [운영 반영 기록](MATERIAL_LEARNING_RELEASE_2026-11-06.md)을 우선한다.

### 08:01 UTC 과거 source checkpoint

08:01 UTC: 기존 compatible API/Web/Runner와 head0074, material 전용493144f8은 실제
운영 반영됐다. 실제 canary에서 발견·문항 Registry·base 분석·V11 공개 풀이 및 공통
embedding text AVAILABLE을 확인했다. 설명은 공유 Graph 및 공식 RAG evidence V6
조회/동일 요청 replay까지 PASS다. 문항은 공유 Graph PUBLISHING이며, DB 목록/INDEX
최종 연결 확인은 아직 남았다. 실제 HTTPS 인증 사용자의 육안 확인은 미기록이다.
Map은 사용자 지정 순서대로 계속 대기한다. 아래는 시간순 과거 구현 기록이며 최신
설치물/실제 결과는 운영 반영 문서를 우선한다.

### 2026-11-06 운영 단계 갱신

API·Web·Catalog·global Runner와 창작 producer는 `e1df5c8f`로 호환 배포했고 production
head0074와 공식 control release까지 반영했다. 실제2쪽 canary 접수·재전송·페이지 준비와
typed read는 PASS, 실제 DISCOVER가03번 slot의 Job/lease를 받아 RUNNING이다. 아직
INDEX source 인계·coordinator 자동 활성화·문항/설명 Graph·임베딩 handoff 완주는 남았다.
따라서 아래 ‘production 변경0’ 문구는 **이전 source checkpoint 당시**의 기록이다.
현재 상태와 정확한 설치/복구 증거는
[운영 반영 기록](MATERIAL_LEARNING_RELEASE_2026-11-06.md)을 우선한다. 목표는 계속ACTIVE다.

후속 실제 결과: INDEX는 자연 종료→공식 후속 identity/config→e1df5c8f 기동을 완료했다.
DISCOVER 모델도 실제 성공했지만 기존 file-set 전용 포트를 잘못 사용한 결과 reader가
single-primary Artifact를 읽지 못했다. 기존 verified JSON primary 포트 재사용으로 수정하고
실제 writer/reader 회귀70 PASS·임시 DB41 PASS를 확인했다. material owner만 후속 호환
prefix로 반영해 같은 성공 Artifact를 재조회한다. 기존 API/Web/QUERY/INDEX는 유지한다.

### 공식 배포 경계 누락 보완

최종 8b4632d8 API/Web source-free wheel과 보호된 후보 prefix 준비는 PASS다. 운영
migration 0074의 임시 DB 검사는 통과했지만 기존 release operator는 0073까지만 허용함을
배포 전 발견했다. 새 context/admission 1.21·0073→0074 고정 callback을 schema-first로
추가하고 이전 schema/callback은 보존한다. 관련 회귀102 PASS, type/lint/shell parsing
PASS다. 이 후속 변경을 포함한 최종 commit/wheel을 새로 고정하며, 8b 후보를 최종 운영
release로 잘못 표시하지 않는다. 실제 운영은 아직0073이고 feature 활성화·모델 canary는0이다.

### 실패 단위 복구·위치 조회 — 최신 후보

- 새 retry/task-detail JSON Schema 2020-12와 Pydantic/API/BFF/GUI를 연결했다. 실패한
  run/task는 그대로 두고 같은 자료 revision의 successor를 만든다. 이미 끝난 준비·문항·
  추출/등록과 accepted base는 재사용하며, 새 시도가 필요한 단위만 기존 owner로 제출한다.
  기존 child Workflow/analysis의 unique owner를 복사하거나 실패를 성공으로 바꾸지 않는다.
- 실제 임시 PostgreSQL에서 동시 retry 한 건 생성·동일 요청 재조회·transaction 중단 후
  재시도·준비 Artifact 재사용과 다음 READY 입력 생성·현재 actor의 파일/페이지 열람을
  확인했다. 전역 command 수는 retry 자체로 늘지 않는다. predecessor는 batch 한 번의
  recursive query로 읽고, 기존 history 변경은 DB trigger와 source read 양쪽에서 거부한다.
- 조회 화면에서 `오류 난 부분 다시 처리`, `위치·오류 확인`, `2차 처리`를 표시한다.
  별도 업로드 없이 source 파일·실제 페이지·문항 번호를 읽으며 source filename을 HTML로
  해석하지 않는다. 완료 task를 routine poll에서 새로 읽거나 source 전체를 재복사하지 않는다.
- 직접 API 및 BFF actor/CSRF/key·identity 검사, accepted base/공개 풀이 재사용 판단,
  살아 있는 child/held lease 차단과 dependency/resource/context/alignment 집중 검사
  **98 PASS**, 확장된 material/source/dependency/alignment suite **284 PASS**.
  opt-in browser1 skip은 별도 실제 Chromium PASS로 구분한다. 핵심17개
  source mypy PASS. 최종 source-free wheel은 이 새 diff로 다시 검사한다.
- 최신 material persistence suite **41 PASS**. 암호화/페이지 제한 자료를 terminal로
  남긴 뒤 다음 자료 준비가 실제로 진행되며, 단원 힌트가 비어 있는 GUI 기본 입력도
  같은 공유 Graph/RAG로 연결된다. 검사 로그는
  `/tmp/material-learning-retry-db-20261106-7.log`,
  `/tmp/material-learning-retry-final-focused-20261106-3.log`,
  `/tmp/material-learning-retry-browser-20261106-2.log`다.
- 준비가 끝나지 않은 원본 문제와 구조 EXCEPTION은 자동 retry 대상이 아니다. 암호화·
  페이지/렌더링 한도는 해당 자료의 FAILED로 기록하고 다음 자료는 계속 처리한다.
  profile/hash/권한/일반 코드 오류를 원본 문제로 뭉개지 않는다. 실제 임시 DB의 원본
  예외 및 다음 자료 진행 회귀와 최신 전체 결과는 최종 release 기록에서 확인한다.
- 다음은 최종 wheel·권한/호환 release 및 실제 업로드 canary다. 새 Graph V10 활성화
  전에 INDEX source 소비 경계를 정렬하며 기존 numerical pin/실행은 보존한다. Goal 종료
  뒤에도 background owner·감시 timer를 유지한다. 아직 production migration/feature 배포/모델
  canary는0이며 goal은 ACTIVE다. 아래 예전 ‘실패 단위 retry 미구현’ 기록은 이 후보로 대체한다.

### 가변 자료 배치의 프롬프트 보강

사용자 질문을 반영해 기존 DISCOVER/EXTRACT_ITEM 역할 지침을 보강했다. 고정 양식을
가정하지 않고 실제 페이지 그림에서 다단·공통 자료/소문항·예제·정답표·번호 재시작·
뒤쪽/별도 해설을 구분한다. 관측하지 못한 단원/번호나 해설 대응을 만들어 채우지 않는다.
별도 설명 분석은 줄글뿐 아니라 표·수식·그림/캡션·탐구도 원문 근거로 읽고 옆 문항의
정답을 일반 개념 설명으로 섞지 않는다. 새 프롬프트·기존 역할/실행·단위 대응 회귀
**74 PASS**, prompt 모듈 mypy PASS다. 실제 모델 레이아웃 정확도나 운영 활성화 PASS는
아니며 최종 canary와 installed control/instruction hash 검증이 남는다.

### 실제 저장소 통합 검사 — 2026-11-06 후속

- marker-guarded 임시 PostgreSQL에서 실제 원본 접수·Document 등록·분석 수락·공유
  Graph append·RAG evidence 생성과 같은 요청 재전송까지 확인했다. 합성인 것은
  모델 응답이며, Graph/Artifact/권한/분석 수락을 가짜 객체로 대체하지 않았다.
- 이 검사로 교과서 전용 구조 V2에 설명을 추가할 때 무조건 구조 V6 publication을
  요청하던 실제 불일치를 발견했다. 미출시 snapshot V10은 정확한 기존 구조 V2–V6를
  보존하고 해당 공식 publication을 선택한다. 가짜 기출·문항 placement를 만들거나
  구 snapshot/structure bytes를 변경하지 않는다. 이전 snapshot의 source membership도
  그대로 읽히는 것을 확인했다.
- 새 일반형 `assessment-item-content/1.0` 문항을 실제 Registry에 등록하고, 실제 base
  accepted analysis → 별도 V11 공개 풀이 수락 → 공통 public-solution-text projection까지
  확인했다. 원문 정답·문항을 덮지 않고 같은 등록·풀이 명령은 기존 결과를 재사용한다.
  등록 입력의 완료 role/source port는 명시적 합성 fixture이므로 실제 worker/원본 권한
  검증 전체나 수치 GPU 임베딩 완료로 확대 해석하지 않는다.
- 현재 material persistence suite **35 PASS**, Graph/source/RAG/공개 풀이/context 집중
  unit suite **77 PASS**, 별도 설치 resource·구 계약·runtime/창작 대기 회귀 **82 PASS**,
  수정한 핵심 세 모듈 mypy PASS. 범위가 겹치므로 합산하지 않는다. 최신 로그는
  `/tmp/material-learning-graph-db-20261106-10.log`,
  `/tmp/material-graph-final-unit-20261106-1.log`,
  `/tmp/material-graph-final-contracts-20261106-1.log`다. 테스트 fixture의 초기 오류·실패 로그도
  보존하며 운영 DB를 테스트 대상으로 쓰지 않았다.
- 다음은 실패 단위의 공식 retry/예외 조회와 최종 설치본·runtime/control 호환 배포다.
  기존 INDEX source 소비 경계가 새 Graph V10을 이해하게 정렬되기 전에는 새 Graph를
  운영에 publish하지 않는다. 운영 migration/feature 배포/실제 학습 canary는 아직0이다.
- 사용자 추가 지시대로 목표 완료 뒤에도 배경 owner와 감시 timer를 유지한다. 처리할
  자료가 없는 슬롯은 점유하지 않으며, 원본 보류를 작업 성공이나 실행 중으로 표시하지 않는다.

### 설치본 실행 확인 — source `897a2468`

- API full source-free wheel/RECORD·모든 historical Workflow/신규 material/knowledge12
  admission 검사 PASS. Web wheel 실제 설치 simulation PASS(62파일).
- 새 root-owned 후보 prefix에서 실제 eom-image systemd sandbox로 synthetic PDF의
  page inspect/text/PNG/OCR PASS(180dpi,1페이지). root로 PDF를 파싱하거나 NAS에
  원본 사본을 추가하지 않았다. 임시 입력의 권한만 정확한 read-only bind용으로 넘겼다.
- 실제 Catalog-manager UID와 고정 Office unit으로 staging의 기존 HWPX→PDF PASS.
  완료 결과 재조회도 동일 identity이며 원본 hash는 불변이다. 첫 시도에서 새 prefix의
  부모가 root umask 때문에0700이던 release staging 문제를 확인해 그 새 directory만
 0755로 바로잡았다. 기존 converter/staging 권한 검사를 완화하지 않았다. 실패 로그 보존.
- 위 검증은 production application 배포/자료학습 모델 실행이 아니다(둘 다 아직0).
  기존 서비스/수치 runtime 설정은 변경하지 않고 새 prefix·wheel만 보호 저장소에 준비했다.
- 중단/재개를 포함한 실제 임시 DB33 PASS, 관련 source319 PASS, 별도 BFF/브라우저와
  installed version gate49 PASS를 참고한다. 중복 범위는 합산하지 않는다.

다음은 final runtime/control pin preflight→0074/권한·호환 API/Web/runner 배포→공식
실제 업로드의 Item/설명·공유 Graph/INDEX handoff다. 새 Graph10을 모르는 기존 INDEX
entry의 source 소비 경계도 수치 작업의 안전한 인계 시점에 정렬해야 한다. 단순 서비스
READY를 이 마지막 사용자 경로 성공 증거로 쓰지 않는다.

- 새 업로드 문항은 사용자 결정대로 **외부 / EXTERNAL**이다. 기존 Notion 창작과
  기출·AI를 바꾸지 않는다. DB 목록/상세에 자료명·원본 파일·페이지·자료 내 번호·목차를
  표시하며 가짜 5자리 번호를 만들지 않는다. 같은 Graph의 Map V2가 외부 layer를 표현하고
  released V1 bytes는 유지한다. BFF는 독립된 작은 DTO로 읽으며 backend package를
  Web runtime에 추가 의존성으로 넣지 않는다.
- 완료 role 결과의 실제 Job/Workflow/plan/Artifact closure reader, source-fidelity
  Registry 등록, PDF 그림과 native picture-use resolver, 별도 실제 base/V11 공개 풀이,
  document V12→공유 Graph publication과 단일 AI lane coordinator를 연결했다.
- 자료 설명 source V5는 공식 retrieval owner의 명시적 `create_material_evidence`에서
  Evidence V6로 읽는다. released 소비자는 V5를 모르는 채 V6를 받지 않는다. 이것은 모든
  과거 authoring/chat consumer를 자동 업그레이드했다는 뜻이 아니다. 실제 RAG 읽기와
  소비 가능 범위는 최종 canary에서 구분해 기록한다.
- control capacity V7은 같은 물리 03–06/host 동시4를 공유한다. 같은 control bundle을
  동시 최초 등록할 때의 충돌을 실제 임시 DB에서 재현해 lifecycle owner 잠금으로
  수정했다. explanation 생성도 같은 key를 동시에 보내면 충돌하던 것을 실제 재현한 뒤
  기존 knowledge-analysis owner에서 key 잠금→원래 자식 재조회로 수정했다.
- source/권한/그림/계약/API/BFF/기존 공개 풀이 회귀 261 PASS(그 시점 browser opt-in1 skip).
  후속 소비 경계 suite69 PASS, runtime/control/소비 집중 suite47 PASS. 서로 겹치는 수를
  합산하지 않는다. 명시적 실제 Chromium의 업로드·재전송·owner 전환과 DB 외부 상세 화면은
  별도로 PASS다. 주요 새 source17개 mypy PASS, 변경 Python formatter/linter PASS.
- 새 marker-guarded PostgreSQL에서 candidate0074 upgrade/downgrade/upgrade PASS.
  최신 저장/Workflow/권한/동시 control release/준비 중단 복구/설명 자식 원자 연결/
  Registry commit 후 중단·재전송/동시 등록 **32 PASS**. worker 결과·extractor는 명시적
  합성 port이며 운영 모델 실행이나 전체 실제 source 권한 증거로 확대 해석하지 않는다.
- source-free platform wheel/resource/RECORD·개발 context suite44 PASS. API OpenAPI를
  다시 생성했다. 최종 API/Web 호환 release wheel 검증은 마지막 runtime 수정 후 재실행한다.

### 다음 완료 경계

후속 후보: GUI pause/resume→BFF→API→Catalog 실제 control을 연결했다. updated_at fence와
동시 pause·같은 action 재조회·오래된 반대 action 거부를 임시 DB에서 검증했다(최신33 PASS).
자료 owner는 별도 WorkflowRuntime을 만들지 않고 운영 global Runner를 사용한다. 실제
Chromium에서 중단/재개와 원래 업로드 재전송·owner 전환 PASS. source 회귀319 PASS 및
추가 BFF/설치 gate 회귀111 PASS(범위 중복/브라우저 별도). installed API build에서 실제로
드러난 신규 material/knowledge12 정의 staging 누락도 기존 release inspector에서 수정했다.
이후 실제 role/registry/public solution/Graph/INDEX canary와 최종 운영 배포가 남는다.

현재 INDEX producer entry525ae472의 설치본은 새 Graph10/material source를 아직 모른다.
새 Graph를 활성화하기 전에 이 소비 경계도 호환 prefix로 정렬해야 한다. 기존 numerical
GPU runtime/진행 요청은 그대로 두고, 현재 준비/수치 작업의 안전한 경계에서 owner source만
인계한다. 옛 producer가 새 Graph를 읽을 수 있다고 가정해 먼저 publication하지 않는다.

1. 앞서 source897a2468의 실제 격리 PDF·Catalog-owner Office port는 PASS다. 그 이후의
   복구/조회/Graph 후보를 포함한 최종 installed wheel/RECORD와 runtime/control 조합을
   다시 확인한다. root/Catalog-manager 소유 경계를 권한 완화/임의 path로 덮지 않는다.
2. GUI pause/resume와 실패 단위 successor/attempt·예외 위치 조회는 위 최신 후보로
   완료했다. 최종 운영 설치본에서 실제 role/출처/등록·공개 풀이 흐름을 확인한다.
3. 실제 worker-facing 입력·결과부터 Registry/Document/공유 Graph/공통 INDEX handoff,
   공식 RAG 읽기·DB 열람·같은 요청 재조회를 한 bounded 업로드 경로로 검증한다.
4. 최종 wheel/권한/호환 rollback 검증, 기존 역할 자연 drain, helper와 영향 driver prefix
   동시 정렬, migration0074/필요한 grants/정책·서비스·API/Web 배포 및 실제 canary가 남았다.
   이 feature의 운영 migration·배포·실제 모델 실행은 아직0이며 goal은 ACTIVE다.
5. 완료 뒤에도 기존 창작·임베딩 서비스를 유지한다. 아래 background recovery의 실제
   수치 진행까지 확인해야 하며 service active만으로 완료하지 않는다.

### 현재 별도 배경 작업

후속 운영 확인: 기존 protected numeric retirement를 직접 확인했다. 원래 numerical unit의
FAILED retirement가 이미 존재해 새 unit effect 없이 공식
`recover_retired_indexing_workflow`로 원래 Workflow/native Job/encoding4건의 실패를
원자적으로 기록했다. SUCCEEDED planning/정본/수치 runtime pin은 그대로다. INDEX owner는
같은 invocation에서 다시 source 준비를 진행 중이며 새 CUDA 수치 완료는 아직 미확인이다.
기존 창작 owner는 03:07 UTC에 남은 원본 미리보기 준비 대기(`BLOCKED_SOURCES`)를
technical failure로 처리해 종료했다. 입력 대기를 worker 성공으로 바꾸지 않고 5분 간격으로
정상 대기하도록 후보를 수정·검증 중이다. 따라서 아래 02:53의 실행 중 관측을 현재
슬롯 실행 증거로 재사용하지 않는다. 완료 전 실제 남은 대상/활성 lease를 다시 확인한다.

최신 candidate source gate313 PASS/별도 실제 Chromium PASS, parser command port와
Office owner schema/adapter 회귀39 PASS, core source51개 mypy PASS. counts는 서로 겹친다.
PDF parser는 정확한 파일을 기존 eom-image sandbox에 readonly bind하며 root parsing과
페이지별 전체 원본 재복사를 피한다. 한글은 실제 Catalog-manager helper로 기존 고정
workspace/converter를 호출한다. 아직 이 adapter의 실제 설치/실행 PASS를 주장하지 않는다.

기존 창작 producer는 같은 PID/invocation으로 계속 실행되며 11월6일02:53 UTC에도 새
VERIFIED/PROCESSING checkpoint가 관측됐다. GPU INDEX는 11월5일22:24 UTC channel EOF로
종료돼 있었다. 기존 설정/수치 runtime/요청/실패 이력을 수정하지 않고 기존 INDEX service만
02:52 UTC에 시작했다. 재기동은 성공했지만 원래 CONCRETE_FACETS Workflow에
`RECOVERY_REQUIRED`가 남아 있고 GPU compute process는 아직 없다. **연산 복구 완료가
아니다.** 공식 recovery 확인이 남는다. diagnostic의 가장 안쪽 BlockingIOError만으로
현재 read-loop 결함을 단정하지 않는다(실제 설치 read-loop에도 해당 예외 처리가 있음).

## 앞선 2026-11-05 기록

아래는 그 시점의 후보/검증/다음 단계다. 최신 미완료 범위와 background 상태는 위를 따른다.

## 완료한 소스 후보

- D0 설계 후 R1·R2 검토와 D2 반영. 기존 교과서 구매 권리/기출 occurrence/Notion
  출처를 일반 자료에 만들어 넣지 않는다.
- `679e48c1`, `bdfb23e7`, `a349b143`, `df7419fb`, `acde0850`: 기본 계약·wheel 경계,
  실제 형식 기반 업로드, 작은 진행 상태, 긴 자료 준비/재개·공식 Document 등록,
  원래 Workflow/command/Job/slot/Artifact owner를 통한 발견·추출 실행 후보.
- 일반 설명은 source V5/request·result V12/receipt V11/role 1.38/plan V34로 기존
  knowledge-analysis·risk·proposal·shared Graph projection에 연결했다. 안정된
  proposal V6의 개념·관계 identity를 재사용한다. snapshot V10은 같은 Graph와 구조 V6를
  사용하며, 구 snapshot bytes를 수정하지 않는다.
- Catalog가 실제 저장된 child/업로더를 기준으로 원본·권리·문서·page chunk·선택 범위와
  현재 권한을 재인가한다. Worker는 로컬 staged PNG/text만 받는다. V34도 준비 후 실행,
  결과 commit 직전의 source fence를 통과해야 한다. 임의 actor 입력은 없다.
- page reader를 준비된 자료·canonical Document 양쪽의 공식 읽기에 재사용한다.
  선택 chunk당 한 번 읽고 페이지는 이분 탐색한다. child Workflow/analysis는 partial
  unique indexed lookup이다. 자료 role output은 NAS Artifact이고 DB에는 작은 receipt만 둔다.
- 일반 문항용 source-lineage 계약과 기존 Registry용 등록 Pack 후보를 추가했다.
  독립 풀이로 원문 정답을 바꾸지 않는 compiler와 native picture-use pointer resolver를
  공유한다. 이것은 실제 Item 등록/공개 풀이/INDEX 완료 증거가 아니다.

## 이번 checkpoint 검증

- 관련 schema/model, 실행 fence, 지식 staging, Graph projection/structure, 기존 resolver/
  materializer, 한글 picture-use, 원문 보존, 조회·runner source 회귀: **256 PASS**.
- 위 범위에는 일반 문항 lineage/Pack/compiler/native pointer 계약 **4 PASS**도 포함된다.
- 주요 후보 source 20개 mypy PASS. 전체 변경 Python formatter/linter를 적용한다.
- 공식 marker-guarded 새 disposable PostgreSQL의 candidate migration 0074 왕복과
  role/Workflow/task/intake/page 준비·재개·유일성/동시성: **25 PASS**.
- 앞선 package/설치 resource·의존 경계/계약 보존 suite **20 PASS**. 새 후속 diff의 최종
  전체 wheel/release 검증은 배포 전에 다시 한다.
- fixture는 가상 worker/제한된 로컬 파일 및 실제 임시 DB를 사용했다. 운영 DB를 pytest
  대상으로 쓰지 않았다. 아직 이 기능의 실제 모델/GPU 실행·운영 migration/배포는 0이다.

상세 로그는 Git에 넣지 않고 임시 작업 증거로 유지한다. 실패한 초기 schema reference/
fixture 실행도 성공으로 바꾸지 않았다. 최종 운영 보고서는 별도로 작성한다.

## 반드시 남은 일

1. 일반 설명 source의 retrieval/evidence 소비 연결과 공유 Graph 증분 publication을
   완성한다. source V5를 구 licensed bundle로 위장하거나 구 consumer에 억지로 넣지 않는다.
2. material task의 실제 완료 result를 읽어 Registry 등록·공개 풀이·Graph 및 기존 common
   incremental INDEX에 연결한다. native 그림/PDF 그림과 원문 위치, source quality 경고,
   창작/AI 구분 및 DB 조회를 유지한다.
3. bounded coordinator/설정·control release·한 AI lane/전역 capacity 4, pause/retry/replay,
   중단 시 기존 child 재조회를 구현·검증한다. 준비/등록/Graph 중 슬롯을 잡아두지 않는다.
4. schema/DB/중단·재전송·권한·실제 browser·source-free wheel 및 호환 release/rollback을
   검증한 뒤 운영에 배포한다. 0074는 아직 production 미적용이며 현재 head는 0073이다.
5. actual actor로 제한된 자료의 업로드→내용/문항→Graph→INDEX handoff와 같은 요청 재조회를
   확인한다. 결과 없는 health/READY를 실제 학습 성공으로 보고하지 않는다.

## 보존 및 배포 주의

기존 창작 producer와 GPU INDEX 실행은 계속 유지 중이다. 마지막 확인 22:16 UTC에
실제 worker lease 4개와 동일 producer/INDEX PID·invocation을 확인했다. 운영 분류의
source 보류 수는 36이며 이번 개발에서 수정하거나 성공으로 재해석하지 않았다.

새 image input V5 parser 때문에 protected worker helper의 hash가 바뀐다. 최종 배포는
진행 중 Codex 역할을 자연 완료시킨 뒤 helper와 영향을 받는 driver/runner prefix를
호환 set으로 맞춘다. 모델·입력·기존 cohort/실패 이력은 보존한다. 별도 numeric GPU INDEX는
같은 실행을 유지하며, 새 권리 정책으로 기존 RAG access policy를 조용히 확장하지 않는다.
