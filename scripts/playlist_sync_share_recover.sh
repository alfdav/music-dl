#!/usr/bin/env bash
# One-shot recovery for a stale SMB download share before a playlist fill.
#
# A scheduler can see the share still listed as smbfs while a directory
# listing hangs. This helper checks that listing once. When the listing is
# stale it tries exactly one unmount and one remount, then lists again.
# It never loops and never retries.
#
# The caller passes configuration only through the environment:
#
#   MUSIC_DL_SHARE_MOUNTPOINT          required, for example /path/to/mountpoint
#   MUSIC_DL_SHARE_URL                 smb://USER@SERVER/SHARE
#                                      required only when a remount is needed
#                                      a userinfo colon (user:password@) is refused
#   MUSIC_DL_SHARE_PROBE_TIMEOUT       seconds, default 20
#   MUSIC_DL_SHARE_UNMOUNT_TIMEOUT     seconds, default 30
#   MUSIC_DL_SHARE_REMOUNT_TIMEOUT     seconds, default 45
#   MUSIC_DL_SHARE_KEYCHAIN_TIMEOUT    seconds, default 10 (saved-login lookup)
#   MUSIC_DL_SHARE_LOG                 optional file for one appended summary line
#
# Exit codes:
#    0  listing ok (already healthy, or healthy after the one remount)
#   10  mountpoint is not an smbfs mount; nothing else is tried
#   11  listing was refused by permissions; not a stale session; no remount
#   20  the one recovery ran and the share still fails
#   21  fail-fast: bad config, no saved login, or the remount timed out
#
# Logs use the tag "share-recover" and never include the URL, user, or server.
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
REMOUNT_OUT=""
SMB_USER=""
SMB_SERVER=""

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

list_smbfs_mountpoints() {
  local line mp file
  file="${WORKDIR}/mount.txt"
  # mount's own errors can echo a server name; keep them out of our stderr.
  mount >"${file}" 2>"${WORKDIR}/mount.err" || true
  while IFS= read -r line || [ -n "${line}" ]; do
    mp="$(mountpoint_from_line "${line}")" || continue
    printf '%s\n' "${mp}"
  done <"${file}"
}

is_smbfs_mount() {
  local want="$1"
  local mp
  while IFS= read -r mp || [ -n "${mp}" ]; do
    if [ "${mp}" = "${want}" ]; then
      return 0
    fi
  done < <(list_smbfs_mountpoints)
  return 1
}

first_line() {
  local file="$1"
  local line
  if [ ! -f "${file}" ]; then
    return 0
  fi
  IFS= read -r line <"${file}" || true
  printf '%s' "${line%$'\r'}"
}

normalize_volume_path() {
  local p="$1"
  case "${p}" in
    file://*) p="${p#file://}" ;;
  esac
  case "${p}" in
    /) ;;
    */) p="${p%/}" ;;
  esac
  printf '%s' "${p}"
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

sanitize_note() {
  local line="$1"
  local url="$2"
  (
    set -f
    local tok out
    if [ -n "${url}" ]; then
      line="${line//"$url"/}"
    fi
    line="${line%$'\r'}"
    out=""
    for tok in ${line}; do
      case "${tok}" in
        *"://"* | *"@"* | *"//"*) continue ;;
        *) out="${out:+${out} }${tok}" ;;
      esac
    done
    printf '%.120s' "${out}"
  )
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
  local out err expr err_line clean
  out="${WORKDIR}/remount.out"
  err="${WORKDIR}/remount.err"
  REMOUNT_OUT="${out}"
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
  err_line="$(first_line "${err}")"
  clean="$(sanitize_note "${err_line}" "${url}")"
  if [ -n "${clean}" ]; then
    REMOUNT_RESULT="osascript:${REMOUNT_RC}:${clean}"
  else
    REMOUNT_RESULT="osascript:${REMOUNT_RC}"
  fi
}

stray_mountpoint() {
  local mp="$1"
  local snap="$2"
  local out_file="$3"
  local returned candidate old found
  returned="$(first_line "${out_file}")"
  returned="$(normalize_volume_path "${returned}")"
  if [ -n "${returned}" ] && [ "${returned}" != "${mp}" ]; then
    case "${returned}" in
      /*)
        printf '%s\n' "${returned}"
        return 0
        ;;
    esac
  fi
  while IFS= read -r candidate || [ -n "${candidate}" ]; do
    [ -n "${candidate}" ] || continue
    if [ "${candidate}" = "${mp}" ]; then
      continue
    fi
    found=0
    while IFS= read -r old || [ -n "${old}" ]; do
      if [ "${old}" = "${candidate}" ]; then
        found=1
        break
      fi
    done <"${snap}"
    if [ "${found}" -eq 0 ]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done < <(list_smbfs_mountpoints)
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

main() {
  local url mp probe_t unmount_t remount_t keychain_t
  local snap stray stray_note

  url="${MUSIC_DL_SHARE_URL:-}"
  mp="${MUSIC_DL_SHARE_MOUNTPOINT:-}"

  if url_has_password "${url}"; then
    finish 21 "bad config: password in share url"
  fi
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

  WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/share-recover.XXXXXX")" || finish 21 "bad config: no work dir"
  trap cleanup EXIT

  if ! is_smbfs_mount "${mp}"; then
    finish 10 "not mounted"
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
  list_smbfs_mountpoints >"${snap}"

  unmount_once "${mp}" "${unmount_t}"
  remount_once "${url}" "${remount_t}"
  if [ "${REMOUNT_RC}" -eq 124 ]; then
    finish 21 "remount timed out (auth prompt likely) unmount=${UNMOUNT_RESULT}"
  fi

  if is_smbfs_mount "${mp}"; then
    probe_share "${mp}" "${probe_t}"
    if [ "${PROBE_RC}" -eq 0 ]; then
      finish 0 "remount ok unmount=${UNMOUNT_RESULT} remount=${REMOUNT_RESULT} probe=0"
    fi
    finish 20 "recovery failed unmount=${UNMOUNT_RESULT} remount=${REMOUNT_RESULT} probe=${PROBE_RESULT}"
  fi

  stray="$(stray_mountpoint "${mp}" "${snap}" "${REMOUNT_OUT}")" || stray=""
  if [ -n "${stray}" ]; then
    stray_note="$(unmount_stray "${stray}" "${unmount_t}")"
    finish 20 "recovery failed: different volume path unmount=${UNMOUNT_RESULT} remount=${REMOUNT_RESULT} stray=${stray_note}"
  fi

  finish 20 "recovery failed unmount=${UNMOUNT_RESULT} remount=${REMOUNT_RESULT} probe=not-at-mountpoint"
}

main "$@"
