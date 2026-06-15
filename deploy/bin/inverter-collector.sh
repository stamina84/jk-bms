#!/usr/bin/bash
#
# Long-running inverter collector for one serial port.
#
# Replaces the cron + read_inverter.sh approach. Detects the inverter type once
# at startup (by AC output active power, like the original script), then loops
# `getstatus` -> MQTT in a single sequential loop. Because it is one process
# reading one port in sequence, reads on this port can never overlap.
#
# Usage:   inverter-collector.sh <ttyUSBx>
# Config:  MQTT_BROKER, PROTOCOL, INTERVAL, INVERTER_MAP, INVERTER_<port>
#          (see collector.env)

set -uo pipefail

PORT="${1:?usage: inverter-collector.sh <ttyUSBx>}"

MQTT_BROKER="${MQTT_BROKER:-localhost}"
PROTOCOL="${PROTOCOL:-PI30}"
INTERVAL="${INTERVAL:-30}"

# Detection table: space-separated "power:name" pairs matched against the
# AC output active power reported by --getsettings. Override or extend in
# collector.env to support one or many inverters, e.g.
#   INVERTER_MAP="2400:easun 3000:sp24 5000:big"
INVERTER_MAP="${INVERTER_MAP:-2400:easun 3000:sp24}"

# Leveled logging via journald severity prefixes (SyslogLevelPrefix=yes parses
# the <N>). journald adds the timestamp and SyslogIdentifier, so we don't.
notice() { echo "<5>$*" >&2; }   # normal but significant
warn()   { echo "<4>$*" >&2; }   # warning
err()    { echo "<3>$*" >&2; }   # error

# Map AC output active power -> inverter name using INVERTER_MAP.
detect_inverter() {
  local settings pair
  settings=$(mpp-solar -p "/dev/${PORT}" -P "${PROTOCOL}" --getsettings 2>/dev/null \
    | grep ac_output_active_power) || return 1
  # shellcheck disable=SC2086
  set -- $settings
  for word in "$@"; do
    for pair in $INVERTER_MAP; do
      if [[ "$word" == "${pair%%:*}" ]]; then
        echo "${pair#*:}"
        return 0
      fi
    done
  done
  return 1
}

# A per-port override (INVERTER_<port>, e.g. INVERTER_ttyUSB0=easun) skips
# detection entirely -- handy when you already know what is on the port.
force_var="INVERTER_${PORT}"
INVERTER="${!force_var:-}"
if [[ -n "$INVERTER" ]]; then
  notice "using forced inverter '${INVERTER}' (${force_var})"
else
  until INVERTER=$(detect_inverter); do
    warn "no inverter detected (map: ${INVERTER_MAP}), retrying in ${INTERVAL}s"
    sleep "$INTERVAL"
  done
  notice "detected inverter '${INVERTER}'"
fi

while true; do
  start=$(date +%s)

  if ! mpp-solar -p "/dev/${PORT}" -P "${PROTOCOL}" --getstatus \
        -q "${MQTT_BROKER}" -T "inverter/${INVERTER}" -o json_mqtt; then
    warn "getstatus failed"
  fi

  elapsed=$(( $(date +%s) - start ))
  remainder=$(( INTERVAL - elapsed ))
  (( remainder < 1 )) && remainder=1
  sleep "$remainder"
done
