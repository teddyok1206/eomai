# 모델 설정 중복 선택 안내 수정

## 확인된 원인

사용자가 본 `PRESET_MODEL_CANDIDATES_DUPLICATED`는 설정 저장 전 Web의
`reviewedPresetDraft → cloneRolePolicy`에서 발생한다. 같은 역할 안의 후보에
동일한 model/effort가 두 번 들어가는 것을 거부하는 기존 규칙이다.
기본·강화 검토는 서로 다른 후보여야 하며 서버의 `ResolvedStepExecutionV12`도
이를 요구한다. 모델 실행 실패나 저장된 정책을 고치는 작업이 아니다.

실제 Chromium에서 강화 검토의 모델을 바꾸자, 기존 xhigh를 지원하지 않는 모델의
첫 깊이 medium이 자동 선택되어 기본 검토와 같아지는 경로를 재현했다.
사용자가 두 후보를 직접 같게 골라도 확인 버튼을 누르기 전에는 안내가 없었다.

## 수정 경계

- 기존 `execution-preset-controller`가 선택 중인 역할/model/effort를 Map으로 묶어
  O(C)로 충돌을 표시한다. 다른 역할의 같은 쌍은 충돌로 취급하지 않는다.
- 같은 역할의 충돌은 해당 카드에 쉬운 한국어로 안내하고 확인 버튼을 비활성화한다.
  사용자의 편집값은 보존하며 수정하면 다시 확인·저장할 수 있다.
- 지원하지 않는 깊이는 명시적인 빈 선택 상태로 둔다. 상태 갱신도 임의의 깊이를
  선택하지 않는다. 모델만 고른 미완성 편집 상태도 갱신 후 보존한다.
- 후보 수·순서와 서버의 유일성·강화 검토 규칙은 유지한다. 자동 dedup이나 무조건
  중복 허용은 기존 실행 의미를 바꾸므로 사용하지 않는다.

새 DB/schema/API·추론·인증·프리셋 발행 변경은 없고 Web-only 배포다.
반영 중 API/QUERY/INDEX/runner/채팅/HWPX 및 현재 허용 정책을 보존한다.

## 검증

브라우저 회귀는 자동 깊이 선택으로 발생한 중복, 직접 중복 선택의 안내,
같은 모델의 다른 깊이 허용, 다른 역할 간 같은 쌍 허용, 수정 후 저장의 후보 순서,
미완성 선택/중복 선택의 상태 갱신, 확인 후 다시 중복으로 바꿀 때 기존 저장 승인의
폐기, 기존 재전송·stale 응답·모바일 경로를 확인한다. 운영 문항이나 모델은 호출하지 않는다.

초기 실행의 Playwright 경로 오류를 기존 설치된 browser cache 설정으로 바로잡았다.
그 후 수정 전 제품 코드에서 `actual=medium, expected=빈 선택` 실패를 재현했다.
1차 수정에서 미완성 선택의 갱신 시 모델도 비워지는 문제가 발견되어 함께 수정했다.
집중 검사 65 PASS. 최초 실패 로그는 staging에 보존한다.

전체 Web(옵트인 실제 Chromium 포함)·프리셋 모델 선택·개발 문맥 검사 합계
592 PASS. JS 구문 검사·diff 공백 검사 PASS. Python/DB/worker 변경은 없다.
설치 API DB role의 읽기 전용 조회에서 현재 13개 작업 단계의 후보는 모두 유일하며,
문항 제작의 검토 후보는 기존 Terra high/xhigh로 정상이다. 운영 설정을 보정하지 않았다.

## 운영 반영

- 2026-11-12 11:43:58 UTC, Web `858680cfaaa3e091b6e98b220e50ccb8d70e3735`
  설치·활성화 완료. 설치 RECORD 80개와 실제 Web 서비스 계정 검증 PASS.
- wheel SHA-256: `534238494ba6262652115223688a4b04b3b97764b00274a99660e265ef15185f`.
- 실제 HTTPS ready·로그인 페이지·변경된 JS/CSS bytes와 wheel 일치 PASS.
  로그인 페이지 조회는 사용자 인증·수동 저장 확인의 대체 증거가 아니다.
- API/QUERY/INDEX/runner/자료 학습/채팅/HWPX 서비스의 PID·invocation·상태와
  Web 설정·허용 모델 정책 hash는 배포 전후 동일하다. INDEX는 배포 전부터 failed였으며
  이번 Web 변경으로 재시작하거나 복구하지 않았다.
- DB 변경 0, 모델 호출 0. 사용자 화면 확인은 아직 PENDING이다.
- 운영 기록: `/var/lib/eom-preset-duplicate-web-release-20261112/activated.json`.
  이전 Web `fd35ed69631305610ee29e16b4d340376d798582`의 검증된 wheel을
  같은 배포의 보호된 staging에 보존해 rollback 가능하다.
