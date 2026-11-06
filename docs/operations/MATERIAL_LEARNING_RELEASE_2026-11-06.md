# 자료 학습 운영 반영 — 단계별 증거

기준: 2026-11-06 08:01 UTC. **전체 목표의 완료 보고서가 아니다.**
사용자 지정 순서는 자료 학습의 운영 반영·실제 처리 확인을 완료한 뒤 Map의 Layer
표시 개선에 착수하는 것이다. Map은 아직 시작하지 않았다.

## 08:30 UTC 실제 등록 완료 및 남은 INDEX gate

후속 source 수정: 기존 source pool prefetch와 관계 dependency 관측이 같은
`accepted_public_solution_successor_predicate`를 사용한다. 정확한 predecessor·ACCEPTED·
기출 V10/등록 V11만 선택하며 별도 DB/schema/cache나 문항별 fallback을 추가하지 않는다.
실제 marker-guarded DB에서 일반/자료 전용 preset 양쪽의 등록→accepted V11→같은 bulk
선택→strict physical Artifact reader→공통 projection을 확인했다(44 PASS). 집중 source82
PASS와 dependency/context62 PASS, core3개 type/format/lint PASS다. 검사는 범위가 겹치며
합산하지 않는다. 후속 설치물에서 같은 운영 canary와 INDEX 재개 확인이 남아 있다.

같은 canary retry run의4개 task와 전체 run이08:18 UTC에 **COMPLETED**됐다. 문항
Graph는 `graphrev_f8f21cfea70f16464dc7dc26195e7ef4`이고 설명의 이전 Graph도 보존한다.
실제 V11 풀이 조회·공통 text AVAILABLE, 설치 API의 DB 외부 목록에서 같은 Item이
표시됨, 설명 RAG V6와 문항 주제 RAG V2의 동일 요청 replay/정확한 source 포함까지
확인했다. 실제 권한을 확인한 owner 호출이지 HTTPS 로그인/사람 검수 증거는 아니다.

마지막 실제 INDEX source capture에서 **추가로 닫아야 할 결함**을 확인했다. 원래 bounded
source pool의 successor metadata prefetch/관계 관측이 V10만 선택해, 새 등록 문항의
V11 accepted/proposal Artifact가 strict reader에 준비되지 않는다. 직접 Catalog 공개
보고서 읽기는 성공하지만 공통 INDEX용 `PinnedArtifactReadContext`에서는
`pinned Artifact metadata was not captured`로 거부된다. 검증을 완화하거나 별도 파일
reader로 우회하지 않는다. 기존 bulk predecessor query와 관계 관측에 실제 지원하는
V11 family를 포함하고 실제 임시 DB 및 같은 canary capture로 검증한 뒤 안전한 runtime
경계에서 반영해야 한다. 아직 전체 goal 완료/Map 착수로 표시하지 않는다.

현재 확인 근거는 `/tmp/material-learning-actual-read-evidence-20261106-9.log`와
`/tmp/material-learning-postdeploy-read-20261106-28.log`다. 한글 편집 가능한 HWPX 재출력은
사용자가 이번 목표에서 제외한 후속 기능이며, 이 INDEX gate를 그것으로 바꾸지 않는다.

### 관측 복구와 로컬 공간

observer35267c85를 실제 반영했고,17:19 한국시간 Slack의 정상1줄 보고까지 확인했다.
창작 원본 대기를 모르는 관측기가 전체 보고를 실패로 뭉치던 오류는 수정됐다. GPU 관측기는
그동안에도 정상 동작했으며293/520·CPU 원래 작업 실행 중·GPU 현재0%를 보고했다.
producer/INDEX/API/Web/QUERY/자료 coordinator PID와 인증/수치 환경은 교체하지 않았다.

이어서 여유 공간 약9.2GiB가 기존10GiB guard를 넘지 못해 창작 producer가 실제
`WAITING_FOR_RESOURCES/BACKGROUND_LOCAL_STORAGE_LOW`로 기다리는 것도 확인했다.
검증된 기존 일회성 cleanup을 재사용해 고정 목록의 완료 API source 복사본10개만
정리했다. 같은 source.tar·wheel·Git commit·설치본·rollback·원본·NAS·모델은 보존했고
실행 중 argv/cwd/exe/FD 참조와 활성 commit은 제외했다. 약1,294,733,312 bytes를
확보해 여유11,128,094,720 bytes를 확인했다. 원래 archive/wheel로 복구할 수 있다.
운영 DB/모델 실행/서비스 재시작은0이다.
고정 plan/report는 `/tmp/eom-material-source-copy-cleanup-plan-20261106.json`,
`/tmp/eom-material-source-copy-cleanup-report-20261106.json`이다.

## 08:01 UTC 실제 canary checkpoint

| 경계 | 실제 결과 |
| --- | --- |
| API/Web/Catalog/Runner 및 migration | e1df5c8f 호환 배포, head0074 |
| 자료 학습 전용 coordinator | 493144f8, enabled/active |
| 원본 업로드·준비·동일 명령 재전송 | PASS, 원본/준비 포인터 재사용 |
| 실제 발견·문항 추출 | 실제 Codex Workflow/Job 성공, 최초 실패 이력 보존 |
| 문항 Registry 및 base 분석 | 등록·exact content read·ACCEPTED |
| 문항 공개 풀이 | 실제 Workflow/Job 성공·accepted V11 공개 조회 PASS |
| 공통 임베딩 입력 | 실제 공개 보고서로 public-solution-text AVAILABLE |
| 설명 분석·공유 Graph·공식 RAG | ACCEPTED·Graph 등록·evidence V6 read/replay PASS |
| 문항 공유 Graph | PUBLISHING, 완료를 기다리는 중 |
| 설치 API의 DB 외부 목록 | 호출 PASS, Graph 반영 전 canary 미포함은 예상 상태 |
| 실제 HTTPS 인증 사용자 화면 | NOT_RECORDED, owner application을 로그인 증거로 확대하지 않음 |

실제 root owner application에서 원래 guiadmin의 현재 role/permission을 확인했다.
RAG의 Graph·policy·source pin은 고정했으며 같은 요청은 기존 evidence Artifact를
재사용했다. 원문/worker 내용을 Slack에 노출하거나 권한을 WORKER/ADMIN으로 위조하지
않았다. 공개 풀이 수정은 한 모듈만 배포했고 API/Web/QUERY/INDEX의 PID/invocation·
설정·수치 runtime·Codex 인증/helper/capability policy는 인계 전후 불변이다.
원래 문항/accepted base/성공 child를 재생성하지 않았고 동일 solution intent만 이어갔다.

소스46 PASS·material 임시 PostgreSQL44 PASS·type/format/lint·source-free wheel/RECORD
PASS는 해당 결함의 회귀 증거이며 실제 canary 성공과 별도로 기록한다.
INDEX는 기존 CUDA/CPU 묶음을 실제로 완료하고 다음 원래 CPU standby를 처리 중이다.
새 자료의 전체 임베딩/검색 준비나 기존 corpus 전체 완료를 주장하지 않는다.

추가 근거:
`/var/lib/eom-material-owner-493144f8-20261106`,
`/tmp/material-learning-receipt-owner-release-20261106-1.log`,
`/tmp/material-learning-actual-read-evidence-20261106-2.log`,
`/tmp/material-learning-postdeploy-read-20261106-22.log`.
아래 시간별 기록의 ‘미배포/실행 전’ 표현은 해당 과거 단계의 상태다.

### 배경 감시의 원본 대기 표시

08:10 UTC 기존 창작 producer는 실제 status에서1013/1053 확인 완료·40개 원본 보류인
`BLOCKED_SOURCES`였다. producer는 계속 실행되며 원본 준비를5분마다 다시 확인한다.
별도10분 observer가 이 상태를 모르는 allowed-state 목록 때문에
`CREATIVE_OBSERVATION_STATUS_INVALID`로 종료하는 불일치를 발견했다. observer의 기존
검증·freshness·실제 service 상태를 유지해 명시적 `SOURCE_WAIT`로 표시하고, 선택적
Slack reporter는 ‘원본 확인 대기’라고 구분한다. 보류를 성공으로 바꾸거나 슬롯이 바쁘다고
표시하지 않는다. 집중26 PASS·core2개 type/format/lint PASS. 실제 producer/INDEX/자료
등록 실행은 멈추지 않고 observer/선택적 reporter만 후속 설치한다.

## 06:58 UTC 후속 확인

- material coordinator64bcc2fa를 전용 prefix로 활성화했다. 기존 실제 DISCOVER 결과를
  재사용해 다음 문항 child로 진행했으며 API/Web/QUERY/INDEX를 이 reader 수정 때문에
  다시 설치하지 않았다.
- 실행 helper 교체 뒤 reviewed Codex compatibility가 이전 helper hash를 pin해 슬롯이
  DEGRADED로 관측된 원인을 확인했다. 계정/사용량 소진이나 새 로그인이 필요한 문제가
  아니었다. 기존8개 slot/model/effort 조합을 현재e1 실행 환경에서 실제 검증했다:
  **8/8 PASS, 실제 model calls8, verify97.7초**. 공식 committed report와 policy installer로
  반영한 뒤 지원된 OBSERVE로6개 슬롯 모두 READY를 확인했다. 인증 파일은 불변이다.
- 자동 관측 및 readiness probe가 request resource version과 경합했다. 앞선 preflight
  실패들은 모델 호출0이며 보존했다. 실제 실행 중 command/worker lease가 없는 것을
  확인한 뒤 main/maintenance와 당시 active였던 accelerator3개만 짧게 중지·원래대로
  복구했다. INDEX를 이 점검을 위해 중지하지 않았다. 앞으로 helper 교체를 포함한
  배포는 CLI version뿐 아니라 이 compatibility runtime 일치를 확인해야 한다.
- INDEX는 첫 새 CUDA 묶음 `CONCRETE_FACETS`, selected targets4를 완료하고 CPU standby
  후보의 readiness에서 종료됐다. 기존 완료와 실패 이력을 보존하고 같은 설치/설정으로
  재개했다. 실제 INDEX mount namespace에서 보호된 CPU verifier PASS와 active를 확인했다.
  일반 host namespace의 진단에서는 고정 loader-cache bind가 없어 MOUNT_INVALID가
  발생하므로, 그 결과를 실제 service의 실패 원인으로 오인하지 않는다. 후속 진행을
  계속 관측하며 아직 모든 미래 readiness 오류가 해결됐다고 주장하지 않는다.
- 실제 문항 추출 child는 `content_region_map`에 `solution` 부모만 넣고 기존 필수인
  `solution.explanation`/`solution.correct_choice_ids` leaf를 빠뜨려 거부됐다. 기존 typed
  검증은 유지한다. 새로운 V2 지침 보완을 별도 immutable instruction/preset successor로
  발행하고, 기존 source/run/성공한 단위는 보존한 공식 실패 단위 retry로 확인한다.
  원래 V1 prompt bytes·FAILED Job을 변경하거나 잘못된 결과를 정규화해 성공시키지 않는다.
- 독립 설명 단위의 실제 분석은 ACCEPTED에 이르러 공유 Graph publication 단계다.
  문항 등록·공개 풀이·공유 Graph/INDEX handoff는 여전히 확인 중이며 Map은 대기다.

재검증 증거:
`/var/lib/eom-material-codex-revalidation-20261106-accelerator-window-2`,
`/tmp/material-learning-codex-revalidation-20261106-5.log`,
`/tmp/material-learning-supported-observe-20261106-1.log`,
`/tmp/material-learning-index-resume-read-20261106-1.log`.
외부에 공유하는 보고에는 자격 증명·원문·worker 결과를 넣지 않는다.

## 실제 설명 등록 및 실패 문항의 한정 재시도

설명 분석은 실제 ACCEPTED 및 공유 Graph publication을 완료했다. 저장이15분 coordinator
lease보다 길어져 옛 owner는 `MATERIAL_LEARNING_COORDINATOR_LEASE_STALE`로 종료됐고,
기존 restart/replay가 이미 등록된 Graph를 재사용해 설명 task COMPLETED와 원 run의
COMPLETED_WITH_EXCEPTIONS를 확인했다. 이 실패를 숨기거나 현재 lease를 직접 연장하지
않았다. 새 claim renewal 후보는 Graph 저장 두 호출만 감싸 기존 owner/token을30초마다
갱신하고 종료 시 다시 fence한다. 원래15분 값은 coordinator 한 곳에서 전달한다.
집중 source61 PASS·임시 PostgreSQL43 PASS·core3개 mypy/format/lint PASS. source 검사는
각기 겹치는 범위이며 합산하지 않는다. 실제 긴 작업과 운영 반영 검증은 후속이다.

지침 보완은 cd3fe05b의 작은 addendum을 원래 역할 지침에 결합해 기존 bundle owner의
정확한 predecessor CAS로 인접한 immutable revision을 발행했다. 기존 platform component는
새 복사 없이 pointer를 재사용했다. 같은 `material-learning` logical preset의 공식
draft→evaluation→release successor를 만들었으며 모델·격리·용량·wire schema는 불변이다.
다른 서비스의 설치물/인증/수치 환경을 바꾸지 않고 material 환경의 learning preset pin만
`execpresetrev_863b1dc8cfa3449eb64e90de337ac7dd`로 선택했다.

공식 retry는 원 source와 성공한3개 task를 재사용하고 실패한 QUESTION만 successor로
처리한다. 같은 retry command 재전송에서 동일 run/중복0을 확인했다. 첫 FAILED Job과
run은 보존한다. 새 run은 `materialrun_581cc9a2d0895f06a430740ee5a5a2c2`이며 실제 child가
RUNNING이다. 아직 문항 등록과 공개 풀이·Graph/INDEX 완료의 증거로 해석하지 않는다.
근거: `/var/lib/eom-material-source-map-v2-20261106`,
`/tmp/material-learning-retry-canary-20261106-1.log`,
`/tmp/material-learning-claim-renewal-db-20261106-2.log`.

## 문항 등록 후 공개 풀이 admission 수정

V2 지침으로 재처리한 실제 추출 Job은 SUCCEEDED이고 문항
`itemrev_4043e2e3e95b4474a1b1ef6231e8847a`가 Registry에 등록됐다. base 분석도
`analysisrun_13e816fc93dd46dcad05c0382b441608` ACCEPTED다. claim 갱신 owner41147228은
07:22 UTC 전용 prefix로 운영 활성화했으며 API/Web/QUERY/INDEX PID·설정, Codex helper/
capability policy는 그 인계 동안 불변이었다.

다음 단계에서 기존 공개 solution command의 `knowledge-analysis` literal과 material 전용
preset logical key를 동일시해 `KNOWLEDGE_ANALYSIS_PRESET_INCOMPATIBLE`가 발생했다.
아직 solution run이 만들어지지 않은 admission 단계이며 모델 결과 오류가 아니다.
coordinator만 지원된 stop으로 멈춰 반복 재시작을 중단했다. 등록 문항·accepted base·
원래 작업·실패 로그·INDEX는 보존했다.

수정 후보는 기존 분석 서비스의 명시적인 내부
`create_material_solution_with_pinned_preset`에서 정확한 material key/ID/revision을
검증하게 한다. 공개 command/schema literal, RPC와 worker 프로토콜은 넓히지 않는다.
같은 V11 엔진의 source/operator·accepted base·protocol/hash·멱등 규칙을 공유하고
일반 기출 base를 이 전용 경로로 채택하지 않는다. 실제 material preset 조합을 쓰는
임시 DB 회귀를 추가해 일반/전용 양쪽의 accepted V11 보고서→공통 임베딩 텍스트를
검증했다: 집중33 PASS, material 임시 PostgreSQL44 PASS, core2개 mypy/format/lint PASS.
다음 전용 owner 인계 뒤 같은 문항·base·동일 solution 의도로 이어가며 재등록하지 않는다.

재개한 INDEX에서 위 첫 CUDA workflow와 그 원래 CPU standby workflow
`workflow_b3f529a5fa5f40229c64eca61d78c42a` 모두 COMPLETED/SUCCEEDED를 확인했다.
실제 저장 완료를 health/active로 대체하지 않는다. 전체 corpus 완결과는 별개다.

## 최신 인계·실제 결과 확인

기존 INDEX는 지원된 main stop Event로 현재 묶음을 자연 종료했다(`Result=success`).
현재 service revision의 non-terminal 요청과 native lifetime이 비어 있음을 기존 owner가
검증한 뒤 unchanged-scope 후속 identity/config를 선택했다.06:08 UTC 새 e1df5c8f INDEX가
enabled/active로 기동했다. 수치 controller/model·CPU/GPU 환경과 과거 기록은 불변이다.
아래 ‘INDEX 인계 대기’ 설명은 배포 순서와 그 당시 상태이며, 인계 자체는 완료했다.

첫 DISCOVER Workflow/Job은 실제로COMPLETED/SUCCEEDED였다. 그러나 coordinator의
완료 결과 읽기에서 file-set 전용 `read_member`를 사용해, 실제 Orchestrator가 저장한
single-primary `ArtifactManifest`에 존재하지 않는 `files` 배열을 요구하는 결함을 발견했다.
모델 실패가 아니다. 같은 결과를 보존하고 기존 `load_json_revision` owner로 읽도록
수정했다. 이 owner는 두 실제 JSON 저장 형식의 identity·lifecycle·manifest·size·hash·
bounded nofollow FD를 이미 검증하며, material reader는 기존 Job/Workflow/plan/source
closure와 정확한 role schema/receipt를 그대로 검증한다. 새 wire format이나 file 변환,
DB/NAS 덮어쓰기·예외 무시는 없다.

실제 Orchestrator writer→Catalog verified JSON reader 회귀를 추가했다(권한/DB port는
명시적 synthetic). 집중70 PASS·material 임시 PostgreSQL41 PASS·mypy/format/lint PASS.
수정 후보는 **material owner에만** 호환 prefix로 반영하며 API/Web/QUERY/실행 중 INDEX를
다시 바꾸지 않는다. 새 모델 요청 없이 이미 성공한 DISCOVER 결과부터 이어서 확인한다.

## 실제 운영에 반영한 범위

### 공개 풀이 연결의 실제 canary 보완

실제 재처리 문항은 원래 Registry에 등록됐고 기본 분석도 ACCEPTED다. 새 전용
`material-item-solution` preset을 기존 공개 command의 literal과 혼동하던 문제는
내부 purpose 경계로 수정해 `55d1c599` material owner에만 반영했다. 공개 wire/RPC나
원래 preset 의미를 넓히지 않았다. 관련 실제 임시 DB44 PASS를 확인했다.

그 후 같은 accepted base를 재사용하는 실제 호출에서 `KNOWLEDGE_ANALYSIS_BASE_INVALID`를
확인했다. source/request/receipt pointer/hash/count는 모두 일치했으며, 유일한 차이는
canonical writer의 `completed_at=...50.000000Z`와 Pydantic 표시의 `...50Z`였다.
기존 Artifact reader의 byte/hash/schema/lifecycle 검증 뒤 receipt를 원래 typed model로
비교하도록 보완한다. 시각이 실제로 달라지면 여전히 거부한다. 정본 bytes·기존 FAILED·
accepted 분석을 수정하거나 문항을 다시 등록하지 않는다. 실제 canonical writer를 쓰는
임시 DB44 PASS와 source 회귀를 확인했으며, 이 한 모듈의 후속 배포·공개 풀이 실제
완료 확인은 아직 남아 있다. API/Web/QUERY/INDEX source·설정·현재 실행은 유지한다.

- 설치 source `e1df5c8f9925d977028c66e2b99ad056a1ada583`: API·Web·Catalog·
  global Workflow Runner·채팅 연결 설정·창작 producer/관측 owner.
- production head `20261105_0074`. 공식 protected release operator context/admission
  1.21로 정확한0073→0074 upgrade와 verify, API/Catalog 기존 role bootstrap을 수행했다.
  테스트를 운영 DB에 실행하거나 row를 직접 수정하지 않았다.
- API/Web 설치 wheel·RECORD, API provider의 정확한 source/wheel/member hash,
  QUERY public/mixed/private wrapper와 Catalog read pin을 호환 set으로 정렬했다.
  QUERY의 수치 owner7f0566c4와 HWPX intent-box 수정본은 바꾸지 않았다.
- 자연 quiescence를 확인한 뒤 worker helper와 영향을 받는 driver/runner를 함께
  교체했다. 실행 중 worker를 강제 종료하거나 인증 파일을 교체하지 않았다.
- 새 material control의 capacity·instruction·네 preset·정확한 Workflow definition과
  `uploaded-material-item@1.0.0` Pack은 기존 owner로 release했다. 실제 권한을 확인한
  운영자와 기존 source policy를 사용했고, 기존 policy의 허용 범위를 넓히지 않았다.
- 새 coordinator unit은 설치·검증됐으나 **INDEX source 인계 전에는 disabled/inactive**다.
  현재 API에 접수된 요청은 영속 보관되며, 서비스 READY를 자동 처리 완료로 간주하지 않는다.

## 설치물 identity

| 구성 | SHA-256 |
| --- | --- |
| API contracts wheel | `b1db6b1e0e08aadcbcc82d94104aa857e3420f89041f6594c8baf7719f516b32` |
| Application API wheel | `759403fd7e32af8be1fc5a0ab2491d0ad2000fd411b90bf18198bc127efce412` |
| Platform wheel | `9b245c55a57228367d6e1ae93fbbafcbac95e28b8f8710123dccc35a978bebee` |
| Web wheel | `a393a58b6990f4460c2fd9910e62acc93b4e7590fb55ed4c0d1d367a222331aa` |

root-owned release/rollback 자료:

- `/var/lib/eom-material-compatible-release-20261106`
- `/var/lib/eom-material-compatible74-rollback-20261106`
- `/var/lib/eom-material-controls-release-20261106`
- `/var/lib/eom-api/deployments/e1df5c8f9925d977028c66e2b99ad056a1ada583.json`

0074 적용 후에는 head73용 platform으로 되돌리거나 새 자료 history를 drop하지 않는다.
배포 실패 시 사용할 **이미 검사한 compatible74 8b4632d8 전체 set**과 해당 provider/
runner/helper 설정을 별도로 준비했다. 이번 배포는 rollback 없이 성공했다.

## 실제 확인과 남은 확인

1. API readiness PASS. 실제 HTTPS 로그인 화면200·새 자료 API의 anonymous401 PASS.
   이것은 인증된 사용자 화면 acceptance의 대체가 아니다.
2. 실제 HTTPS `/studio/assets/material-learning.js` bytes와 설치 파일 SHA 동일 PASS.
   API/Web installed build metadata도 위 source와 일치한다.
3. 직접 작성한 작은 PDF2쪽을 실제 source/intake owner로 접수하고 같은 명령 재전송에서
   동일 run을 재사용했다. 실제 parser sandbox→Document/page Artifact 준비와 typed
   progress read PASS. 별도 Graph/예제용 fake worker 결과는 사용하지 않았다.
4. 이 검증은 **권한을 확인한 owner application 호출**이며 HTTPS 로그인 canary라고
   부르지 않는다. 첫 실제 DISCOVER child가 기존 global Runner에서03번 slot의 실제
   lease/Job을 얻고 RUNNING인 것을06:02 UTC에 확인했다. 아직 모델 결과·등록·공유
   Graph·공통 INDEX 완료의 증거는 아니다.
5. 이어갈 것: 기존 INDEX의 현재 묶음 자연 완료→source consumer 인계→coordinator
   enable/start→동일 canary의 설명/문항·공개 풀이·공유 Graph/INDEX handoff·RAG 읽기·
   DB 조회 및 동일 요청 재조회. 새로운 acceptance identity로 원래 실패를 우회하지 않는다.

## background 보존 및 인계

API/Web 배포 동안 INDEX PID/invocation·설정·수치 runtime/model은 불변이었다. 새 자료
Graph10을 읽을 후속 INDEX source와 unchanged-scope control은 보호 저장소에 준비했다.
05:57 UTC에 기존 INDEX **main에만 SIGINT**를 보내 지원된 stop Event를 설정했다.
이는 현재 preparation/numerical 작업을 끝까지 수행한 뒤 새 묶음을 잡지 않는 graceful
인계 요청이다. `systemctl stop`의4분 강제 종료를 사용하지 않았고 numerical child를
신호로 중단하지 않았다. 실제 unit/원래 Workflow/CPU standby 상태를 대조한 뒤에만
후속 identity/config를 활성화한다. 같은 요청을 새 identity로 복제하지 않는다.

창작 owner는 같은1053 source scope를 유지해 새 prefix로 재기동했다. 마지막 종료 당시
처리 가능한1013개 완료·원본 보류40개였으며 이 숫자는 현재 다시 조회할 대상이다.
보류를 성공으로 바꾸거나4개 슬롯이 바쁜 것처럼 꾸미지 않는다. 기존10분 observer timer는
enabled/active로 보존했다. 목표 종료 뒤에도 background 서비스를 유지한다.

## 증거 파일

상세 로그는 Git에 포함하지 않는다. 이들은 개발·운영 증거 경로이며 runtime authority가 아니다.

- `/tmp/material-learning-compatible-activate-20261106-1.log`
- `/tmp/material-learning-controls-release-20261106-2.log`
- `/tmp/material-learning-live-canary-submit-20261106-1.log`
- `/tmp/material-learning-live-canary-advance-20261106-1.log`부터`-3.log`
- `/tmp/material-learning-postdeploy-read-20261106-2.log`
- `/tmp/material-learning-release-record-20261106-1.log`

source/격리 검증의 범위는[구현 checkpoint](MATERIAL_LEARNING_IMPLEMENTATION_CHECKPOINT.md)를
참조한다. 자료 임시 디렉터리의 초기0700과 읽기 전용 관측 스크립트의 열 이름 오류는
해당 operator helper에서 바로잡았으며 초기 실패 로그도 보존했다. 모델/원본/운영 history를
오류 처리 편의상 수정하지 않았다.
