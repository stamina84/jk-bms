#!/usr/bin/bash
#
# Uninstall the jk-bms / inverter systemd collectors.
# Stops and disables all collector services, removes the unit files and the
# installed script. By default it KEEPS /etc/jk-bms config; pass --purge to
# remove that too.
#
#   sudo ./deploy/uninstall.sh            # remove services, keep config
#   sudo ./deploy/uninstall.sh --purge    # also remove /etc/jk-bms

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root: sudo $0" >&2
  exit 1
fi

PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1

ETC_DIR=/etc/jk-bms
BIN_DIR=/opt/jk-bms
UNIT_DIR=/etc/systemd/system

# --- Stop & disable every collector unit (BMS + all inverter instances) -------
mapfile -t UNITS < <(
  systemctl list-units --all --type=service --no-legend \
    'jkbms-collector.service' 'inverter-collector@*.service' 2>/dev/null \
    | awk '{print $1}'
)
# Always include the base instances in case they are loaded but not listed.
for unit in "${UNITS[@]:-}" jkbms-collector.service; do
  [[ -z "$unit" ]] && continue
  echo "Stopping and disabling $unit"
  systemctl disable --now "$unit" 2>/dev/null || true
done

# --- Remove unit files --------------------------------------------------------
rm -f "$UNIT_DIR/jkbms-collector.service" \
      "$UNIT_DIR/inverter-collector@.service"

# --- Remove journal retention drop-in -----------------------------------------
if [[ -f /etc/systemd/journald.conf.d/10-jk-bms.conf ]]; then
  rm -f /etc/systemd/journald.conf.d/10-jk-bms.conf
  systemctl restart systemd-journald
fi

systemctl daemon-reload
systemctl reset-failed 2>/dev/null || true

# --- Remove installed scripts and the jk-bms-logs symlink ---------------------
rm -f /usr/local/bin/jk-bms-logs
rm -rf "$BIN_DIR"

# --- Optionally remove config -------------------------------------------------
if [[ "$PURGE" -eq 1 ]]; then
  rm -rf "$ETC_DIR"
  echo "Removed $ETC_DIR (config purged)."
else
  echo "Kept $ETC_DIR (config preserved). Re-run with --purge to remove it."
fi

cat <<'EOF'

Uninstalled. The collector services are stopped, disabled, and removed.
Note: this does not restore the old cron jobs -- re-add them manually if needed.
EOF
