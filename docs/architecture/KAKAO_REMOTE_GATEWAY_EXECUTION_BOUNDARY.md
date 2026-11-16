# KakaoTalk 원격 gateway 실행 경계

상태: 설치 전 소스 구현. 카카오 로그인·원격 화면·Catalog lease owner·Caddy 연결은 아직
활성화하지 않는다. 정본 요구는 `KAKAO_CHANNEL_ARCHIVE_STUDIO_IMPLEMENTATION_SPEC.md` §11이다.

## 작은 설계 결정

1. 책임은 한 lease의 private WebSocket gateway를 시작하고, 허가가 끝나면 **이미 연결된
   stream까지** 닫는 것이다. browser/profile/AUTO↔MANUAL 전환·현재 사용자 인증은 담당하지 않는다.
2. 정본 허가는 Catalog owner가 현재 session/ADMIN/remote 권한·binding owner·MANUAL fence를
   확인한 뒤 쓰는 `/var/lib/eom-kakao-runtime/remote/grant.json`이다. 공개 DTO나 worker 주장을
   이 파일로 받지 않는다. 이 파일의 실제 publisher와 persistent lease는 후속 owner 구현이다.
3. 기존 `GatewayLeaseGrant`/`GatewayRevocation` schema를 그대로 사용한다. lease ID,
   source binding/profile ID, fence/gateway epoch, grant revision을 구분한다. 경로는 identity가 아니다.
4. 매 읽기는 no-follow parent walk, Catalog UID 소유·권한·regular file·단일 link·최대 4 KiB를
   검사한다. 원자적 replace는 완전한 이전/다음 grant만 보이게 한다. 잘못된 JSON·누락·stale
   revision·다른 epoch·만료는 닫힘이다. grant에는 cookie/token/operator session/임의 경로가 없다.
5. 접근은 고정 파일 하나와 현재 lease 하나의 O(1) 조회다. 100 ms watchdog, 30초 TTL과 최초
   발행부터 최대 20분 한계를 UTC와 monotonic deadline으로 함께 검사한다. 동일 grant 재읽기는
   시간을 연장하지 않고, UTC 역행이나 늦은 renewal도 종료된 lease를 살리지 않는다.
6. 기존 mutable `RemoteGatewayLifetime`을 미배포 PDF worker에서 별도 gateway의 `lifetime.py`로
   이동한다. 별도 registry/queue/DB/cache를 만들지 않는다. immutable 원격 계약은 contracts에 둔다.
7. scale은 현재 browser profile에 해당하는 gateway 1개다. 메모리는 grant 4 KiB와 고정 runtime
   metadata뿐이다. 정적 noVNC 파일은 설치된 read-only release에서 제공하며 매 heartbeat 복사하지 않는다.
8. owner는 grant를 원자 교체하고 gateway만 읽는다. supervisor는 own child session/process group을
   종료한다. systemd `KillMode=control-group`, `SendSIGKILL=yes`, `Restart=no`가 descendant까지
   정리한다. supervisor는 cgroup-empty receipt를 만들지 않는다. 다음 실행 전 실제 unit/cgroup
   종료 확인은 owner 책임이며 단순 socket unlink/child exit를 그 증거로 쓰지 않는다.
9. gateway wheel → contracts 의존만 기본으로 두고, 실행 extras에 `websockify==0.13.0`을 고정한다.
   PyMuPDF/Pillow/collector/DB/API를 의존하지 않는다. 신규 의존 이유는 검증된 UDS→UDS WebSocket
   변환이며 기존 API 환경에 설치하지 않는다. Python 코드 자체에 HTTP/WebSocket 서버를 구현하지 않는다.
10. grant 상실·회수·오류·child 종료 시 전체 owned group에 TERM 후 bounded KILL하고 종료한다.
    자동 재시작·새 epoch 추정·임의 stale socket 삭제는 없다. process leader는 group 종료 전 reaping하지
    않아 PID 재사용으로 다른 process group을 죽이는 일을 피한다. 사후 owner가 실패 원인을 판정한다.
11. 더 단순한 listener 삭제만으로는 이미 열린 WebSocket이 유지된다. 반대로 별도 인증 서버·범용
    실행 framework는 필요 없다. 작은 owner grant reader + 기존 lifetime + OS supervisor로 한정한다.

## 고정 설치 경계

- UID `eom-kakao-remote`, browser `eom-kakao` 및 Caddy와 다른 UID. 기존 `eom`/`caddy` 그룹 금지.
- listener `/run/eom-kakao-remote/gateway.sock` 0660, proxy group `eom-kakao-proxy`.
- target `/run/eom-kakao-vnc/vnc.sock` 0660, VNC group `eom-kakao-vnc`.
- grant directory Catalog owner만 쓰기, gateway는 전용 read group으로 읽기만 한다.
- interpreter `/opt/eom/conda/envs/eom-kakao-remote/bin/python`; root-installed noVNC 1.6.0
  `/opt/eom/kakao-remote/releases/novnc-1.6.0/noVNC`. 실행/자산 inventory·hash는 실제 설치 gate다.
- noVNC directory에는 release 정적 파일만 둔다. profile·NAS·capture·credentials는 접근 금지.
- TCP listener/target, `--libserver`, `--daemon`, 사용자 argv, URL bearer, 기록/traffic logging은 없다.
- upstream `websockify` 0.13.0의 `--unix-listen`, `--unix-listen-mode`, `--unix-target`, `--web`
  지원과 Unix listener의 TCP 옵션 우회는 [공식 소스](https://github.com/novnc/websockify/blob/v0.13.0/websockify/websocketproxy.py)로 확인했다.
  자식 연결 프로세스는 [server 구현](https://github.com/novnc/websockify/blob/v0.13.0/websockify/websockifyserver.py)에 근거해 함께 종료한다.
  noVNC는 [1.6.0 license와 포함 license](https://github.com/novnc/noVNC/blob/v1.6.0/LICENSE.txt)를 함께 설치해야 한다.
  distro websockify 0.10은 Unix listener를 지원하지 않으므로 대체 설치로 인정하지 않는다.

## 검증과 남은 경계

실제 local child/accepted UDS stream 종료, grant replay/rollback/expiry/old epoch,
owner/file/symlink/oversize 차단과 isolated wheel을 source 검증한다. 이는 실제 카카오 로그인이나
systemd UID/Caddy 인증·WebSocket 업그레이드·noVNC 시각 검증을 대신하지 않는다.
후속 설치는 root-owned release 전체와 directory group 권한을 확인하고, Catalog owner가 실제
session/fence에서 grant를 만들며, Caddy auth가 cookie/authorization을 gateway로 전달하지 않음을
증명한 후에만 활성화한다. browser profile 전환/lock은 기존 browser owner 경계를 그대로 사용한다.
`After`/`BindsTo`는 browser가 준비된 VNC 화면을 제공한다는 증거가 아니다. owner는 보호된 실제
현재 MANUAL fence를 확인하고, gateway UID가 실제 VNC socket 준비를 확인해 READY가 된 뒤에만
원격 화면을 열어야 한다. unit 파일 설치 자체는 원격 화면 사용 가능의 증거가 아니다.

## Catalog owner가 사용할 고정 OS adapter

`FixedKakaoGatewayRuntime`은 `kakao_gateway_runtime.py`에 둔다. DB/권한 엔진이 아니며
Catalog UID만 고정 control lock 아래에서 실행한다. owner는 immutable dispatch intent를
먼저 보존하고 `boot_identity()`를 함께 기록한다. 공개 request나 worker 결과를 handle로 받지 않는다.

- `start(grant, browser, prior, assert_current, observe_browser)`는 이전 unit의 Job 부재와
  cgroup closure를 새로 확인하고, 새 lease/epoch와 **현재 MANUAL browser handle**을 검사한다.
  현재 권한 callback 뒤 canonical grant를 원자 발행한다.
- `observe_dispatch(grant, dispatched_boot_id)`는 timeout 후 재실행 없이 원래 실행을 조회한다.
  READY 이전 실패/재부팅은 물리적으로 닫혔다는 결과일 뿐 로그인 성공·profile flush가 아니다.
- `renew(run, grant, browser, ...)`는 같은 immutable 실행 identity와 증가한 grant revision을
  유지한다. 현재 grant가 이미 만료/회수되면 재생시키지 않는다. 동일 값 replay는 재발행하지 않는다.
- `stop(run, revocation)`은 같은 실행에 회수를 발행하고 fixed unit을 중단한다. 완료는 Job 없음과
  같은 invocation의 종료·전체 cgroup closure로 확인한다. systemctl timeout만으로 종료를 선언하지 않는다.

gateway는 `Type=notify`이며 실제 VNC peer UID/고정 browser cgroup membership과 자식의 UDS
listener 준비, 현재 grant 유효성을 확인했을 때만 READY를
낸다. STATUS는 `gateway_execution_digest()`로 계산한 immutable lease identity다. heartbeat의
revision/authorized_at/expires_at은 identity에서 제외하되 기존 watchdog이 계속 검사한다.
미리 READY가 된 browser를 VNC 준비 완료로 간주하거나, 살아 있는 다른 gateway epoch를 인계하지 않는다.
Catalog는 VNC 그룹에 들어가지 않으며 raw VNC에 연결하지 않는다. gateway는 ProtectProc를
완화하지 않고 root-owned 고정 `cgroup.procs`를 읽어 커널의 peer PID 소속을 확인한다.

두 fixed-unit adapter의 보호 파일·boot·systemd show·cgroup 읽기는 작은 public
`kakao_runtime_os.py`를 공유한다. 실행 상태·profile·lease 규칙은 각 adapter에 남긴다.
원자 발행은 작은 schema-validated grant/revocation 한 개만 저장한다. 부분 staging은 명시적
불확실 상태로 남기며, 같은 bytes가 완성돼 있는 경우만 원래 발행을 이어간다. 이 파일은 영구
lease/감사 DB의 대체물이 아니다. 설치 publisher·Caddy forward-auth·실제 session gate는 별도다.
