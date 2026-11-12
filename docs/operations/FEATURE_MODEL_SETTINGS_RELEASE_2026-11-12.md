# 기능별 모델 설정 정리 · 운영 반영

2026-11-12 10:30 UTC 기준. 운영 source는
`748f6acfc1b696ec44e96c7b680a9bc1701bcca3`이다.
설계: [기능별 모델 설정](../architecture/FEATURE_MODEL_SETTINGS_CONSOLIDATION.md).

## 사용 방법

`관리자 설정 → 모델·생각하는 깊이`에서 다음7개 기능 중 하나를 선택한다.

| 기능 | 필요한 작업 단계 |
| --- | --- |
| 문항 제작 | 출제·그림·검토의 역할별 모델 |
| 자료 검토 | 문제지·해설지 검토 |
| 자료 학습 | 내용 읽기·개념·문항·풀이·기출/교과서 분석 |
| 기존 문항 등록 | 원문/그림/풀이·Graph·추출·출력 양식 |
| 유사도 정밀 비교 | 풀이 방식 비교(Codex, 벡터 계산과 별개) |
| 고객지원 | 시스템 문의 |
| ChatGPT | 전용06의 대화 모델·깊이 |

서로 다른 프롬프트/결과 규약을 한 프리셋으로 합치지 않았다. 내부의13개 현행
Workflow 단계 설정과 기존 ChatGPT owner를 기능별로 묶는다. 단계가 하나면 단계
선택란도 숨긴다. 기존 model-only 검증·발행 절차와 미적용 초안 재개를 유지한다.
사용자에게 과거 버전·슬롯 수별 중복 프리셋 목록을 보여주지 않는다.

## 실제 정리 결과

- 신규 실행에서 구 프리셋7개 퇴역: `standard-item`, `external-item-learning`,
  `creative-source-learning`, `creative-source-learning-parallel`,
  `creative-office-learning`, `creative-knowledge-analysis`,
  `creative-knowledge-analysis-parallel`.
- 현재 pointer·실행·분석·배치·평가·검증 참조 및 설치 환경/cohort pin에서 사용하지
  않는 과거 revision36개를 실제 삭제했다. 정확한 ID/hash를 사전 고정했다.
- 기존 revision207개에서36개를 제거하고 퇴역 증거7개를 추가하여178개가 남았다.
  보존된 것은 현행 설정과 이력/검증 연결 기록이다. 참조 FK는 해제하지 않았다.
- 풀이·분석2,929건, 실행 plan4,878건, 분석 batch6건의 수와 참조를 보존했다.
  문항·Graph·원문·NAS Artifact는 삭제 대상이 아니다.
- 설정 백업: `/mnt/nas/eom/backups/control-plane/feature-settings-20261112-748f6acf`.
  설정 JSON과 SHA manifest만 보관하며 인증·사용자 내용은 포함하지 않는다.
- 정확한 운영 영수증:
  `/var/lib/eom-feature-settings-release-20261112/presets-cleaned.json`.

삭제는 기존 DB-owner maintenance 경계에서 두 설정 테이블만 트랜잭션으로 처리했다.
불변 trigger는 동일 트랜잭션에서 복원되며 runtime API/worker의 권한은 늘리지 않았다.
이력 pin을 다른 revision으로 바꾸지 않았고, 모든 과거 프리셋을 가짜 최신 별칭으로
재해석하지 않았다. source의 historical protocol/loader는 과거 계약 재현을 위해 남는다.

## 검증

- Web/API/model-selection focused:904 PASS,15 opt-in browser skips.
- 별도 실제 Chromium: 기능 전환·초안 재개·저장 뒤 조회 timeout·동일 intent 재전송·
  늦은 응답·로그아웃·검증/발행·320/390px 화면과 ChatGPT 설정 확인.
- 추가 API contract/release inventory/context149 PASS, OpenAPI7 PASS.
- Disposable PostgreSQL21 PASS: 참조/현재 revision 삭제 거부, hash/실행 중 거부,
  동시 정리, 동일 요청 재전송, 삭제 후 중단 rollback/trigger 복원,
  current+새 draft 조회의 고정3queries.
- Ruff/format PASS. 변경 source9개 strict mypy는 `--follow-imports=silent`로 PASS.
  전체 dependency traversal의 기존 material-learning union 관련12개 오류는 이번
  변경 대상 밖이며 전체 저장소 type-check PASS로 보고하지 않는다.
- API/platform wheel RECORD, Web non-editable 설치 simulation78files PASS.

## 운영 확인

API/platform/Web 및 공유 owner의 호환 release set을 배포했다. DBhead0079 그대로,
schema migration·모델 추론·계정 로그인 변경은0이다. QUERY의 별도 numerical source는
유지하고 API provider pins만 호환 갱신했다. INDEX의 기존 failed 상태/설치 pin은
보존했으며 이번 설정 정리가 임베딩 복구를 했다는 뜻이 아니다.

설치된 API runtime DB역할의 read-only 조회로7개 기능/13개 현행 단계가 반환됨을
확인했다. 실제 HTTPS의 HTML/JS/CSS5개가 설치 wheel과 일치하고, 비로그인 관리자
조회는401로 거부된다. API/Web/ChatGPT owner·worker/runner/material/QUERY active.
사용자 로그인 화면에서 최종 시각 확인은 별도 요청했으며 아직 결과를 기록하지 않았다.

설치·read 결과는 같은 보호된 release 디렉터리의 `activated.json`,
`release-set.json`, `live-read-check.json`에 있다. Git의 이후 문서 commit은 runtime
source 교체로 간주하지 않는다. 삭제 전 백업은 운영자의 정확한 복원 scope 검토용이며
일괄 자동 rollback이나 기존 실패 이력의 성공 변경을 수행하지 않는다.
