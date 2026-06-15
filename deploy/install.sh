#!/usr/bin/bash
#
# Installer for the jk-bms / inverter systemd collectors.
# Run as root on the Ubuntu box:  sudo ./deploy/install.sh
#
# It does NOT enable/start the inverter instances automatically, because the
# ttyUSB port numbers are site-specific. The final output prints the exact
# commands to run.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root: sudo $0" >&2
  exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SRC_DIR")"

ETC_DIR=/etc/jk-bms
BIN_DIR=/opt/jk-bms/bin
UNIT_DIR=/etc/systemd/system

valid_mac() { [[ "$1" =~ ^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$ ]]; }

# --- Check CLI binaries are present (the services resolve them via PATH) ------
for bin in jkbms mpp-solar; do
  if ! command -v "$bin" >/dev/null; then
    echo "WARNING: '$bin' not found on PATH. Install with: pip install mppsolar[ble]" >&2
  fi
done

# --- Directories --------------------------------------------------------------
install -d -m 0755 "$ETC_DIR" "$BIN_DIR"

# --- Collector scripts --------------------------------------------------------
install -m 0755 "$SRC_DIR/bin/inverter-collector.sh" "$BIN_DIR/inverter-collector.sh"
install -m 0755 "$SRC_DIR/bin/jkbms-collector.sh"    "$BIN_DIR/jkbms-collector.sh"
install -m 0755 "$SRC_DIR/bin/collector-logs.sh"     "$BIN_DIR/collector-logs.sh"

# Handy combined log viewer on PATH: `jk-bms-logs`
ln -sf "$BIN_DIR/collector-logs.sh" /usr/local/bin/jk-bms-logs

# --- Shared env: collect local values, then fill the template -----------------
# MQTT_BROKER and JKBMS come from the environment if set (non-interactive),
# otherwise we prompt. An existing, edited file is never overwritten.
if [[ ! -f "$ETC_DIR/collector.env" ]]; then
  JKBMS_DEFAULT_PROTO=JK02_32
  broker="${MQTT_BROKER:-}"
  jkbms_list="${JKBMS:-}"

  if [[ ( -z "$broker" || -z "$jkbms_list" ) && ! -t 0 ]]; then
    echo "ERROR: collector.env needs MQTT_BROKER and JKBMS." >&2
    echo "For a non-interactive install, pass them in the environment:" >&2
    echo "  sudo env MQTT_BROKER=10.0.0.5 JKBMS='AA:BB:CC:DD:EE:01=JKBMS1' $0" >&2
    exit 1
  fi

  while [[ -z "$broker" ]]; do
    read -rp "MQTT broker host/IP: " broker || true
  done

  if [[ -z "$jkbms_list" ]]; then
    echo "Enter JK-BMS batteries (blank MAC to finish):"
    list=(); n=1
    while :; do
      read -rp "  battery #$n MAC: " mac || break
      [[ -z "$mac" ]] && break
      if ! valid_mac "$mac"; then
        echo "    not a valid MAC (expected AA:BB:CC:DD:EE:FF)" >&2; continue
      fi
      read -rp "    name [JKBMS$n]: " name || true; name="${name:-JKBMS$n}"
      read -rp "    protocol [$JKBMS_DEFAULT_PROTO]: " proto || true
      if [[ -n "$proto" ]]; then list+=("$mac=$name=$proto"); else list+=("$mac=$name"); fi
      n=$((n+1))
    done
    jkbms_list="${list[*]}"
  fi

  [[ -n "$jkbms_list" ]] || { echo "ERROR: at least one battery is required" >&2; exit 1; }
  for entry in $jkbms_list; do
    valid_mac "${entry%%=*}" \
      || { echo "ERROR: invalid MAC in JKBMS: '${entry%%=*}'" >&2; exit 1; }
  done

  sed -e "s#__MQTT_BROKER__#${broker}#g" -e "s#__JKBMS__#${jkbms_list}#g" \
    "$SRC_DIR/collector.env.example" > "$ETC_DIR/collector.env"
  chmod 0640 "$ETC_DIR/collector.env"
  echo "Created $ETC_DIR/collector.env (broker=$broker)"
else
  echo "Kept existing $ETC_DIR/collector.env"
fi

# --- systemd units ------------------------------------------------------------
install -m 0644 "$SRC_DIR/systemd/jkbms-collector.service"     "$UNIT_DIR/jkbms-collector.service"
install -m 0644 "$SRC_DIR/systemd/inverter-collector@.service" "$UNIT_DIR/inverter-collector@.service"

# --- journal retention (system-wide drop-in) ---------------------------------
JOURNALD_DROPIN=/etc/systemd/journald.conf.d/10-jk-bms.conf
install -d -m 0755 /etc/systemd/journald.conf.d
if install -m 0644 "$SRC_DIR/journald-jk-bms.conf" "$JOURNALD_DROPIN.new" \
   && ! cmp -s "$JOURNALD_DROPIN.new" "$JOURNALD_DROPIN" 2>/dev/null; then
  mv "$JOURNALD_DROPIN.new" "$JOURNALD_DROPIN"
  echo "Updated $JOURNALD_DROPIN; restarting systemd-journald"
  systemctl restart systemd-journald
else
  rm -f "$JOURNALD_DROPIN.new"
fi

systemctl daemon-reload

# --- Restart already-running services so a re-run applies updates -------------
# (First-time install: nothing is active yet, so this is a no-op.)
restarted=0
mapfile -t ACTIVE_UNITS < <(
  systemctl list-units --type=service --state=running --no-legend \
    'jkbms-collector.service' 'inverter-collector@*.service' 2>/dev/null \
    | awk '{print $1}'
)
for unit in "${ACTIVE_UNITS[@]:-}"; do
  [[ -z "$unit" ]] && continue
  echo "Restarting running service: $unit"
  systemctl restart "$unit"
  restarted=1
done

if [[ "$restarted" -eq 1 ]]; then
  cat <<EOF

Update applied: code/units refreshed and running services restarted.
Config files were left untouched. Check the logs:
  journalctl -u jkbms-collector -u 'inverter-collector@*' -n 50 --no-pager
EOF
  exit 0
fi

cat <<EOF

Installed. Next steps:

  1. Review config (broker + battery MACs were set above; tune INVERTER_MAP /
     INTERVAL / PATH if needed):
       sudoedit $ETC_DIR/collector.env

  2. Remove the old cron lines from /etc/crontab (read_inverter.sh x2, read_jkbms.sh).

  3. Enable and start the services (adjust the ttyUSB names for your box):
       systemctl enable --now jkbms-collector
       systemctl enable --now inverter-collector@ttyUSB0
       systemctl enable --now inverter-collector@ttyUSB1

  4. Watch the logs (combined across all devices):
       jk-bms-logs -f                 # live
       jk-bms-logs                    # last 24h warnings + errors
EOF
