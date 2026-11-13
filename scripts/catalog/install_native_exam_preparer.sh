#!/usr/bin/env bash
set -euo pipefail

# Install only the reviewed fixed unit/polkit rule. Do not start work or alter worker/DB pins.
readonly SCRIPT_DIRECTORY=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
readonly REPOSITORY=$(cd -- "${SCRIPT_DIRECTORY}/../.." && pwd)
readonly UNIT=eom-native-exam-preparer@.service
readonly RULE=45-eom-native-exam-preparer.rules
readonly DROPIN=/etc/systemd/system/eom-native-exam-preparer@.service.d/installed-release.conf

fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }
[[ $(id -u) == 0 ]] || fail 'Native exam unit installation requires root'
[[ $# == 2 && $1 == --tool-python ]] || fail 'usage: install_native_exam_preparer.sh --tool-python /absolute/protected/runtime/bin/python'
readonly TOOL_PYTHON=$2
[[ ${TOOL_PYTHON} =~ ^/[A-Za-z0-9_./-]+$ && -x ${TOOL_PYTHON} ]] || fail 'Native exam Python is invalid'

# Keep the lexical venv path while validating its resolved executable and every parent.
"${TOOL_PYTHON}" -I -B -c '
import os,pathlib,stat,sys
p=pathlib.Path(sys.argv[1]); r=p.resolve(strict=True)
m=p.lstat(); t=r.stat()
assert m.st_uid==m.st_gid==0 and (stat.S_ISLNK(m.st_mode) or (stat.S_ISREG(m.st_mode) and not m.st_mode&0o022))
assert stat.S_ISREG(t.st_mode) and t.st_uid==t.st_gid==0 and not t.st_mode&0o022
assert os.access(r,os.X_OK)
for d in {*p.parents,*r.parents}:
 m=d.lstat(); assert stat.S_ISDIR(m.st_mode) and m.st_uid==m.st_gid==0 and not m.st_mode&0o022
import eom_hwpx_builder.native_exam_tool
' "${TOOL_PYTHON}"

install -d -o eom-catalog-manager -g eom-api -m 0700 /var/lib/eom-catalog-api/staging/native-exam
install -o root -g root -m 0644 "${REPOSITORY}/infra/systemd/${UNIT}" "/etc/systemd/system/${UNIT}"
install -o root -g root -m 0644 "${REPOSITORY}/infra/polkit/${RULE}" "/etc/polkit-1/rules.d/${RULE}"
install -d -o root -g root -m 0755 /etc/systemd/system/eom-native-exam-preparer@.service.d
staged_dropin=$(mktemp)
trap 'rm -f -- "${staged_dropin}"' EXIT
sed "s|@NATIVE_EXAM_TOOL_PYTHON@|${TOOL_PYTHON}|g" \
  "${REPOSITORY}/infra/systemd/eom-native-exam-preparer-installed-release.conf.in" >"${staged_dropin}"
install -o root -g root -m 0644 "${staged_dropin}" "${DROPIN}"
systemd-analyze verify "/etc/systemd/system/${UNIT}"
systemctl daemon-reload
printf 'native_exam_preparer=INSTALLED\nunit=%s\ntool_python=%s\n' "${UNIT}" "${TOOL_PYTHON}"
