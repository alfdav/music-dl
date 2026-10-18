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
CANON_MP="${MP}"
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
n=0
if [ -f "${STATE}/mount.count" ]; then
  n="$(cat "${STATE}/mount.count")"
fi
n=$((n + 1))
printf '%s\n' "${n}" >"${STATE}/mount.count"
if [ -f "${STATE}/mount.hang_after" ]; then
  after="$(cat "${STATE}/mount.hang_after")"
  if [ "${n}" -ge "${after}" ]; then
    exec sleep 30
  fi
fi
if [ -f "${STATE}/mount.hang" ]; then
  exec sleep 30
fi
rc="0"
if [ -f "${STATE}/mount.rc" ]; then
  rc="$(cat "${STATE}/mount.rc")"
fi
if [ "${rc}" != "0" ]; then
  exit "${rc}"
fi
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
if [ -f "${STATE}/diskutil.hang" ]; then
  exec sleep 30
fi
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
if [ -f "${STATE}/umount.hang" ]; then
  exec sleep 30
fi
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

smbfs_line() {
  local share="$1" path="$2" fstype="${3:-smbfs}"
  printf '//exampleuser@nas.example/%s on %s (%s, nodev, nosuid)\n' "${share}" "${path}" "${fstype}"
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
    "${STATE}/security.hang" \
    "${STATE}/mount.hang" \
    "${STATE}/mount.hang_after" \
    "${STATE}/mount.count" \
    "${STATE}/mount.rc" \
    "${STATE}/diskutil.hang" \
    "${STATE}/umount.hang"
  MP="${CANON_MP}"
  URL="${SHARE_URL}"
  PROBE_TIMEOUT=1
  UNMOUNT_TIMEOUT=1
  REMOUNT_TIMEOUT=1
  MOUNT_TABLE_TIMEOUT=1
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
      MUSIC_DL_SHARE_MOUNT_TABLE_TIMEOUT="${MOUNT_TABLE_TIMEOUT}" \
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

assert_no_names() {
  local label="$1"
  local blob="${STDOUT}${LOG}"
  case "${blob}" in
    *exampleuser*) fail "${label}: user leaked" ;;
    *nas.example*) fail "${label}: server leaked" ;;
  esac
  pass "${label}: server and user redacted"
}

# Recovery unmounts the original share once. A stray must not add another.
refuse_stray() {
  local label="$1"
  local forbidden
  shift
  assert_eq "${STATUS}" "20" "${label} exits 20"
  assert_contains "${LOG}" "not-at-mountpoint" "${label} reports not-at-mountpoint"
  assert_eq "$(count_diskutil_unmount)" "1" "${label} does not unmount a stray"
  assert_count umount 0 "${label} does not umount a stray"
  assert_count osascript 1 "${label} still tries osascript once"
  for forbidden in "$@"; do
    case "${CALLS}" in
      *"${forbidden}"*) fail "${label}: unmounted ${forbidden}" ;;
    esac
  done
  assert_common "${label}"
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

# Not an smbfs mount, and no share URL is configured. Nothing is mounted.
reset_state
URL=""
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
assert_contains "${LOG}" "share now unmounted" "remount hang records the share is unmounted"
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

# osascript failure text is not logged. Only the status is kept when stderr
# has no trailing AppleScript error number.
reset_state
set_ls 1 fail
printf '%s\n' "1" >"${STATE}/osascript.rc"
printf '%s\n' "failed ${SHARE_URL} //exampleuser@nas.example leftover" >"${STATE}/osascript.stderr"
rm -f "${STATE}/osascript.mount" "${STATE}/osascript.stdout"
run_helper
assert_eq "${STATUS}" "20" "remount error exits 20"
assert_contains "${LOG}" "remount=osascript:1 probe=" "remount error logs only the status"
case "${LOG}" in
  *leftover* | *osascript:1:failed*) fail "remount error kept free text" ;;
esac
pass "remount error drops free text"
assert_contains "${LOG}" "unmount=" "remount error records unmount"
assert_contains "${LOG}" "not-at-mountpoint" "remount error is not at the mountpoint"
assert_no_names "remount error"
assert_common "remount error"
assert_count osascript 1 "remount error tries osascript once"
assert_eq "$(count_diskutil_unmount)" "1" "remount error unmounts once"
assert_count ls 1 "remount error does not probe again"

# Real osascript wording: U+201C/U+201D around the server, error (-5014).
reset_state
set_ls 1 fail
printf '%s\n' "1" >"${STATE}/osascript.rc"
APPLE_LQ="$(printf '\342\200\234')"
APPLE_RQ="$(printf '\342\200\235')"
printf '%s\n' "execution error: The server ${APPLE_LQ}nas.example${APPLE_RQ} may not exist or it is unavailable at this time. (-5014)" >"${STATE}/osascript.stderr"
rm -f "${STATE}/osascript.mount" "${STATE}/osascript.stdout"
run_helper
assert_eq "${STATUS}" "20" "server error exits 20"
assert_contains "${LOG}" "remount=osascript:1:-5014" "server error keeps the number"
assert_no_names "server error"
case "${LOG}${STDOUT}" in
  *"may not exist"* | *"execution error"*) fail "server error kept free text" ;;
esac
pass "server error drops the sentence"
assert_common "server error"

# Real osascript wording: the account name and the server, error (-5000).
reset_state
set_ls 1 fail
printf '%s\n' "1" >"${STATE}/osascript.rc"
printf '%s\n' "execution error: The user exampleuser could not log in to nas.example. (-5000)" >"${STATE}/osascript.stderr"
rm -f "${STATE}/osascript.mount" "${STATE}/osascript.stdout"
run_helper
assert_eq "${STATUS}" "20" "login error exits 20"
assert_contains "${LOG}" "remount=osascript:1:-5000" "login error keeps the number"
assert_no_names "login error"
case "${LOG}${STDOUT}" in
  *"could not log"* | *"execution error"*) fail "login error kept free text" ;;
esac
pass "login error drops the sentence"
assert_common "login error"

# osascript prints "/". That path is not a stray.
reset_state
set_ls 1 fail
printf '%s\n' "/" >"${STATE}/osascript.stdout"
rm -f "${STATE}/osascript.mount"
run_helper
refuse_stray "root hint" "diskutil [unmount] [force] [/]"

# osascript prints a path that is not smbfs.
reset_state
set_ls 1 fail
printf '%s\n' "/path/to/other" >"${STATE}/osascript.stdout"
smbfs_line share "/path/to/other" apfs >"${STATE}/osascript.mount"
run_helper
refuse_stray "non-smbfs hint" "diskutil [unmount] [force] [/path/to/other]"

# A new smbfs mount of a different share, same parent, name <base>-1.
reset_state
set_ls 1 fail
printf '%s\n' "${MP}-1" >"${STATE}/osascript.stdout"
smbfs_line other "${MP}-1" >"${STATE}/osascript.mount"
run_helper
refuse_stray "different share" "diskutil [unmount] [force] [${MP}-1]"

# Right share, but the new mount is in a different parent.
reset_state
set_ls 1 fail
printf '%s\n' "/path/to/mountpoint-1" >"${STATE}/osascript.stdout"
smbfs_line share "/path/to/mountpoint-1" >"${STATE}/osascript.mount"
run_helper
refuse_stray "different parent" "diskutil [unmount] [force] [/path/to/mountpoint-1]"

# Right share and parent, but the name is not <base>-N.
reset_state
set_ls 1 fail
printf '%s\n' "${MP}copy" >"${STATE}/osascript.stdout"
smbfs_line share "${MP}copy" >"${STATE}/osascript.mount"
run_helper
refuse_stray "wrong basename" "diskutil [unmount] [force] [${MP}copy]"

# Two new <base>-N mounts. The hint names one of them. Unmount neither.
reset_state
set_ls 1 fail
printf '%s\n' "${MP}-1" >"${STATE}/osascript.stdout"
{
  smbfs_line share "${MP}-1"
  smbfs_line share "${MP}-2"
} >"${STATE}/osascript.mount"
run_helper
assert_eq "${STATUS}" "20" "ambiguous stray exits 20"
assert_contains "${LOG}" "stray-ambiguous" "ambiguous stray is logged"
assert_eq "$(count_diskutil_unmount)" "1" "ambiguous stray unmounts neither candidate"
assert_count umount 0 "ambiguous stray does not run umount"
assert_count osascript 1 "ambiguous stray remounts once"
case "${CALLS}" in
  *"diskutil [unmount] [force] [${MP}-1]"*) fail "ambiguous stray unmounted -1" ;;
  *"diskutil [unmount] [force] [${MP}-2]"*) fail "ambiguous stray unmounted -2" ;;
esac
pass "ambiguous stray leaves both candidates mounted"
assert_common "ambiguous stray"

# Share names are case-insensitive. Share matches share.
reset_state
set_ls 1 fail
printf '%s\n' "${MP}-1" >"${STATE}/osascript.stdout"
smbfs_line Share "${MP}-1" >"${STATE}/osascript.mount"
run_helper
assert_eq "${STATUS}" "20" "share case exits 20"
assert_contains "${LOG}" "different volume path" "share case unmounts the stray"
assert_eq "$(count_diskutil_unmount)" "2" "share case unmounts the share and the stray"
case "${CALLS}" in
  *"diskutil [unmount] [force] [${MP}-1]"*) pass "share case unmounts the stray path" ;;
  *) fail "share case did not unmount the stray path" ;;
esac
assert_common "share case"

# A <base>-N volume that was already mounted is not a stray.
reset_state
set_ls 1 fail
{
  smbfs_line share "${MP}"
  smbfs_line share "${MP}-1"
} >"${STATE}/mount.table"
rm -f "${STATE}/osascript.mount" "${STATE}/osascript.stdout"
run_helper
refuse_stray "pre-existing volume" "diskutil [unmount] [force] [${MP}-1]"

# Remount returns 0, the share is not at the mountpoint, and nothing qualifies.
reset_state
set_ls 1 fail
rm -f "${STATE}/osascript.mount" "${STATE}/osascript.stdout"
run_helper
assert_eq "${STATUS}" "20" "no stray exits 20"
assert_contains "${LOG}" "remount=osascript:0" "no stray records a successful remount"
assert_contains "${LOG}" "not-at-mountpoint" "no stray reports not-at-mountpoint"
assert_eq "$(count_diskutil_unmount)" "1" "no stray unmounts only the original share"
assert_count umount 0 "no stray does not run umount"
assert_count osascript 1 "no stray remounts once"
assert_count ls 1 "no stray does not probe again"
assert_common "no stray"

# mount table times out before any unmount.
reset_state
: >"${STATE}/mount.hang"
run_helper
assert_eq "${STATUS}" "21" "mount hang exits 21"
assert_contains "${LOG}" "mount table unavailable" "mount hang explains why"
assert_common "mount hang"
assert_hang_window "mount hang returns inside the mount-table timeout"
assert_count mount 1 "mount hang reads the table once"
assert_count ls 0 "mount hang does not list"
assert_count diskutil 0 "mount hang does not unmount"
assert_count umount 0 "mount hang does not fall back"
assert_count osascript 0 "mount hang does not remount"
assert_count security 0 "mount hang does not check the keychain"

# mount exits non-zero before any unmount.
reset_state
printf '%s\n' "3" >"${STATE}/mount.rc"
run_helper
assert_eq "${STATUS}" "21" "mount failure exits 21"
assert_contains "${LOG}" "mount table unavailable" "mount failure explains why"
assert_common "mount failure"
assert_count mount 1 "mount failure reads the table once"
assert_count ls 0 "mount failure does not list"
assert_count diskutil 0 "mount failure does not unmount"
assert_count osascript 0 "mount failure does not remount"

# Snapshot times out after the stale probe and before unmount.
reset_state
set_ls 1 fail
printf '%s\n' "2" >"${STATE}/mount.hang_after"
run_helper
assert_eq "${STATUS}" "21" "snapshot hang exits 21"
assert_contains "${LOG}" "mount table unavailable" "snapshot hang explains why"
assert_common "snapshot hang"
assert_hang_window "snapshot hang returns inside the mount-table timeout"
assert_count diskutil 0 "snapshot hang does not unmount"
assert_count umount 0 "snapshot hang does not fall back"
assert_count osascript 0 "snapshot hang does not remount"
assert_count security 1 "snapshot hang checks the keychain first"

# After unmount and remount, a mount-table timeout is not-at-mountpoint.
reset_state
set_ls 1 fail
printf '%s\n' "3" >"${STATE}/mount.hang_after"
run_helper
assert_eq "${STATUS}" "20" "post-remount mount hang exits 20"
assert_contains "${LOG}" "not-at-mountpoint" "post-remount mount hang is not-at-mountpoint"
assert_common "post-remount mount hang"
assert_hang_window "post-remount mount hang returns inside the mount-table timeout"
assert_count osascript 1 "post-remount mount hang remounts once"
assert_eq "$(count_diskutil_unmount)" "1" "post-remount mount hang does not unmount a stray"
assert_count umount 0 "post-remount mount hang does not fall back"

# Trailing slashes name the same mountpoint. "/" does not.
reset_state
set_ls 1 ok
PLAIN_MP="${MP}"
MP="${PLAIN_MP}/"
run_helper
assert_eq "${STATUS}" "0" "one trailing slash exits 0"
assert_contains "${LOG}" "listing ok" "one trailing slash is healthy"
case "${CALLS}" in
  *"ls [-A] [${PLAIN_MP}]"*) pass "one trailing slash lists the normalized path" ;;
  *) fail "one trailing slash listed the wrong path" ;;
esac
assert_count diskutil 0 "one trailing slash does not unmount"
assert_common "one trailing slash"

reset_state
set_ls 1 ok
PLAIN_MP="${MP}"
MP="${PLAIN_MP}//"
run_helper
assert_eq "${STATUS}" "0" "two trailing slashes exit 0"
assert_contains "${LOG}" "listing ok" "two trailing slashes are healthy"
case "${CALLS}" in
  *"ls [-A] [${PLAIN_MP}]"*) pass "two trailing slashes list the normalized path" ;;
  *) fail "two trailing slashes listed the wrong path" ;;
esac
assert_common "two trailing slashes"

reset_state
MP="/"
run_helper
assert_eq "${STATUS}" "21" "root mountpoint exits 21"
assert_contains "${LOG}" "bad config: mountpoint" "root mountpoint explains why"
assert_eq "$(wc -c <"${CALL_LOG}" | tr -d ' ')" "0" "root mountpoint calls nothing"
assert_common "root mountpoint"

reset_state
MP="///"
run_helper
assert_eq "${STATUS}" "21" "all-slashes mountpoint exits 21"
assert_contains "${LOG}" "bad config: mountpoint" "all-slashes mountpoint explains why"
assert_eq "$(wc -c <"${CALL_LOG}" | tr -d ' ')" "0" "all-slashes mountpoint calls nothing"
assert_common "all-slashes mountpoint"

reset_state
MP=""
run_helper
assert_eq "${STATUS}" "21" "missing mountpoint exits 21"
assert_contains "${LOG}" "bad config: mountpoint" "missing mountpoint explains why"
assert_eq "$(wc -c <"${CALL_LOG}" | tr -d ' ')" "0" "missing mountpoint calls nothing"
assert_common "missing mountpoint"

reset_state
MP="relative/mount"
run_helper
assert_eq "${STATUS}" "21" "relative mountpoint exits 21"
assert_contains "${LOG}" "bad config: mountpoint" "relative mountpoint explains why"
assert_eq "$(wc -c <"${CALL_LOG}" | tr -d ' ')" "0" "relative mountpoint calls nothing"
assert_common "relative mountpoint"

reset_state
PROBE_TIMEOUT=0
run_helper
assert_eq "${STATUS}" "21" "zero timeout exits 21"
assert_contains "${LOG}" "bad config: timeout" "zero timeout explains why"
assert_eq "$(wc -c <"${CALL_LOG}" | tr -d ' ')" "0" "zero timeout calls nothing"
assert_common "zero timeout"

reset_state
MOUNT_TABLE_TIMEOUT="10s"
run_helper
assert_eq "${STATUS}" "21" "non-numeric timeout exits 21"
assert_contains "${LOG}" "bad config: timeout" "non-numeric timeout explains why"
assert_eq "$(wc -c <"${CALL_LOG}" | tr -d ' ')" "0" "non-numeric timeout calls nothing"
assert_common "non-numeric timeout"

reset_state
set_ls 1 fail
URL="http://exampleuser@nas.example/share"
run_helper
assert_eq "${STATUS}" "21" "non-smb url exits 21"
assert_contains "${LOG}" "bad config: share url" "non-smb url explains why"
assert_common "non-smb url"
assert_count ls 1 "non-smb url probes once"
assert_count mount 1 "non-smb url reads the mount table once"
assert_count security 0 "non-smb url does not check the keychain"
assert_count diskutil 0 "non-smb url does not unmount"
assert_count osascript 0 "non-smb url does not remount"

reset_state
set_ls 1 fail
URL="smb://exampleuser@nas.example"
run_helper
assert_eq "${STATUS}" "21" "url missing share exits 21"
assert_contains "${LOG}" "bad config: share url" "url missing share explains why"
assert_common "url missing share"
assert_count security 0 "url missing share does not check the keychain"
assert_count diskutil 0 "url missing share does not unmount"
assert_count osascript 0 "url missing share does not remount"

# Both unmount tools fail. Remount still runs exactly once.
reset_state
set_ls 1 fail
set_ls 2 ok
printf '%s\n' "3" >"${STATE}/diskutil.rc"
printf '%s\n' "5" >"${STATE}/umount.rc"
run_helper
assert_eq "${STATUS}" "0" "both unmounts fail then recover"
assert_contains "${LOG}" "unmount=diskutil:3,umount:5" "both unmounts fail records both results"
assert_common "both unmounts fail"
assert_eq "$(count_diskutil_unmount)" "1" "both unmounts fail try diskutil once"
assert_count umount 1 "both unmounts fail try umount once"
assert_count osascript 1 "both unmounts fail remount once"

reset_state
set_ls 1 fail
set_ls 2 ok
: >"${STATE}/diskutil.hang"
: >"${STATE}/umount.hang"
run_helper
assert_eq "${STATUS}" "0" "both unmounts time out then recover"
assert_contains "${LOG}" "unmount=diskutil:timeout,umount:timeout" "both unmount timeouts are logged"
assert_common "both unmount timeouts"
assert_eq "$(count_diskutil_unmount)" "1" "both unmount timeouts try diskutil once"
assert_count umount 1 "both unmount timeouts try umount once"
assert_count osascript 1 "both unmount timeouts remount once"

hide_share() {
  printf '%s\n' "/dev/disk0s1 on / (apfs, local, read-only)" >"${STATE}/mount.table"
}

# Not mounted, no saved login: do not mount.
reset_state
hide_share
: >"${STATE}/security.missing"
run_helper
assert_eq "${STATUS}" "21" "absent share missing login exits 21"
assert_contains "${LOG}" "no saved login; mount would prompt" "absent share missing login explains why"
assert_common "absent share missing login"
assert_count security 1 "absent share missing login checks the keychain once"
assert_count osascript 0 "absent share missing login does not mount"
assert_count diskutil 0 "absent share missing login does not unmount"
assert_count umount 0 "absent share missing login does not fall back"
assert_count ls 0 "absent share missing login does not list"
assert_security_query "absent share missing login keychain query has no secret flag"

# Not mounted, URL is not smb://.
reset_state
hide_share
URL="http://exampleuser@nas.example/share"
run_helper
assert_eq "${STATUS}" "21" "absent share bad url exits 21"
assert_contains "${LOG}" "bad config: share url" "absent share bad url explains why"
assert_common "absent share bad url"
assert_count security 0 "absent share bad url does not check the keychain"
assert_count osascript 0 "absent share bad url does not mount"
assert_count diskutil 0 "absent share bad url does not unmount"

# Not mounted, saved login, mount lands on the mountpoint and the probe works.
reset_state
hide_share
set_ls 1 ok
run_helper
assert_eq "${STATUS}" "0" "absent share mount exits 0"
assert_contains "${LOG}" "mount ok mount=osascript:0 probe=0" "absent share mount logs mount ok"
assert_common "absent share mount"
assert_count osascript 1 "absent share mount runs osascript once"
assert_count ls 1 "absent share mount probes once"
assert_count security 1 "absent share mount checks the keychain once"
assert_count diskutil 0 "absent share mount does not unmount"
assert_count umount 0 "absent share mount does not fall back"
assert_osascript_url "absent share mount passes the url only to osascript"

# Not mounted, mount lands, probe fails.
reset_state
hide_share
set_ls 1 fail
run_helper
assert_eq "${STATUS}" "20" "absent share probe failure exits 20"
assert_contains "${LOG}" "mount failed" "absent share probe failure logs mount failed"
assert_contains "${LOG}" "mount=osascript:0" "absent share probe failure records the mount"
assert_common "absent share probe failure"
assert_count osascript 1 "absent share probe failure mounts once"
assert_count ls 1 "absent share probe failure probes once"
assert_count diskutil 0 "absent share probe failure does not unmount"
assert_count umount 0 "absent share probe failure does not fall back"

# Not mounted, the listing is refused after the mount.
reset_state
hide_share
set_ls 1 tcc
run_helper
assert_eq "${STATUS}" "11" "absent share permission exits 11"
assert_contains "${LOG}" "listing not permitted" "absent share permission explains why"
assert_common "absent share permission"
assert_count osascript 1 "absent share permission mounts once"
assert_count ls 1 "absent share permission probes once"
assert_count diskutil 0 "absent share permission does not unmount"
assert_count umount 0 "absent share permission does not fall back"

# Not mounted, osascript blocks.
reset_state
hide_share
: >"${STATE}/osascript.sleep"
run_helper
assert_eq "${STATUS}" "21" "absent share mount hang exits 21"
assert_contains "${LOG}" "mount timed out (auth prompt likely)" "absent share mount hang names the timeout"
case "${LOG}" in
  *"share now unmounted"*) fail "absent share mount hang claimed an unmount" ;;
esac
pass "absent share mount hang does not claim an unmount"
assert_common "absent share mount hang"
assert_hang_window "absent share mount hang returns inside the remount timeout"
assert_count osascript 1 "absent share mount hang tries osascript once"
assert_count diskutil 0 "absent share mount hang does not unmount"
assert_count umount 0 "absent share mount hang does not fall back"
assert_count ls 0 "absent share mount hang does not list"

# Not mounted, keychain lookup blocks. Do not mount.
reset_state
hide_share
: >"${STATE}/security.hang"
run_helper
assert_eq "${STATUS}" "21" "absent share keychain hang exits 21"
assert_contains "${LOG}" "keychain lookup timed out" "absent share keychain hang names the timeout"
assert_contains "${LOG}" "mount would prompt" "absent share keychain hang would prompt"
assert_common "absent share keychain hang"
assert_hang_window "absent share keychain hang returns inside the keychain timeout"
assert_count osascript 0 "absent share keychain hang does not mount"
assert_count diskutil 0 "absent share keychain hang does not unmount"
assert_count umount 0 "absent share keychain hang does not fall back"

# Not mounted, the volume appears at a valid stray path. Unmount that once.
reset_state
hide_share
printf '%s\n' "${MP}-1" >"${STATE}/osascript.stdout"
smbfs_line share "${MP}-1" >"${STATE}/osascript.mount"
run_helper
assert_eq "${STATUS}" "20" "absent share stray exits 20"
assert_contains "${LOG}" "mount failed" "absent share stray logs mount failed"
assert_common "absent share stray"
assert_eq "$(count_diskutil_unmount)" "1" "absent share stray unmounts once"
assert_count umount 0 "absent share stray does not fall back"
assert_count osascript 1 "absent share stray mounts once"
assert_count ls 0 "absent share stray does not probe the mountpoint"
case "${CALLS}" in
  *"diskutil [unmount] [force] [${MP}]"*) fail "absent share stray unmounted the mountpoint" ;;
esac
case "${CALLS}" in
  *"diskutil [unmount] [force] [${MP}-1]"*) pass "absent share stray unmounts the stray path" ;;
  *) fail "absent share stray did not unmount the stray path" ;;
esac

pass "playlist share recover tests"
