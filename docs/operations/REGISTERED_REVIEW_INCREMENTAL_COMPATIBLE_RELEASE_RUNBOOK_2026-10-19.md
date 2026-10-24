# Registered REVIEW 증분 연결 — 호환 배포 실행 전 runbook

2026-10-19 UTC. **실행 전 입력·순서이며 아직 배포/활성화/실제 source 증거가 아니다.**
최종 clean source/tree/build/설정/receipt SHA는 root가 freeze 후 채운다. 이 문서 작성에서
운영·DB·HTTP·로그인·모델 실행은 없었다. CPU와 기존520/PAST 범위·role prompt를 유지한다.
설계: [통합 경계](../architecture/REGISTERED_REVIEW_INCREMENTAL_INTEGRATION_DESIGN.md),
[근거 의미](../architecture/REGISTERED_ITEM_REVIEW_SOLUTION_EVIDENCE_DESIGN.md).

## 1. 실행 전에 고정할 입력과 보존할 predecessor

| 선택 | 필요한 실제 입력 |
| --- | --- |
| shared API/Catalog/Chat | 최종 source40/tree40, source.tar rawSHA, build-only3wheel rawSHA, source/contract gate |
| operator0058 | 새 protected libexec, launcher/helper/schema1.7 rawSHA, 기존 admitted operator prefix/treeSHA, 새 context/admission SHA |
| INDEX19 | 새 불변 service revision(18의 정확한 predecessor), final owner SDK, runtime.json SHA, owner4+legacy selection SHA, 새1.1/1.2 data grant 및 각각 native policy member/hash |
| QUERY | final owner SDK, primary1/private1 유지값과 derived hashes, optional configuration2, 실제 설치 후 API wheel/12 provider-code/config pins |
| Catalog read | primary1/C5 기존 파일 보존, optional mixed reader2 및 `EOM_MIXED_SIMILARITY_READ_CONFIG_SHA256` |
| CPU | 기존 prefix/config/receipt/space/bundle/resources/verifier 보존; 새 publication/probe/seal 불필요 |
| 복구 | 원 파일의 rawSHA/epoch/before bytes, 실제 기존3wheels/owner SDK, DB0057 복구 근거, DB0058-compatible forward-recovery 선택 |

현재 기록된 predecessor는 shared `881584aa`, QUERY SDK `052223d3`, INDEX/benchmark SDK
`ee97239d`, logical INDEX18이다. 이는 새로 관측한 service 상태가 아니다. 기존 actual shared
delivery `/tmp/eom-api-build/881584aa8533507e00e0ec4a231284658858e549.ZxQTar/dist`
의 아래 rawSHA는 이번 비특권 파일 읽기로 다시 일치 확인했다. `.TatfQx`는 build-only이다.

- platform `3ee953a1aeaf57727dec1ec47689e47031cde2075f74ef3c33aabc44cfb6ecac`
- contracts `af3668c82be0a37530e1fdac05ae0802c9633b3c8fb62057c28fb74d8368b299`
- API `e8fb6aa8114cad1505f0ec5843f954f66f59d3ed32f3866a1ad429c6bae3b52e`

보존된052 owner platform rawSHA는 `5c19892569a236aa1feda003aeec26fd668ba9a55c2c1415ff9bae8dd381b801`,
EE owner는 `9e93b076cf4026ca426632e0f031b6849e542293df66932c2c522154144dc1de`이다.
이 파일 확보는 DB0058에서 구버전 전체가 READY라는 증거가 아니다.

## 2. 실제 candidate를 찾는 공식 읽기 경계

기존 API의 제한된 pointer-only 읽기를 사용한다. 비밀번호/token/source text를 증거에 남기지 않는다.

1. `GET /api/v1/knowledge-analyses?state=ACCEPTED&limit=200`와 반환된 exact cursor:
   `source_kind=APPROVED_ITEM_REVISION`, source revision/Artifact, accepted Artifact/revision/SHA를 확인한다.
   이 route는 실제 fresh ADMIN+`KNOWLEDGE_ANALYSIS_READ`를 요구한다.
2. `GET /api/v1/items?state=ACTIVE&limit=200`, `/items/{id}`,
   `/item-revisions/{revision}`와 `/item-revisions/{revision}/components`로 current APPROVED와
   originating Workflow, 등록 manifest, AUTHORING/REVIEW11|12 exact pair를 대조한다.
3. `/api/v1/item-bank/production-candidates?source_class=APPROVED_ITEM&eligible=true`는
   이미 current Graph에 출판된 후보다. 아직 미출판된 ordinary 후보를 찾는 유일한 목록이 아니다.

구현은 `eom_api.services.query_adapter.QueryAdapter`의 공개 `list_items`, `revision`, `components`,
`list_knowledge_analyses`이다. 별도 승인된 root metadata-only adapter가 이 읽기 ports를 기존
protected owner engine의 read-only root에서 호출할 수는 있다. 그 관측은 로그인/actor 권한·V2·
trusted receipt의 PASS가 아니다. 제한 page의0은 PARTIAL/UNKNOWN이며 전체 모집단0으로 쓰지 않는다.
`KnowledgeAnalysisRunView`는 request schema를 노출하지 않으므로 ACCEPTED 목록만으로 V2를 확정하지 않는다.

최종 자격은 기존 `KnowledgeGraphPublicationService.resolve_accepted_analyses`와
`resolve_registered_item_review_solutions`가 실제 accepted V2·source·등록·role·receipt를 해석하여 닫는다.
그 결과가 없으면 **명시적 prerequisite/UNKNOWN**이다. 구버전@10을 재분류하거나 V2/Graph를 만들지 않는다.
V2가 정말 없다면 기존 첫 분석 use case는 별도 승인할 선행조건이지 INDEX가 대신 실행할 일이 아니다.

## 3. source build → operator1.7 stage/ADMIT

기존 공식 build를 clean final HEAD에서 개발 UID로 실행한다. 아래 변수는 freeze manifest 입력이며
값을 추측하거나 build-only wheel을 installed provider로 사용하지 않는다.

```sh
/usr/bin/bash scripts/api/deploy_release.sh --build-only
```

기존 `/tmp/eom-onepass-release.LX3CNCB7`의 `stage-reviewed-current-release.py`, `stage_once.py`,
`admit_contexts_once.py`를 **새 evidence namespace에만** 재사용한다. 원본/소비된 결과는 불변이다.
새 stage spec은 context1.7/`20261019_0058`이며 source/archive/3wheels/tree를 exact pin한다.
1.6 stage나 현재 root helper를1.7로 조용히 해석하지 않는다.

root가 새 전용 libexec(예: `/usr/local/libexec/eom-release-operator-registered-review-0058`, 미생성)에
검토한 `scripts/api/release_operator_runtime.sh`, `.py`, 필요한 기존 schema와1.7 mirror를
exclusive/보호 권한으로 게시한다. 기존 libexec를 덮지 않는다. 새1.7 canonical/mirror rawSHA:
`6cbf0efad7da8d81da7e3e9cc5453e67611a0188d246ec0a8b8c2d42b3207250`.
기존 public `load_context`가 schema/hash를 검증한다. parent가 고정한 actual context 경로를 사용한다.

```sh
# root만, 새 admission 1회. 다음 EXECUTE도 동일한 원본 pins를 사용한다.
/usr/bin/sudo -n /usr/bin/bash "${release_operator_root}/release_operator_runtime.sh" \
  ADMIT "${release_operator_prefix}" "${release_operator_runtime_sha}" \
  "${release_context_path}" "${release_context_sha}" \
  "${release_launcher_sha}" "${release_helper_sha}" ADMIT "${release_source}"
```

## 4. 중단 전 준비 → 실제0058 migration → shared install

1. existing composition/preflight로 실제 predecessor 파일/SDK/CPU/CLI/policy/DB owner·OID,
   root plan과 복구 입력을 닫는다. C5 mode가 이미 ENABLED이므로 기존 C5 JSON/hash drop-in도
   설치 전에 유지·검증한다. final owner/config/grant/QUERY read2 경로 준비 전에는 drain하지 않는다.
2. 기존 normal owner drain을 새 관측 PID/invocation에 한 번만 main-only SIGTERM한다.
   현재 INDEX command의 정상 종료·PID0/empty cgroup/원 invocation을 기다린다. child kill/재시도/row repair 금지.
   revision18의 남은 original PENDING은 별도로 분류한다. 새19가 그 audit를 재분류해 claim하지 않는다.
   실제 필요한 경우만 기존 `cancel_unstarted_indexing_workflow`의 exact never-claimed proof를 사용한다.
3. 기존 shared preflight `CHECK`→`STOP`으로 나머지8개를 멈추고 전10개와 전역 Job/native quiescence를 확인한다.
   historical active/exited 무보유 unit은 삭제/reset하지 않는다. migration 전 백업/복구 근거를 고정한다.
4. 같은 protected stage의 exact callback을 실행한다. 0057만 predecessor이며 이미0058이면 verify/replay만 한다.

```sh
/usr/bin/sudo -n /usr/bin/bash "${release_operator_root}/release_operator_runtime.sh" \
  EXECUTE "${release_operator_prefix}" "${release_operator_runtime_sha}" \
  "${release_context_path}" "${release_context_sha}" \
  "${release_launcher_sha}" "${release_helper_sha}" MIGRATION_UPGRADE_0058 "${release_source}"
# 동일 pins로 MIGRATION_VERIFY_0058. migrate_release.sh는 historical0051이므로 사용하지 않는다.
```

5. 기존 source-only Catalog drop-in CAS를 새 source에만 적용하고 기존 reader/mode/범위는 보존한다.
   새 operator pins를 `EOM_RELEASE_OPERATOR_*` 비밀 없는 고정 입력으로 전달한 기존 `install_release_once.py`가
   `/usr/bin/bash /home/eom/EOM/scripts/api/deploy_release.sh --install`을 한 번 호출한다.
   installer는0058 VERIFY→기존 role bootstrap/reconcile→별도 actual delivery build/install→5개 service 재기동을 소유한다.
6. 실제 install terminal을 관측한다. unknown이면 원 child/handle만 관측하고 새 install을 제출하지 않는다.
   postinstall5 restop 후 actual installed3wheels/RECORD/12 provider members를 기존 observer로 확인한다.
   원 build-only rawSHA와 실제 설치 rawSHA가 다를 수 있으며 provider는 후자만 pin한다.

## 5. stopped control selection → legacy warm baseline → optional mixed 활성화

먼저 같은58-compatible binary/새identity19에서 **legacy-only** 정상 구성을 확보한다.
primary QUERY1/private1/read1과 INDEX owner1|2의 같은 namespace1을 선택해 health를 확인하고 이를
feature rollback baseline으로 남긴다. 아래 mixed2/config4 값은 미리 PREPARE하되 그 다음에만 선택한다.
새 fallback wheel/queue는 필요 없다. CPU·SDK·identity를 되돌리는 rollback과 혼동하지 않는다.

- 기존 `scripts/embedding/install_owner_release.sh`를 protected installer 경로로 사용해 final SDK를 별도 불변
  owner release에 설치한다: `SOURCE platform-wheel platform-rawSHA contracts-wheel contracts-rawSHA`.
  이는 numerical prefix 설치나 owner 활성화가 아니다. API/INDEX/QUERY가 모두 같은 SDK 기능을 필요로 하지만
  benchmark EE source/원6 allocation은 바꾸지 않는다.
- 같은 release sibling에 공식 bootstrap을 보호된 exclusive
  `prepare-native-index.py`로 준비한다. `/etc/eom/embedding-native-owner.env`가 실제 새 fixed INDEX/QUERY
  prepare entry를 선택해야 한다. 이 bootstrap은 자기 sibling SDK를 import하므로 old EE/eecf path를 남기면
  association2를 처리하지 못한다. 새 owner-env rawSHA를 INDEX/QUERY 관련 선택들에 함께 반영한다.
  2026-10-24 후속 후보에서는 정본을 wheel member
  `eom_catalog_service/embedding_owner_bootstrap.py`로 이동했다. 최신 owner installer는 검증된 그 member를
  sibling `prepare_native_index.py`로 materialize한다. checkout 파일을 복사하거나 wheel `.data`를 설치하지
  않는다. 종전 immutable release/선택은 보존하고 실제 prepare path·rawSHA는 함께 명시적으로 선택한다.
- 공개 `register_local_indexing_service`→`activate_local_indexing_service`와
  `publish_local_indexing_access_policy`를 기존 deployment owner transaction에서 사용한다.
  새19/새 runtime.json SHA에 귀속한 legacy grant1.1와 mixed grant1.2가 필요하다. old18 grant를 빌리지 않는다.
  native service policy는 기존 `LocalEmbeddingControlArtifactPublisher.publish_service_policy`로만 게시한다.
  legacy는 원 definition1 SHA, mixed는 definition2의 실제 compiled SHA를 선택한다.
- 같은 owner transaction의 public `import_workflow_definition`으로 canonical
  `config/workflows/local-embedding-index.v2.yaml`을 import하고 exact active/hash를 확인한다.
  `EmbeddingEncodingReservationStorage.prepare_mixed_ownership_protocol`을 table-owner로 명시 준비한다.
  runtime은 `require_protocol`/`require_mixed_ownership_protocol`만 하며 스스로 준비하지 않는다.
- 기존 stopped PREPARE/SELECT/backup/epoch/fsync 경계로 `/etc/eom/local-indexing-runtime.json`,
  `/etc/eom/local-indexing-owner.json`, INDEX unit과 해당 control pins를 일관되게 선택한다.
  첫 legacy warm baseline 뒤 선택하는 owner4의 optional `legacy_configuration`도 새19 아래 원 namespace1을 계속 갱신한다. 한 service의 기존
  round-robin을 쓰며 두 번째 INDEX process는 만들지 않는다. runtime.json SHA와 owner.json SHA는 별개다.
  frozen schema4 rawSHA는 `161027494d7be6b2736c41f1257689a04904282bf1e9e59927ff56c239d22188`이다.
  source gate185 PASS는 실제 config 선택이나 runtime 활성화의 증거가 아니다.
- 먼저 QUERY primary1/private1의 새 SDK와 actual provider-derived hashes를 선택한다. warm baseline 뒤 optional
  `/etc/eom/mixed-reference-query-owner.json` + `EOM_MIXED_REFERENCE_QUERY_CONFIGURATION_SHA256`,
  새 SDK entry/unit pins를 하나의 검토된 stopped selection으로 닫는다. primary/private의 PAST 범위를 넓히지 않는다.
- Catalog optional `/etc/eom/catalog-mixed-similarity-read.json`와 hash pin을 선택한다.
  primary `.owner`/C5/Chat/role의 기존 읽기는 유지한다. mixed2 없이 read2를 성공시키는 fallback은 없다.
- 기존5개 shared services를 정상 기동하고 공식 Chat installer `activate SOURCE EXISTING_MODEL
  --previous-runtime-commit OLD --previous-unit-commit OLD --previous-model-config-sha256 HASH
  --rag-policy-revision-id ID --rag-policy-sha256 HASH --private-query-source READ_ONLY
  --similarity-search NATIVE_TOPIC`으로 broker/Chat을 복구한다. 기존 model/CLI를 읽어 보존하고 재포획하지 않는다.
  QUERY READY·INDEX19 STARTED와 versioned API LIVE/READY, 기존10개 service metadata를 별도로 기록한다.
  optional mixed 활성화는 그 baseline 이후 기존 정상 중단/CAS/재기동으로만 한다. 설치를 다시 하지 않는다.

## 6. ordinary source 1회 출판 → 자동 증분의 실제 종료 증거

새 HTTP endpoint나 registration hook은 필요하지 않다. 설치된 공개 application use case
`OrdinaryItemGraphPublicationService(engine).publish(PublishOrdinaryApprovedItemAnalysesCommand(...))`
를 기존 trusted deployment/operator 경계에서 정확한 실제 actor·policy·source command로1회 호출할 수 있다.
현재 자동 registration caller가 연결되었다고 주장하지 않는다. 이 use case가 real actor/current ADMIN
read/retrieve/publish, 실제 accepted V2·원 plan/REVIEW/receipt·최종 Graph CAS를 검증한다. actor ID를
모델/worker/root 기본 ADMIN으로 만들어 넣지 않는다. accepted V2나 REVIEW를 새로 만들지 않는다.

출판 결과의 old/new Graph와 실제 source revision/accepted pointer/evidence SHA를 기록하고, INDEX19의
기존 reconcile이 missing new binding만 접수하는지 확인한다. 완료 receipt/index2의 신규 encoding 수와
기존 row 재사용 수, selected source 범위를 검증한다. old520 coverage backfill을 새 arrival로 계산하지 않는다.
그 뒤 실제 권한의 query2→completed read2 및 같은-key replay를 확인한다. 기존 pinned query1/read1 replay와
새 Graph에서 primary1/private1 준비도 보존해야 한다. 실제 source delta/검색/재사용/철회·복구 증거와
source/disposable DB/설치/READY는 구분하여 원 integration 기록에 남긴다.

## 7. 복구 경계 — 자동 downgrade/재시도 없음

0058 적용 전에는 정확한 inverse file CAS와 보존된 기존 runtime/config로 복구할 수 있다.
0058 이후에는 DB를58로 둔다. migration의 successor history 존재 시 downgrade 거부를 우회하지 않는다.
새 mixed admissions를 멈추고 **동일58-compatible binary/identity19에서 위의 legacy-only 설정과
동일범위 grant**를 선택한다. mixed QUERY/Catalog 환경 pin만 정확히 해제하고 primary1/private1은 유지한다.
미리 확인한 warm baseline으로 복구하며 새 fallback wheel은 만들지 않는다. CPU/old namespace/history는 보존한다.

`apps/application_api/eom_api/health.py`는 installed runtime head와 DB head를 exact 비교한다.
옛881 source/배포 script는57을 기대하므로 old wheels만 되돌려 DB58 READY를 얻는다고 보장하지 않는다.
현재 legacy1 source/PG 회귀는 **새58-compatible code가 old1을 읽는 증거**이지 old881 binary의58 호환 증거가 아니다.
old18/052/881 재선택이나 전체 DB restore는 해당 exact compatible set/공식 recovery 근거를 따로 검토한 경우만 한다.
복구를 위해 old history·failed Job·source 승인·권한·schema 체크를 고치거나 새 key로 우회하지 않는다.
