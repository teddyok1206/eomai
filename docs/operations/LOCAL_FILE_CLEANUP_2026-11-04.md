# 로컬 개발 산출물 정리

2026-11-04 UTC. 사용자 요청으로 재생성 가능한 로컬 파일만 정리했다. 문항·자료·Graph·
벡터·실패 이력과 기존 실행은 삭제 대상이 아니며 `/home/eom/EOMIS`는 건드리지 않았다.

## 정리 결과

| 종류 | 디렉터리 수 | 복구 방법 |
| --- | ---: | --- |
| 저장소 개발 캐시와 build/egg-info | 5 | 같은 source와 명시적 개발 환경에서 재생성 |
| source가 남아 있는 bytecode cache | 42 | 원래 Python source에서 재생성 |
| 완료된 API build source 복사본 | 91 | 보존한 같은 `source.tar`, wheel와 Git commit |
| marker가 확인된 오래된 임시 mypy cache | 9 | 원래 개발 검사 재실행 |
| 오래된 Web 설치 시뮬레이션 | 110 | 보존한 wheel과 같은 build source/Git |
| 오래된 Web staging 복사본 | 111 | 보존한 wheel과 같은 Git commit |
| 합계 | 368 | 정리 plan에 개별 경로와 원래 identity·복구 참조 보존 |

공간 차이는 약 13,225,914,368 bytes, 약 12.3GiB다. root 여유는 약 52GiB에서 64GiB로
늘었다. 백그라운드 writer가 계속 동작하므로 파일별 크기 합계가 아닌 같은 파일시스템의
관측 차이다. 개발 검사로 새로 만들어진 cache는 정리 실패나 남아 있는 이전 객체가 아니다.

## 보호한 범위

Git tracked 코드·released schema/설정·테스트, 설치 runtime와 활성 source commit,
wheel·source archive·env/auth·rollback 기록, 사용자 ZIP 업로드·staging 증거, NAS 정본·
모델·벡터·백업을 보존했다. workspace의 `EOM`은 일반 파일이 아닌 socket이므로 보존했다.
오래됐거나 정적 import가 없다는 이유만으로 계약 버전을 삭제하지 않았다.

정확한 디렉터리·소유자·inode·mtime, wheel source commit과 Git ancestry를 확인한 목록만
사용했다. 실행 중 argv/cwd/exe/open descriptor의 참조와 활성 commit은 제외했다.
삭제는 낮은 CPU/I/O 우선순위로 실행했고 service/worker 재시작·업무 DB 변경·모델 호출은
수행하지 않았다. 정리 전후 서비스 PID/상태가 같고 API READY·HTTPS 200 및 계속되는
slot/INDEX 작업을 확인했다.

## 중단과 재개 기록

첫 정리는 Web의 `installed` 삭제가 부모 디렉터리 mtime을 바꿔, 형제 `staging`의 안전
검사에서 멈췄다. 부모 mtime이 아닌 frozen target 자체의 identity/age와 복구 wheel/Git을
재검사하도록 고쳤다. 새 대상을 보태지 않고 같은 plan의 남은 디렉터리만 처리했으며,
이미 없어진 대상은 다시 지우지 않았다. 최초 실패 로그와 같은 plan의 재개 결과를 보존했다.

## 감사 Artifact

기존 Orchestrator file-set publisher로 9개 증거 member를 등록했고 Catalog에서 committed
report의 bytes/hash를 다시 확인했다. 자격증명이나 원문 문항은 증거에 복사하지 않았다.

- Artifact: `artifact_252f35cc243a45a39c1ef595a28ee5c9`
- Revision: `rev_ede6b8d1da6b4574934450b70cd1cd2e`
- Member: `cleanup-report.json`
- SHA-256: `sha256:9a3ed6cf7e327454e0af6bfe29feed5bac2f17a3f1f734b61c9c7d2a3b0fe772`

이번 정리는 일회성 운영 작업이다. 새 자동 삭제 timer나 runtime 의존성을 만들지 않았다.
함께 만든 `docs/agent-context`는 개발용 탐색 메모이며 운영 GraphRAG나 worker authority가 아니다.
