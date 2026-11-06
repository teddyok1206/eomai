# Map 출처 Layer 조회와 기존 슬롯 작업 재개

2026-11-06 UTC. API/platform/Catalog 및 Web 호환 배포 완료. 마지막 실행 확인은
10:34 UTC이며, 실제 사용자 Map 육안 검토는 아직 기록되지 않았다.

## 범위

- 같은 published Graph에서 교과서·기출·창작·외부·AI를 읽는다. 선택한 Layer를 현재
  화면의 일부 노드에서만 숨기는 대신 서버에서 seed 제한 전에 조회한다.
- 기존 Map V2 response/Layer enum을 그대로 쓰고 API/BFF OpenAPI에 optional `layer`
  query만 추가한다. 새 Graph·벡터·schema version·DB migration·캐시·worker는 없다.
- 표시와 SQL은 한 불변 분류 rule tuple을 공유한다. 최초 화면은 각 주요 출처를 조금씩
  보여주며 공통 개념은 복제하지 않고 여러 색으로 표시한다. 상세 근거도 선택한 출처로
  제한한다. 같은 snapshot/hash와 실제 권한·정본 문항 열기는 유지한다.
- 기존 INDEX/numerical 환경과 accepted/FAILED 이력·원본은 변경하지 않는다.

## 호환 운영 릴리스

| 담당 | 설치 source / 보존 범위 |
| --- | --- |
| API/platform/Catalog/global Runner | `0373ef482a60203f5ade5db729f1ea5656ca66ab` |
| Web | `593224698fd6bef3823ae20563f3c95a9cf584e5` |
| QUERY numerical owner | `7f0566c44884982d9a9782a28bd6a66c81d35cda`, 기존 실행환경 유지 |
| INDEX | `fedb975085d88978e2b468d51ca0f13ddd598d49`, PID1123320·invocation 유지 |
| 자료 학습 coordinator | `493144f861a13efe05d3119902b3be4476e007c2`, PID1049221·invocation 유지 |
| 창작 producer | `e1df5c8f9925d977028c66e2b99ad056a1ada583`, 원래 1,053개 범위 재개 |

Web 이후 API commit은 생성 OpenAPI의 optional query 반영이다. 서로 다른 source를 같은
commit으로 보고하지 않는다. 기존 DB migration `20261105_0074`·인증·정책·수치 recipe와
namespace는 변경하지 않았다. 기존 창작 producer만 지원된 SIGINT drain으로 workers와
Graph 반영이 자연 완료한 뒤 호환 owner를 바꿨고, 원래 작업을 PID1195806으로 재개했다.
INDEX/GPU·자료 학습 coordinator는 재시작하지 않았다.

- 활성화/보호 대상 해시와 rollback 기록:
  `/var/lib/eom-map-layers-compatible-20261106/activated.json` 및 같은 디렉터리.
- API 정식 배포 기록:
  `/var/lib/eom-api/deployments/0373ef482a60203f5ade5db729f1ea5656ca66ab.json`.
- API ready=`READY`, HTTPS `/studio/login`=200을 배포·정리 뒤 확인했다.
- 기존 HWPX 출제의도 수정과 설치 wheel/RECORD를 보존했다. 문서 commit을 위해 다시
  runtime을 배포하거나 background 작업을 재시작하지 않는다.

개발 중 OpenAPI 생성본 누락은 source-free gate에서 검출해 기존 export로 고쳤다.
staging 상위 디렉터리의 umask 권한도 실제 설치 UID 사전 검사에서 검출해 해당 새
공개 wheel 경로만 수정했다. 두 건 모두 운영 activation 전의 개발/사전 검증 실패이며,
실패 로그를 보존하고 통과해야 할 gate를 생략하지 않았다.

## 슬롯 재개와 현재 실행

기존 보류를 원본 변환 실패·읽기 불가·과거 terminal FAILED로 구분했다. 기존 공식 recovery가
허용하는 네 문항11771·11791·11853·11891을 동일 source/controls로 successor 준비·START했다.
네 추출 Workflow가 모두 COMPLETED/Job SUCCEEDED가 됐고 실제 창작 Graph 누적은
1013→1017로 늘었다. 추출 완료와 후속 풀이·Graph 등록 완료를 같은 수로 보고하지 않는다.

이어 같은 공식 경계로 12건11894·11952·11981·12030·12031·12079·12172·12207·12224·12311·
12323·12339를 준비·START했다. 원래 FAILED는 그대로 두고 기존 전역 동시4/claim/lease를
사용한다. 10:34 UTC 16건 중 추출15건 COMPLETED·1건 RUNNING, 실제03·04·05·06 슬롯이
각각 유효 lease로 RUNNING임을 확인했다. 같은 시점 원래 cohort producer는 PROCESSING이다.

재시작 직후 producer의 `verified_count=0`은 원래 selection을 다시 순회하는 진행값이다.
기존 Graph 등록이 삭제됐다는 뜻이 아니다. 순회 중 누적된 원본 보류19건도 최종 모집단
집계로 취급하지 않는다. 다른 실패 종류를 억지로 같은 recovery로 취급하거나 읽을 수 없는
원본을 가짜 문항으로 등록하지 않았다. 원본 변환·읽기 불가·지원되지 않는 terminal 실패는
명시적으로 남는다. 복구 계획/결과는 `/var/lib/eom-map-layer-slot-recovery-20261106`이다.

INDEX는 같은 PID/실행환경을 유지하며 입력 준비 로그가 계속 진행된다. 10:30 UTC 정기 관측의
기출 공통 임베딩은295/520이며, 모든 문항 계산 완료를 주장하지 않는다. 순간 GPU 사용률0%는
당시 입력 준비/대기 상태다. 디스크 정리로 자원 여유는 회복됐지만 GPU 수치 계산 중이라고
과장하지 않는다. 기존 슬롯/GPU 관측과 10분 Slack 타이머3개는 active이며19:30 한국시간
정기 보고의 실제 SENT/HTTP200을 확인했다.

## 검증

- 집중 API/BFF/분류·SQL·브라우저/문맥/의존 경계54 PASS. 선택 Layer의 source bound
  검사도 포함한다. 실제 Chromium은 기존 설치를 명시적으로 사용했다.
- disposable PostgreSQL material suite44 PASS: 실제 교과서/일반 설명 Graph의 Layer
  조회·고정한 이전 Graph·동일 조회 재전송·근거 조회 및 EXPLAIN을 확인했다. 모델 응답은
  합성 fixture이고 DB/Artifact/Graph owner는 실제다. 작은 fixture의 seq scan을 실패로
  취급하거나 운영 규모 성능의 증거로 확대하지 않는다.
- core6개 mypy 및 formatter/linter PASS. 검증 범위는 겹치므로 합산하지 않는다.
- 별도 frontend/backend alignment·gateway/security·wheel/context87 PASS, 생성 OpenAPI/API
  검사13 PASS. 기존 suite와 범위가 겹치므로 합산하지 않는다.
- API source-free/wheel/RECORD/OpenAPI gate와 Web 설치 시뮬레이션62파일 검사 PASS.
- 배포된 Catalog owner application에서 실제 관리자 권한을 확인하고 고정 Graph
  `graphrev_607ad35289e5121a9daec7fcc9ef627e`의 기본/Layer별 읽기·같은 query 재조회·
  상세 근거 읽기를 확인했다. 가짜 ADMIN/WORKER를 만들거나 worker로 DB를 읽지 않았다.
- 기본 혼합 조회120nodes는3.208초. 교과서·기출·창작·외부별 read/replay/detail는 각각
  92/80/67/609ms였다. 한 회의 실측이며 응답시간 보장이나 node 수=문항 수가 아니다.
- AI 조회도 정상적으로 빈 결과를 반환했다. 해당 pinned Graph의 AI 근거0건을 등록 문항
  삭제나 장애로 확대하지 않는다. DB 문항 존재와 published Graph membership은 다르다.

브라우저 fixture의 실제 Chromium PASS, 설치 owner의 실제 권한 조회 PASS, HTTPS login
200은 각각 다른 증거다. 사용자의 인증된 실제 Map 화면/육안 PASS는 아직 NOT_RECORDED이며,
사용자에게 기존 화면을 새로고침해 출처 선택을 확인해 달라고 요청해 둔 상태다.

## 로컬 디스크 정리

기능 배포 후 사용자가 승인한 범위의 정확한 local disposable 목록만 정리했다.

- 이전 API `source.tar`294개:22,224,138,240bytes. 파일별 identity·SHA·retained wheel의
  source/tree/archive hash·실행 참조를 대조하고 Git archive로 동일 SHA가 복원됨을 확인했다.
  삭제 전후 모든 해당 commit이 retained Git refs에서 reachable임을 확인했다.
- 임시 source/설치 시뮬레이션·staging 복사본·개발 캐시39개: 회수 공간 약353.9MB.
  현재 runtime·rollback·모델·원본·벡터 참조와 겹치는 대상은 제외했다.
- 합계 약22.6GB를 추가 확보했다. background writer가 계속 실행되므로 전체 디스크 차이는
  정확한 파일 합계와 다를 수 있다. 정리 후 local 여유 공간은 약31GiB다.
- 이번 검사 전용 disposable DB `/tmp/eom-api-testdb-20261106022510_8175c34b`만 공식
  `testdb_cleanup.sh --confirm`으로 제거했다. 운영 DB 테스트·데이터 삭제는 하지 않았다.
- 추가 source-copy 정리 계획은 안전 조건을 만족한 대상0개였다. 남은 복사본을 무리하게
  지우지 않았다. runtime/wheel·인증·실패 로그·228GB 규모 모델 저장소·업로드 ZIP·원본
  문항·현재/구형 벡터·백업을 보존했다. EOMIS 변경·NAS 이동은 없다.

삭제한 archive는 retained Git commit의 `git archive --format=tar <commit>`으로 같은
SHA를 복원할 수 있고 캐시/시뮬레이션은 보존된 source/wheel과 지정 환경에서 재생성한다.
실행 중인 프로세스의 argv/cwd/exe/FD를 확인했으며 정리로 인한 서비스 재시작은0회다.

원래 plan/report·복구 검증6개를 기존 Orchestrator `ControlFileSetPublisher`로 정식
Artifact에 보관하고, Catalog의 정확한 revision/member/SHA 읽기로 재확인했다. worker가
NAS에 직접 쓴 것이 아니며 감사 파일은 Git에 넣지 않았다.

- Artifact: `artifact_9592d81fda4849eab8db8a8299633585`
- Revision: `rev_e50f2a30fbd54483a24ce2e81317a34c`
- Primary: `cleanup-report.json`
- Primary SHA: `sha256:1956775d87d14a52176a23454201326c12b868bee7b48daafef38741ff76fb21`
- Manifest SHA: `sha256:be8fbdff3da4bd8f371e6a53185aba1fccf9104c304de11962f5f79792c6e2d1`
- NAS: `/mnt/nas/eom/artifacts/artifact_9592d81fda4849eab8db8a8299633585/rev_e50f2a30fbd54483a24ce2e81317a34c`

## 남은 검증과 운영

Map 실제 사용자 육안 검토만 별도 기록으로 남긴다. source 보류와 전체1,053개 처리·전체
임베딩 완료는 이번 Map/로컬 정리의 완료로 덮어쓰지 않는다. 원래4슬롯·INDEX·자료 학습과
정기 관측은 계속 유지하며, 정리 감사와 배포 checkpoint에서 후속 작업을 시작한다.
