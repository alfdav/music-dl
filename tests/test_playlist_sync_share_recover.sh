#!/usr/bin/env bash
# Exercises scripts/playlist_sync_share_recover.sh with PATH shims.
# No network and no real mounts. Timeouts stay at 1s so a hang cannot last.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="${ROOT}/scripts/playlist_sync_share_recover.sh"
PASS_MARK="pwexample"
SHARE_URL="smb://exampleuser@nas.example/share"
HANG_SECS=30

pass() { printf 'ok - %s\n' "$1"; }
fail() {
  printf 'not ok - %s\n' "$1" >&2
  if [ -n "${STDOUT:-}" ]; then
    printf 'stdout: %s\n' "${STDOUT}" >&2
  fi
  if [ -n "${STDERR:-}" ]; then
    printf 'stderr: %s\n' "${STDERR}" >&2
  fi
  if [ -n "${CALLS:-}" ]; then
    printf 'calls:\n%s\n' "${CALLS}" >&2
  fi
  exit 1
}

assert_eq() {
  local got="$1" expected="$2" label="$3"
  [ "${got}" = "${expected}" ] || fail "${label} (got=${got} expected=${expected})"
  pass "${label}"
}

assert_contains() {
  local haystack="$1" needle="$2" label="$3"
  case "${haystack}" in
    *"${needle}"*) pass "${label}" ;;
    *) fail "${label} (missing=${needle})" ;;
  esac
}

[ -f "${SCRIPT}" ] || fail "missing helper: ${SCRIPT}"
[ -x "${SCRIPT}" ] || fail "helper is not executable"
bash -n "${SCRIPT}"
pass "helper parses"

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
BIN="${TMP}/bin"
STATE="${TMP}/state"
CALL_LOG="${STATE}/calls"
MP="${TMP}/mountpoint"
LIB="${BIN}/lib.sh"
mkdir -p "${BIN}" "${STATE}"

now_ms() {
  if [ -n "${EPOCHREALTIME:-}" ]; then
    local t="${EPOCHREALTIME}"
    t="${t/./}"
    printf '%s\n' "${t%???}"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import time; print(int(time.time() * 1000))'
    return 0
  fi
  perl -MTime::HiRes=time -e 'printf "%d\n", time()*1000'
}

cat >"${LIB}" <<'EOF'
log_call() {
  local name="$1"
  shift
  local arg
  printf '%s' "${name}" >>"${CALL_LOG:?}"
  for arg in "$@"; do
    printf ' [%s]' "${arg}" >>"${CALL_LOG}"
  done
  printf '\n' >>"${CALL_LOG}"
}

remove_mountpoint() {
  local target="$1"
  local line tmp table
  table="${STATE:?}/mount.table"
  tmp="${STATE}/mount.table.tmp"
  : >"${tmp}"
  if [ -f "${table}" ]; then
    while IFS= read -r line || [ -n "${line}" ]; do
      case "${line}" in
        *" on ${target} ("*) ;;
        *) printf '%s\n' "${line}" >>"${tmp}" ;;
      esac
    done <"${table}"
  fi
  mv "${tmp}" "${table}"
}
EOF

install_shim() {
  local name="$1"
  {
    printf '#!/usr/bin/env bash\nset -u\n. %q\n' "${LIB}"
    cat
  } >"${BIN}/${name}"
  chmod +x "${BIN}/${name}"
}

install_shim mount <<'EOF'
log_call mount "$@"
if [ -f "${STATE}/mount.table" ]; then
  cat "${STATE}/mount.table"
fi
exit 0
EOF

install_shim ls <<'EOF'
log_call ls "$@"
n=0
if [ -f "${STATE}/ls.count" ]; then
  n="$(cat "${STATE}/ls.count")"
fi
n=$((n + 1))
printf '%s\n' "${n}" >"${STATE}/ls.count"
mode=""
if [ -f "${STATE}/ls.mode.${n}" ]; then
  mode="$(cat "${STATE}/ls.mode.${n}")"
elif [ -f "${STATE}/ls.mode.default" ]; then
  mode="$(cat "${STATE}/ls.mode.default")"
fi
case "${mode}" in
  ok) exit 0 ;;
  tcc)
    printf '%s\n' "ls: Operation not permitted" >&2
    exit 1
    ;;
  fail)
    printf '%s\n' "ls: Input/output error" >&2
    exit 2
    ;;
  hang) exec sleep 30 ;;
  *)
    printf '%s\n' "ls shim bad mode" >&2
    exit 99
    ;;
esac
EOF

install_shim diskutil <<'EOF'
log_call diskutil "$@"
if [ "${1:-}" != "unmount" ] || [ "${2:-}" != "force" ] || [ -z "${3:-}" ]; then
  printf '%s\n' "unexpected diskutil args" >&2
  exit 97
fi
printf '%s\n' "diskutil saw //exampleuser@nas.example/share" >&2
rc="0"
if [ -f "${STATE}/diskutil.rc" ]; then
  rc="$(cat "${STATE}/diskutil.rc")"
fi
if [ "${rc}" != "0" ]; then
  exit "${rc}"
fi
remove_mountpoint "${3}"
exit 0
EOF

install_shim umount <<'EOF'
log_call umount "$@"
if [ "${1:-}" != "-f" ] || [ -z "${2:-}" ]; then
  printf '%s\n' "unexpected umount args" >&2
  exit 96
fi
printf '%s\n' "umount saw //exampleuser@nas.example/share" >&2
rc="0"
if [ -f "${STATE}/umount.rc" ]; then
  rc="$(cat "${STATE}/umount.rc")"
fi
if [ "${rc}" != "0" ]; then
  exit "${rc}"
fi
remove_mountpoint "${2}"
exit 0
EOF

install_shim osascript <<'EOF'
log_call osascript "$@"
if [ -f "${STATE}/osascript.sleep" ]; then
  exec sleep 30
fi
if [ -f "${STATE}/osascript.stdout" ]; then
  cat "${STATE}/osascript.stdout"
fi
if [ -f "${STATE}/osascript.stderr" ]; then
  cat "${STATE}/osascript.stderr" >&2
fi
rc="0"
if [ -f "${STATE}/osascript.rc" ]; then
  rc="$(cat "${STATE}/osascript.rc")"
fi
if [ "${rc}" != "0" ]; then
  exit "${rc}"
fi
if [ -f "${STATE}/osascript.mount" ]; then
  cat "${STATE}/osascript.mount" >"${STATE}/mount.table"
fi
exit 0
EOF

install_shim security <<'EOF'
log_call security "$@"
for arg in "$@"; do
  case "${arg}" in
    -w | -g) exit 3 ;;
  esac
done
printf '%s\n' "acct: exampleuser svce: nas.example"
if [ -f "${STATE}/security.missing" ]; then
  exit 44
fi
if [ -f "${STATE}/security.hang" ]; then
  exec sleep 30
fi
exit 0
EOF

install_shim timeout <<'EOF'
log_call timeout "$@"
printf '%s\n' "external timeout must not be used" >&2
exit 99
EOF

write_mount_at() {
  local path="$1"
  local dest="${2:-${STATE}/mount.table}"
  printf '%s\n' "//exampleuser@nas.example/share on ${path} (smbfs, nodev, nosuid)" >"${dest}"
}

set_ls() {
  printf '%s\n' "$2" >"${STATE}/ls.mode.$1"
}

arm_remount_at() {
  local path="$1"
  printf '%s\n' "${path}" >"${STATE}/osascript.stdout"
  write_mount_at "${path}" "${STATE}/osascript.mount"
}

reset_state() {
  : >"${CALL_LOG}"
  rm -f \
    "${STATE}/ls.count" \
    "${STATE}/ls.mode.default" \
    "${STATE}/ls.mode.1" \
    "${STATE}/ls.mode.2" \
    "${STATE}/ls.mode.3" \
    "${STATE}/diskutil.rc" \
    "${STATE}/umount.rc" \
    "${STATE}/osascript.sleep" \
    "${STATE}/osascript.rc" \
    "${STATE}/osascript.stdout" \
    "${STATE}/osascript.stderr" \
    "${STATE}/osascript.mount" \
    "${STATE}/security.missing" \
    "${STATE}/security.hang"
  URL="${SHARE_URL}"
  PROBE_TIMEOUT=1
  UNMOUNT_TIMEOUT=1
  REMOUNT_TIMEOUT=1
  write_mount_at "${MP}"
  arm_remount_at "${MP}"
}

count_cmd() {
  local name="$1"
  local n=0 line first
  while IFS= read -r line || [ -n "${line}" ]; do
    first="${line%% *}"
    if [ "${first}" = "${name}" ]; then
      n=$((n + 1))
    fi
  done <"${CALL_LOG}"
  printf '%s\n' "${n}"
}

count_diskutil_unmount() {
  local n=0 line
  while IFS= read -r line || [ -n "${line}" ]; do
    case "${line}" in
      "diskutil [unmount] "*) n=$((n + 1)) ;;
    esac
  done <"${CALL_LOG}"
  printf '%s\n' "${n}"
}

run_helper() {
  local log="${STATE}/share.log"
  local err="${STATE}/script.err"
  local start end
  : >"${log}"
  : >"${err}"
  start="$(now_ms)"
  set +e
  STDOUT="$(
    PATH="${BIN}:${PATH}" \
      STATE="${STATE}" \
      CALL_LOG="${CALL_LOG}" \
      MUSIC_DL_SHARE_MOUNTPOINT="${MP}" \
      MUSIC_DL_SHARE_URL="${URL}" \
      MUSIC_DL_SHARE_PROBE_TIMEOUT="${PROBE_TIMEOUT}" \
      MUSIC_DL_SHARE_KEYCHAIN_TIMEOUT=1 \
      MUSIC_DL_SHARE_UNMOUNT_TIMEOUT="${UNMOUNT_TIMEOUT}" \
      MUSIC_DL_SHARE_REMOUNT_TIMEOUT="${REMOUNT_TIMEOUT}" \
      MUSIC_DL_SHARE_LOG="${log}" \
      "${SCRIPT}" \
      2>"${err}"
  )"
  STATUS=$?
  set -e
  end="$(now_ms)"
  ELAPSED_MS=$((end - start))
  LOG="$(cat "${log}")"
  STDERR="$(cat "${err}")"
  CALLS="$(cat "${CALL_LOG}")"
}

assert_common() {
  local label="$1"
  local needle blob
  case "${STDOUT}" in
    *$'\n'*) fail "${label}: more than one stdout line" ;;
  esac
  case "${STDOUT}" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]\ [0-9][0-9]:[0-9][0-9]:[0-9][0-9]\ *\ share-recover:*) ;;
    *) fail "${label}: summary format (${STDOUT})" ;;
  esac
  [ "${STDOUT}" = "${LOG}" ] || fail "${label}: stdout and log differ"
  [ -z "${STDERR}" ] || fail "${label}: stderr not empty (${STDERR})"
  [ "${ELAPSED_MS}" -lt 8000 ] || fail "${label}: too slow (${ELAPSED_MS}ms, shim sleep is ${HANG_SECS}s)"
  blob="${STDOUT}${LOG}${STDERR}"
  for needle in exampleuser nas.example "smb://" "${PASS_MARK}"; do
    case "${blob}" in
      *"${needle}"*) fail "${label}: leaked ${needle}" ;;
    esac
  done
  case "${CALLS}" in
    *"[-w]"* | *"[-g]"*) fail "${label}: security read a secret" ;;
  esac
  pass "${label}: summary, timing, and redaction"
}

assert_count() {
  local name="$1" expected="$2" label="$3" got
  got="$(count_cmd "${name}")"
  assert_eq "${got}" "${expected}" "${label}"
}

assert_security_query() {
  local label="$1"
  local expected="security [find-internet-password] [-r] [smb ] [-s] [nas.example] [-a] [exampleuser]"
  case "${CALLS}" in
    *"${expected}"*) pass "${label}" ;;
    *) fail "${label} (calls=${CALLS})" ;;
  esac
}

assert_osascript_url() {
  local label="$1"
  local expected="osascript [-e] [mount volume \"${URL}\"]"
  case "${CALLS}" in
    *"${expected}"*) pass "${label}" ;;
    *) fail "${label} (calls=${CALLS})" ;;
  esac
}

assert_hang_window() {
  local label="$1"
  if [ "${ELAPSED_MS}" -lt 500 ] || [ "${ELAPSED_MS}" -ge 6000 ]; then
    fail "${label} (elapsed_ms=${ELAPSED_MS}, shim sleeps ${HANG_SECS}s)"
  fi
  pass "${label} (${ELAPSED_MS}ms)"
}

# Healthy listing: no recovery tools.
reset_state
set_ls 1 ok
run_helper
assert_eq "${STATUS}" "0" "healthy exits 0"
assert_contains "${LOG}" "listing ok" "healthy says listing ok"
assert_contains "${LOG}" "share-recover:" "healthy log tag"
assert_common "healthy"
assert_count ls 1 "healthy probes once"
assert_count diskutil 0 "healthy skips diskutil"
assert_count osascript 0 "healthy skips osascript"
assert_count umount 0 "healthy skips umount"
assert_count security 0 "healthy skips security"
assert_count timeout 0 "healthy skips timeout"
case "${CALLS}" in
  *"ls [-A] [${MP}]"*) pass "healthy lists the mountpoint" ;;
  *) fail "healthy did not list the mountpoint" ;;
esac

# Not an smbfs mount at the configured path.
reset_state
{
  printf '%s\n' "/dev/disk0s1 on / (apfs, local, read-only)"
  printf '%s\n' "//exampleuser@nas.example/share on /path/to/other (smbfs, nodev, nosuid)"
} >"${STATE}/mount.table"
run_helper
assert_eq "${STATUS}" "10" "not mounted exits 10"
assert_contains "${LOG}" "not mounted" "not mounted explains why"
assert_common "not mounted"
assert_count ls 0 "not mounted does not list"
assert_count diskutil 0 "not mounted skips diskutil"
assert_count osascript 0 "not mounted skips osascript"
assert_count umount 0 "not mounted skips umount"
assert_count security 0 "not mounted skips security"
assert_count mount 1 "not mounted only consults mount"

# Permission error is not a stale session.
reset_state
set_ls 1 tcc
run_helper
assert_eq "${STATUS}" "11" "permission error exits 11"
assert_contains "${LOG}" "listing not permitted" "permission error explains why"
assert_common "permission"
assert_count ls 1 "permission error probes once"
assert_count diskutil 0 "permission error skips diskutil"
assert_count umount 0 "permission error skips umount"
assert_count osascript 0 "permission error skips osascript"
assert_count security 0 "permission error skips security"

# Stale listing, one unmount, one remount, listing recovers.
reset_state
set_ls 1 fail
set_ls 2 ok
run_helper
assert_eq "${STATUS}" "0" "stale recovery exits 0"
assert_contains "${LOG}" "remount ok" "stale recovery logs remount ok"
assert_contains "${LOG}" "unmount=diskutil:0" "stale recovery records unmount"
assert_contains "${LOG}" "remount=osascript:0" "stale recovery records remount"
assert_common "stale recovery"
assert_count ls 2 "stale recovery probes twice"
assert_eq "$(count_diskutil_unmount)" "1" "stale recovery unmounts once"
assert_count osascript 1 "stale recovery remounts once"
assert_count umount 0 "stale recovery does not fall back"
assert_count security 1 "stale recovery checks the keychain once"
assert_security_query "stale recovery keychain query has no secret flag"
assert_osascript_url "stale recovery passes the url only to osascript"

# Remount lands, but the second listing still hangs.
reset_state
set_ls 1 fail
set_ls 2 hang
run_helper
assert_eq "${STATUS}" "20" "second hang exits 20"
assert_contains "${LOG}" "unmount=diskutil:0" "second hang records unmount"
assert_contains "${LOG}" "remount=osascript:0" "second hang records remount"
assert_contains "${LOG}" "probe=timeout" "second hang records probe"
assert_common "second hang"
assert_hang_window "second hang returns inside the probe timeout"
assert_count ls 2 "second hang probes twice"
assert_eq "$(count_diskutil_unmount)" "1" "second hang unmounts once"
assert_count osascript 1 "second hang remounts once"
assert_count umount 0 "second hang does not fall back"

# diskutil unmount fails once; umount -f is the single fallback.
reset_state
set_ls 1 fail
set_ls 2 ok
printf '%s\n' "1" >"${STATE}/diskutil.rc"
run_helper
assert_eq "${STATUS}" "0" "umount fallback still recovers"
assert_contains "${LOG}" "remount ok" "umount fallback logs remount ok"
assert_contains "${LOG}" "diskutil:1,umount:0" "umount fallback records both results"
assert_common "umount fallback"
assert_eq "$(count_diskutil_unmount)" "1" "umount fallback tries diskutil once"
assert_count umount 1 "umount fallback runs once"
assert_count osascript 1 "umount fallback remounts once"
assert_count ls 2 "umount fallback probes twice"
case "${CALLS}" in
  *"umount [-f] [${MP}]"*) pass "umount fallback uses -f on the mountpoint" ;;
  *) fail "umount fallback args were wrong" ;;
esac

# No saved login: do not unmount.
reset_state
set_ls 1 fail
: >"${STATE}/security.missing"
run_helper
assert_eq "${STATUS}" "21" "missing login exits 21"
assert_contains "${LOG}" "no saved login; remount would prompt" "missing login explains why"
assert_common "missing login"
assert_count ls 1 "missing login probes once"
assert_count security 1 "missing login checks the keychain once"
assert_count diskutil 0 "missing login does not unmount"
assert_count umount 0 "missing login does not fall back"
assert_count osascript 0 "missing login does not remount"
assert_security_query "missing login keychain query has no secret flag"

# Keychain lookup blocks (locked keychain, unlock dialog). Fail fast, no unmount.
reset_state
set_ls 1 fail
: >"${STATE}/security.hang"
run_helper
assert_eq "${STATUS}" "21" "keychain hang exits 21"
assert_contains "${LOG}" "keychain lookup timed out" "keychain hang names the timeout"
assert_common "keychain hang"
assert_hang_window "keychain hang returns inside the keychain timeout"
assert_count diskutil 0 "keychain hang does not unmount"
assert_count umount 0 "keychain hang does not fall back"
assert_count osascript 0 "keychain hang does not remount"

# Remount blocks (auth dialog). Fail fast inside REMOUNT_TIMEOUT.
reset_state
set_ls 1 fail
: >"${STATE}/osascript.sleep"
run_helper
assert_eq "${STATUS}" "21" "remount hang exits 21"
assert_contains "${LOG}" "remount timed out (auth prompt likely)" "remount hang names the timeout"
assert_common "remount hang"
assert_hang_window "remount hang returns inside the remount timeout"
assert_count ls 1 "remount hang does not probe again"
assert_eq "$(count_diskutil_unmount)" "1" "remount hang unmounts once"
assert_count osascript 1 "remount hang tries osascript once"
assert_count umount 0 "remount hang does not fall back"

# A hung probe still gets exactly one recovery afterwards.
reset_state
set_ls 1 hang
set_ls 2 ok
run_helper
assert_eq "${STATUS}" "0" "probe hang then recovery exits 0"
assert_contains "${LOG}" "remount ok" "probe hang then recovery logs remount ok"
assert_common "probe hang"
assert_hang_window "probe hang returns inside the probe timeout"
assert_count ls 2 "probe hang probes twice"
assert_eq "$(count_diskutil_unmount)" "1" "probe hang unmounts once"
assert_count osascript 1 "probe hang remounts once"

# Password in the URL is refused before any tool runs.
reset_state
set_ls 1 ok
URL="smb://exampleuser:${PASS_MARK}@nas.example/share"
run_helper
assert_eq "${STATUS}" "21" "password url exits 21"
assert_contains "${LOG}" "bad config: password in share url" "password url explains why"
assert_common "password url"
assert_eq "$(wc -c <"${CALL_LOG}" | tr -d ' ')" "0" "password url calls nothing"

# osascript lands on a different volume path. Unmount that stray once.
reset_state
set_ls 1 fail
set_ls 2 ok
arm_remount_at "${MP}-1"
run_helper
assert_eq "${STATUS}" "20" "stray volume exits 20"
assert_contains "${LOG}" "different volume path" "stray volume is logged"
assert_common "stray volume"
assert_count ls 1 "stray volume does not probe again"
assert_eq "$(count_diskutil_unmount)" "2" "stray volume unmounts the share and the stray"
assert_count osascript 1 "stray volume remounts once"
assert_count umount 0 "stray volume does not fall back"
case "${CALLS}" in
  *"diskutil [unmount] [force] [${MP}-1]"*) pass "stray volume unmounts the returned path" ;;
  *) fail "stray volume did not unmount the returned path" ;;
esac

# osascript returns an alias, not a path. A new smbfs mount is the stray.
reset_state
set_ls 1 fail
printf '%s\n' "file nas:share" >"${STATE}/osascript.stdout"
write_mount_at "${MP}-1" "${STATE}/osascript.mount"
run_helper
assert_eq "${STATUS}" "20" "alias stray exits 20"
assert_contains "${LOG}" "different volume path" "alias stray is logged"
assert_common "alias stray"
assert_count ls 1 "alias stray does not probe again"
assert_eq "$(count_diskutil_unmount)" "2" "alias stray unmounts the share and the new mount"
assert_count osascript 1 "alias stray remounts once"
case "${CALLS}" in
  *"diskutil [unmount] [force] [${MP}-1]"*) pass "alias stray unmounts the new mountpoint" ;;
  *) fail "alias stray did not unmount the new mountpoint" ;;
esac

# osascript failure text that echoes the URL is stripped before logging.
reset_state
set_ls 1 fail
printf '%s\n' "1" >"${STATE}/osascript.rc"
printf '%s\n' "failed ${SHARE_URL} //exampleuser@nas.example leftover" >"${STATE}/osascript.stderr"
rm -f "${STATE}/osascript.mount" "${STATE}/osascript.stdout"
run_helper
assert_eq "${STATUS}" "20" "remount error exits 20"
assert_contains "${LOG}" "osascript:1:failed leftover" "remount error keeps the safe words"
assert_contains "${LOG}" "unmount=" "remount error records unmount"
assert_contains "${LOG}" "probe=" "remount error records probe"
assert_common "remount error"
assert_count osascript 1 "remount error tries osascript once"
assert_eq "$(count_diskutil_unmount)" "1" "remount error unmounts once"
assert_count ls 1 "remount error does not probe again"

pass "playlist share recover tests"
