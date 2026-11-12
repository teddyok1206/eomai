# 모델 선택지 추가 실행 검증

## 범위

사용자의 추가 검증 요청에 따라 설치된 Codex `0.162.1`의 계정 목록에서 확인한
8개 모델을 기존 EOM 실행 계약의 `low/medium/high/xhigh`로 검사한다.
GPT-5.6 Luna/Sol/Terra, GPT-6 Astra/Luna/Sol, GPT-6.1 Sol/Terra가 대상이다.
`max/ultra`는 목록 표시와 EOM 실행 계약 지원이 다르므로 이번 실행에는 포함하지 않는다.

- 일반 실행의 기존 검증 쌍인 슬롯 01·02: 최대 64회.
- 채팅 전용 슬롯 06: 최대 32회.
- 합성 이미지 읽기·간단한 계산·정확한 구조화 결과만 검사하며 실제 문항은 생성하지 않는다.
- 모델 제공 여부 및 실행 계약 호환성을 검사한다. 교육 품질의 비교 평가가 아니다.
- 기존 프리셋 기본값, 계정 인증, 슬롯 03–05의 검증 범위와 기존 실행 이력은 보존한다.

## 실행·반영

설치 platform/API `748f6acfc1b696ec44e96c7b680a9bc1701bcca3`의 공식
scoped compatibility application과 기존 host-capacity fence를 사용한다.
소스 HEAD와 설치 release가 다른 것은 Web·문서 후속 변경 때문이며,
검증 입력은 실제 설치 source/runtime/hash/계정 assignment에 고정한다.
진행 중인 작업을 중단하거나 GPU runtime을 변경하지 않는다.
검증 동안 새 Codex claim은 host fence를 기다릴 수 있다.

기존 request/checkpoint/replay와 Orchestrator Artifact commit을 재사용한다.
실패는 보존하고 자동 우회·성공 재분류를 하지 않는다.
committed report의 PASS 조합만 공식 policy installer로 반영한다.
반영 전 기존 허용 조합이 빠지지 않는지 비교하며 정확한 이전 정책 SHA와
runtime/assignment를 다시 확인한다. installer의 보호된 이전 정책 백업을 유지한다.

새 schema·DB migration·framework는 없다. 산출물은 Git에 넣지 않고
`/var/lib/eom-model-choices-proof-20261112/`와 공식 Artifact에 보관한다.
상태 확인이 모델 추론 검증을 대신하지 않으며, 계정의 모델 목록만으로 허용하지 않는다.

## 검증 결과

실행 전 기존 정책 설치·프리셋 선택 회귀 검사 120 PASS.
추가 runtime/maintenance/정책 V3/probe/matrix/계약/현재 계정 snapshot 회귀 326 PASS.
핵심 런타임 코드는 변경하지 않았다.

첫 64-case 요청은 실제 12회 중 11 PASS, GPT-6.1 Sol/xhigh의 1 FAIL에서
기존 fail-stop 규칙대로 종료했다. 실행·strict JSON·identity·계산은 맞았지만
합성 이미지의 사각형을 원으로 읽은 `RESULT_CONTENT_MISMATCH`다.
나머지 52개는 `NOT_RUN`이며 실패와 같은 의미가 아니다. 정책은 변경하지 않았다.

후속 검증은 사용자가 바로 모델을 고를 수 있는 경로에 집중하여
8개 모델의 medium/high를 일반 슬롯 01·02(32회), 채팅 06(16회)에서 우선 확인한다.
총 최대 60회이며 최초 상한 96회 이내다. 실패한 xhigh를 재시도하지 않고
새 범위의 독립된 request로 기록한다. medium/high의 이전 성공 일부를 다시 실행하는
이유는 기존 policy owner가 검증한 슬롯의 전체 허용 범위를 하나의 committed report로
교체하기 때문이다. 여러 report의 결과를 임의로 합쳐 새 canonical proof를 만들지 않는다.

일반 슬롯 01·02의 후속 32회는 모두 PASS, worker 경과시간 합계 290.013초다.
11:17 UTC에 공식 installer의 검증 후 정책을 설치했으며 기존 허용 쌍은 모두 보존하고
30개 슬롯/model/effort 조합을 추가했다. 프리셋 및 채팅 기본 설정은 변경 전후 동일하다.
공식 OBSERVE 두 건도 SUCCEEDED다. API DB role의 실제 설치 adapter로 확인했을 때
문항 제작 4개 역할과 자료 검토/학습/등록/유사도 비교/A/S의 각 단계에 8개 모델의
medium/high 16개 조합이 반환된다. 슬롯 6개 모두 READY다.

일반 실행 proof:

- run: `codexcompat_7a72e08f34e747799d018ea07bb038c0`
- artifact: `artifact_fe67ca308e7c4148bf102c145bf9ed0b`
- revision: `rev_ab84e3ff520e406eb53b5100930116a0`
- member: `report.json`
- SHA-256: `a1be25829ead71ae0d931c6bb006f45e45c6231b0718273e2472715d766f841f`

첫 실패 기록은 `codexcompat_3b51394bfb024639b511f97bfb5edc74`,
`artifact_4b340573aa114d32957035c8386edc36` /
`rev_51d0170643a34297936d1ee6880a7aa1`의 `report.json`에 보존했다.
SHA-256: `9fab2a1670b5721aa1b3500fb6d3b465e887fd48ff45811d22fde9624edbee0e`.

## 최종 운영 확인

채팅 슬롯 06의 16회도 모두 PASS이며 worker 경과시간 합계는 139.920초다.
총 모델 호출은 **60회(59 PASS, 1 FAIL)**다. 이는 호출 수이며 서로 다른
조합 수나 문항 생성 수가 아니다. 실제 문항·채팅 대화 생성은 0건이다.
채팅 슬롯에서도 기존 CLI diagnostic owner를 검사했으며, 새 모델로 실제 ChatGPT
대화를 생성한 사용자 수용 검증과는 구분한다.

채팅 슬롯 proof:

- run: `codexcompat_825f4467f17f47df95d6d09e9a1531d2`
- artifact: `artifact_33e8fed801304816b006f00c9a24c48b`
- revision: `rev_20385183b2514d138820188aa06b0bf5`
- member: `report.json`
- SHA-256: `b5523fd7179d008c39dbfea9129be2a626c5fa0d6ca106909dcc9dab6b079fa0`

최종 정책 SHA-256은
`699237c4a50b6f692cae19446f86509c39245464854392b1795a8d414e37ea0c`다.
정확한 이전 정책 백업은 `/etc/eom/codex-capabilities.previous.<sha256>.yaml`,
설치 전후 비교와 공식 OBSERVE의 요청 참조는
`/var/lib/eom-model-choices-proof-20261112/{pair-core,chat-core}/admission.json`에 있다.

11:21:50 UTC, API DB role의 설치 adapter로 최종 확인:

- 슬롯 6개 모두 READY, 이번 공식 OBSERVE 8건 모두 SUCCEEDED.
- 문항 제작·검토 및 다른 일반 기능: 8개 모델의 medium/high와
  기존 Terra/xhigh가 유지되어 각 역할에 17개 조합이 반환됨.
- ChatGPT: 8개 모델 × medium/high = 16개 조합이 반환됨.
- 현재 프리셋·채팅 설정 변경 없음. API/Web/runner/chat/QUERY 프로세스 재시작 없음.
- runtime wheel/DB schema/실제 문항/Graph/임베딩 입력·벡터 변경 없음.

새 모델은 실제 검증한 일반 슬롯 01·02 또는 예약된 채팅 06에만 허용된다.
검증을 다른 계정·슬롯 03–05로 복사하지 않았다. 일반 claim은 기존 공유 pool과
모델별 capability 조건을 그대로 따른다. low/xhigh의 전체 모델 검증은 완료하지 않았으며,
GPT-6.1 Sol/xhigh의 첫 실패도 보존한다. max/ultra는 기존 실행 규약 미지원 상태다.
사용자 브라우저의 새 선택지 육안 확인과 모델별 출제 품질 평가는 별도다.
