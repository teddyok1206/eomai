# EOMIS 퇴역과 미사용 모델 캐시 정리

2026-11-06 UTC. 사용자 명시적 요청에 따른 일회성 정리를 완료했다. NAS 암호화 백업·
전체 대조·정리 감사 발행을 확인했다. 슬롯 재개와 전체 문항 처리 완료는 별도로 구분한다.

## 범위와 보호 경계

- 사용자의 이번 `/home/eom/EOMIS` 삭제 요청을 기존 AGENTS의 해당 경로 보호 규칙에 대한
  이번 작업만의 예외로 적용한다. 현재 EOM source/history는 별개이며 수정하지 않는다.
- 기존 systemd sandbox의 `InaccessiblePaths=/home/eom/EOMIS`가 경로 존재를 요구하므로
  EOMIS 소스·데이터를 제거하되 같은 빈 디렉터리 inode를 남긴다. 보호 규칙을 풀거나
  서비스 unit을 대량 수정하지 않는다. NAS의 기존 EOMIS 자료는 삭제 대상이 아니다.
- 오래된 `scripts/watch_one_variant_nas.py`만 정확한 PID·exe·cwd·entry를 대조한 뒤
  종료했다. 현재 EOM 서비스를 정리 대상으로 종료하지 않았다. 도중 INDEX owner가
  스스로 만료·종료한 사건과 같은 설정의 복구 1회는 아래에 별도로 기록한다.
- 정리는 정확한 model-cache leaf와 다운로드 archive만 대상으로 한다. HF token/
  stored_tokens, Codex/Studio/SSH 인증, 설치 model/runtime/환경, 원본·벡터·DB·실패 이력은
  보존한다. 기존 정상 작동을 중단해서 작업 시간을 맞추지 않는다.

## 선택·검증·복구 방법

정본은 현재 protected binding/model store와 NAS Artifact다. home 아래 HuggingFace cache를
정본이나 설치 모델로 간주하지 않는다. `/proc` argv/cwd/exe/FD/mmap과 설치 config/tool의
실제 참조를 확인하며, `InaccessiblePaths` 차단 경로를 모델 입력 참조로 오인하지 않는다.

모델별 map/set membership과 고정된 경로 allowlist를 사용한다. 입력 수/바이트에 선형으로
한 번씩 content-address를 검증한다. blob SHA-256 또는 Git-blob SHA-1과 파일명, 정확한
snapshot revision을 보존하고 변조·특수 파일·다른 경로를 가리키는 symlink는 정리에서
제외한다. 삭제 직전에 inode/dev/size/mtime/ctime와 실행 참조·설치 설정을 다시 대조한다.
캐시 root 전체를 이름만 보고 삭제하는 대안은 인증이나 실제 사용 모델을 잃을 수 있어 쓰지 않는다.

Conda는 `.conda`/`.tar.bz2` 다운로드 파일만 정리하며 환경과 풀린 package cache를 남긴다.
활성 환경이 symlink로 의존할 수 있는 `conda clean --all`은 실행하지 않는다. pip 캐시는
재생성 가능한 정확한 디렉터리만 대상으로 한다. 모델 가중치/보고서는 Git에 넣지 않는다.

EOMIS는 전체 native tar(기존 Git·비추적 작업·adapter 포함)를 만든다. private 환경 파일도
있으므로 기존 시스템 OpenSSL의 AES-256-CBC/PBKDF2(200,000회)로 암호화한 파일만 기존
Catalog file-set application → Orchestrator commit owner로 NAS Artifact에 발행한다.
작은 합성 입력의 암복호화 roundtrip과 key mode0400을 확인했다. 새 복구 키는
`/etc/eom/secrets/eomis-retirement-backup-20261106.key`에 root 전용으로 두며 NAS/Artifact/
Git/로그에 키나 평문 환경 내용을 넣지 않는다. 기존 계정·로그인 키는 바꾸지 않는다.
서버 유실까지 포함한 재해 복구 훈련은 이번 정리의 검증 범위가 아니다.

전체 NAS ciphertext SHA를 재검증하고, 삭제 직전 local archive와 원본 전체를 `tar --compare`로 대조한다.
백업 실패 시 EOMIS 원본 삭제를 하지 않는다. 동시 작업용 queue·새 cleanup 서비스·runtime
계약/DB schema는 만들지 않는다. 같은 디렉터리의 로컬 임시 백업은 정식 NAS 백업을 검증한
뒤 제거하며, public cache는 기록한 repository/snapshot/hash로 다시 받을 수 있다.
암호화 전 로컬 백업은 NAS 발행 전에 중단했고, 생성 중이던 임시 파일만 정확한 identity로
정리했다. 그 시도의 로그·중단 사유는 보존했으며 EOMIS 원본 삭제나 Artifact 발행은 없었다.

## 증거 위치와 완료 조건

- 정확한 inventory·config hashes·model manifests·보고서:
  `/var/lib/eom-storage-retirement-20261106`.
- 실행 로그: `/tmp/eom-legacy-model-*.log`. 로그에 자격증명·원문 문항을 넣지 않는다.
- 캐시 정리는 CPU nice15/idle I/O를 사용했다. 대용량 백업에서 대기가 길어져 백업
  operator만 best-effort7을 거쳐 nice5/best-effort5로 조정했다. 기존 EOM worker/INDEX의
  priority·config는 변경하지 않았다. INDEX의 PID/InvocationID는 아래 복구 때 변경됐다.
- 완료 조건: 캐시 결과/예외, 정식 NAS 백업 pointer/hash·전체 readback, 빈 sandbox guard,
  현재 EOM 설치 설정 보존, 주요 service identity 대조와 명시적 복구 기록,
  API/HTTPS·background 진행 확인.
- 기존 `check_repository_boundaries.sh`의 초기 EOMIS Git-root 검사는 퇴역 후 적용되지 않는다.
  빈 sandbox guard는 옛 Git repository가 아니다. 기존 보존 baseline이 여전히 일치한다고
  주장하거나 옛 EOMIS history를 현재 EOM repository에 합치지 않는다.

## 실제 결과

### 회수·보존

| 대상 | 실제 정리 결과 |
| --- | --- |
| 공개 모델 cache leaf | 11개, 할당 크기 228,218,544,128bytes. snapshot·blob hash와 현재 실행 참조를 확인했다. |
| Conda 다운로드 archive | 473개, 3,797,856,373bytes. 설치 환경·풀린 package는 보존했고 범위 밖 1개는 남겼다. |
| pip 재생성 cache | 약14.5MB. HF 인증 파일과는 별개다. |
| EOMIS repository 내용 | 할당 크기 32,912,105,472bytes. 전체 Git·비추적 작업·adapter·환경 파일을 암호화 백업한 뒤 제거했다. |
| 로컬 임시 백업 | NAS 전체 hash와 원본 전체 대조를 확인한 뒤 평문 tar·암호문 임시 파일을 제거했다. |
| SSD 여유 | 정리 전 약29GiB → 정리 후 약276GiB. root filesystem 사용량 약600GiB/914GiB, 사용률69%. |

이번 요청의 회수량은 약264.9GB(246.7GiB)다. 앞선 빌드/임시 파일 정리 약22.6GB와
같은 분모로 중복 합산하지 않는다. 디렉터리 할당 크기와 다운로드 파일 길이의 합이며
`df`는 동시 운영 쓰기도 포함하는 시점 값이다.

2026-11-06T16:51:20Z에 EOMIS 내용 제거를 완료했다. 같은 빈 `/home/eom/EOMIS`
디렉터리만 남겼고, 현재 tmux server와 서비스의 sandbox guard를 보존했다. 현재 설치 모델
`/opt/eom/embedding-models`, `/opt/eom-evaluation-models`, `/srv/eom/models`, 운영 wheel/
Conda 환경, PostgreSQL, 원본·Graph·현재/구형 벡터, 기존 인증은 삭제하지 않았다.

### 정식 백업과 감사 Artifact

복구 백업은 다음 immutable pointer로 NAS에 보관했다.

- Artifact: `artifact_361b86a194f24b21b58d812502d50b4f`.
- Revision: `rev_ec57410b8b434d869a0d52f5c48f9ff8`.
- Primary metadata: `backup-manifest.json`; 암호문 member: `legacy-eomis.tar.enc`.
- 암호문 길이: 32,887,869,472bytes.
- 암호문 SHA-256: `822fc440fe50f6f97634c43b96dc8bfcbe99903cef91046f0f114a6d00831cdd`.

NAS 암호문 전체 readback hash와 local tar 대 원본 전체 `tar --compare --numeric-owner`가
모두 PASS한 뒤에만 삭제했다. 암호화 키는 위 root 전용 경로에 보존하며 백업 Artifact에
포함하지 않는다. 현재 호스트에서의 복구 재료 확인과 호스트 전체 유실 복구 검증은 다르다.

정리 감사는 기존 Orchestrator file-set commit과 Catalog exact-member readback을 통과했다.

- Artifact: `artifact_d73f8ee0a5094cb99839ddc921243b41`.
- Revision: `rev_af7a125d55204b8f8b847e098bbdf345`.
- Primary: `retirement-report.json`.
- Primary SHA-256: `08ef02b3bac9c5762cf4cb35d6e67ef0e26085d4e763fa33bec7d751685daba2`.
- Manifest SHA-256: `b503fed3dedda884e66e9b46c0d2883c424e4e33d392d6fa8f0acfac0361fef4`.

이 pointer들은 현재 EOM Artifact storage 아래에 있고, 옛 EOMIS NAS 저장소를 삭제하거나
그 저장소에 임의로 복사하지 않았다. 감사 발행 로그는
`/tmp/eom-legacy-model-retirement-audit-20261106.log`다.

### INDEX 만료와 복구

16:42:01 UTC에 INDEX owner가 `WORKFLOW_CONCURRENCY_CONFLICT` /
`native command expired during current source admission`으로 종료했다. 백업과 겹친
source admission 지연은 관측됐으나, 백업 I/O가 유일한 원인임을 입증한 것은 아니다.
설치 모델/cache 누락 오류는 아니었다. 삭제 전 service-identity guard가 이를 발견해
EOMIS 내용 제거를 멈췄다.

실패 invocation·실행 이력·벡터를 보존하고 실제 남은 수치 작업이 없음을 확인했다.
설치 설정/tool hash 332개가 그대로인 상태에서 지원된 동일 INDEX unit start로 복구했다.
source/model/namespace를 바꾸거나 실패 기록을 성공으로 바꾸지 않았다.

- 이전 PID1123320 / invocation `914eeac595df486c9391927bf8e59262`.
- 16:47:57 UTC 복구 PID1626367 / invocation `67ec9e4eca6e4dd8b4c5ce22b998bbf8`.
- 동일 source `fedb975085d88978e2b468d51ca0f13ddd598d49`.
- 이후 실제 admission/preparation 진행을 확인했다. 전체 임베딩 완료 판정은 아니다.

INDEX owner 복구는 1회다. API/Web/global runner/창작 producer/자료 학습 service는
감사 시점에 기존 PID·InvocationID를 유지했다. API READY와 HTTPS 로그인 화면200,
기존 정기 관측의 지속을 확인했다. 상세는 `index-recovery.json`과 실패·복구 로그에 남겼다.

### 슬롯 재개와 남은 원본 보류

재개 전 canonical Graph 기준 창작 대상은 1,029/1,053건 등록이었다. 남은24건은 변환
출력 미생성6건, 추출 `proposal` 없음12건, worker 실행 실패3건, 과거 Workflow 실패/
Job RUNNING 불일치2건, 분석 실패1건으로 분류했다. producer가 다시 훑는 도중의 일부
hold cache 수를 canonical Graph 완료 수로 대신하지 않았다.

분석 실패1건(고유번호12113)은 공식 predecessor-linked retry를 같은 원본/preset으로
제출했다. 원래 FAILED는 보존했고 임의 row 수정이나 중복 요청을 만들지 않았다.

- 이전 run: `analysisrun_ffeee8bad5624adc8b6610ce15a6302b`.
- 재개 run: `analysisrun_daaa8b93eaf840c98ca02fa0bb1ee5c4`.
- 16:54:52 UTC 실제 유효 lease의 slot03 RUNNING을 확인했다.
- 17:03:16 UTC 공식 reconcile에서 ACCEPTED를 확인했다.
- 동일 retry의 Graph 발행은 bounded one-off controller가 기존
  `CreativeItemGraphLearningService.publish_accepted`를 호출해 이어간다.
  새 model 요청·새 retry는 하지 않으며, Graph 등록 후의 임베딩은 기존 증분 INDEX에 맡긴다.

나머지23건은 위 원본/복구 경계에서 보류한 상태다. 4슬롯 모두 실행 중이거나 전체
1,053건 완료라고 보고하지 않는다. RUNNING이라고 남은 과거 Job 2건도 유효 lease가
없었으며 성공으로 보정하지 않았다. 원래 producer의 옛 analysis-run cache가 재시도
successor를 자동 추적한다는 보장은 없으므로 후속 Graph 등록 결과와 분리해서 본다.

### 검증 범위와 코드 영향

- 모델 content-address/참조 보호 fixtures 6개 PASS: SHA-256·Git blob, 손상 blob,
  외부 symlink·실행 참조 거부 등을 검사했다.
- 합성 입력 OpenSSL 암복호화 roundtrip 및 root key0400 PASS.
- 임시 운영 helper syntax와 실제 설치 API import/source/predecessor 계약 확인 PASS.
- 개발 문맥 navigation tests 13개 PASS. 변경 문서의 링크 대상과 `git diff --check`도 확인했다.
- 새 dependency, DB migration, runtime contract/설치 release 변경은 없다. 운영 DB에
  pytest를 실행하지 않았으며 실제 재개는 기존 application use case만 사용했다.
- 임시 helper·대형 파일·로그·계정/인증 정보는 Git에 넣지 않는다. README·운영 기록·
  개발 탐색 노트만 갱신한다. 문서 commit은 새 runtime 배포나 임베딩 재시작을 요구하지 않는다.
