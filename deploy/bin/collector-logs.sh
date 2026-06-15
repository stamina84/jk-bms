#!/usr/bin/bash
#
# Combined journal viewer for all jk-bms collectors (BMS + every inverter).
# Installed as /usr/local/bin/jk-bms-logs.
#
# Defaults: last 24h, warning level and above, all devices.
#
#   jk-bms-logs                 # last 24h: warnings + errors, all devices
#   jk-bms-logs -p err          # errors only
#   jk-bms-logs -p info         # everything (incl. normal tool output)
#   jk-bms-logs -s "2 days ago" # custom window
#   jk-bms-logs -s today        # since midnight
#   jk-bms-logs -f              # follow live
#   jk-bms-logs -- -o cat       # pass extra args straight to journalctl
#
# Reading the system journal usually needs root or the systemd-journal group;
# run with sudo if you see nothing.

set -euo pipefail

SINCE="24 hours ago"
PRIORITY="warning"
FOLLOW=0

usage() { grep '^#' "$0" | sed 's/^# \{0,1\}//; 1d'; }

while getopts ":s:p:fh" opt; do
  case "$opt" in
    s) SINCE="$OPTARG" ;;
    p) PRIORITY="$OPTARG" ;;
    f) FOLLOW=1 ;;
    h) usage; exit 0 ;;
    \?) echo "unknown option: -$OPTARG" >&2; usage; exit 2 ;;
    :)  echo "option -$OPTARG requires a value" >&2; exit 2 ;;
  esac
done
shift $((OPTIND - 1))

ARGS=( -u jkbms-collector -u 'inverter-collector@*'
       --since "$SINCE" --priority "$PRIORITY"
       --output short-iso )
if (( FOLLOW )); then
  ARGS+=( -f )
else
  ARGS+=( --no-pager )
fi

exec journalctl "${ARGS[@]}" "$@"
