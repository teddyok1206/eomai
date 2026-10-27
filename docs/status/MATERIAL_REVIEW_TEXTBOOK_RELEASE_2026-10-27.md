# 자료 검토 교과서 Graph 근거 운영 반영 — 2026-10-27

관측 시각: 2026-10-27 04:02 UTC. 이 기록은 새 자료 검토 경로의 설치·활성화 증거이며, 실제 새 문서를 끝까지 검토한 교육 품질 승인 기록은 아니다.

## 반영 범위

- 운영 Application API/Catalog/Workflow 호환 릴리스의 설치 소스는 `9e69795ae2c219d77a9a49c975b900184284d1b2`다. 설치된 `command_adapter.py`, Catalog `application_server.py`, 교과서 근거 검증기, Workflow 문서 검토 계약의 바이트 SHA-256은 해당 커밋의 각 파일과 일치했다.
- 단일 자료 검토 `pdf-document-review@1.4.0` (`workflow-role/1.31.0`)와 문제지·해설지 검토 `@1.5.0` (`workflow-role/1.32.0`)는 모두 `active`, `admitted`, `accepts_new_work=true`였다.
- `pdf-document-review` 실행 프리셋의 현재 revision은 `execpresetrev_2ff223fbb92340f68c6b125d5921fd67` (14, `RELEASED`), 지침 번들의 현재 revision은 `instrrev_25ef24a2a5f5efe9a6ed9e3ac0723717` (7, `RELEASED`)이다. 두 새 프로토콜 모두 현재 프리셋에서 해석됐고, 고정 corpus는 `integrated-science-textbooks`이며 허용 출처에 `TEXTBOOK`이 포함된다.
- API, Catalog application runner, Workflow runner는 active였다. 로컬 API `/api/v1/health/live`와 `/ready`는 각각 `LIVE`·`READY`였고, 외부 `https://eomai.duckdns.org/studio/api/v1/health/ready`는 HTTP 200/`READY`였다. 외부 단일 업로드·문제지/해설지 생성 경로는 비인증 POST를 HTTP 401로 거부했다.
- 단일·쌍문서 교과서 근거 회귀 테스트는 23 PASS. 기존 GPU INDEX owner의 PID `734655`와 invocation `9718f2ed05ac404e84ce7a69559b110c`는 그대로 active였으며, 이번 확인에서 재시작·GPU 기본 선택·새 모델 작업을 실행하지 않았다.

## 남은 검증 경계

- 활성화 이후 새 문서에 대한 사람 인증 업로드·Graph 근거 발행·worker 결과·영수증까지의 live canary는 아직 실행하지 않았다. 따라서 실제 문서 검토 완료나 교육적 정확성을 이 기록으로 주장하지 않는다.
- 전역 `workflow definition admission`의 `consistent=false`는 별도 `item-inference-transfer-comparison@1.0.0` 정의 누락을 포함한다. 자료 검토 1.4/1.5 두 정의 자체는 신규 작업 허용 상태다. 이 전역 항목을 맞추려고 GPU 실험의 핀이나 기존 실패 이력을 수정하지 않았다.
- 생성 문항의 검토 경로는 별도 Workflow다. 이 배포는 단일·쌍문서 자료 검토의 교과서 Graph 근거 활성화이며, 생성 문항 검토까지 완료했다고 확대하지 않는다.
