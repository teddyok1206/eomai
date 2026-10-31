# 설치 인증 provider의 폴더 identity

## 장애와 재현

`webreq_248233cb9ea34845b0925596`의 유사도 요청은 API의 검색 준비 단계에서
`REFERENCE_QUERY_PREPARE_UNAVAILABLE`로 종료됐다. 운영 provider의 현재 파일·wheel·unit
검사는 PASS였고 삭제된 FD도 없었다. 반면 장기 실행 QUERY가 보관한 code 폴더들은 기동 후
mtime/ctime이 바뀌어 있었다. 기존 `_check_file`은 폴더의 전체 file epoch까지 비교했다.
임시 파일/FD 단위 검사에서도 **대상 파일이 아닌 형제 파일 하나를 추가하는 것만으로**
같은 `OWNER_SESSION_PROVIDER_UNAVAILABLE`이 재현됐다. 원본 실패 로그는 보존한다.

## 책임과 최소 수정

- 기존 설치 provider observation adapter의 invalidation 범위만 바로잡는다. 새 인증 경로,
  session 저장, 토큰 발급, principal 확대, DB/queue/schema 변경은 없다.
- 정본은 설치된 API의 exact source/wheel/configuration/code SHA와 현재 systemd process/birth다.
  열린 파일 FD와 논리 경로는 이를 확인하는 일시적 witness이지 별도 권한이 아니다.
- 대상 파일은 기존 full epoch(dev/inode/uid/gid/mode/nlink/size/mtime/ctime), named path,
  SHA, 정규 파일·link 수·읽기 모드·owner/permission을 계속 고정한다.
- 부모 폴더는 **dev/inode/uid/gid/mode**로 identity를 고정한다. 열린 parent FD와 현재 named
  parent 경로를 모두 대조한다. 형제 항목의 추가·삭제에 변하는 nlink/size/mtime/ctime은
  그 폴더의 identity가 아니므로 파일 권한과 함께 묶어 무효화하지 않는다.
- key witness는 여전히 O_PATH metadata-only이며 key bytes를 열거나 읽지 않는다.
  capture HMAC/nonce/deadline/실제 operator/current authorization 규칙은 그대로다.

## 구조·검증·배포

고정12개 code pointer와 config/key pointer를 순회하는 기존 O(N) 검사 그대로다. 새로운
캐시나 영속 모델은 없다. 양성 검사(형제 생성/삭제)와 음성 검사(파일 교체·내용 변경·named
parent 교체·symlink·권한 변경·PID/InvocationID 변경)를 함께 실행한다. 단순 예외 무시나
인증 검사 삭제는 대안이 아니다. 동일 버전 재기동으로 현재 witness를 새로 잡는 긴급 복구와,
설치 wheel/compatible release의 영구 수정은 구분한다.

## 실제 privilege-drop 검증에서 확인한 보완

첫 호환 배포의 API health는 PASS였지만 QUERY child는 private API configuration의 named
file을 `lstat`하려다 권한 거부됐다. `/etc/eom-api`를 새로 개방하거나 worker 그룹을
늘리지 않는다. root가 전달한 읽기 전용 FD의 full epoch/link/name/hash와 held/named 부모
identity는 유지하고, CONFIGURATION만 inaccessible named file 재조회에 의존하지 않는다.
교체·이동·삭제는 held FD의 link 수와 `/proc/self/fd`의 현재 이름 및 hash로 거부한다.
CODE와 KEY_METADATA는 기존 named target 확인도 유지한다. 정상 root 검사뿐 아니라
실제 dropped UID/GID 및 supplementary groups 없음 조건을 별도 운영 preflight로 확인한다.
