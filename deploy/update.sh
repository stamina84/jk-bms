#!/usr/bin/bash
#
# Update the collectors on the remote box: pull the latest code, then re-run the
# installer (which refreshes the script + units and restarts running services,
# leaving /etc/jk-bms config untouched).
#
#   sudo ./deploy/update.sh

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root: sudo $0" >&2
  exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SRC_DIR")"

echo "Pulling latest changes in $REPO_DIR ..."
git -C "$REPO_DIR" pull --ff-only

echo "Re-running installer ..."
exec "$SRC_DIR/install.sh"
