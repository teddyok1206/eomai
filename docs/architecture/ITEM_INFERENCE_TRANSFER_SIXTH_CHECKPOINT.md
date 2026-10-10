# 문항 핵심 착상 전이 — 인증 호출부·CPU 설치 경계 checkpoint

기록일: 2026-10-10 UTC. 상태: **SOURCE_VERIFIED / LIVE_EXPERIMENT_PENDING**.
이 문서는 앞선 역사적 검증을 대체하지 않으며 실제 corpus 비교·교육 품질 PASS가 아니다.

## 승인 및 구현 범위

사용자가 실제 `guiadmin`으로 운영 설치와 제한된 비교 실험 진행을 승인하고,
`inference-transfer` tmux 창에서 sudo 인증을 완료했다. 목표 카드도 ACTIVE로 재개됐다.
계정 사칭, 비밀번호 추측, browser token 추출, worker의 DB/NAS 접근은 허용하지 않는다.

- 기존 API 로그인·`/me` 계약을 재사용하는 owner session을 추가했다. 고정 API socket의
  실제 peer UID를 자격 증명 전송 전에 확인한다. 토큰은 메모리/상속 FD에만 두고
  CLI 로그인은 비표시 TTY 입력만 허용한다. 만료·principal 교체는 자동 갱신하지 않는다.
- actor 없는 exact-pin metadata 계약을 먼저 정의하고 Catalog 소유 read와 API에 연결했다.
  raw manifest SHA와 Graph semantic SHA를 분리한다. 이 조회는 execution 권한 토큰이 아니다.
- 기존 `assessment-learning-corpus`와 `execution-presets` GET을 같은 typed session으로
  연결했다. 원래 기출의 Graph와 textbook Graph를 혼동하지 않으며 목록의 exact revision을
  검토·pin한다. 새 discovery API나 DB 직접 RAG 조회는 만들지 않는다.
- authenticated snapshot → 기존 staging/exclusive execution → CPU → source 재인가 →
  기존 Orchestrator Artifact publisher를 설치된 owner CLI에서 연결했다.
- capacity 조회는 현재 실제 control 권한으로 exact RELEASED revision을 읽는다.
  관측값을 갱신하거나 슬롯을 예약·활성화하는 작업이 아니다.
- 검토한 최초 platform/rubric 원문을 별도 config에 보존했다. PREPARE는 DRAFT만 만들며
  RELEASE는 별도 명령이다. 기존 출제·PDF·support preset을 변경하지 않는다.

## CPU 환경과 설치 경계

별도 Conda prefix `/opt/eom/conda/envs/eom-embedding-experiment`와 보호된 모델 저장소를
사용한다. 기존 API 환경의 부모가 developer-writable이므로 root bootstrap interpreter로
재사용하지 않는다. system Python 예외도 추가하지 않는다.

developer가 명시적 Conda `--copy` clone과 non-editable wheel을 준비한다. root는
독립 검토 SHA가 확인된 **root-private installer 사본**으로 새 inode tree를 검증하고,
고정 prefix를 교체한 이후에만 첫 Conda instruction을 실행한다. 원래 mutable tree는
별도 보존하며 root 신뢰 runtime으로 간주하지 않는다. 모델은 독립 pin과 FD/type/size/hash
검사 뒤 공개한다. 설치 자체는 모델 forward를 수행하지 않는다.

별도 CPU UID/private group, fixed prepare/main/probe units와 좁은 polkit start 경계를
검증한다. no-forward probe는 설치·격리 증거이며 검색 품질·과학 정확성 증거가 아니다.
상세 절차: [CPU runtime runbook](../operations/INFERENCE_TRANSFER_CPU_RUNTIME.md).

## 현재 검증과 운영 관측

- 인증 HTTP/owner CLI 관련 focused source 회귀: 306 PASS.
- metadata 계약·API·Catalog 관련 회귀: 226 PASS.
- root의 프롬프트/capacity/deployment 관련 회귀: 157 PASS.
- 새 read-only metadata POST를 OpenAPI operation inventory에 추가하고 OpenAPI 6 PASS.
- 위 suite는 일부 중복되므로 더한 숫자를 고유 총 테스트 수로 보고하지 않는다.
  최종 unified source 검사 88개 파일 **2,286 PASS / 88.21초**, Ruff check·format
  39개 파일 PASS, strict mypy production 21개 파일 PASS, bash syntax·diff check PASS.
  최초 unified 실행은 2,285 PASS + 1 failure였고, 배포 resource inventory의 신규 metadata
  스키마 누락을 보완한 뒤 관련 9개와 전체 suite를 재실행했다. 이 실패 이력을 숨기지 않는다.
  설치 wheel 검증과 live gate는 별도로 기록한다.

실제 installed owner의 읽기 전용 점검에서 source `83884224651d8b9516a7a54370077757138c518c`,
DB head `20261009_0050`을 확인했다. 최초 점검은 Workflow models를 등록하지 않은
불완전한 composition이라 보수적 `CODEX_COMPATIBILITY_JOB_BUSY` fallback을 반환했다.
owner의 read-only metadata 및 기존 inspect로 오래된 CANCELLED/FAILED Workflow의 자식
기록을 분류하고, 정상 Workflow model composition을 포함한 같은 공식 점검을 다시 실행해
`DATABASE_QUIESCENCE=PASS`를 확인했다. active/reconciling lease 0, queued job 0,
claimable command false, active worker unit 없음이다. 역사적 row는 변경하지 않았다.
배포 실행 직전 같은 점검을 다시 확인해야 하며 read-only 관측은 reservation이 아니다.
전용 CPU prefix 준비와 Conda clone은 기존 작업 환경과 분리해서 완료했다.

## 남은 gate

1. 새 소스의 통합 format/lint/type/focused regression 및 exact wheel build 검증.
2. 전용 CPU 설치·effective sandbox/polkit·no-forward actual probe.
3. 기존 실행 작업 분류와 호환 공유 release 배포 및 필요한 supported migration.
4. 실제 guiadmin 인증으로 원래 기출 Graph/policy/revision 조회·재인가.
5. 원래 승인 기출 520개에 대한 길이/overflow·비용 및 세 표현 비교의 bounded 실험.
6. 기존 Orchestrator 경유 제한된 쌍 비교, 실제 대응·차이·추가 추론 기록.
7. 사람용 평가 묶음. `HUMAN_TRANSFER_REVIEW=NOT_EVALUATED`를 자동 PASS로 바꾸지 않는다.

새 Item/HWPX/GPU 생성, 기존 520개 분석 재처리, 새 queue/vector DB는 이 범위에 없다.
timeout/UNCERTAIN 뒤 새 identity로 중복 실행하지 않으며, 실패 이력과 partial 설치 자료를 보존한다.
