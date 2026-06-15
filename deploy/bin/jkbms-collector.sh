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
    if ! jkbms -P "$proto" -p "$mac" -c getCellData \
          -q "$MQTT_BROKER" -T "battery/${name}" -o json_mqtt; then
      warn "read failed for ${name} (${mac}, ${proto})"
    fi
  done

  elapsed=$(( $(date +%s) - start ))
  remainder=$(( INTERVAL - elapsed ))
  (( remainder < 1 )) && remainder=1
  sleep "$remainder"
done
