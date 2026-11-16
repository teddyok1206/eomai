# 자료 학습 구현 checkpoint

2026-11-06 UTC. 사용자의 최종 범위는 운영 배포·제한된 실제 업로드 처리 확인까지다.
goal 카드의 초기 배포 금지 문구는 후속 사용자 지시로 대체됐다. 구현 중간 기록은 보존하며,
최종 운영 결과와 검증 한계는 [운영 반영 기록](MATERIAL_LEARNING_RELEASE_2026-11-06.md)을
우선한다. 전 corpus의 임베딩 완료를 뜻하지 않는다.

## 2026-11-16 00:11 UTC — 실제 원본 읽기 통과, canonical1.1의 풀이 소비 경계 수정

회차3의 새11번(고유번호78612)을 실제 installed owner로 읽었다. 원문2점과 canonical1.0의
2점이 일치하고 문제·해설 HWPX의 bytes/SHA 및 native section을 확인했다. 엑셀 worksheet/
row/hash와 원본 단원도 연결되어 있다. 원본을 PDF로 재생성/캡처하지 않았다. 실제 모델의
base/public 풀이를 마쳐 PUBLISHING이 됐고 다음 문항으로 진행했다. 아직25개 window의
Graph 게시나 이 문항의 vector commit 완료 증거는 아니다.

다음12번은 실제 원문1.5점/canonical1.1/1.5점 등록·두 native 문서 읽기까지 PASS였지만
기존 Knowledge source resolver가 `Item Revision content component is incompatible`로
거절했다. 중복 관리하던 canonical ref 목록에1.1이 빠진 실제 소비 결함이다. Material의
자동 재시작을 멈췄고 같은 registered task/Item은 보존했다. 실제 readonly 진단은
`staging/native-score-half-read-before-fix-20261116.json`에 있다.

source resolver는 공통 canonical reader의 불변 schema mapping을 재사용하도록 수정했다.
처음 end-to-end disposable 검사에서는1.1의 공개 풀이 reference field 분류도 빠져 있음을
발견했고, block1.0/1.1에 같은 frozen field tuple을 연결했다. 양쪽 wire/schema bytes·권한·
Artifact 검증이나 정본은 바꾸지 않는다. 최종 Material suite145 PASS(새 Native 세 배점의
등록→base/public 풀이→strict read→embedding-text 포함), control2 PASS, Workflow4 PASS다.
실제 AI 추론을 했다는 테스트가 아니며 전체450개의 운영 완료로 대체하지 않는다. 실패한
첫 fixture run2건도 보존했다. 수정본의 설치·같은12번 재개 및 실제 풀이 승인은 다음이다.

INDEX 원래 invocation7126e44f…는 CUDA4건을 실제 계산/등록해 head1420→1424가 되었고
해당 GPU Workflow는 BATCH_COMPLETED다. CPU drain에서는 고정 unit의2/5/10초 상태 조회가
모두 timeout하여 `LOCAL_INDEXING_RUNTIME_UNAVAILABLE`/`EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE`로
종료했다. 실패와 네 기존 성공 encoding은 보존한다. INDEX metadata84 후보는 같은 기존
PREPARE owner로 staging만 했으며 live runtime/DB 변경은0이다. 이 후보도 Knowledge1.1
소비 수정이 없으므로 활성화하지 않는다. 새 수정 SDK로 대체 후보를 준비하며 기존 stage는
보존한다. 현재 INDEX는 failed/PID0이고 새 metadata SDK/남은 CPU 요청 정리·재개는 미완료다.
전체450개 목표는 ACTIVE이며 추가 사용자 인증은 아직 없다.

## 2026-11-15 23:07 UTC — exact-score 호환 운영 반영과 후속 등록 소유 관계 수정

73ea7068의 Material ROLE1.40/Workflow3/Pack1.4·1.5를 기존 control owner로 release하고
Catalog·네 ROLE runner 및 API/Web/Chat/QUERY의 호환 SDK를 반영했다. 모델·추론·capacity,
Office CPU70과 GPU 수치 controller/model/recipe/space는 유지했다. 자료 학습 서비스는
후속 등록 검증이 끝날 때까지 inactive로 두었다. migration head는0079이며 변경 없음이다.

공유 배포의 첫 QUERY 시작은 typed configuration의 owner_source_commit이 이전 SDK를
가리켜 SOURCE_MISMATCH로 거절됐다. 기록은 보존하고, 이미 설치된 패키지를 재설치하지
않았다. 기존 typed serializer로 owner source만73ea7068로 갱신한 configuration successor와
관련 reference/hash를 반영한 뒤 QUERY를 시작했다. numerical 설정·검색 권한은 변경하지
않았다. 공유 배포의 aggregate 기록은 이 명시적 successor를 참조한다. HTTPS asset5개
byte 비교·비인증401 거부 및 관련 장기 서비스 활성 상태가 PASS다. 새 자료를 실제 로그인으로
읽었다는 증거는 아니며 shared postdeploy의 authenticated_ui는 PENDING_REAL_USER_LOGIN이다.
운영 evidence는 `/var/lib/eom-native-exact-score-shared-release-20261115/postdeploy.json`과
`/var/lib/eom-native-exact-score-query-metadata-20261115`에 있다.

첫 회차16개를 보정할 같은 command/key로 proof16개를 게시했으나 linked task 저장이
`uq_material_learning_child_analysis`에 거절됐다. 정상 문항의 분석 FK까지 새 task에
복사한 application 버그다. run/task/event transaction은 rollback되어 원래 completed run,
Item·풀이·Graph는 그대로이며, 게시된 proof는 실패 기록과 함께 보존한다. 제약을 완화하지
않고 기존 clone 규칙으로 돌아가 predecessor 이력에서 accepted base/public을 재사용하도록
수정한다. SDK 변경 뒤 동일 proof의 최초 provenance가 달라지지 않도록 기존 publication
lookup에서 bytes/hash/target을 검증해 재사용한다. 새 identity로 우회하지 않는다.

새 disposable 회귀는 원래 분석 FK가 null인 fixture를 보강해 accepted base/public·Item·Graph가
연결된 completed task의 동일 요청/동시 상속을 검사한다. 첫 실행의 fixture가 terminal 입력을
늦게 추가하려다 immutable trigger에 거절된 로그도 보존했으며, fixture를 insert 전에 준비하도록
수정하고 재검사했다. production row/trigger/unique constraint는 바꾸지 않는다.
같은 disposable DB의 최종 Material/동시성 회귀142 PASS, control upgrade2 PASS,
score Workflow4 PASS다(`native-score-inheritance-storage-r2-20261115.log`). source의 관련
단위 회귀124 PASS, mypy/Ruff/format PASS다. 실제 correction run 등록·
회차2/3 재개·나머지 회차 처리 및 INDEX 소비 SDK/실제 벡터 완료는 아직 남았다.
INDEX는 기존 실패 invocation677a2051…/PID0를 보존 중이며 GPU가 실행 중이라고 보고하지 않는다.
전체450개 goal은 ACTIVE다.

### 23:13 UTC 후속 — 같은 보정 요청 등록·재조회 성공, 공통 materializer 연결 보완

5745f2a5를 commit/push하고 공식 API build-only 및 별도 immutable SDK 설치를 통과했다.
같은 command/key의16개 proof를 그대로 재사용해 correction run을 만들었다. retried16/
reused16이며 즉시 replay는 같은 run과 `replayed=true`다. 원래 completed run·원문·기존
분석은 보존했다. 회차2/3은 공식 RESUME으로 DISCOVERING/PROCESSING이 됐다.
`native-score-create-correction-r2-20261115.log`와 `native-score-resume-runs-20261115.log`.

Material 재개 후 새 ROLE 작업이 모델 실행 전 `execution_materializer:1275`에서 실패했다.
공통 Artifact allowlist reader와 workspace materializer의 dispatch에 plan41이 빠져
기본 구 plan validator가 새 문서를 거절하는 것이 확인됐다. 신규 제출을 멈췄고 실패 이력은
보존했다. 두 기존 진입점에 exact plan41 parser를 연결하며, 기존33/40의 권한·페이지 검증과
analysis 크기 한도를 재사용한다. 새 schema/실행 권한/우회 validator는 없다.
mocked Orchestrator 내부 결과만 확인하던 검사에 실제 두 진입점의 plan40/41 페이지
materialization을 보강했다. 관련 실제 source materializer 회귀72 PASS, mypy PASS다.
수정 ROLE 설치/실제 재개와 남은450개 처리 검증은 계속 진행한다.

### 23:34 UTC 후속 — 실제 ROLE 결과 검증 통과, INDEX 기존 CPU 작업 인계 중

84ae184f를 commit/push하고 공식 API build-only/RECORD/별도 SDK 설치를 통과했다.
기존 private handoff의 prepare·ADMIT·migration VERIFY0079·activate·postdeploy가 PASS다.
Catalog/Material/네 ROLE runner만84ae184f SDK로 선택했다. API/Web/Chat/QUERY는73ea7068의
호환 설치본을 유지하며 source·수치 CPU70/controller0f/model/recipe/space·관리자 모델과
capacity는 변경하지 않았다. HTTPS Studio redirect 후200도 확인했다. helper는
`/usr/local/libexec/eom-native-exact-score-release-20261115/materializer_r3.py`, 기록은
`/var/lib/eom-native-score-materializer-release-20261115`다.

prepare 앞선 두 검사의 historical shared51 baseline 가정 및 단일 EnvironmentFile 가정은
현재 설치와 달라 거절됐다. 둘 다 stage/운영 변경 전 실패 로그를 보존했다. 최종 helper는
동일 phase owner를 실제 shared73 baseline에 compose하고, 기존 coverage owner의 두 env
파일·전체 drop-in hash inventory를 재사용했다. 검사를 삭제하거나 설치 source를 위조하지 않았다.
관련 원본 materializer72 PASS와 최종 control/maintenance/source 경계72 PASS는 겹칠 수 있어
합산하지 않는다. 별도 Schema/DDL 변경은 없다.

Material invocation c9dbfde2…/PID1724599를 시작했고 회차3의 새 task가 실제3번 슬롯에서
workflow_8b446382…/job_f42f79e6…로 실행되어23:33에 RESULT_READY까지 왔다. 이는 새 plan41
실행·결과 검증의 실제 증거이지, 해당 Item/풀이/Graph 전체 완료 증거는 아니다. 재개 직후
관측한 첫 FAILED는 앞선 구 실행기의 이미 실패한 task를 기록한 것이며 성공으로 바꾸지 않았다.
원본450개 전체와16개 배점 보정 완료는 계속 확인한다.

INDEX readonly23:27: CUDA head1420/1582, CPU head1336/1582다. 서로 다른 space이며 합산하지
않는다. 현재 service의 미완료6건은 **CPU RUNNING1건(4 encoding SUCCEEDED, lease 만료)**과
미실행 CPU PENDING5건이었다. 전부 unstarted로 보는 probe는 assert로 종료됐고 cancellation
write는0이다. 네 성공 encoding과 원래 요청을 보존한다. 기존 installed0a56 SDK/runtime으로
INDEX를 재시작해 invocation7126e44f…/PID1728282가 실제 CPU-overlap/reconciliation에 진입했다.
새 설치본 인계를 위해 main의 supported SIGINT Event만 설정했고, 진행 중 call과 CPU future가
자연 종료하도록 drain 중이다. numerical unit/worker에 강제 종료를 하지 않았다. 이는 INDEX84
전환 완료나 새 GPU vector commit 증거가 아니다. 원래 CPU 작업 처리 및 미실행 요청의 기존
maintenance owner 정리 후에만 metadata SDK84 successor를 활성화한다. 추가 인증은 현재 없다.

## 2026-11-15 22:07 UTC — 최종 설치 후보와 실제 원본 보정 대상 확인

source73ea7068을 커밋·push했다. 공식 API build-only의 RECORD/source-free installed
OpenAPI/definition/admission/resource/CLI 검사가 PASS다. 빌드는
`/tmp/eom-api-build/73ea7068f1ef89331eea7904b52909f45e5915d3.ChIslM`이며 platform SHA는
`0c488afb0f703149d0c7c8019ba1fa3ed63b37d0ecadee650bd7b0354696c41c`다.
Web wheel도 같은 source의 artifact/import/installed simulation PASS(82파일)이며
`/tmp/eom-web-gui-build/73ea7068f1ef89331eea7904b52909f45e5915d3.XaMMfa`에 있다.

기존 protected owner installer로 새 platform/API-contract SDK만 별도 immutable prefix에
설치했다. 수치 interpreter·기존 CPU Office70·운영 API/Web·QUERY와 credential은 바꾸지 않았다.
설치본에서 실제 첫 회차의 기존 source/role/result/원문 HWPX/현재 Item을 **read-only DB**로
해석했다. 선정은 정확히16개(원문1.5점8,2.5점8)이며16개 모두 prepare-time current CAS와
source pointer/배점 재확인 PASS다. 앞선22번 그림 보정 current revision도 그대로 pin됐다.
DB write·proof publication·model 호출0이며 이 검사가 이미 배점을 고쳤다는 뜻은 아니다.
증거는 `staging/native-score-actual-target-inspection-r1-20261115.json`이다.

기존 private handoff owner의 prepare도 PASS다. root stage는
`/var/lib/eom-native-exact-score-release-20261115`, frozen helper는
`/usr/local/libexec/eom-native-exact-score-release-20261115/release_r3.py`다.
**PREPARED_ONLY**이며 admission/control 전환·서비스 활성화·Material 재개는 아직 하지 않았다.
초기 wrapper의 frozen-file 경로 오류와 그 뒤 autonomous INDEX 실패 invocation 변경으로
중단된 prepare 로그도 남겼다. 두 번 모두 stage 생성 전이었고, 새로 관측한 실제 실패
invocation을 기준으로 준비를 끝냈다. INDEX 실패를 성공으로 고치거나 INDEX를 재시작하지 않았다.
마지막 QUERY PID416239/invocation99376675…는 그대로이고 INDEX는 failed/PID0이다.

임시 DB 두 개는 모두 공식 confirmed cleanup으로 제거했다(`native-score-reanalysis-db-cleanup-r1/r2`).
다음은 staged control/Pack1.4·1.5/Workflow3의 호환 전환과 API/Web/ROLE/소비 SDK 활성화,
실제16개 재추출·등록·source-score 대조 및2·3회/나머지 회차 재개다. 원래450개 전체,
공개 풀이/Graph/INDEX 완료는 아직 미완료이며 goal은 ACTIVE다. 추가 사용자 인증은 현재 없다.

## 2026-11-15 — 선택적 배점 재추출·같은 Item 후속 등록 후보 검증

원본 run이 terminal이고 실제 Workflow/analysis/lease가 quiescent인 경우만 받는
`NativeMaterialScoreReanalysisService`를 연결했다. source owner가 원래 한글 question을 읽어
등록 배점 불일치/구 계약의 배점 표현 거부를 확인한다. 원문·old result를 수정하지 않고
선정 문항별 작은 proof Artifact와 기존 predecessor run/task를 만든다. 정상 checkpoint는
기존 Item/base/public solution/Graph pin까지 유지한다. 동일 command는 같은 후속 run이다.

fresh result3은 Registry의 기존 REVISE_ITEM/base_revision_id로 같은 logical Item의 새
revision이 된다. 준비 시점 current revision을 명시적으로 고정하므로 앞선 그림 보정 revision을
옛 버전으로 되돌리지 않는다. Lineage4는 exact repair proof pointer를 보존하고, 일반 result3은
기존 Lineage3다. exact Pack이 명시된 runtime에서는 old-role의 *신규* Native 등록만
`MATERIAL_NATIVE_SCORE_REANALYSIS_REQUIRED`로 기록하며 기존 등록 replay는 유지한다.
이 예외는 한 task의 명시적 후속 보정 대상으로 기록하지 resident owner를 종료시키지 않는다.

최종 guarded disposable DB: migration0079 왕복·제한 계정 reconcile PASS,
Material 저장/Registry **141 PASS**, protocol upgrade **2 PASS**, score Workflow **4 PASS**.
새 검사에는 선택적 상속·부정 범위·실제 proof publication/read·동시 생성·transaction rollback,
동일 Item revision CAS·원본6 component 보존·Registry commit 직후 중단/replay와 old-role
cutover가 포함된다. completed worker/source eligibility는 명시한 fixture port이며 실제 운영
재추출/450개 검증의 대체 증거가 아니다. 첫 임시 DB 실행의 잘못된 fixture가 terminal 이력을
바꾸려다 DB trigger에 거절된 기록도 보존했다. trigger를 완화하지 않고 fixture를 수정했다.

source 회귀1325 PASS, 최종 disposition/proof/구 role hash/context44 PASS, 새 핵심4개 mypy와
Ruff/format PASS. wire audit1421 canonical /1072 mirror /12095 refs PASS. 실행 로그는
`staging/native-score-reanalysis-storage-r3-20261115.log`, `native-score-reanalysis-source-full-r1-20261115.log`,
`native-score-reanalysis-final-unit-20261115.log`에 임시 보존한다. 두 번째 임시 DB는 새로 준비해
최종141개를 재검사했다. 범위가 겹치는 수치는 합산하지 않는다.

**현재는 source 후보이고 운영 미반영**이다. 이번 단계의 운영 write/model/GPU 실행0.
실제 첫 회차25개의 보정 후 source-score 대조, 멈춘 두 run과 나머지 회차 재개, 공유 Graph/
공개 풀이/INDEX 연결 및 전체450 검증이 남는다. 목표는 ACTIVE다. 18회 업로드·원본 Excel과
250개 고유번호/200개 미지정 값, 원본 단원, 과거 실패 이력은 보존한다.

## 2026-11-15 — 설치 wheel의 API 명세 경계 후속 보정

등록·조회 후보610d8c05를 공식 `deploy_release.sh --build-only`로 검사했다. wheel RECORD는
통과했지만 bundled OpenAPI가 새 canonical1.1 read family를 포함하지 않아 installed route
비교가 중단됐다. 운영 설치/서비스 변경은 없었고 첫 build 로그를 보존했다.

공식 exporter로 OpenAPI·SHA를 갱신했다. 동시에 새 read union이 기존 수동 import 입력을
묵시적으로 넓히지 않도록 실제 두 입력 DTO와 import owner의 공통 타입을 기존1/2/3 전용
`ReviewedItemContentContract`로 분리했다. content1.1은 기존 Native 등록과 읽기로만 들어오며
미지원 수동 입력은 typed/closed wire에서 거절한다. 이력 schema bytes나 권한은 바꾸지 않았다.

OpenAPI breaking 검사 PASS(검사 범위 내 finding0), API 명세의 결정성/실제 route 일치·읽기/
기존 import·frontend alignment 등 **77 PASS**와 source4개 mypy PASS다. Starlette TestClient의
기존 deprecation warning1은 별도로 남았다. `native-score-openapi-final-regression-20261115.log`.
설치본 재검증과 실제 배포/Native canary는 이어서 진행하며 전체 goal은 ACTIVE다.

두 번째 build의 RECORD/OpenAPI 비교는 통과했으나, 실제 isolated admission 비교가 새
Material3 definition의 staging/compile 목록 누락을 발견했다. 비교 gate를 완화하지 않고 공식
build의 기존 copy/compile/profile/schema 검사에3.0을 추가했다. 기존1/2도 계속 검사한다.
정의 사본을 실제 copy block에서 읽고 compiler/admission과 대조하며, 새 Material3을 일부러
누락하면 같은 installed 비교가 거절하는 회귀를 추가했다. 두 build 실패는 미설치 상태다.
관련 release inventory·admission·wheel 검사97 PASS 후594dd7b6으로 재빌드했다. 최종
`native-score-registration-api-build-r3-20261115.log`는 wheel RECORD 및 source-free installed
OpenAPI/definition/admission/resource/CLI 검사 PASS다. frozen build는
`/tmp/eom-api-build/594dd7b6feb3b2408248a484bd35429eefad99b6.iIkTaU`다. 빌드·검증만 했으며
운영 설치·활성화·모델 실행·우리가 멈춘 Material 재개는 아직 하지 않았다.

## 2026-11-15 — 정확한 배점 등록·조회·설정 전환 후보 검증, 실제 활성화는 다음

새 Lineage3 / 일반 Pack1.4 / Native Pack1.5를 기존 Registry owner에 연결했다. Native result3은
등록 잠금 안에서 exact question Artifact 배점을 다시 읽어 proposal과 비교한다.0/15/반올림/
UNPRINTED 대체는 등록 전에 거절한다. canonical integer는1.0, half는1.1의 실제 schema·hash로
게시한다. 문제·해설 OTHER pointer,6 component, 원본 Excel metadata와 EXTERNAL 구분은 그대로다.

canonical GET은 기존 request10/new response19, 표시 읽기는 response2로 API와 Catalog 양쪽을
연결했다. 실제 로컬 socket에서 두 번씩 읽어1.5/2.5와 body·image pointer가 같은 것을 확인했다.
Native 그림은 기존 Office picture-use를 그대로 사용한다. 일반 PDF visual-set2의 result2/3
연결도 기존 publisher 안에서 추가했으며 Native를 PDF crop으로 대체하지 않는다.

현재 관리자 모델·추론·instruction·capacity·권한을 보존하는1.39→1.40 갱신은 기존 protocol-only
upgrade owner를 공유한다. 새 preset/queue/DB migration은 없다. 실제 disposable DB에서 동시
호출과 같은 요청 replay가 같은 released revision/evaluation을 쓰고 구 문서·다른 preset을
바꾸지 않는 것을 확인했다. 평가가 pin하는 것은 draft ID와 동일 policy hash다. 이를 released
revision ID와 같다고 가정했던 새 테스트의 잘못된 assertion은 수정했고 실패 로그를 보존했다.

최종 공식 guarded DB 경로: migration head0079 왕복·제한 계정 reconcile PASS,
기존/새 Registry suite **129 PASS**(새 exact 등록11개 포함), sequential protocol upgrades
**2 PASS**, score Workflow 저장·동시성·late denial **4 PASS**. Native 원문 descriptor는 실제
Artifact owner로 읽지만 completed worker/source admission은 fixture이므로 live 모델·실제 권한
증거로 확대하지 않는다. `native-score-registration-testdb-r3-20261115.log`가 최종 결과다.
앞선 두 임시 DB의 실행/테스트 assertion 실패 기록도 보존하고 공식 cleanup으로 제거했다.
최종 세 번째 임시 DB도 공식 confirmed cleanup으로 제거했고 cleanup-r3 로그에 보존했다.

source 회귀1419 PASS, 새 최종 read/hash 회귀9 PASS, context/immutability/embedding projection/
Preview81 PASS, changed source9개 mypy와 Ruff/format/diff check PASS다. 기존40 role bundle의
baseline hash가 그대로라는 executable 회귀도 추가했다. wire audit1419 canonical /1070 mirror /
12080 refs PASS다. 앞선 SVG 테스트의 함수명 문자열 검사는 실제 request-aware validator 이름을
따르도록 보정했으며 unsafe SVG의 schema/typed 거절과 commit 이전 순서 검증은 유지했다.

**아직 미배포**다. Material owner 및 우리가 PAUSE한 두 run은 유지보수 상태를 유지한다.
다음은 오류가 확인된 target의 supported linked re-extraction·same logical Item successor를
연결하고, 설치 wheel/SDK 호환 배포 뒤 실제 Native1.5/2.5/2 등록·조회와 전체 처리 재개를 확인하는
일이다. 이미 제출된 old extraction을 그대로 잘못 신규 등록하지 않는 cutover도 확인해야 한다.
이 단계는 운영 DB·원본·등록 정본·accepted 분석·실패 이력·INDEX/QUERY에 쓰지 않았고,
모델/GPU 실행0이다.450개 전체 goal은 계속 ACTIVE이며 완료로 선언하지 않는다.

## 2026-11-15 — 정확한 배점 실행 family와 임시 DB 검증, 등록/배포 연결은 계속

Workflow3 / ROLE1.40 / request3 / result3 / plan41 / receipt3의 source 후보를 연결했다.
work1의 문항·페이지 선택은 그대로다. Catalog의 기존 source owner가 같은 Native question
descriptor를 읽어 `native_printed_score`를 만들고, 제출·재인가·plan replay·결과 수신에서
이 값을 확인한다. 모델이 이 값이나 operator를 고르지 않는다. Native가 아니면 명시적 null,
진짜 unreadable/UNRESOLVED는 관측 기록으로 보존하며 무조건 WORKER_RESULT_INVALID로
바꾸지 않는다. 원문에서 확인한 점수를 proposal이0/15/다른 반점으로 내면 거절한다.

실제 Orchestrator 구성의 source tests에서 stage/commit 후 DB 값은 receipt3의 다섯 작은
필드뿐이고 전체 결과·coverage는 Artifact에 남는 것을 확인했다. sourceScore generation은
canonical의 엄밀한 끝문자 검증을 완화하지 않고, Codex 양식에서만 동일한 반점99개 enum으로
표현한다. Native 입력의 값은 다시 exact constant로 제한한다. 새 resource의 property/array
fragment는 기존 inliner에서 요청한 작은 subschema만 읽어 unrelated old proposal을 붙이지 않는다.

검증: Material 계열72개 파일과 기존 Office/외부 role/score/context source 회귀1339 PASS,
후속 exact-score chain47 PASS. 기존40개 protocol의 schema bundle hash를 baseline6607eed1과
대조해 변경0을 확인했다. source21개 focused mypy PASS와 wire audit1415/1066/12068도 확인했다.
최종 실행/role/결과 읽기/context 회귀62 PASS와 source21개 mypy PASS,
Ruff/format/diff-check PASS는 `native-score-execution-final-*` 로그에 남겼다.

운영 DB를 사용하지 않고 공식 guarded 임시 PostgreSQL을 준비해 migration 왕복·제한 계정
reconcile을 수행했다. 첫 DB에서 기존118개와 coverage upgrade1개는 통과했으나, 새4개 검사
중3개가 새 definition의 admitted 목록 누락을 발견했다. source의 중앙 admission에 정확한
3.0/1.40 쌍을 추가했고, late-denial 검사도 실제4번째 authorization까지 도달해야 PASS로
강화했다. inactive row를 직접 UPDATE하지 않고 첫 임시 DB를 공식 cleanup했다.

새 임시 DB에서 같은 경로를 다시 실행해 **118 PASS + upgrade1 PASS + 새4 PASS**를 확인했다.
새4개는 actual Workflow/READY/command transaction·동시 동일 요청·재전송·late denial rollback·
배점이 달라진 source의 거절을 검사한다. source와 plan port는 합성이라 live 인가·실제 released
preset/plan의 DB 저장·모델 실행 증거로 확대하지 않는다. 두 실행의 실패/성공 로그는 보존한다.
증거: `staging/native-score-disposable-material-tests{,-r2}-20261115.log`,
`staging/native-score-all-historical-protocol-hashes-20261115.json`.
검증용 두 DB는 공식 `testdb_cleanup.sh --confirm`으로 제거했고 각 cleanup 로그를 보존했다.
운영 DB·원문·기등록 Item·accepted 분석·실패 이력에는 이번 단계의 쓰기가 없다.

**아직 미배포**다. 다음 경계는 새 lineage/등록 Pack과 canonical1.1 등록·HTTP 읽기 및
실제 소비 SDK의 호환 연결이다. 기존 Pack1.3은 ROLE<1.40 / Workflow2를 명시하므로
metadata가 같다는 이유로 재사용하지 않는다. 기등록 원본 배점 오류 target만 새 linked 추출과
기존 logical Item의 successor Revision으로 보정하는 경로를 우선 검증한다. old accepted result나
분석의 hash/source pin만 고쳐 성공으로 꾸미지 않는다. Material owner와 우리가 PAUSE한 두 run은
아직 재개하지 않았고,450개 등록·Graph·임베딩 완료는 아니다. 전체 goal은 ACTIVE다.

## 2026-11-15 — 배점 보존 기초 구현·검증, 운영 재개는 미완료

새 `source-score/2.0`, source draft2, material extraction2와 canonical block content1.1을
추가했다. old schema bytes는 바꾸지 않았다. 원문 ZIP/XML score reader는 정확한 question
descriptor만 열고 bounded read·FD close·전후 재인가를 하며, 모호함/미관측/지원하지 않는
소수와0/15/반올림 대체를 구분해 거절한다. 기존 region/answer/reference 검증은 두 실제
형식에서 공유한다. 정수/미인쇄 materialization은 기존1.0을 유지한다.

Catalog reader·Graph block element·그림 조회·question embedding projection과 Web Preview의
source 후보가1.1을 이해한다. Preview는 schema URI/version mismatch를 거절하고, 새 source를
구 template로 재생성할 수 있다고 표시하지 않는다. 배점만 바뀌어도 질문 임베딩 text/hash는
동일하다는 회귀를 확인했다. 이것은 새 public solution/source revision을 이미 등록하거나
옛 임베딩을 새 revision의 것이라고 바꾸었다는 뜻이 아니다.

최종 후보 검증: `native-score-regression-r5-20261115.log`367 PASS,
`native-score-historical-consumers-r2-20261115.log`117 PASS, source17개 focused mypy PASS,
Ruff/format/diff-check PASS. wire audit의 canonical1411/mirror1062/reference12048 확인도 PASS다.
개발용 index의40-path 제한을 넘긴 초기 오류는 경로 제한을 늘리지 않고 수정했다.
이전 실패 로그는 보존했다. DB write/model 실행/worker 재생성0이며 이번 단계에 migration은 없다.

**미배포**: 실제 ROLE/request/result·plan·등록 Pack·Catalog HTTP/visual response의 closed
소비 경계를 아직 새 형식으로 연결하지 않았다. 값 모델 추가만으로 Material owner를 다시
켜지 않는다. 다음은 최소 successor 연결과 Native 원문 score gate, 기등록 배점의 reviewed
successor correction 및 기존 task/analysis 재사용을 검증하는 일이다.450개 전체 목표는 ACTIVE다.

19:14:48 INDEX read-only 관측에서 GPU 저장 head는1420/1582, CPU1336/1582였다.
앞선1412/1332보다 늘었지만 현재 INDEX unit은failed이고 QUERY는active다. 두 space를
합산하지 않는다. evidence는 `staging/native-score-maintenance-index-20261115.json`이다.
이 배점 유지보수는 INDEX를 stop/restart하지 않았으며 성공 벡터는 보존했다. 서비스가 현재
돌고 있다는 주장이나 반복 OS 관측 실패가 해결됐다는 주장은 하지 않는다.

## 2026-11-15 — 원본 배점 충실도 결함 확인, 등록 유지보수

공식 Native question Artifact와 등록 content를 읽어 첫 회차25개를 대조한 결과,
16개 배점이 원본과 달랐다. 기존 정수 전용 draft 때문에1.5/2.5를15/0/2로 제안·등록한
사례다. 앞선25개 기술 완료를 배점 충실도 PASS로 해석하지 않는다. 원문 HWPX·Excel·
해설·그림과 실패 이력은 보존했다. 증거는
`staging/native-registered-score-audit-20261115.json`이다.

분리된 실제450개 question XML을 bounded parser로 읽었다.1.5점144개·2.5점146개·
2점160개이며,16회/18회 원 인쇄 합계50.5도 임의 보정하지 않는다.
`staging/native-printed-score-corpus-450-r2-20261115.json`은 입력 판독 증거이지
450개 등록 충실도나 운영 수정 완료 증거가 아니다.

Material owner는 main-only SIGINT로 drain되어 inactive다. 지원된 control에서2회차
후속 run과3회차를 PAUSED로 바꿨다.4회차 RECEIVED의 PAUSE는 기존 phase guard가
거절했고 그 이후 요청은 하지 않았다. 해당 guard나 DB row를 우회하지 않는다.
`staging/native-score-scope-pause-20261115.jsonl`과 root 보관 receipt가 우리가 바꾼
두 pause만 기록한다. 나머지 RECEIVED를 실행시키지 않도록 수정 배포 전까지
Material owner를 inactive로 유지한다. INDEX/QUERY는 이 유지보수로 교체·중단하지 않았다.

새 score2 값 계약·원문 XML 판독기는 개발 후보다. 회귀132개·Ruff·두 파일 mypy는
통과했지만 운영 연결/기등록 successor 보정은 아직 미완료다.3회차1번은 파일을 못
읽은 것이 아니라 정수 계약에 소수 배점을 넣을 수 없어 proposal을 거부한 사례다.
3회차2번 공개 풀이는 별개인 earlier-step dependency 검증 실패이며 검증을 완화하지 않는다.
설계는 `docs/architecture/NATIVE_PRINTED_SCORE_FIDELITY.md`다. 전체 목표는 ACTIVE다.

## 2026-11-15 18:18 UTC — Native3 실제 선택 retry·Web 운영 반영, 전체 목표 계속

Catalog-only 후속 source `36152674a37cd5e1f50e25e19dc35853b5097c75`를 설치·활성화했다.
Material와 실제 ROLE runner4곳은 이미 안내문을 반영한 `b84d0dc9` 그대로다. API51·QUERY0a56·
기존 CPU/CUDA 모델/recipe/space·Office CPU70·Pack/control·원본 및 실패 이력은 변경하지 않았다.
`staging/native-reanalysis-catalog-v3-activate-20261115.json`은 peer PID/Invocation 보존 PASS다.

실제2회차의 원래 실패 `materialrun_3b66485a97fb5324b136228e0f18b120`에서 새 linked run
`materialrun_612042aeff585cbd9a0c9e96e5015d15`를 만들었다. **2개 재분석 / 5개 재사용**이며
같은 공식 retry 재전송은 **replayed=true / 동일 successor**를 반환했다. 원 실패의 상태·시각,
성공한6개 결과는 불변이다. 증거: `staging/native-reanalysis-v3-real-retry-20261115.json`.
새 run은18:15 공식 조회 기준 DISCOVERING, PREPARE완료1·DISCOVER완료4·PENDING2다.
이는 복구 등록 성공이지 두 모델 작업의 실행/완료 증거가 아니다. 기존 생성 시각 순서의
공식 대기열을 사용하므로 현재 처리 중인3회차와 먼저 접수된 다른 회차 뒤에 기다릴 수 있다.
대기 순서를 바꾸려고 DB 시각/priority를 직접 수정하거나 별도 worker를 띄우지 않았다.

Web은 검증한 `b84d0dc9` wheel로 갱신했다. 공식 설치기·82개 RECORD member 검사 PASS,
실제 HTTPS `/studio/assets/material-learning.js` SHA가 source와 같다:
`3a820612ae883f4257c6a5ab506145d8fc56e76756ffcce036fab15b476e77e4`.
HTTPS ready도 PASS다. 실제 운영 브라우저 버튼의 사람 확인은 아직 별도 기록하지 않았다.
DB2개는 공식 cleanup으로 제거했고 검증·실패 로그는 보존했다.

18:15 현재:1회차25 Item/base/풀이/Graph 완료.3회차 Item/base2, Graph0이며1개 source-unreadable
예외와1개 analysis-terminal-failure가 기록됐다.3회차의 실제 풀이 worker는 계속 실행 중이다.
`staging/native-reanalysis-current-progress-20261115.json`은 원 실패와 후속 run을 따로 보여 준다.
다음 핵심은3회차 실패한 분석의 정확한 원인 조회·terminal 후 지원된 재시도와 다른 회차의
실제 등록/Graph 검증이다. **18회 접수 완료 ≠450개 등록/풀이/Graph/임베딩 완료**다.

INDEX는 성공한 원벡터를 보존하고 동일 source/config로 재개했다. 재개 전 native lifetime의
drained=true/blocking=[]를 확인했다.18:18 unit은 active(PID1307845,
Invocation`677a2051de244de385c04bfb0d04b9a1`)다. 마지막 저장 head는 GPU1412/1582,
CPU1332/1582로 두 space는 합산하지 않는다. 재개 뒤 head 증가나 반복 OS 관측 실패의
영구 해결은 아직 주장하지 않는다. 증거: `staging/native-reanalysis-index-after-resume-20261115.json`.

## 2026-11-15 — 선택 재분석 첫 운영 사전 검사와 Native3 호환 보완

`b84d0dc9`를 private Catalog/Material/실제 ROLE runner4곳에 설치·활성화했다.
`native-reanalysis-release-{prepare-r2,admit,activate,postdeploy}-20261115` 로그는 PASS다.
API/Web/QUERY/numerical source·기존 CPU Office tool은 교체하지 않았다. 기존 풀이 worker의
정상 종료를 기다린 뒤 교체했고 Material도 다시 시작했다.

그러나 실제2회차 retry는 새 run 생성 **전** `MATERIAL_NATIVE_REANALYSIS_CHECKPOINT_INVALID`로
거부됐다. 원본 실패와6개 성공 결과는 그대로이며 새 모델 실행은 없었다. 정확한 공식 읽기로
prepared3 / preparation-input2 / profile 일치를 확인했다:
`staging/native-reanalysis-checkpoint-real-schemas-20261115.json`.
이는 손상된 checkpoint가 아니라 새 retry 코드의 prepared2 전용 type 조건 누락이다.

기존 prepared reader의 Native3→exact Native2 base 검증을 그대로 재사용하고 outer3 pointer와
base2의 최종 metadata fence를 보존하도록 보완했다. 그림 준비/worker prompt/Material runtime은
그대로이며 후속 배포 범위는 이 Catalog 경계뿐이다. schema bytes·DB migration·실패 이력을
수정하거나 원본 그림을 다시 만드는 변경이 아니다.

- Native2/3 실제 source/rights/Artifact/history 및 동시성·rollback 집중 DB **7 PASS**.
- 관련 source **120 PASS**, mypy/Ruff PASS.
- 새 disposable DB `20261115180509_f1470456`의 migration79 왕복·Material 전체 **118 PASS**.
  재사용한 앞 DB는 마지막 ROLE1.39 upgrade 뒤 구ROLE1.37 fixture를 재실행해 기존 control
  pins 불일치가 났다. published control을 되돌리지 않고 새 DB에서 다시 검증했다. 두 로그 모두 보존한다.
- Web BFF/실제 브라우저 fixture **17 PASS**. 운영 Web 새 패키지 적용은 후속이다.

Native3 보완의 실제2-task retry/새 등록 성공과 전체450완료는 아직 선언하지 않는다.

## 2026-11-15 17:49 UTC — 선택 재분석 구현·DB 검증 완료, 배포 전

기존 retry wire와 linked run/task를 쓰는 `NativeMaterialDiscoveryReanalysisService`를
구현했다. 원본/권리/prepared/native bundle/accepted result를 읽어 incomplete producer만
선정하고 revision→run 잠금 아래 새 task를 만든다. 두 번째 회차의 예정 선택은2개이며
PREPARE와 정상 발견4개는 그대로 재사용한다. 기존 FAILED/COMPLETED 기록은 수정하지 않는다.

- Source 집중 회귀 **238 PASS**, core3파일 mypy와 Ruff/format PASS.
- Guarded disposable DB migration79 왕복 PASS, Material suite **117 PASS**, 별도 coverage
  upgrade **1 PASS**. 실제 source/rights/Artifact/history를 읽는 Native 복구 테스트도 포함한다.
- 실제 브라우저 fixture PASS: task가 전부 완료됐어도 정확한 incomplete 실패에는 기존 retry
  버튼이 보이고, 다른 실패를 임의 재처리하지 않는다. 실제 운영 retry 성공은 아직 아니다.
- 초기 검증 실패는 invocation/합성 fixture와 새 코드의 task→event flush 순서를 구분해 보존했다.
  DB에서 FK 실패를 재현한 뒤 기존 retry와 동일하게 task를 먼저 flush하도록 고쳤다.
  immutable 실패/승인 Artifact를 시험용으로 덮어쓰는 fixture도 제거했다. DB 제약은 완화하지 않았다.
- 증거: `staging/native-discovery-reanalysis-source-final-r2-20261115.log`,
  `staging/native-discovery-reanalysis-db-full-20261115.log`,
  `staging/native-discovery-reanalysis-browser-r3-20261115.log`.

17:47 공식18회차 조회는 첫 회차25개 등록/풀이/Graph 완료, 두 번째 범위 실패,
세 번째25개 task 생성·1개 Item/base·1개 source-unreadable 예외, 나머지15회차 RECEIVED다.
`staging/native18-reanalysis-validation-progress-20261115.json`은 이 시점의 관측이며 전체450완료가 아니다.
INDEX도 같은 Invocation이 OS runtime 관측 실패로 다시 멈춘 상태를 확인했다.
성공한 벡터를 다시 계산하거나 Native 복구의 완료 증거로 합산하지 않는다.

## 2026-11-15 17:14 UTC — 두 번째 회차의 범위 완료 판정 실패·선택 재분석 후보

두 번째 run `materialrun_3b66485a97fb5324b136228e0f18b120`은 발견6개를 모두 COMPLETED로
마쳤으나 최종 Native 검증에서 `MATERIAL_NATIVE_DISCOVERY_REGION_INCOMPLETE`로 FAILED가
됐다. 원본과 성공한 발견 Artifact 및 실패 상태는 보존한다. 다른 회차는 정상 queue에서
계속 처리하며 이 실패를450개 완료로 숨기지 않는다.

공식 source/결과 해석으로 문제25개·상세 해설25개·정답표1개를 확인했다. 문제9번과 해설
6/11/16/21번만 TO_NEXT이며 실제 다음 페이지 anchor도 들어 있다. 이5개 unit의 원래
owner는 MAIN 발견1개와 SOLUTIONS 발견1개, 합계2개 task다. 모델이 '다음 물리 페이지'와
'제공한 context까지 읽어도 남은 미관측 부분'을 혼동했을 가능성을 확인했다. 이를 근거로
원문/이미지를 보지 않고 모델 flag를 강제 COMPLETE로 바꾸지는 않는다. 증거는
`staging/native-region-incomplete-inspection-r2-20261115.json`이다. 최초 진단 helper의 잘못된
ORM 속성 접근도 READ_STOPPED로 보존했고 원본·DB write는0이었다.

후속 설계를 `NATIVE_DISCOVERY_COMPLETENESS_REANALYSIS.md`에 기록했다. 기존 JSON Schema의
continuation 의미를 명확히 하는 안내 후보와 Native inventory의 순수 공통 검증/대상 선정
모듈을 작성했다. 엄격한 등록 binder는 incomplete를 계속 거부하며, 대상 선정은 COMPLETE
변경이나 Artifact/DB mutation을 하지 않는다. 기존 coordinator 공개 binder 이름도 유지한다.
source 회귀146 PASS, formatter/linter와 source3개 mypy PASS다. 이는 후보이며 아직 선택
retry의 persistence/동시성 구현·운영 배포·실제 모델 재분석 성공을 뜻하지 않는다. 기존 retry
owner로 정확한2개만 새 successor에서 재분석하고 나머지 준비/발견5개를 상속하는 연결이 남았다.

INDEX는 재개 후 GPU1408/1582·CPU1332/1582까지 저장했다.17:03:05 새 CUDA batch 완료
뒤17:03:10에 같은 OS unit 조회 timeout 소진으로 종료했다. 공식 read-only 관측에서 성공한
encoding4개가 남은 CPU 요청의 만료 claim과 세 미시도 CPU 요청을 확인했고, physical batch
관측은 blocking0이었다. 동일 source/pin으로 공식 service만 다시 시작했다. 새 PID1186360/
invocation743275a9b86246f89391a47ba51d388c다. 조회 지연의 근본 원인은 여전히 미확인이며
수치/저장 성공을 실패로 바꾸거나 timeout·권한 조건을 완화하지 않았다.

## 2026-11-15 16:24 UTC — 18회차 전체 접수·두 번째 회차 실제 발견 진행

실제 guiadmin 세션에서16:13:58부터 기존 r4 driver의 direct continuation으로 남은17회차를
순차 제출했다. 마지막 native-exams 응답은16:18:53이며 모든17건이 `EXAM_ACCEPTED`,
replayed=false였다. 원래18 source key/18 preparation key를 유지했고 checkpoint18건 모두
acceptance가 있으며 pending/error0이다. 원래 첫 회차 acceptance와 R5 복구 이력은 그대로다.
실행은 정상적으로 자신의 세션만 로그아웃하고 종료했다. 원본 Excel의250개 번호와200개
미기입을 유지하며 새 고유번호를 생성하지 않았다. 근거는
`staging/native-exam-http-driver-r4-remaining17-20261115.log`와 원래 batch checkpoint다.

공식 `MaterialLearningReadService.inspect`를 default-transaction-read-only 연결에서 사용해
18개 accepted run의 현재 상태를 확인했다.16:23:28의 실제 판정은 첫 회차 COMPLETED
25개 Item/analysis/Graph 연결, 두 번째 회차 DISCOVERING, 나머지16개 RECEIVED다.
두 번째 회차의 DISCOVER1개가 완료됐고 다음 DISCOVER가 같은 run에서 RUNNING이다.
오류 코드는 없으며 실제 role worker unit의 live MainPID도 확인했다. 접수18개를
450개 Item/풀이/Graph/임베딩 완료로 확대하지 않는다. 이후 worker·등록·공통 Graph·INDEX의
실제 완료와 원본 metadata 및 Native 문서 읽기를 검증해야 하므로 전체 목표는 ACTIVE다.

관측은 기존 공식 owner-read와 task history projection을 재사용하며 문항/worker 내용이나
문서 bytes를 읽지 않았다. bounded18 run lookup이고 DB/NAS write·model call0이다.
읽기 전용 helper는 protected driver와 SDK0a56 및 원본 archive/operator를 고정한다.
진행 증거는 `staging/native18-accepted-progress-20261115.json`,
`native18-active-task-progress-20261115.json`이며 현재 frozen helper는
`/usr/local/libexec/eom-native-exam-http-driver-20261114/progress-18-r2.py`,
SHA9946296cd11948b347740e991d2698d966548515ab3372249151db54b6cff9de다.

## 2026-11-15 16:10 UTC — 실제 Native 다운로드 PASS·원래 INDEX 저장 완료 확인

실제 guiadmin HTTP 세션에서 R5의 인쇄9번 등록 문항
`itemrev_1302ff00302c467389e4056d209faf45`를 기존 DB/Native source 조회로 읽었다.
문항 metadata·원본 workbook SHA·material revision을 대조했고 MAIN/SOLUTIONS를 각각
다운로드했다. MAIN501680bytes/SHA116e204f, SOLUTIONS14074bytes/SHA39dec0c4가 정본 pointer와
같으며 ETag·ZIP mimetype·native section도 PASS다. PDF 캡처나 새 HWPX 재생성이 아니다.
실제 한글 레이아웃 육안 판정은 `NOT_RECORDED`로 구분한다. 증거는 기존 checkpoint의
`checkpoint.canary-native.json`, checked_at16:04:22 UTC다.

인증 재실행 중 구형 SDK7084를 지정한 operator invocation은 로그인 후 복구 계약의 lazy
import에서 종료됐다. 실제 계정/API 로그인 문제가 아니다. 현 SDK0a56에서 archive18개,
원본 checkpoint 재계획의 동일성, 선택한 복구 receipt4개와 installed Web gateway를
로그인 없이 검증해 통과했다. 소스·비밀번호·정본·요청 key는 바꾸지 않았다. 이후 같은
세션의 Native 다운로드 검증은 통과했으나 interactive 명령 전송의 빈 Enter가 정상 종료를
유발했다. 이를 업로드 실패나 성공으로 바꾸지 않는다. 재실행은 검증된 exact R5 ID를
`--continue-after-canary`에 직접 고정해 별도 interactive 입력 없이 남은17회차를 제출한다.
이 기록 시점 새 실행은 기존 숨김 Studio 입력 대기이며 남은425개는 아직 미제출이다.

별도 INDEX의05:24 CPU 원래 Workflow1440bc409e9143148293381c3b6c2a6f가 실제 COMPLETED,
command SUCCEEDED와 기존4개 encoding/완료 checkpoint를 유지한 것을 공식 observer로
확인했다. CUDA 후속2묶음도 COMPLETED이며 최신 GPU 저장 head1400/1582,
CPU1328/1582다. INDEX는05:47:20에 기존 OS unit 조회 timeout 소진으로 다시 종료됐고
수치/저장 실패의 증거는 없다. 관측 지연의 근본 원인은 여전히 미확인이다.

16:07 공식 read-only observer로 정확한 남은 CPU 요청의 성공 encoding4개·만료 claim과
두 미시도 CPU 요청을 확인했다.16:08 native batch lifetime 관측은528개 모두 terminal,
blocking0/drained였다. 이후 동일 source0a56·Identity·runtime pin으로 공식 INDEX service만
시작했다. 새 PID1098145/invocation0ab5ae52d9d7465380c7caeafc4e45bc이며16:09의 실제
PUBLIC_SOLUTION_REPORTS/admission은 PASS다. 재개 후 새 index 저장 완료와450문항 전체
완료를 뜻하지 않는다. 설정·모델·timeout을 바꾸거나 성공한 벡터를 재계산하지 않았다.
근거는 `staging/native-index-current-input-resumed-inspect-20261115.json`,
`native-index-before-resume-lifetimes-20261115.json`과 공식 service journal이다.

## 2026-11-15 05:08 UTC — 동일 capture 소비자 운영 정렬·중단된 CPU 저장 재개

검증된 source `0a56aaf1ff82051fa7cd4c40eef8ddd163ed93ec`의 동일 SDK를 QUERY와 private
Catalog에도 반영했다. 기존 QUERY release owner를 재사용한6파일 metadata CAS이며 새 DB
migration/Identity/policy·model/recipe/space 변경은 없다. 실제 Catalog UID에서 구/신 role
schema와 installed import를 먼저 확인했다. QUERY와 Catalog는 각각 main-only SIGINT로
자식을 자연 종료한 뒤 전환했다. 04:49 활성화, 04:51 postdeploy에서 파일·effective
config hash·SDK import 선택·다른 실행과 수치 환경의 보존을 확인했다.

QUERY의 과거 nonterminal12건은 모두 현 서비스 기동 전 기록이고 유효 lease가 없었다.
정확한12개 Workflow/12개 command metadata fingerprint
`3ea5b1b537e1c2fb479537ecb78e7c76b58cff6868cdf7a1ee4c042701eaafdd`를 전후 대조했다.
새로운 in-flight는 허용하지 않았으며 과거 요청의 상태·갱신 시각·실패 이력을 고치거나
자동 재실행하지 않았다. QUERY의 기동이 과거 전체 queue를 실행하지 않는 경로도 확인했다.
기존 prepared plan을 바꾸거나 다시 만들지 않았고 공유 GPU env SHA도 같았다. 후보 설치
검사/배포 검증은 실제 사용자 검색 성공의 대체 증거가 아니며 `SEARCH_NOT_RUN`으로 남긴다.
근거는 `staging/query-historical-capture-{activate,postdeploy}-20261115.log`와 과거 요청의
읽기 전용 `query-historical-capture-blocked-inspect-20261115.json`이다.

별도로 INDEX는 두 번째 새 CUDA batch를04:19:54에 완료한 뒤04:19:59 OS unit 관측
timeout으로 종료했다. 기존2/5/10초 조회를 모두 소진한
`EMBEDDING_REGISTRY_AUTHORITY_UNAVAILABLE / LOCAL_INDEXING_RUNTIME_UNAVAILABLE`이며
수치 실패나 model 오류가 아니다. PID1 지연의 근본 원인은 미확인이고 QUERY 준비와의 인과도
확인되지 않았다. QUERY 배포의 첫 preserved snapshot부터 INDEX는 이미 failed/PID0이었다.
이를 배포가 실행 중 INDEX를 계속 유지한 증거로 과장하지 않는다.

성공한 GPU 저장 head1392/1582와 원래 CPU 요청의 성공 encoding4개·만료 claim을 먼저
확인했다. QUERY/Catalog postdeploy 뒤04:53 동일 source0a56·service revision3f43091e의
공식 INDEX service만 시작했다. PID420457/invocation61f6b45cfdcf4947a8235376a8ad0498이며
보호 설정·timeout·수치 실행 권한을 변경하지 않았다.04:58 원래 CPU Workflow
`workflow_1440bc409e9143148293381c3b6c2a6f`의 같은 command가 lease generation2로 재개됐다.
성공한4개 owned encoding의 Job/hash/completion을 그대로 재사용했다.05:06:50 관측에서는
CPU의 REGISTERED checkpoint와 저장 head1328/1582를 확인했다. 이 시점 Workflow는 아직
COMMITTING이므로 COMPLETED라고 보고하지 않는다. 다음 CUDA 요청도 encoding4개가
SUCCEEDED지만 아직 head 저장/전체 완료는 미확인이다. GPU와 CPU의 서로 다른 space를
더하거나 이를 신규 Native450개 완료 수로 해석하지 않는다. 근거는
`staging/native-index-post-consumer-release-progress-20261115.json`이다.

전체450개 목표는 ACTIVE다. 실제 등록·분석·Graph 완료는 첫 회차25개이며, 남은17회차는
동일 EOM2 `native-import` HTTP driver가 Studio 인증 입력을 기다려 아직 미제출이다.
원래 main/solution HWPX의 실제 사용자 다운로드 gate와 이후425개 처리·최종 공식 조회가
남아 있다. 로그인 인증을 대신했다고 간주하거나 원본·완료 이력·비밀번호를 바꾸지 않았다.

## 2026-11-15 04:05 UTC — 새 GPU 저장 완료·Web 안내 운영 반영 / 동일 소비자 확인

03:57:21 UTC 새 CUDA 요청이 BATCH_COMPLETED, selected4/missing_reports0으로 완료됐다.
공식 observer의04:00:45 관측에서 새 Graph
`graphrev_54f1af9a585a980475e784e30376e094`에 GPU head1388/1582를 확인했다. 기존1384개에
새 계산4개가 연결됐다. CPU head1324/1581과 원래 성공 이력은 보존됐고 다음 CPU 요청도
같은 invocation에서 RUNNING이다. 전체 Native450 완료나 CPU/GPU 동등 scope 완료를 뜻하지
않는다. 근거는 `staging/native-index-history-first-batch-completed-20261115.json`이다.

GUI 안내/회귀만 바꾼 `f855faa8db191e2b77cc8d146ef97de8fcd69afb`를 커밋·푸시하고 기존
Web release build/RECORD/target-runtime import/installed simulation82파일 및 실제 서비스 UID
검증 후 Web만 반영했다. 이전 Web51과 runtime source diff는 HTML 안내1줄뿐이다.
Web PID357932/invocation11ff9f3d1e8b4b2299f5fa8f9ed70975이며 API/QUERY/INDEX/Material/
Catalog/ROLE의 PID·invocation은 전후 같다. 설치 wheel SHA는
`4c93c66f626908ba10a0f9fffcfae21eb291eafbee26192f935c2e5525b7bd24`다. HTTPS 공개 static
HTML과 설치본/source의 SHA14d2e520이 같고 HTTPS ready도 PASS다. 미인증 `/studio/`는
의도대로303 login redirect였다. 이를 실제 사용자 로그인·Native 다운로드 PASS로 해석하지
않는다. 첫 health 요청의 잘못된 URL404도 관측 오류로 구분한다.

동일 capture의 실제 consumer를 더 대조해 누락된 활성 설치본을 확인했다. QUERY는 고정 SDK
`11d826...`에서 직접, 결과 조회는 private Catalog1b30에서 실행하며 두 곳에 이전
APPROVED-only 조건이 남아 있다. prepared anchor가 current이거나 정상 cache hit면 통과할 수
있으므로 모든 검색 실패를 주장하지 않는다. 그러나 pinned historical population의 fresh
검증은 같은 이유로 거부될 수 있다. INDEX0a56만으로 이 leaf 수정의 완전 반영은 아니다.
동일0a56 SDK를 QUERY와 private Catalog에 최소 호환 반영하는 후속을 준비한다. 새 Identity/
정책/DB migration·model/space/vector 변경은 필요 없으며 기존 QUERY/config file-set owner를
재사용한다. 아직 두 소비자는 미전환이고 실제 새 사용자 검색은 실행하지 않았다.

전체450개 목표는 ACTIVE다. EOM2의 같은 native HTTP driver는 Studio 로그인 입력 대기이고,
나머지17회차는 미제출이다. 비밀번호·인증 파일·이미 완료한 원본/분석/Graph/벡터를 바꾸지 않았다.

## 2026-11-15 03:54 UTC — 새 GPU 계산4건 성공 / Native 화면 경계 회귀

재개한 같은 INDEX invocation의 새 요청
`workflow_e74413aeeab44740b0aff664d9dd3c9f`와 owned encoding4개가 생성됐다. 03:47:37 UTC
공식 observer에서4개 모두 SUCCEEDED 및 completion event 있음을 확인했다. Root service의
active/READY만으로 대신 판정하지 않았다. 이때 새 index head 저장/Workflow 완료는 아직
진행 중이고 stored GPU/CPU head는 각각1384/1324다. 근거는
`staging/native-index-history-resumed-progress-0348-20261115.json`이다. 다른 원래 실행·
첫 회차 문항·성공/실패 이력과 나머지17회차의 대기 중 HTTP driver는 보존했다.

재사용 GUI/API를 추가 대조했다. Native 기능은 이 dataset driver만의 우회가 아니라
기존 자료 학습의 문제 HWP/HWPX+해설 HWP/HWPX+실제 XLSX→공식 Native API 경로다.
엑셀 없이 올리는 기존 일반 학습과는 동작이 다르므로 안내/문서의 경계를 명시했다.
신규 mode/flag/worker/DB/wire/권한 변경은 없다. 이번450개는18개 실제 XLSX가 있어 전부
현재 Native 입력 범위다. XLSX 없는 Native pair를 완료된 기능으로 확대해 말하지 않는다.

기존 local Playwright module/binary를 사용해 합성 Chromium 포함49 PASS/SKIP0, developer
context13 PASS, lint·JS 문법 검사가 통과했다. 별도 다운로드/설치0이다. 첫 browser 실행의
기본 cache 경로 미발견은 실제 local browser 경로 지정으로 해소했다. 실제 사용자 HTTPS
Native 업로드/다운로드 검증은 여전히 별도이며 첫25 Native download gate를 아직 통과했다고
주장하지 않는다. root gate 로그는 `staging/native-material-guidance-root-gate-20261115.log`다.
화면 안내 변경은 source 후보이며 Web-only wheel/설치·운영 HTML 대조 뒤 따로 기록한다.
전체450개 목표는 ACTIVE다.

## 2026-11-15 03:37 UTC — 동일 완료 재조회 PASS·INDEX 재개

같은 publication command의 APPLY replay는 원래 Workflow/index/hash/binding1384를 반환했다.
resumed_commands0, model_calls0, encoding4개와 전체 cutoff fingerprint 불변이다. completion
영수증도 같은 bytes를 유지했다. replay 로그는
`staging/native-index-history-publication-replay-20261115.log`다.

공식 read-only observer에서 기존 GPU head1384/1581, CPU head1324/1581, 두 head의 approved
Artifact와 첫 Native canary3개의 accepted 공개 풀이 및 양 space binding metadata를 확인했다.
이 분모는 원래 Graph `graphrev_b5ddf74ca106b2bb2725477931fcd183`의 published scope이며
450개 신규 문항의 완료 수가 아니다. 새 service revision의 처리 건수0은 기존 encoding 삭제를
뜻하지 않는다. 구 revision의 별도 nonterminal 역사12건은 이번 복구 범위에 넣지 않고 보존했다.
근거는 `staging/native-index-history-stored-progress-before-start-20261115.json`이다.

03:36:16 UTC INDEX source0a56를 시작했다. PID322043, invocation
`f691e972135246cab5304a4a2adaee19`이며 CPU overlap과 CONCRETE_FACETS reconciliation을 확인했다.
03:37의 실제 source admission에서 과거 실패 위치 PUBLIC_SOLUTION_REPORTS와 population
revalidation이 COMPLETED로 통과했다. 이는 단순 active/READY보다 강한 실제 읽기 증거지만,
재개 후 다음 새 CUDA 수치 실행·새 head 저장까지 완료했다는 뜻은 아니다. API/Web/QUERY/
Material PID는 각각3297861/3299009/3528016/222919로 보존했다. 원래 first25/22번 보완은
완료 상태이며, 나머지17회차 HTTP 입력은 같은 EOM2 `native-import` 숨김 인증 대기다.
전체450개 목표는 ACTIVE이며 새로운 비밀번호 파일이나 요청 identity를 만들지 않았다.

## 2026-11-15 03:30 UTC — 원래 GPU 요청 완료·기존 벡터 보존 확인

INDEX metadata SDK `0a56aaf1`의 공식 PREPARE/PUBLISH/ACTIVATE를 통과했다. 새 Identity는
`localindexservicerev_3f43091e7e8948159f94216abd4f4908`, runtime SHA는
`f1a63a33409e324d21a1749ff36157a8cafb89affa02672255ffe09dde173407`다. 물리 controller0f282,
모델·recipe·CPU/CUDA bundle/space와 API/Web/QUERY/Material·ROLE Runner는 보존했다. 고정 cutoff의
완료 encoding metadata와 보존 대상 config/peer 상태를 각 phase 전후 대조했다. 아직 INDEX
service는 시작하지 않았다. exact carry guard의 오프라인18개와 기존 publication source17개도
통과했다(실제 source PYTHONPATH 재실행 로그 r2를 기준으로 한다).

기존 `recover_prepared_index_publication`으로 원래 CUDA 요청을 완료했다. 결과는
`workflow_9713c7afeb0047e7b5aacd0c5bf738a8` COMPLETED, 원래 index revision
`embeddingindexrev_bfcc7f7a5b1831d9f6a2f7529f8798e7`, hash
`33193f6924f4afcdcc0e579404a2d6198ce7cfe24705f790e4213696f05cac6c`, binding1384다.
원래 command1개만 재claim했고 encoding4개/ownership/completion과 전체 기존 encoding
fingerprint는 그대로다. 새 모델 실행은0이다. 03:19 시작해03:30:37 관측에서 완료했고,
그 사이의 시간을 새 GPU 계산으로 해석하지 않는다. 공식 owner의 source/등록/영수증
무결성 검증을 수행했다. 원래 실패 이력·CPU 성공 command·기출/창작/Native 정본을 보존했다.

운영 명령/결과는 `/var/lib/eom-native-index-registered-publication-recovery-20261115`,
로그는 `staging/native-index-history-publication-{prepare,complete}-20261115.log`다.
배포 helper SHA는 `cae44fa94373e2aaf84bdb4732eebaeda5477ed4427f2d4e1dee42b10c872848`,
완료 helper SHA는 `472548cb6e9223e538d164836155df4780cfe5b91055299fd7189606b7499db9`다.
다음은 동일 command replay/저장 head 관측 후 INDEX 재개다. HTTP driver는 여전히 같은
2번 창의 Studio 입력을 기다리며 나머지17회차는 미제출이다. 전체450개 목표는 ACTIVE다.

## 2026-11-15 03:07 UTC — INDEX 실제 저장 성공·미완료 영수증 한 건 식별

`0a56aaf1ff82051fa7cd4c40eef8ddd163ed93ec` 후보를 커밋·푸시하고 build-only/RECORD 및 공식
immutable SDK 설치를 완료했다. 실제 runtime은 아직 전환하지 않았다. 최초 설치 시0444
shell helper의 직접 실행은 실패했고, 같은 보호된 helper를 `/bin/bash`로 정상 실행했다.
두 실행 로그를 보존한다. 임시 DB는 정식 cleanup으로 제거했다.

정확한 현행 Identity 조회에서 `workflow_9713c7afeb0047e7b5aacd0c5bf738a8`의 command
`wfcmd_b8e99d7c493442fa94fe3be2a035d391` 한 건이 PROCESSING으로 남은 것을 확인했다.
02:28:38 UTC lease는 만료됐다. 공식 native readers의 짧은 SHARE 관측과 명시적 rollback에서
encoding4개 SUCCEEDED/completion 있음, coordinator COMMITTING과 ALLOCATION/INDEX_PREPARED/
REGISTERED3개 checkpoint를 확인했다. index revision은
`embeddingindexrev_bfcc7f7a5b1831d9f6a2f7529f8798e7`이다. byte 검증은 아직 별도이며 metadata
관측만으로 최종 Workflow COMPLETED를 주장하지 않는다. 원래 CPU 완료 command도 보존한다.

새 영수증 producer는 allocation에서 예약된 ID이며 아직 Job이 없는 것이 정상이다. 진단
초안이 그 예약 ID까지 Job 존재를 요구해 한 번 실패했으며, 원래 frozen helper/실패 로그를
보존하고 필수 native/encoding Job만 검사하는 r3로 수정했다. 운영 row는 변경하지 않았다.
근거는 `staging/native-index-history-blocked-workflow-inspect-r3-20261115.json`이다.

이 한 건은 재계산/FAILED 정산 대신 기존 publication-only 복구로 완료한다. 인계 guard는
완전히 계산·등록된 exact 원요청만 예외로 pin하고, 다른 미완료0·만료 lease·물리 drain·
encoding 불변을 다시 검사한다. 새 service/grant의 공식 successor 반영 뒤 원래 완료
영수증을 저장하고 동일 command replay를 확인한 후에만 INDEX를 시작한다. 세부는
`../architecture/PUBLIC_SOLUTION_HISTORICAL_REVISION_CAPTURE.md`다. 현재 이 인계/복구는 아직
미실행이다. frozen HTTP driver는 Studio 로그인 입력 대기이며 나머지17회차는 미제출이다.
전체450개 목표는 ACTIVE다.

## 2026-11-15 02:51 UTC — 22번 새 풀이·Graph 완료 / INDEX 이력 조건 수정 후보

22번의 image-only 새 revision에 대한 base `analysisrun_790cb7b9e71f4d1c8a8e6833c60ffadf`와
공개 풀이 `analysisrun_16dd0cfa385d45418f7307fdcbe7991f`가 모두 ACCEPTED다. 02:38:37 UTC
관측에서 `graphrev_54f1af9a585a980475e784e30376e094` publication을 확인했다. 원래 task와
구 revision·풀이·Graph는 보존한다. 실제 HTTP Native 다운로드 검증은 별도이며 현재 frozen
driver r4는 같은 checkpoint로 Studio 로그인 입력을 기다린다. 나머지17회차는 아직 미제출이다.

INDEX는 02:14 UTC `EMBEDDING_REGISTRY_POINTER_INVALID`로 종료됐다. 원래 CPU 수치 명령은
SUCCEEDED이며, 실패 위치는 `public_solution_source_capture`의 APPROVED-only row 검사다.
원래 Graph pool/resolver는 완전한 승인 이력이 있는 SUPERSEDED/RETIRED도 정확히 pin하지만
capture만 거부했다. 이는 모델/GPU 계산 실패가 아니다. 기존 resolver의 이력 조건을 공통
함수로 추출해 capture에서 재사용하는 최소 후보를 만들었다. latest 대체·과거 source 제외·
DB row 수정·완료 벡터 삭제는 하지 않는다. 설계는
`../architecture/PUBLIC_SOLUTION_HISTORICAL_REVISION_CAPTURE.md`다.

source 집중62 PASS와 추가 인접151 PASS, formatter/linter/type checker가 통과했다.
별도 guarded disposable DB의 새 실제 row-lock 회귀12 PASS, 정식 chat-knowledge 전체
140 PASS(위12개 포함)다. 원본 source/report/Artifact admission은 일부 synthetic port이므로
이를 live NAS/수치 성공으로 해석하지 않는다. 로그는
`staging/native-index-history-{root-source-gate,disposable,full-disposable}-20261115.log`다.
현재 후보는 미배포이며, 물리 controller·CPU/CUDA/model/recipe와 QUERY/API/Web/Material을
보존하는 INDEX metadata SDK/Identity successor의 안전한 경계 확인·반영·재개가 남았다.
전체450개 목표는 ACTIVE다.

## 2026-11-15 02:22 UTC — 22번 그림 보완 실제 등록·새 분석 실행

공식 correction owner의 prepare/import/validate_applied를 실제 원본에 적용했다.
같은 logical Item `item_c69276cbeac64a03bc1ab0b2c00f45cd`의 새 approved revision은
`itemrev_e57436ab7cd54095843618f8133b3e9a`다. 검토한 source use/PNG를 `block_x_table`
다음에 삽입했으며, 새 영수증 SHA는
`6e7a939d468b1dfb4de39d6c65c0fdce8811126ead829f30cb555206ba55c31c`다.
old revision·task·분석·원본 Native 문제/해설과 비본문 component5개는 보존한다. 25번은
수정하지 않았다. actual owner가 읽은 Native 파일·현재 권한·원본 scope/PNG hash와
image-only content 변경 검증은 PASS다. 이는 HTTPS/브라우저 육안 검증의 대체물이 아니다.

새 base는 `analysisrun_790cb7b9e71f4d1c8a8e6833c60ffadf`, Workflow는
`workflow_27af92742ced4f1fbad3e85ab15fca25`이며 02:21 관측에서 RUNNING이다.
실제 worker는 slot03/job_d7e86d32e06846a5b34772cd71b7b904다. 공개 풀이와 새 Graph는
아직 완료를 주장하지 않는다. 공식 owner의 같은 key를 읽는15분 bounded watch가 진행
중이며 FAILED는 자동으로 새 요청을 만들지 않는다. helper는
`/usr/local/libexec/eom-native-question22-visual-correction-20261115/apply.py`,
SHA `eeab6ce4bba9a845087ea1f79cca9fad10930b70b18224738c68dbaa33f15347`이다.
준비/등록/학습의 별도 로그는 staging의 `native-question22-correction-*-20261115.log`다.

원래450개 checkpoint와4개 공식 복구 영수증을 그대로 사용하는 frozen HTTP driver r4를
EOM2 `native-import`에서 시작했다. 현재 Studio guiadmin의 숨김 로그인 입력을 기다리며
나머지17회차는 아직 제출하지 않았다. 새 요청 identity나 비밀번호 파일은 만들지 않는다.
인증 후 실제 첫 회차 Native 다운로드/해시 gate를 수행하고,22번 새 Graph까지 확인한 뒤
같은 driver에서 나머지를 이어간다. root 운영 명령의 성공을 이 HTTP 로그인 성공으로
대체 해석하지 않는다. 이전 Source70 전용 status helper의 post-release 호출은 Source pin
guard가 올바르게 거절했으며 실패 로그를 보존했다. 이를 운영 run 실패로 분류하지 않는다.

## 2026-11-15 02:02 UTC — coverage 후보 운영 반영·수치 runtime 보존

`1b30a5805cfb04ddbff40cd1aeb59990f018ad56`(tree
`f44687e38e99bab96d3239bca90802184a0dcd7d`)를 커밋·푸시했다. 별도 immutable SDK의
wheel RECORD/source-free import, 정식 ADMIT와 migration0079 VERIFY, private postdeploy가
PASS다. Catalog PID222321, ROLE Runner4개의 PID222549/222548/222551/222550, 재개한
Material PID222919가 active다. Material은 지원된 SIGINT로 먼저 정상 drain했다.
수치 자식이 자연 종료하는 공백에서만 설치 파일을 교체했고 GPU 작업은 중단하지 않았다.

운영은 같은 logical Material preset의 ROLE1.39, definition2/plan40, coverage Pack1.2/1.3을
사용한다. 기존 ROLE1.37·Pack1.0/1.1과 과거 receipt/lineage는 보존한다. 나머지3개 실행
설정은 예전 env pin에서 `current_model_preset`가 검증한 실제 관리자 current로 재고정했다.
현재4개 모두 기존 shared capacity `capacityrev_f145d972c88c4c74a1c698af873e3bcc`를 사용한다.
다른3 logical current/history·관리자가 고른 모델/추론 깊이·실제 한도는 수정하지 않았다.

API/Web PID3297861/3299009, QUERY PID3528016/Invocationd826, INDEX PID4111864/Invocation1186와
수치 코드·worker executable·CPU 그림 도구70은 그대로다. 01:51 공식 읽기에서 GPU head는
1380/1581, 별도 CPU head1320/1581이며 이전 저장 수1376/1316에서 각각4개 늘었다.
이 수를 합치거나 새450개 전체의 임베딩 완료로 해석하지 않는다.

초기 operator 실패도 남겼다. 첫 helper freeze의 터미널 입력 오류는 서비스 효과0이었다.
R5의 상속19개는 분석 포인터를 직접 복사하지 않고 history owner로 읽는 정상 구조이므로
배포 helper의 잘못된 direct-column 조건만 제거했다. controls helper는 실제 Material
unit의 Catalog staging 경로를 사용하고 오래된3개 env pin을 공식 current resolver로
정렬했다. 운영 row를 직접 고치거나 capacity 검사를 완화하지 않았다.

근거는 staging의 `native-coverage-api-build-20261115.log`,
`native-coverage-release-{prepare-r3,admit,activate-postdeploy-r3}-20261115.log`,
`native-coverage-controls-stage-r4-20261115.log`, `native-index-progress-0151-20261115.json`이다.
최종 release helper SHA는 `e009fc00c49dec7796608481bc2ff469c9c9b4b655e94ad9cadcdbcbebe55503`,
controls helper SHA는 `95c90fd850deeed3f956c1164067054278d539728250c4b35b992afae39850f1`이다.
두 disposable DB/제한 계정은 검증 후 정식 cleanup으로 제거했고 소스/실패 로그는 남겼다.

**전체450개 목표는 ACTIVE다.** 이 기록은22번 그림 보완이나 새 풀이/Graph·실제 HTTP 읽기
완료를 뜻하지 않는다. 다음은 검토한22번만 image-only successor로 수정해 새 분석·공개 풀이/
Graph를 연결하고, 첫 회차 실제 다운로드 gate 뒤에 원래 나머지17회차 처리를 이어가는 것이다.

## 2026-11-15 01:34 UTC — 누락 방지 후보의 저장·동시성 회귀

후속 최종 gate는 소스1179 PASS, 새 disposable DB의 정식 자료 학습 suite111개와 마지막
coverage upgrade1개 PASS다. 22번 보완의 실제 Registry 동시성 검사에서 동일 reviewed key의
manifest staging 충돌을 재현해 기존 reviewed import owner에 key별 transaction lock을
추가했다. 두 호출이 예외 우회 없이 같은 successor를 반환하고, 다섯 비본문 component와
Native 읽기·메타데이터를 보존하며 fresh approved-Item 분석이 새 본문을 읽는 것도 확인했다.
과거 Prepared3는 producer source/hash를 그대로 보존하고 tool/parser/options와 실제 원본
재계산 결과로 재인가한다. 호환 SDK 업데이트만으로 historical replay를 막지 않는다.
최종 소스·DB 로그는 각각 `native-material-final-source-gate-r2-20261115.log`와
`native-material-final-disposable-20261115.log`다. 첫 충돌 실패 로그도 보존한다.

새 Material 봉투와 coverage, 구·신 receipt/lineage reader, 실제 source 재인가 및 RuntimePins
후보의 material 소스 suite는1089 PASS다. 별도의 marker-guarded disposable PostgreSQL에서
기존 자료 학습 전체106개, 새 봉투의 실제 Pack/Artifact/Registry 등록3개, 현재 관리자의
모델·추론 설정을 보존하는 protocol-only upgrade1개를 실행해 통과했다. 새 등록은 동시
생성·저장 직후 중단·같은 요청 재전송에서 같은 revision/lineage를 보존한다. upgrade는
관리자 동시 변경을 CAS로 거부하고, Artifact 저장 후 응답 유실에서 같은 draft/report를
재사용한다. 운영 DB를 테스트 대상으로 사용하거나 old current policy를 강제로 되돌리지 않았다.

검증 로그는 staging의 `native-material-whole-source-gate-20261115.log`,
`native-material-disposable-20261115.log`, `native-coverage-registration-disposable-r2-20261115.log`,
`native-coverage-controls-disposable-20261115.log`다. 첫 직접 invocation은 필요한 opt-in을
누락해3 SKIP이었으며 별도 로그로 보존하고 PASS에 포함하지 않는다. 새 coverage preset
동시성 suite는 기존 ROLE1.37 bootstrap suite 뒤에만 수행한다.

이는 설치·활성화·실제22번 보완·나머지425개 등록 완료의 증거가 아니다. 후보는 아직
운영 미배포이며 native correction의 실제 fresh-base 경계 검사와 최종 wheel 검증을
진행한다. 기존 API/Web51·GPU/QUERY의 수치 runtime pin은 변경하지 않는다. CPU 그림
도구70도 자체 runtime/source identity를 갖는 별도 adapter여서, 바뀌지 않은 도구를 새
application commit과 같게 만들기 위한 재설치는 하지 않는다.

## 2026-11-15 01:07 UTC — 첫 회차25개 풀이·Graph 완료와 도식 누락 발견

공식 read-only run5 조회에서 state COMPLETED, QUESTION COMPLETED25, 등록25와 Graph
연결25를 확인했다. 기존19개와 실패분6개의 지원된 후속 처리까지 기술적으로 완주했다.
관측 시각은01:07:44 UTC이며 이를 정확한 완료 시각으로 해석하지 않는다. 기존 run4·
accepted-invalid base·실패 이력은 보존한다. 근거는
`staging/native-reference-run5-public-status-0050-20261115.json`이다.

별도 fidelity 대조에서 실제 차이를 발견했다. Native 문항 파일의 BODY picture use는8개,
등록 JSON의 PNG는6개다. 공식 Artifact/Native reader로 두 원그림과 정본 body를 직접 읽었다.
25번은 같은 내용·표시가 native equation으로 표현돼 있어 정상이며 변경하지 않는다.
22번은 필요한 도식이 body에서 빠져 있고 관련 거리·위치 정보가 다른 block에도 없다.
원본 문제·해설 HWPX50개는 원래 hash 그대로다. 선택한 image↔등록 image의 일치만으로
모든 원그림의 의미 보존을 증명할 수 없다는 한계를 기존 감사에 추가한다. 원본/문항
내용·PNG는 Git/Slack에 복사하지 않는다. 검토 증거는 staging의
`native-body-22-25-{view-export,content-review}-20261114.json` 및 제한된 local 검토 copy다.

이 실제 누락을 수정하기 전에는 나머지17회차를 제출하지 않는다. 구현 후보는 기존
자료 학습의 미래 봉투ROLE1.39/plan40와 같은 logical preset, per-use coverage1,
receipt2/lineage2 및 Pack1.2(generic)/1.3(native)다. Work1/inner Result1/OfficeBindings1과
기존 모든 wire bytes는 유지한다. 22번만 reviewed image-only successor로 고치고 새 base/
공개 풀이/공통 Graph/INDEX를 연결한다. old task/정본/report/Graph를 덮어쓰지 않는다.
이 시각에는 소스 구현·비운영 테스트 단계이며 새 봉투/Pack/프리셋은 운영 미활성이다.
전체450개 목표와 실제 HTTP 조회·나머지425개·전체 대상 임베딩 검증은 계속 남아 있다.

## 2026-11-14 23:25 UTC — 첫 회차25개 Native 실등록 전수 대조 PASS

run5의 실제25 Item을 공식 Native source/완료된 추출/Registry/Artifact reader로 읽어
문제·해설50개 파일, Excel25행과 원본·parsed workbook2개 member, 본문 PNG6개의 hash와
연결을 검증했다. 기존 완료19개의 Item/base/Graph pin도 시작·끝에 그대로다. 검증의
DB/NAS 쓰기와 모델 실행은0이다. read-only summary는25 PASS이며 records SHA는
`305310b8e6da6c0610bab46e78fcd5377bbdb1c0d020d06abe0009cacedb1369`다.

이 검증은 등록 원본·그림 검증이지 남은 풀이·Graph 완료 gate가 아니다. 관측 당시 run5는
PROCESSING, COMPLETED19/PUBLISHING1/ANALYZING1/REGISTERED4, Graph 연결19개다.
실제 후속 분석 슬롯03도 실행 중이다. 나머지17회차 제출은 기존 r4 driver의 최종 gate와
실제 HTTP Native 읽기 뒤에 진행하며, 현재 목표를 완료 처리하지 않는다.

첫 감사 helper는 처리 ordinal에서 인쇄 번호를 계산해 Q1→Q3→Q2 순서를 잘못 해석했다.
운영 문항·코드는 바꾸지 않고 공식 Native metadata의 실제 번호로 대조하도록 수정했다.
실패한 r1/r2 로그와 frozen helper는 보존했고, 그림 없는 정상 문항의 조건은 완화하지 않았다.
최종 frozen helper SHA는 `31cc3f86a6d8c59833486809680a47824052661aaed131c69c5669523b22cb75`,
증거는 `staging/native-run5-all25-visuals-r3-20261114.jsonl`이다. 한글 육안 검수나 실제
유사도 검색 성공까지 이 메타데이터/bytes 검증으로 확대 주장하지 않는다.

## 2026-11-14 23:14 UTC — 재처리 문항 실제 그림·임베딩 저장 확인

run5의9번이 새 Item으로 등록됐다. 실제 actor의 공식 Native source 읽기와 완료된 추출
결과를 대조해 본문 picture use `officeobj_b189714d298cd92309e1ceea45c62427`, 등록 PNG
SHA `41ea433a4bb82f8965310c1683a09729f548c51b430472f0c919f90f75082c41`, 원본 문항 HWPX
SHA가 일치함을 확인했다. 현재 Prepared3의 실제 source catalog를 해석했으며 과거 Prepared2
증거로 대신하지 않았다. 이 검증의 DB/NAS 쓰기와 모델 실행은0이다. 23:13 공식 run 읽기는
등록24/25, Graph 연결19/25, COMPLETED19/PUBLISHING1/REGISTERED4/RUNNING1이다.
이는 첫 회차 전체 완료나450개 등록 완료를 뜻하지 않는다.

나머지17회차 HTTP 배치 driver r4는 기존 checkpoint/원본 archive와 정확한6개 복구 집합을
유지한다. 설치된70 SDK의 offline preflight는18회450개 PASS, 네트워크/로그인0이다.
첫 회차25개 완료 및 실제 공개 읽기 뒤에만 나머지를 제출한다. driver의 로컬 HTTP 검증을
HTTPS 브라우저 검증이라고 보고하지 않는다.

INDEX는 active 확인뿐 아니라 새 수치 결과의 저장까지 진척됐다. 23:14 관측의 GPU head는
1356→1360(22:52 게시), CPU head는1296→1300(22:44 게시)이다. 새 GPU4개의 계산·등록과
Workflow 완료가 확인됐다. 다음 GPU4개는 RUNNING, CPU4개는 계산 후 결과 검증 중이다.
두 공간의 수를 합치지 않으며 관측 window의 완료 수를 누적 전체 수로 부르지 않는다.
QUERY PID3528016/Invocationd826은 그대로다. 이전 FAILED retirement는 보존한다.

근거: `staging/native-run5-q9-visual-20261114.json`,
`native-reference-run5-public-status-2315-20261114.json`,
`native-batch-driver-r4-installed-preflight-20261114.log`,
`native-index-progress-2316-20261114.json`이다. 관측 파일명보다 내부 UTC 시각을 우선한다.

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
