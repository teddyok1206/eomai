# 공통 풀이 GPU 재임베딩 실행 체크포인트

시각: 2026-10-31 09:38 UTC. Goal ACTIVE. 재임베딩/검색 전환/구 벡터 삭제 완료 보고가 아니다.

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

**구 벡터 삭제0. 운영 검색 전환 및 goal 완료는 아직 미확정이다.**
