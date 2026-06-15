#!/usr/bin/bash
#
# Long-running JK-BMS collector (BLE).
#
# Replaces the cron + read_jkbms.sh approach and the per-device config file.
# Reads every battery listed in JKBMS sequentially in a single loop, publishes
# to MQTT, then sleeps the remainder of INTERVAL. Because it is one process
# reading one battery at a time, BLE connections never overlap (a single
# adapter can't multiplex anyway).
#
# Config (see collector.env):
#   JKBMS           space-separated "MAC=name[=protocol]" entries, e.g.
#                   "AA:BB:CC:DD:EE:01=JKBMS1 AA:BB:CC:DD:EE:02=JKBMS2=JK02"
#                   The optional third field overrides the protocol per battery.
#   MQTT_BROKER     MQTT broker host/IP
#   JKBMS_PROTOCOL  default jkbms protocol when an entry omits one (default JK02_32)
#   INTERVAL        full-cycle target in seconds (default 30)

set -uo pipefail

MQTT_BROKER="${MQTT_BROKER:-localhost}"
JKBMS_PROTOCOL="${JKBMS_PROTOCOL:-JK02_32}"
# Per-service interval wins over the shared INTERVAL. BLE reads are slow
# (~10s per pack, sequential), so this is the practical floor for the BMS.
INTERVAL="${JKBMS_INTERVAL:-${INTERVAL:-30}}"
# Hard cap on a single battery read so a hung BLE connection (e.g. a dead or
# out-of-range pack) can't stall the loop and starve the other batteries.
# Should be comfortably above a normal read (~10s).
READ_TIMEOUT="${JKBMS_READ_TIMEOUT:-25}"
# Seconds to let the BLE adapter settle after each read. jkbms/bleak does not
# always tear the connection down cleanly; a lingering link makes the *next*
# battery's connect fail fast with rc=1, so we explicitly disconnect and pause.
SETTLE_DELAY="${JKBMS_SETTLE_DELAY:-2}"
JKBMS="${JKBMS:-}"

# Leveled logging via journald severity prefixes (SyslogLevelPrefix=yes parses
# the <N>). journald adds the timestamp and SyslogIdentifier, so we don't.
warn() { echo "<4>$*" >&2; }   # warning
err()  { echo "<3>$*" >&2; }   # error

if [[ -z "${JKBMS// /}" ]]; then
  err "no batteries configured -- set JKBMS in collector.env"
  exit 1
fi

while true; do
  start=$(date +%s)

  for entry in $JKBMS; do
    IFS='=' read -r mac name proto <<< "$entry"
    proto="${proto:-$JKBMS_PROTOCOL}"
    timeout "$READ_TIMEOUT" jkbms -P "$proto" -p "$mac" -c getCellData \
      -q "$MQTT_BROKER" -T "battery/${name}" -o json_mqtt && rc=0 || rc=$?
    if (( rc == 124 )); then
      warn "read timed out (>${READ_TIMEOUT}s) for ${name} (${mac}, ${proto})"
    elif (( rc != 0 )); then
      warn "read failed (rc=${rc}) for ${name} (${mac}, ${proto})"
    fi

    # Drop any lingering BLE connection so the next battery starts clean, then
    # let the adapter settle. Without this the next connect can fail with rc=1.
    bluetoothctl disconnect "$mac" >/dev/null 2>&1 || true
    (( SETTLE_DELAY > 0 )) && sleep "$SETTLE_DELAY"
  done

  elapsed=$(( $(date +%s) - start ))
  remainder=$(( INTERVAL - elapsed ))
  (( remainder < 1 )) && remainder=1
  sleep "$remainder"
done
