#!/usr/bin/env bash
# One-shot recovery for a stale SMB download share before a playlist fill.
#
# A scheduler can see the share still listed as smbfs while a directory
# listing hangs. This helper checks that listing once. When the listing is
# stale it tries exactly one unmount and one remount, then lists again.
# When the mountpoint is not smbfs and a share URL is set, it tries one
# mount and does not unmount the mountpoint. With no share URL it exits 10.
# It never loops and never retries.
#
# The caller passes configuration only through the environment:
#
#   MUSIC_DL_SHARE_MOUNTPOINT           required, for example /path/to/mountpoint
#                                       a trailing slash is ignored; "/" is refused
#   MUSIC_DL_SHARE_URL                  smb://USER@SERVER/SHARE
#                                       required to remount, or to mount when
#                                       the share is not mounted. An empty URL
#                                       leaves a not-mounted share at exit 10
#                                       a userinfo colon (user:password@) is refused
#   MUSIC_DL_SHARE_PROBE_TIMEOUT        seconds, default 20
#   MUSIC_DL_SHARE_UNMOUNT_TIMEOUT      seconds, default 30
#   MUSIC_DL_SHARE_REMOUNT_TIMEOUT      seconds, default 45
#   MUSIC_DL_SHARE_KEYCHAIN_TIMEOUT     seconds, default 10 (saved-login lookup)
#   MUSIC_DL_SHARE_MOUNT_TABLE_TIMEOUT  seconds, default 10 (`mount` table read)
#   MUSIC_DL_SHARE_LOG                  optional file for one appended summary line
#
# Exit codes:
#    0  listing ok (already healthy, healthy after the one remount, or mount ok)
#   10  not mounted and no share URL configured
#   11  listing was refused by permissions; not a stale session
#   20  the one recovery or mount attempt ran and the share still fails
#       (not at the mountpoint, or more than one possible stray)
#   21  fail-fast: bad config, no saved login, mount table unavailable,
#       the remount timed out, or the mount timed out
#       Exit 21 after a remount timeout means the share has already been
#       unmounted. The log line includes "share now unmounted".
#       A mount timeout means the share was not mounted and nothing was
#       unmounted. The log line says "mount timed out (auth prompt likely)".
#
# Worst-case duration is about 3.3 minutes (199s). The longest path is a
# stale listing, a saved login, both unmount commands, a remount that
# returns, and one stray volume unmounted afterwards. Steps that time out
# and still continue also wait about 1s while the child is killed:
#   mount table ×3 × 10s = 30s  (initial, pre-unmount snapshot, post-remount)
#   probe                   20s  (times out; recovery still runs) + ~1s
#   keychain                10s  (must succeed; finishes at the deadline)
#   diskutil                30s  (times out; umount still runs) + ~1s
#   umount                  30s  (times out; remount still runs) + ~1s
#   osascript               45s  (must return; a timeout stops earlier)
#   stray unmount           30s  (times out; then the helper stops) + ~1s
#   3×10 + 20 + 10 + 30 + 30 + 45 + 30 + 4 = 199s
# A second listing after a remount that lands on the mountpoint is shorter.
#
# Logs use the tag "share-recover" and never include the URL, user, or server.
# osascript failures log only the exit status and, when stderr ends in
# (-NNNN), that AppleScript error number.
# The keychain lookup asks for attributes only. It does not read the secret.
# Remount uses the saved login. A password is never placed on an argument list.
#
# Summary line (stdout, and the log when MUSIC_DL_SHARE_LOG is set):
#   YYYY-MM-DD HH:MM:SS TZ share-recover: <result>

set -u

RUN_RC=1
PROBE_RC=1
PROBE_ERR=""
PROBE_RESULT=""
UNMOUNT_RESULT=""
REMOUNT_RC=1
REMOUNT_RESULT=""
SMB_USER=""
SMB_SERVER=""
SMB_SHARE=""
MOUNT_TABLE_RC=0
MOUNT_TABLE_T=""
STRAY_STATUS=""
STRAY_PATH=""

# Invoked by the EXIT trap inside main. ShellCheck does not see that call.
# shellcheck disable=SC2317,SC2329
cleanup() {
  local dir="${WORKDIR:-}"
  case "${dir}" in
    */share-recover.*)
      rm -rf "${dir}"
      ;;
    *) ;;
  esac
}

finish() {
  local code="$1"
  shift
  local ts line
  ts="$(date '+%Y-%m-%d %H:%M:%S %Z')"
  line="${ts} share-recover: $*"
  if [ -n "${MUSIC_DL_SHARE_LOG:-}" ]; then
    printf '%s\n' "${line}" >>"${MUSIC_DL_SHARE_LOG}"
  fi
  printf '%s\n' "${line}"
  exit "${code}"
}

normalize_pos_int() {
  local value="$1"
  local number
  case "${value}" in
    "" | *[!0-9]*) return 1 ;;
  esac
  number=$((10#${value})) 2>/dev/null || return 1
  if [ "${number}" -le 0 ]; then
    return 1
  fi
  printf '%s\n' "${number}"
}

url_has_password() {
  local url="$1"
  local rest userinfo
  [ -n "${url}" ] || return 1
  rest="${url#*://}"
  case "${rest}" in
    *@*) ;;
    *) return 1 ;;
  esac
  userinfo="${rest%%@*}"
  case "${userinfo}" in
    *:*) return 0 ;;
    *) return 1 ;;
  esac
}

parse_smb_url() {
  local url="$1"
  local rest user hostpath server share
  SMB_USER=""
  SMB_SERVER=""
  SMB_SHARE=""
  case "${url}" in
    smb://*) ;;
    *) return 1 ;;
  esac
  rest="${url#smb://}"
  case "${rest}" in
    *@*/*) ;;
    *) return 1 ;;
  esac
  user="${rest%%@*}"
  hostpath="${rest#*@}"
  server="${hostpath%%/*}"
  share="${hostpath#*/}"
  [ -n "${user}" ] && [ -n "${server}" ] && [ -n "${share}" ] || return 1
  case "${user}" in
    *[!A-Za-z0-9._-]*) return 1 ;;
  esac
  case "${server}" in
    *[!A-Za-z0-9._-]*) return 1 ;;
  esac
  case "${share}" in
    *[!A-Za-z0-9._-]*) return 1 ;;
  esac
  SMB_USER="${user}"
  SMB_SERVER="${server}"
  SMB_SHARE="${share}"
  return 0
}

# Run a command with a hard timeout. On expiry, TERM, then KILL.
# A hung network mount can ignore both signals, so a still-live child is
# disowned and never waited on. A finished child is reaped. Timeout is 124.
run_with_timeout() {
  local timeout_s="$1"
  local out_file="$2"
  local err_file="$3"
  shift 3
  local pid slices i timed_out g

  : >"${out_file}"
  : >"${err_file}"
  "$@" >"${out_file}" 2>"${err_file}" &
  pid=$!
  slices=$((timeout_s * 5))
  i=0
  timed_out=0

  while kill -0 "${pid}" 2>/dev/null; do
    if [ "${i}" -ge "${slices}" ]; then
      timed_out=1
      break
    fi
    sleep 0.2
    i=$((i + 1))
  done

  if [ "${timed_out}" -eq 0 ]; then
    wait "${pid}"
    RUN_RC=$?
    return 0
  fi

  # bash 3.2 prints a job-status line ("Terminated") when it reaps a killed
  # child; keep that off our stderr. The helper reports only via stdout/log.
  {
    kill -TERM "${pid}" 2>/dev/null || true
    g=0
    while [ "${g}" -lt 5 ]; do
      if ! kill -0 "${pid}" 2>/dev/null; then
        break
      fi
      sleep 0.2
      g=$((g + 1))
    done
    if kill -0 "${pid}" 2>/dev/null; then
      kill -KILL "${pid}" 2>/dev/null || true
    fi
    if kill -0 "${pid}" 2>/dev/null; then
      disown "${pid}" 2>/dev/null || true
    else
      wait "${pid}" 2>/dev/null || true
    fi
  } 2>/dev/null
  RUN_RC=124
  return 0
}

slurp() {
  local file="$1"
  local line text
  text=""
  if [ ! -f "${file}" ]; then
    return 0
  fi
  while IFS= read -r line || [ -n "${line}" ]; do
    text="${text}${line}
"
  done <"${file}"
  printf '%s' "${text}"
}

mountpoint_from_line() {
  local line="$1"
  local rest mp opts type
  case "${line}" in
    *" on "*) ;;
    *) return 1 ;;
  esac
  rest="${line#* on }"
  case "${rest}" in
    *" ("*) ;;
    *) return 1 ;;
  esac
  mp="${rest%% (*}"
  opts="${rest#*(}"
  opts="${opts%)}"
  type="${opts%%,*}"
  type="${type#"${type%%[![:space:]]*}"}"
  type="${type%"${type##*[![:space:]]}"}"
  [ "${type}" = "smbfs" ] || return 1
  [ -n "${mp}" ] || return 1
  printf '%s\n' "${mp}"
}

# Read the mount table. Non-zero (including timeout) leaves MOUNT_TABLE_RC set
# and returns 1. mount's own errors can echo a server name; they stay in the
# work file, not on our stderr.
load_mount_table() {
  run_with_timeout "${MOUNT_TABLE_T}" "${WORKDIR}/mount.txt" "${WORKDIR}/mount.err" mount
  MOUNT_TABLE_RC="${RUN_RC}"
  [ "${MOUNT_TABLE_RC}" -eq 0 ]
}

mount_table_has() {
  local want="$1"
  local line path
  while IFS= read -r line || [ -n "${line}" ]; do
    path="$(mountpoint_from_line "${line}")" || continue
    path="$(normalize_volume_path "${path}")"
    if [ "${path}" = "${want}" ]; then
      return 0
    fi
  done <"${WORKDIR}/mount.txt"
  return 1
}

write_smbfs_paths() {
  local dest="$1"
  local line path
  : >"${dest}"
  while IFS= read -r line || [ -n "${line}" ]; do
    path="$(mountpoint_from_line "${line}")" || continue
    path="$(normalize_volume_path "${path}")"
    [ -n "${path}" ] || continue
    printf '%s\n' "${path}" >>"${dest}"
  done <"${WORKDIR}/mount.txt"
}

strip_trailing_slashes() {
  local p="$1"
  local prev
  while [ -n "${p}" ]; do
    case "${p}" in
      /) break ;;
      */)
        prev="${p}"
        p="${p%/}"
        [ "${p}" = "${prev}" ] && break
        ;;
      *) break ;;
    esac
  done
  printf '%s' "${p}"
}

normalize_volume_path() {
  local p="$1"
  case "${p}" in
    file://*) p="${p#file://}" ;;
  esac
  p="$(strip_trailing_slashes "${p}")"
  printf '%s' "${p}"
}

to_lower() {
  # stdin is /dev/null so a caller reading a file is not consumed.
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
} </dev/null

path_parent() {
  local p="$1"
  local parent
  parent="${p%/*}"
  if [ -z "${parent}" ]; then
    parent="/"
  fi
  printf '%s' "${parent}"
}

path_in_file() {
  local want="$1"
  local file="$2"
  local line
  [ -f "${file}" ] || return 1
  # fd 4 so this read cannot consume a caller's mount-table loop.
  while IFS= read -r line <&4 || [ -n "${line}" ]; do
    if [ "${line}" = "${want}" ]; then
      return 0
    fi
  done 4<"${file}"
  return 1
}

# Basename is exactly "<base>-" plus one or more digits.
stray_name_ok() {
  local base="$1"
  local name="$2"
  local rest
  case "${name}" in
    "${base}-"*) ;;
    *) return 1 ;;
  esac
  rest="${name#"${base}-"}"
  case "${rest}" in
    "" | *[!0-9]*) return 1 ;;
  esac
  return 0
}

note_rc() {
  local name="$1"
  local rc="$2"
  if [ "${rc}" -eq 124 ]; then
    printf '%s:timeout' "${name}"
  else
    printf '%s:%s' "${name}" "${rc}"
  fi
}

# AppleScript appends "(-NNNN)" to a failed osascript. Return that number,
# including the minus sign, only when stderr ends with it.
applescript_errno() {
  local s="$1"
  local prev tail num
  while [ -n "${s}" ]; do
    case "${s}" in
      *[[:space:]]) ;;
      *) break ;;
    esac
    prev="${s}"
    s="${s%[[:space:]]}"
    [ "${s}" = "${prev}" ] && break
  done
  case "${s}" in
    *\(-[0-9]*\)) ;;
    *) return 1 ;;
  esac
  tail="${s##*(}"
  tail="${tail%)}"
  case "${tail}" in
    -*) ;;
    *) return 1 ;;
  esac
  num="${tail#-}"
  case "${num}" in
    "" | *[!0-9]*) return 1 ;;
  esac
  printf '%s' "${tail}"
}

probe_share() {
  local mp="$1"
  local timeout_s="$2"
  local out err
  out="${WORKDIR}/probe.out"
  err="${WORKDIR}/probe.err"
  run_with_timeout "${timeout_s}" "${out}" "${err}" ls -A "${mp}"
  PROBE_RC="${RUN_RC}"
  PROBE_ERR="$(slurp "${err}")"
  if [ "${PROBE_RC}" -eq 124 ]; then
    PROBE_RESULT="timeout"
  else
    PROBE_RESULT="${PROBE_RC}"
  fi
}

probe_is_denied() {
  case "${PROBE_ERR}" in
    *"Operation not permitted"* | *"not permitted"*) return 0 ;;
    *) return 1 ;;
  esac
}

unmount_once() {
  local mp="$1"
  local timeout_s="$2"
  local out err disk_note umount_note
  out="${WORKDIR}/unmount.out"
  err="${WORKDIR}/unmount.err"
  run_with_timeout "${timeout_s}" "${out}" "${err}" diskutil unmount force "${mp}"
  if [ "${RUN_RC}" -eq 0 ]; then
    UNMOUNT_RESULT="diskutil:0"
    return 0
  fi
  disk_note="$(note_rc diskutil "${RUN_RC}")"
  run_with_timeout "${timeout_s}" "${out}" "${err}" umount -f "${mp}"
  umount_note="$(note_rc umount "${RUN_RC}")"
  UNMOUNT_RESULT="${disk_note},${umount_note}"
}

remount_once() {
  local url="$1"
  local timeout_s="$2"
  local out err expr errno
  out="${WORKDIR}/remount.out"
  err="${WORKDIR}/remount.err"
  expr="mount volume \"${url}\""
  run_with_timeout "${timeout_s}" "${out}" "${err}" osascript -e "${expr}"
  REMOUNT_RC="${RUN_RC}"
  if [ "${REMOUNT_RC}" -eq 124 ]; then
    REMOUNT_RESULT="osascript:timeout"
    return 0
  fi
  if [ "${REMOUNT_RC}" -eq 0 ]; then
    REMOUNT_RESULT="osascript:0"
    return 0
  fi
  errno="$(applescript_errno "$(slurp "${err}")")" || errno=""
  if [ -n "${errno}" ]; then
    REMOUNT_RESULT="osascript:${REMOUNT_RC}:${errno}"
  else
    REMOUNT_RESULT="osascript:${REMOUNT_RC}"
  fi
}

# A stray is unmounted only when exactly one smbfs path passes every rule:
# the share name matches (case-insensitive), the parent directory matches,
# the basename is "<mountpoint-basename>-<digits>", and the path was absent
# before the remount. The path osascript prints is only a hint: this scan
# never unmounts a path that fails the rules, including that hint.
# STRAY_STATUS is one, ambiguous, or none. STRAY_PATH is set for one.
# Runs in the current shell so those globals survive.
find_stray() {
  local mp="$1"
  local snap="$2"
  local base parent want_share line src share_name share_lc path
  local cand_parent count found
  STRAY_STATUS="none"
  STRAY_PATH=""
  if [ "${MOUNT_TABLE_RC}" -ne 0 ]; then
    return 1
  fi
  base="${mp##*/}"
  parent="$(path_parent "${mp}")"
  want_share="$(to_lower "${SMB_SHARE}")"
  count=0
  found=""
  while IFS= read -r line <&3 || [ -n "${line}" ]; do
    path="$(mountpoint_from_line "${line}")" || continue
    path="$(normalize_volume_path "${path}")"
    [ -n "${path}" ] || continue
    [ "${path}" = "${mp}" ] && continue
    case "${path}" in
      /*) ;;
      *) continue ;;
    esac
    src="${line%% on *}"
    case "${src}" in
      //*/*) ;;
      *) continue ;;
    esac
    share_name="${src##*/}"
    share_lc="$(to_lower "${share_name}")"
    [ "${share_lc}" = "${want_share}" ] || continue
    cand_parent="$(path_parent "${path}")"
    [ "${cand_parent}" = "${parent}" ] || continue
    stray_name_ok "${base}" "${path##*/}" || continue
    if path_in_file "${path}" "${snap}"; then
      continue
    fi
    if [ "${count}" -eq 1 ] && [ "${path}" = "${found}" ]; then
      continue
    fi
    count=$((count + 1))
    if [ "${count}" -gt 1 ]; then
      STRAY_STATUS="ambiguous"
      return 0
    fi
    found="${path}"
  done 3<"${WORKDIR}/mount.txt"
  if [ "${count}" -eq 1 ]; then
    STRAY_STATUS="one"
    STRAY_PATH="${found}"
    return 0
  fi
  STRAY_STATUS="none"
  return 1
}

unmount_stray() {
  local stray="$1"
  local timeout_s="$2"
  local out err
  out="${WORKDIR}/stray.out"
  err="${WORKDIR}/stray.err"
  run_with_timeout "${timeout_s}" "${out}" "${err}" diskutil unmount force "${stray}"
  note_rc diskutil "${RUN_RC}"
}

# The mountpoint is not smbfs. Never unmount it. One mount, then the same
# stray rules, then one probe at the mountpoint.
mount_absent_share() {
  local url="$1"
  local mp="$2"
  local probe_t="$3"
  local unmount_t="$4"
  local remount_t="$5"
  local keychain_t="$6"
  local snap stray_note

  if ! parse_smb_url "${url}"; then
    finish 21 "bad config: share url"
  fi
  # Attributes only. A locked keychain can raise an unlock dialog.
  run_with_timeout "${keychain_t}" "${WORKDIR}/security.out" "${WORKDIR}/security.err" \
    security find-internet-password -r "smb " -s "${SMB_SERVER}" -a "${SMB_USER}"
  : >"${WORKDIR}/security.out"
  if [ "${RUN_RC}" -eq 124 ]; then
    finish 21 "keychain lookup timed out (keychain locked?); mount would prompt"
  fi
  if [ "${RUN_RC}" -ne 0 ]; then
    finish 21 "no saved login; mount would prompt"
  fi

  snap="${WORKDIR}/before.txt"
  write_smbfs_paths "${snap}"

  remount_once "${url}" "${remount_t}"
  if [ "${REMOUNT_RC}" -eq 124 ]; then
    finish 21 "mount timed out (auth prompt likely)"
  fi

  if ! load_mount_table; then
    finish 20 "mount failed mount=${REMOUNT_RESULT} probe=not-at-mountpoint"
  fi
  if mount_table_has "${mp}"; then
    probe_share "${mp}" "${probe_t}"
    if probe_is_denied; then
      finish 11 "listing not permitted"
    fi
    if [ "${PROBE_RC}" -eq 0 ]; then
      finish 0 "mount ok mount=${REMOUNT_RESULT} probe=0"
    fi
    finish 20 "mount failed mount=${REMOUNT_RESULT} probe=${PROBE_RESULT}"
  fi

  find_stray "${mp}" "${snap}" || true
  case "${STRAY_STATUS}" in
    one)
      if [ -z "${STRAY_PATH}" ]; then
        finish 20 "mount failed mount=${REMOUNT_RESULT} probe=not-at-mountpoint"
      fi
      stray_note="$(unmount_stray "${STRAY_PATH}" "${unmount_t}")"
      finish 20 "mount failed mount=${REMOUNT_RESULT} stray=${stray_note}"
      ;;
    ambiguous)
      finish 20 "mount failed mount=${REMOUNT_RESULT} probe=stray-ambiguous"
      ;;
    *)
      finish 20 "mount failed mount=${REMOUNT_RESULT} probe=not-at-mountpoint"
      ;;
  esac
}

main() {
  local url mp probe_t unmount_t remount_t keychain_t mount_t
  local snap stray_note

  url="${MUSIC_DL_SHARE_URL:-}"
  mp="${MUSIC_DL_SHARE_MOUNTPOINT:-}"

  if url_has_password "${url}"; then
    finish 21 "bad config: password in share url"
  fi
  mp="$(strip_trailing_slashes "${mp}")"
  case "${mp}" in
    /*)
      if [ "${mp}" = "/" ]; then
        finish 21 "bad config: mountpoint"
      fi
      ;;
    *) finish 21 "bad config: mountpoint" ;;
  esac
  if ! probe_t="$(normalize_pos_int "${MUSIC_DL_SHARE_PROBE_TIMEOUT:-20}")"; then
    finish 21 "bad config: timeout"
  fi
  if ! unmount_t="$(normalize_pos_int "${MUSIC_DL_SHARE_UNMOUNT_TIMEOUT:-30}")"; then
    finish 21 "bad config: timeout"
  fi
  if ! remount_t="$(normalize_pos_int "${MUSIC_DL_SHARE_REMOUNT_TIMEOUT:-45}")"; then
    finish 21 "bad config: timeout"
  fi
  if ! keychain_t="$(normalize_pos_int "${MUSIC_DL_SHARE_KEYCHAIN_TIMEOUT:-10}")"; then
    finish 21 "bad config: timeout"
  fi
  if ! mount_t="$(normalize_pos_int "${MUSIC_DL_SHARE_MOUNT_TABLE_TIMEOUT:-10}")"; then
    finish 21 "bad config: timeout"
  fi
  MOUNT_TABLE_T="${mount_t}"

  WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/share-recover.XXXXXX")" || finish 21 "bad config: no work dir"
  trap cleanup EXIT

  if ! load_mount_table; then
    finish 21 "mount table unavailable"
  fi
  if ! mount_table_has "${mp}"; then
    if [ -z "${url}" ]; then
      finish 10 "not mounted"
    fi
    mount_absent_share "${url}" "${mp}" "${probe_t}" "${unmount_t}" "${remount_t}" "${keychain_t}"
  fi

  probe_share "${mp}" "${probe_t}"
  if probe_is_denied; then
    finish 11 "listing not permitted"
  fi
  if [ "${PROBE_RC}" -eq 0 ]; then
    finish 0 "listing ok"
  fi

  if ! parse_smb_url "${url}"; then
    finish 21 "bad config: share url"
  fi
  # Four-character protocol code includes the trailing space. Attributes only.
  # A locked keychain can raise an unlock dialog, so this lookup is timed too.
  run_with_timeout "${keychain_t}" "${WORKDIR}/security.out" "${WORKDIR}/security.err" \
    security find-internet-password -r "smb " -s "${SMB_SERVER}" -a "${SMB_USER}"
  : >"${WORKDIR}/security.out"
  if [ "${RUN_RC}" -eq 124 ]; then
    finish 21 "keychain lookup timed out (keychain locked?); remount would prompt"
  fi
  if [ "${RUN_RC}" -ne 0 ]; then
    finish 21 "no saved login; remount would prompt"
  fi

  snap="${WORKDIR}/before.txt"
  if ! load_mount_table; then
    finish 21 "mount table unavailable"
  fi
  write_smbfs_paths "${snap}"

  unmount_once "${mp}" "${unmount_t}"
  remount_once "${url}" "${remount_t}"
  if [ "${REMOUNT_RC}" -eq 124 ]; then
    finish 21 "remount timed out (auth prompt likely); share now unmounted unmount=${UNMOUNT_RESULT}"
  fi

  if ! load_mount_table; then
    finish 20 "recovery failed unmount=${UNMOUNT_RESULT} remount=${REMOUNT_RESULT} probe=not-at-mountpoint"
  fi
  if mount_table_has "${mp}"; then
    probe_share "${mp}" "${probe_t}"
    if [ "${PROBE_RC}" -eq 0 ]; then
      finish 0 "remount ok unmount=${UNMOUNT_RESULT} remount=${REMOUNT_RESULT} probe=0"
    fi
    finish 20 "recovery failed unmount=${UNMOUNT_RESULT} remount=${REMOUNT_RESULT} probe=${PROBE_RESULT}"
  fi

  find_stray "${mp}" "${snap}" || true
  case "${STRAY_STATUS}" in
    one)
      if [ -z "${STRAY_PATH}" ]; then
        finish 20 "recovery failed unmount=${UNMOUNT_RESULT} remount=${REMOUNT_RESULT} probe=not-at-mountpoint"
      fi
      stray_note="$(unmount_stray "${STRAY_PATH}" "${unmount_t}")"
      finish 20 "recovery failed: different volume path unmount=${UNMOUNT_RESULT} remount=${REMOUNT_RESULT} stray=${stray_note}"
      ;;
    ambiguous)
      finish 20 "recovery failed unmount=${UNMOUNT_RESULT} remount=${REMOUNT_RESULT} probe=stray-ambiguous"
      ;;
    *)
      finish 20 "recovery failed unmount=${UNMOUNT_RESULT} remount=${REMOUNT_RESULT} probe=not-at-mountpoint"
      ;;
  esac
}

main "$@"
