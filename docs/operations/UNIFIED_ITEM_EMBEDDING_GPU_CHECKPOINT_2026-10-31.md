# 공통 풀이 GPU 재임베딩 실행 체크포인트

시각: 2026-10-31 11:19 UTC. Goal ACTIVE. 재임베딩/검색 전환/구 벡터 삭제 완료 보고가 아니다.

설계 및 종료 조건:
[공통 전환 목표](../architecture/UNIFIED_ITEM_EMBEDDING_GPU_MIGRATION_GOAL_2026-10-31.md).

## 완료한 준비

- 기출520 exact revision/manifest hash 목록을 동결했다. target-set hash는
  `sha256:57a227ea705bedb73cc7573b38f1baf995fa3f697f81c323f251cf4e8e228678`.
  root 보호 `/var/lib/eom-unified-embedding-migration-20261031/baseline.json`에 보관한다.
- 공통 입력은 공개 풀이 단계의 실제 내용이다. 기출/AI accepted full solution report와
  창작 registered source report를 같은 `public-solution-text/1.0`/recipe2로 처리한다.
  보고서 원본·문항·Graph를 수정하지 않는다. 결론만 있는 review를 전체 풀이로 위장하지 않는다.
- 동일 과학 내용의 세 분류 CUDA 입력/encoding identity 동등성, 과학 기호 보존,
  source metadata 불간섭, source 권한·report provenance 및 검색 scope 회귀 **126 PASS**.
  관련 core Ruff/format/mypy PASS. 실제 GPU forward나 전체 자료 품질 평가를 한 테스트는 아니다.
- source commit `9319a75ade8c0cde077ae6bf2f11809d57cd0051`을 main/origin에 반영했다.
  공식 API build-only 경로로 세 wheel의 RECORD 검사 PASS. 이 build는 운영 Catalog/API의
  새 source 설치나 authenticated search acceptance를 뜻하지 않는다.
- DB initial search scope가 CPU/GPU current head의 Graph 일치만 기다리던 조건을 수정했다.
  후보 코드는 실제 published GPU head 한 개의 Graph/policy 전체를 고정하며 QUERY owner's
  정확한 수치 공간/인덱스/허용 fallback 검증과 replay pin은 보존한다. 운영 반영은 별도 단계다.

## 실제 INDEX selection 전환

기존 config6의 지원 범위 안에서 다음 두 필드만 바꿨다.

- `legacy_configuration: null`: 구형6 namespace의 추가 maintenance를 중지.
- public `maximum_targets: 4 → 16`: discovery 대상 묶음을 확대. 실제 forward minibatch,
  memory/VRAM/timeout, model/space/native runtime, source grant는 변경하지 않았다.

기존 INDEX에 SIGTERM을 보내 정상 종료를 기다렸다. 강제 종료하지 않았다. 종료 후 실제
구형 RUNNING/REGISTERING Workflow가0인지 확인한 뒤 before/after SHA CAS로 선택했다.
기존 미시작 standby REQUESTED 이력은 보존하며 U05에서 별도로 검토한다.

- INDEX `225508 → 703354`, 실제 `LOCAL_INDEXING_SERVICE_STARTED` 09:20:17 UTC.
- API469955, QUERY470146, Catalog3760261 PID 보존. 세 서비스 재시작0.
- owner selection SHA `4992e058603ac75513034cdc97b7d6998b00071e36ce99547527d13d45ab06ff`.
- runtime selection SHA `e48b9b9f3c5eacb0ab2fe54dcbf476f7a2836f46ccd1dfd562779097fab006c5` 불변.
- 실제 decoder/source는 계속c68156dd이다. source wheel/model 환경 교체·DB migration·새권한0.
- 원래 CPU public standby의 명령은 09:34:27에 SUCCEEDED를 관측했다. 이를 새 CUDA 계산
  또는 whole Workflow completion receipt로 확대하지 않는다. 후속 GPU source 준비를 진행한다.

전환 계획/원래 config/새 config/실제 PID 증거는
`/var/lib/eom-unified-embedding-migration-20261031/public-priority-*.json`과
`before-owner.json`, `after-owner.json`이다. rollback은 해당 원래 owner selection을
검증·복구하고 INDEX만 정상 경계에서 재시작한다. 현재 수치 작업을 강제 중지하지 않는다.

## 30분 진행률 관측

기존 PID-only `eom-embedding-followup-observe.timer`를 중지하고 이번 목표의
`eom-unified-embedding-observe.timer`로 교체했다. 00/30분마다 다음을 읽는다.

- 고정520 대상과 target-set hash 검증.
- 공통 projection/partition/정확한 CUDA space의 registered binding에 연결된 distinct Item 수.
- non-terminal public Workflow의 CPU/CUDA 구분.
- historical FAILED를 현재 장애와 섞지 않는 별도 집계.

actual first/timer 관측 RC0. **09:30 UTC: GPU 기출16/520, 잔여504**.
같은 snapshot의 public CUDA 전체 encoding28에는 기출 외 등록 문항12도 있으므로
28/520이라고 표시하지 않는다. CPU 결과도 GPU 진행률에 더하지 않는다.
이 metadata count는 최종 source/hash/Artifact/정식 completion/search 검증의 대체가 아니다.

관측은 root 보호 helper가 실제 기존 Catalog runtime credential을 메모리로만 넘겨
제한된 READ ONLY/15초 SQL로 metadata만 읽는다. NAS/worker home/Codex auth/API secret
접근은 막았다. source content/model 추론/DB write/추가 user authentication0.
이 timer는 임시 운영 관측이며 제품 검색 엔진이나 새 worker queue가 아니다.

## 남은 일

1. 실제 새 CUDA numerical result/등록 receipt 및 증가 확인; 실패는 기존 공식 복구로 처리.
2. 520의 공통 입력·새 GPU vector·정식 index 검증과 source별 결측/overflow 정리.
3. Registry의 AI 적격 범위·full-report/Graph 연결 확인. 현재 Graph AI0을 전체 Registry AI0으로
   해석하지 않는다. 새 AI도 동일 full-report 입력을 확보해야 embedding-ready가 된다.
4. Catalog 검색 scope 수정의 호환 운영 반영과 실제 query/read/replay/GUI 검증.
5. 출제·검토·변형·모의고사·chat/experiment의 구 인덱스 참조 및 active consumer inventory.
6. 새 데이터·검색 전환 뒤 구형 파생 벡터/인덱스의 지원 종료·안전 삭제 및 삭제 영수증.

삭제는 **space hash 하나**만으로 선택하지 않는다. 새 public와 구 accepted/mixed는 같은
BGE-M3 CUDA space hash를 가질 수 있다. 반드시 projection/partition/exact encoding·index
identity와 shared-shard 참조를 함께 확인한다. 기존 Graph를 지우는 prelaunch cleanup을
이번 작업에 호출하면 안 된다. source Graph·교과서·기출·창작·AI 정본과 풀이보고서는 보호한다.

## 실제 CUDA 완료와 Catalog 반영 — 10:01 UTC

- 공통 형식의 새 CUDA Workflow `workflow_4ec1cbd475c64c4f8b0926772ebd9a05`가
  09:55:42 UTC에 COMPLETED, Runner 명령도 SUCCEEDED다. CPU fallback 결과가 아니다.
- CUDA public index `embeddingindexrev_6c28aad3c46575f29cb3463d60b2fdc4`의
  binding44/eligible803을 확인했다. **10:00 UTC 원래 기출 목표 진행률은27/520, 잔여493**.
  등록 문항을 포함한44를 기출 진행률로 세지 않는다. 이후 기존 CPU standby가 실행 중이다.
- Catalog만 private source `9319a75ade8c0cde077ae6bf2f11809d57cd0051`로 선택했다.
  실제 Catalog UID composition, API peer의 Unix socket protocol smoke, API READY 확인.
  Catalog PID732310, NRestarts0 확인. API469955/INDEX703354/QUERY470146 PID는 보존했다.
  authenticated search/GUI acceptance는 아직 실행하지 않았다.
- 첫 Catalog activation은 기존 drop-in의 public-reader config hash가 실제 파일과 달라
  기동 실패했다. source만 원복해도 같은 stale pin 때문에 실패가 지속됐다.
  hash 검사를 우회하지 않고 검증된 실제 public config hash
  `ecb34eae39fe05c3b5bd00331e4104ba27d7b811b19cd6160a17c4a96c8680ce`로
  선택값을 정합화해 복구했다. 설정 파일 bytes와 API/INDEX/QUERY는 변경하지 않았다.
  최초 preflight는 파일의 실제 hash를 계산해 넘겨서 service expected pin의 drift를
  놓쳤다. 후속 preflight는 검토된 expected pin과 실제 파일을 대조하고, rollout 전
  effective unit pin과도 일치해야 한다. API READY만으로 Catalog 기동을 판정하지 않는다.
- rollback은 구 source c68156dd와 **정합화된** public-reader pin의 조합이다.
  stale pin을 포함한 원본을 무조건 복구하는 방식은 쓰지 않는다.
  root evidence: `catalog-v2-before-dropin.conf`, `catalog-v2-after-dropin.conf`,
  `catalog-v2-compatible-rollback.conf`, `catalog-activation.json`.
- Registry의 source_kind 미기록 문항은 APPROVED1/IN_REVIEW1이며 두 문항 모두 accepted
  analysis0/Graph source pointer0이다. 현재803 Graph 대상의 보고서 결측0과 이 두 문항의
  준비 상태를 혼동하지 않는다. synthetic AI 공통 입력 회귀 PASS를 실제 AI 등록 완료로
  확대하지 않는다. 기존 공식 분석→Graph→전체 풀이보고서 경계의 연결을 추가 확인한다.
- 구 accepted/mixed index head12개와 public head2개를 확인했다. 구 head도 Graph가 서로
  다르며 historical Artifact/Workflow JSON pins는 FK 목록만으로 발견되지 않는다.
  삭제 전 exact consumer/pin inventory가 필요하다. 새 public와 같은 space라는 이유로
  구형 partition이나 Graph 전체를 삭제하지 않는다.
- 10:04 UTC metadata inventory: 구 partition은 CPU/CUDA 각각1,563 encoding,
  shard revisions 각각356/186이다. 520×3 외 나머지3개씩은 비대상/공유 여부를 별도
  확인해야 한다. 새 public는 CUDA44/CPU24이며 cross-partition shared shard0이다.
  Workflow initial request와 Artifact result의 nested `index_revision_id` 검사에서는
  참조0이지만, manifest/member bytes·다른 키의 포인터·설정·active consumer 코드까지
  모두 확인한 결과는 아니다. 이 검사만으로 삭제 승인 조건을 충족했다고 판정하지 않는다.

**구 벡터 삭제0. 운영 검색 전환 acceptance 및 goal 완료는 아직 미확정이다.**

## 저장 bytes 및 원보고서 역대조 — 10:12 UTC

root 보호 `index-integrity-20261031T*.json`에 별도 결과를 보관했다. 기존 Catalog의
pinned Artifact reader/공식 report resolver/JSON Schema·Pydantic·vector binary validator로
현재 CUDA index를 검증했다. 별도 검색 엔진·모델 추론·DB write는 없다.

- index `embeddingindexrev_6c28aad3c46575f29cb3463d60b2fdc4`, hash
  `sha256:6ac13c48c7587693fd769c05ff48653c7b0a3efc133c3d81c0a44f5919bafb44`.
- index44 binding과 DB encoding/binding의 해시·space·partition·row/shard 포인터 일치.
- shard5개/실제 float32 binary44행의 SHA, 크기·shape, finite/L2 unit norm PASS.
- 원 accepted 기출/registered 창작 보고서44개를 공식 resolver로 읽어 재투영했다.
  실제 profile hash, encoder input text hash와 encoding identity가 모두 기존 저장값과 일치했다.
  원래 기출 목표의 검증 범위는27/520이다. 520개 모두의 재임베딩 검증 PASS가 아니다.
- 별도로 frozen520 Item revision의 ID/manifest hash/승인 상태 불변을 전수 확인했다.
- 이 검사는 관리자 무결성 감사다. actual user 권한의 검색/GUI acceptance를 대체하지 않는다.
  creative 공식 read는 SELECT FOR SHARE를 유지하므로 PostgreSQL READ ONLY root가 아닌
  SELECT-only 실행 guard가 있는 일반 read root를 썼다. runtime 잠금/권한 검사를 제거하지 않았다.
  검증 준비의 첫 실패(미prefetch 보고서 포인터, 이어 READ ONLY/공유 잠금 불일치)도 보존했다.
  운영 source/state-machine의 실패나 모델 재실행이 아니며 해당 검증 helper만 수정했다.

## AI 실제 producer 결측 — 10:16 UTC

AI encoder 동등성은 mocked admitted report를 전제한 값 테스트였다. 실제 V10 보고서
요청은 기출 V9 source 전용이며 승인 AI source를 받을 수 없다. 기존 V10을 강제로 열거나
review 요약을 대입하지 않는다. 이 차이를 명시한 schema/Pydantic 거부 회귀와
AI report missing 시 fallback 금지 회귀를 보강했다. 후속 범위/보존 규칙은 설계 문서의
‘U02 추가 발견’에 기록했다. AI source producer/Graph/public evidence 연결은 아직 남은 일이다.
**현재 기출 GPU INDEX는 이 개발과 독립적으로 계속 실행 중이며 전체 goal은 ACTIVE다.**

### AI successor의 protocol-first 후보 — 10:23 UTC

일반 승인 Item의 accepted V2 base를 가리키는 request11/receipt10/result11 및 base types2,
role input/result11(`workflow-role/1.35.0`), resolved plan29를 별도 후보로 정의했다.
기존 공개 report1/worker proposal8은 그대로 재사용하며 기존 기출 schema bytes를 바꾸지 않는다.
새 base에는 기출 occurrence/page observation을 조작해 넣지 않는다.

- 재현 generator: `scripts/contracts/generate_registered_item_solution_analysis_v11_schema.py`.
- canonical/package schema copies 및 `--check`, JSON Schema 2020-12 검증 PASS.
- 새 후보의 source/base pins/closed outputs/worker protocol/plan source와 기존 경계 회귀
  **60 PASS**, generator strict mypy 및 관련 Ruff/format PASS.
- **Pydantic/application/worker/resolver/evidence successor/DB uniqueness/운영 연결은 아직 미구현**이다.
  이 후보를 source 지원 활성화나 AI end-to-end PASS라고 보고하지 않는다.
  현재 running INDEX/QUERY/private wheels/config/DB schema는 이 후보 때문에 바뀌지 않았다.

### Typed worker/산출물 경계 구현 — 10:42 UTC

- 기존 Catalog schema registry에 후보4개를 hash pin으로 등록하고, 별도
  `registered_item_solution_analysis.py`에 immutable V2 base/request11/receipt10/result11
  Pydantic 모델을 구현했다. schema-first raw 검증으로 extras·coercion·forged nested models를 거부한다.
- 실제 Workflow request/role input/result/Codex constrained schema에1.35를 연결했다.
  보고서의 base identity·node/anchor allowlist는 기출과 같은 report1 검증 로직을 사용한다.
  일반 AI를 기출 page/occurrence로 바꾸지 않고 `image_mode=skip`인 기존 일반 Item 분석 경계를 따른다.
- Orchestrator stage는 새 report와 receipt 두 파일만 로컬에 만든다. 기존 base 파일을 복사하거나
  NAS에 worker가 직접 쓰지 않는다. 원 base 밖의 anchor는 파일 생성 전에 거부한다.
- 기존 V9/V10와 신규 경계의 descriptor/content-set hash 함수 및 report-reference Protocol을
  공유하도록 정리했다. 결과 self-hash와 Artifact member bytes hash는 서로 다른 pin이며
  같다고 가정하지 않는다. 과거 V10의 이 차이도 회귀로 보존했다.
- 설치된9319 private wheel과 source 후보에서 과거 V10의 input/result/Codex schema canonical
  hash3개가 각각 동일함을 독립 interpreter로 확인했다. 기존 schema bytes/의미를 바꾸지 않았다.
- 해당 신·구 경계, 기존 문서/Artifact/source/risk/batch와 공통 projection 회귀 **160 PASS**.
  core6개 모듈 mypy PASS, 관련 Ruff/format 및 generator `--check` PASS.
- **application create/reconcile/accept, resolver/materializer, 신규 evidence의 공통 index 연결,
  accepted successor uniqueness의 disposable DB 검증과 실제 운영 검증은 아직 남아 있다.**
  타입 및 stage PASS를 실제 AI 보고서 생성·등록 완료로 표시하지 않는다.
- 10:30 timer의 frozen 기출 GPU 등록은 **37/520, 잔여483**, 실제 non-terminal CUDA Workflow1이었다.
  INDEX PID703354/NRestarts0, QUERY470146/Catalog732310은 이 구현 때문에 재시작하지 않았다.
  다음 주기 관측은11:00 UTC다. 이번 구현은 source 후보이며 운영 배포·DB migration·모델 실행0이다.

### 일반 Item 보고서 application·실행 준비 경계 — 11:19 UTC

- Plan29의 typed resolver/replay/materializer를 연결했다. 승인 Item JSON과 accepted V2의
  원래7개 members/receipt/result를 exact allowlist·schema/media·byte count·hash로 준비한다.
  기출에만 있는 occurrence/page-images 파일을 만들거나 요구하지 않는다. 기존 V8/V9 계획은
  source 의미와 validation을 유지한다. 새 replay는 request/base/Workflow/definition/preset pins를
  모두 대조하며 다른 current revision으로 바꾸지 않는다.
- Catalog의 기존 `create_solution → reconcile → risk → accept`에 V11을 추가했다.
  원자적 Workflow/plan/run/event/command 생성과 기존 지원 재전송을 재사용한다. 일반 Item은
  definition11/role1.35가 실제로 지원되는 preset에서만 요청할 수 있다. 다른 key/가족으로
  우회하거나 기존 FAILED를 성공으로 바꾸지 않는다. 새 accepted Artifact는 `catalog/1.27`,
  result11/receipt10이며 기존 기출 V10/receipt9 protocol identity는 그대로다.
- base 해석은 별도 책임 모듈 `registered_item_solution_base.py`다. 기존 canonical Item reader와
  Artifact byte reader를 사용하고, accepted-result cache와 실제 JSON 및 원 receipt/member를
  대조한다. source JSON pointer/excerpt hash와 problem/answer 역할, typed node prefix를 확인한다.
  anchor 이름으로 역할을 추측하지 않으며 빈/null 필드를 실제 근거로 취급하지 않는다.
  self-hash와 raw member SHA를 혼동하지 않는 real-file 회귀를 포함한다.
- candidate migration `20261031_0065`는 V11 accepted successor의 별도 partial unique B-tree만
  추가한다. 기존 V10 index/데이터는 바꾸지 않는다. V11 이력이 있으면 downgrade가 보장을
  지우지 못하게 거부한다. **source migration head와 live migration head는 아직 다르다.**
- 임시 DB `eom-api-testdb-20261031111016_5f2728e8`에서 upgrade/downgrade/upgrade PASS,
  실제 B-tree·동시 승인 winner1·중단 rollback/replay·FAILED 보존·이력 있는 downgrade 거부
  **4 PASS**. 모델·운영 DB·worker·NAS 실행이 아닌 synthetic relational constraint 검증이다.
  재현: 기존 `scripts/api/testdb_run.sh registered-solution-tests <guarded-state>`.
  검사 후 marker 검증 cleanup으로 해당 임시 DB·제한 계정을 제거했다. cleanup PASS.
- source 집중 회귀 **245 PASS**, package resources/의존 방향 **16 PASS**, core8개 모듈 mypy,
  Ruff/format, schema generator `--check`, shell syntax/diff 검사 PASS.
- **아직 source 후보**다. AI base 생성 지침/preset·실제 정의 activation, 새 accepted report의
  Graph/public evidence/index 연결과 사용자 권한 실제 검색은 후속이며 end-to-end PASS가 아니다.
  API/Catalog/INDEX/QUERY 설치본, runtime config, 운영 DB schema, 모델 실행은 변경0이다.
- 실제11:00 관측은 기출 GPU **37/520, 잔여483**, CUDA RUNNING1, 새 historical failure 증가0이다.
  30분 관측 간격을 유지한다. 새 벡터 전환 검증 전 구 벡터 삭제0, 보호 정본 변경0이다.

### Source candidate의 설치 wheel 검증 — 11:24 UTC

- application/실행 경계 후보는 `df7a168c`로 main/origin에 보존했다.
- 최초 build-only는 wheel RECORD 확인 후 설치 시뮬레이션에서, 이전0064를 고정한 기대값과
  새 source head0065가 달라 중단됐다. 운영 migration/설치/서비스 재시작은 실행하지 않았다.
  기존 배포 검사를 우회하지 않고 기대값을 정합화하고, 앞으로 비싼 빌드 전에 이 drift를
  잡는 `test_api_installed_migration_admission.py` 회귀1개를 추가했다.
- 보정 source `60aa2d9b0fcb90db9942194bb9e23ccc04ed64c8`의 공식 `--build-only` 재실행 PASS.
  세 wheel RECORD 및 non-editable installed simulation 검증을 마쳤다. 산출물은
  `/tmp/eom-api-build/60aa2d9b0fcb90db9942194bb9e23ccc04ed64c8.e308um/dist`의 후보이며
  아직 운영 설치나 새 AI source end-to-end acceptance가 아니다.
- 운영0065 적용에는 reviewed migration operator successor 및 API/Catalog/INDEX/QUERY의
  호환 runtime 선택이 필요하다. 실행 중인 GPU 작업의 pinned 설치본을 덮어쓰지 않는다.
  새로운 입력 source/control/public evidence/index 연결은 여전히 후속 단계다.

### 일반 Item의 실제 실행 입력·등록 회귀 — 12:02 UTC

- control21/definition11은 기존 모델 `gpt-5.6-terra`/`xhigh`, support pool과 원래10개
  protocol을 유지하고 role1.35만 추가한다. 기존 binding identity·관리자 상태와 이후 capacity
  정책을 덮어쓰지 않는다. bootstrap raw JSON Schema 검증과 재전송을 확인했다.
- disposable DB에서 정본 Item3 → 원래 V2 분석 → V11 전체 풀이 요청 → 실제 실행 입력
  materialization → Orchestrator 산출물 staging/commit → Catalog reconcile/accept → 같은 요청
  재전송을 검증했다. **worker 출력은 synthetic이며 모델 실행·교육 품질 승인이 아니다.**
  기존 post-registration approval5건을 함께 실행해 총 **6 PASS**다.
- 이 통합검사로 canonical Item schema alias를 좁은 Origin pointer로 재포장하던 실제 결함을
  발견했다. 기존 Knowledge source pointer를 그대로 전달해 해결했다. frozen Origin schema를
  넓히지 않았고 media/schema/hash/권한 검사는 보존했다. schema 없는 입력은 계속 거부한다.
- source 집중 회귀101건과 package/의존 경계27건 PASS, core4개 모듈 mypy 및 관련9개 파일
  Ruff/format, shell syntax/diff PASS. 독립 interpreter에서 기존10개 protocol의 schema bundle
  hash가 운영9319 설치본과 각각 같음을 확인했다.
- 임시 DB `eom-api-testdb-20261031114946_efebe863`는0065 migration 왕복 PASS 후 검증했으며,
  marker 검증 cleanup으로 DB와 제한 계정을 제거했다. 운영 DB·서비스·모델 실행 변경0이다.
- 12:00 UTC timer의 original 기출 GPU 등록은 **59/520, 잔여461**이다. 기존 historical 실패2건은
  그대로이며 증가하지 않았다. 관측 당시 CPU standby Workflow1이 실행 중이라는 사실을
  GPU59건과 구분한다. GPU 전체 완료나 실제 사용자 검색 PASS로 확대하지 않는다.
- AI evidence/index successor와 실제 Graph·권한 검색 연결, full520 token 길이 사전 점검,
  운영0065 호환 릴리스와 구 벡터 retirement는 아직 남아 있다. goal은 ACTIVE다.

### 전체 기출 입력 길이·새 control 설치본 검증 — 12:02 UTC

- control/materialization 후보 `195e11c8329b6bf901bb6687285ddcc52bc5f2ca`를 main/origin에
  보존했다. 공식 `deploy_release.sh --build-only` PASS: wheel RECORD와 격리 설치본의
  definition11/role1.35 입출력 schema/정의 admission까지 확인했다. 후보 산출물은
  `/tmp/eom-api-build/195e11c8329b6bf901bb6687285ddcc52bc5f2ca.fZ1VuB/dist`다.
  운영 설치·migration·bootstrap activation은 아직 실행하지 않았다.
- frozen Graph의 원래520개 Item revision을 공식 accepted V10 report resolver로 읽어 공통
  public text1로 projection하고, 실제 선택된 BGE-M3의 보호된 동일 tokenizer로 전체 token
  길이를 검사했다. 모델 weight 추론이나 CUDA를 사용하지 않은 일회성 관리자 read audit다.
  정본 Item manifest520개도 frozen pins와 대조했다. 전체520개 AVAILABLE, token 최대621,
  현재 모델 한도2048 초과0이다. truncation/chunking/요약 교체 없이 현재 동일 space로 계속
  재임베딩할 수 있다. 이는 실제 사용자 권한 검색 또는 vector 전체 완료 증거는 아니다.
- 보고서는 보호된 운영 감사 폴더의 `solution-token-budget-20261031T120201.json`이며,
  token manifest SHA는 `sha256:dcf2d6e3bdcf9ff5c4395a9fb13e06990809c461def09dcfa1f745eacb96e5bd`다.
  보고서/worker 원문은 로그·Git·Slack에 저장하지 않았다. DB writes/model inference/CUDA0이다.
- INDEX703354/QUERY470146/Catalog732310/API469955 PID와 NRestarts0을 유지했다.
  새 vector59/520의 처리와 기존 서비스는 이 source qualification 때문에 재시작하지 않았다.

### AI accepted report의 공통 수치 입력 qualification — 12:10 UTC

- closed entry2는 실제 registered accepted V11/receipt10/report1의 provenance를 보존한다.
  기존 entry1·기출/창작 evidence와 public text1/recipe2 bytes는 그대로다. 새 schema의 canonical/
  package 사본,2020-12 검증과 재현 generator `--check`를 연결했다. source class를 기출로
  위장하거나 기존 검토 결론을 full solution으로 사용하지 않는다.
- 공통 encoder는 entry1/entry2를 명시적으로 구분한 뒤 같은 text/space/partition으로 같은
  input과 encoding identity를 만든다. CPU/CUDA 및 QUERY/DOCUMENT 각각에서 기출·창작·AI
  세 종류의 동일 텍스트 입력이 정확히 같고 provenance hash는 서로 다름을 검사했다.
  semantic result hash와 accepted JSON raw SHA는 별도 핀이다. 검사는 합성 입력이며 실제
  모델 inference의 수치 비교 또는 운영 source admission 증거가 아니다.
- 기존 solution evidence resolver의 indexed bulk query와 accepted-chain 검증을 공유해 V11
  report의 공식 read를 추가했다. V10 함수·envelope와 과거 metadata hash encoding은 보존한다.
  새 read는 실제 accepted JSON/receipt bytes와 report를 읽고 schema/media/hash를 검증한다.
  request/run/source identities 불일치도 명시적으로 거부한다. missing은 명시적 empty이며
  review/latest로 fallback하지 않는다. 실제 operator/Graph/source 권한은 기존 capture owner의
  책임이며 이 resolver 자체가 권한을 부여하지 않는다.
- marker-guarded 임시 DB `eom-api-testdb-20261031120739_947028e5`의 실제 application·staging·
  acceptance·재전송·V11 report read와 기존 승인 회귀 **6 PASS**. accepted JSON/receipt/report
  각각의 변조도 거부했다. worker 결과는 synthetic이며 live 모델 실행이 아니다. 확인 후
  DB/제한 계정을 marker 검증 cleanup으로 제거했다.
- 공통 입출력·과거 evidence·capture·native 및 package/의존 경계 그룹118 PASS, assembly/
  similarity/신규 entry 집중 그룹67 PASS(서로 겹치는 검사는 합산하지 않음). core6개 mypy,
  관련 Ruff/format 및 generator 검사 PASS다.
- **entry2의 global INDEX admission은 아직 닫혀 있다.** frozen carrier/registry/index/QUERY
  successor의 qualification 전에는 현재 GPU runtime에 새 shape를 넣지 않는다. 해당 DB
  CHECK/carrier 의존은 goal 설계 문서에 기록했다. 새 source 후보를 AI 운영 end-to-end PASS로
  표시하지 않으며, 현재520 재임베딩과 보호 정본·구 벡터는 이 구현 때문에 변경하지 않았다.

### AI evidence 설치 후보·index4 값 계약 — 12:15 UTC

- 공통 수치 입력/V11 read 후보 `50107f257d8df5506ffc6fd3462e862029d998e0`를 push했고
  공식 build-only PASS다. wheel RECORD/격리 설치 검증 산출물은
  `/tmp/eom-api-build/50107f257d8df5506ffc6fd3462e862029d998e0.QogYYn/dist`다.
  실제 운영 설치·migration·모델/사용자 검색은 실행하지 않았다.
- index4/profile2/binding4의 별도 closed schema와 immutable value model을 추가했다.
  index4는 원래 binding3를 byte/hash 그대로 포함하고 AI용 binding4만 추가할 수 있다.
  기존 encoding identity·vector row·shard·recipe·space를 바꾸지 않으며 previous manifest는
  실제 index3/index4만 허용한다. 기존 index3 parser/bytes는 그대로다.
- binding3/4의 공통 identity/hash 규칙은 하나의 함수로 유지한다. 새 index의 binding union은
  schema_version discriminator로 분기한다. 단순 union의 첫 frozen validator가 다른 가족을
  검증하다 중단하는 문제를 개발 회귀에서 발견해, 검사를 느슨하게 하지 않고 명시적 dispatch로
  해결했다. generator local ref fragment 오류도 운영 반영 전 회귀에서 수정했다.
- 합성 기출·창작 binding3 두 개와 AI binding4 한 개가 동일 numeric row 한 개를 참조하는
  positive 사례, 원 binding3 bytes 보존, schema/profile/base/hash/중복/source/space/partition/
  predecessor 부정 사례와 기존 registry/package/의존 경계 **88 PASS**다. core3개 mypy,
  Ruff/format, canonical/package 및 generator `--check` PASS다.
- 이 단계는 **metadata 값 계약 후보**다. global INDEX dispatch·source capture·native carrier·
  registry publication·QUERY successor와 DB CHECK migration을 아직 활성화하지 않았다.
  현재 실행 중인520 GPU INDEX/QUERY의 private 설치본은 건드리지 않았다. full520 완료·
  실제 검색 전환 전 구 벡터 삭제0이라는 조건은 유지한다.
