# Running the collectors as systemd services

Replaces the three `cron` jobs (`read_inverter.sh ttyUSB0/1`, `read_jkbms.sh`)
with long-running **systemd services**. Goal for this first step: reproduce the
original ~30s sampling cadence, but with auto-start on boot, restart-on-crash,
and `journald` logging — and without the cron one-minute limit or the
`sleep` + double-read hack.

> Live (10–15s) vs long-term (30–60s) two-tier data is intentionally **out of
> scope here** and will be done later (most likely via an InfluxDB downsampling
> task, so the hardware is still read only once).

## Why a long-running loop solves the overlap problem

Each device is read by a **single process that loops in sequence**, so a read
can never start before the previous one finishes — important for BLE (one
adapter can't multiplex connections) and for the exclusive serial ports.

- **JK-BMS (BLE):** `jkbms-collector.sh` reads every battery in `JKBMS` one at a
  time in a single loop, then sleeps the remainder of `INTERVAL`. One service,
  one BLE connection at a time.
- **Inverters (serial):** `inverter-collector.sh <port>` detects the inverter
  once, then loops `getstatus` → MQTT. It times each read and sleeps only for
  the remainder, so the cadence is `max(read_time, INTERVAL)` and never stacks.
- Each inverter is a separate **instance** of the templated service on its own
  port (`ttyUSB0`, `ttyUSB1`, …), so they don't contend with each other. Enable
  one for a single inverter, or several for multiple.

### Configuring which inverters exist

The power→name mapping lives in `collector.env`, not in the script:

```ini
# space-separated "power:name" pairs, matched on AC output active power
INVERTER_MAP=2400:easun 3000:sp24 5000:big

# optional: force a port to a known inverter and skip auto-detection
#INVERTER_ttyUSB0=easun
```

The matched name becomes the MQTT topic suffix (`inverter/<name>`). Add a pair
per model; use `INVERTER_<port>` when you already know what's on a port.

### Configuring which batteries exist

The JK-BMS MACs live in `collector.env` too (no per-device config file).
`install.sh` fills them in at install time (see step 2); afterwards they look
like this — substitute your own MACs:

```ini
# space-separated "MAC=name[=protocol]" entries; each -> topic battery/<name>
JKBMS=AA:BB:CC:DD:EE:01=JKBMS1 AA:BB:CC:DD:EE:02=JKBMS2
JKBMS_PROTOCOL=JK02_32      # default when an entry omits the 3rd field
```

Add an entry per pack. They are read sequentially in one loop, so any number of
batteries shares the single BLE adapter without overlapping. The optional third
field sets a per-battery protocol for mixed-firmware setups, e.g.
`AA:BB:CC:DD:EE:02=JKBMS2=JK02`.

## Prerequisites

`mpp-solar` and `jkbms` must be installed and on root's PATH (the services
resolve them via the `PATH` set in `collector.env`):

```bash
pip install mppsolar[ble]
which mpp-solar jkbms      # note the path; defaults assume /usr/local/bin
```

## 1. Measure your read times (do this on the box)

Each service has its own interval, so measure both device types:

```bash
# Serial inverter read (typically ~1-2s)
time mpp-solar -p /dev/ttyUSB0 -P PI30 --getstatus

# BLE BMS read, one battery (typically ~10s — mostly BLE connect overhead)
time jkbms -P JK02_32 -p AA:BB:CC:DD:EE:01 -c getCellData -o screen
```

The collector sleeps `interval - read_time` between cycles (1s floor), so an
interval below the read time just means "read as fast as the hardware allows".
Tune in `collector.env`:

- **`INVERTER_INTERVAL`** — serial is fast, so `5` (or even `3`) is fine.
- **`JKBMS_INTERVAL`** — BLE is the bottleneck. The BMS service reads every
  battery in `JKBMS` *sequentially* (one BLE adapter can't multiplex), so the
  floor per cycle is roughly `packs × read_time`. With two ~10s packs you're
  already at ~20s; `JKBMS_INTERVAL=30` (or as low as ~25) is about as fast as it
  gets — lowering it further won't help.
- **`INTERVAL`** — shared fallback used when a per-service override is unset.

## 2. Install

The repo ships no real broker IP or BMS MACs — `install.sh` collects them and
writes `/etc/jk-bms/collector.env` (mode `0640`). Two ways:

```bash
# Interactive: prompts for the MQTT broker, then each battery (MAC, name, protocol)
sudo ./deploy/install.sh

# Non-interactive: pass the values in the environment (note `sudo env`)
sudo env MQTT_BROKER=10.0.0.5 \
         JKBMS='AA:BB:CC:DD:EE:01=JKBMS1 AA:BB:CC:DD:EE:02=JKBMS2' \
         ./deploy/install.sh
```

MACs are validated (`AA:BB:CC:DD:EE:FF`). A non-interactive run with the values
missing is a hard error. This installs:

| Path | What |
|------|------|
| `/opt/jk-bms/bin/inverter-collector.sh` | inverter loop script |
| `/opt/jk-bms/bin/jkbms-collector.sh` | JK-BMS loop script |
| `/opt/jk-bms/bin/collector-logs.sh` → `/usr/local/bin/jk-bms-logs` | combined log viewer |
| `/etc/jk-bms/collector.env` | shared config, filled by installer, mode `0640` (broker, MACs, inverter map, `INTERVAL`, PATH) |
| `/etc/systemd/system/jkbms-collector.service` | BMS service |
| `/etc/systemd/system/inverter-collector@.service` | templated inverter service |
| `/etc/systemd/journald.conf.d/10-jk-bms.conf` | journal retention caps (system-wide) |

An existing `collector.env` is never overwritten.

## 3. Configure (optional)

The broker and battery MACs are already set by the installer. Edit the file to
tune the rest (`INVERTER_MAP`, `INTERVAL`, `PATH`) or add/remove batteries:

```bash
sudoedit /etc/jk-bms/collector.env
```

## 4. Remove the old cron jobs

Edit `/etc/crontab` and delete the three lines:

```
*  *  *  *  *  root /bin/bash -c "/home/unas/read_inverter.sh ttyUSB1"
*  *  *  *  *  root /bin/bash -c "/home/unas/read_inverter.sh ttyUSB0"
*  *  *  *  *  root /bin/bash -c /home/unas/jkbms-influxdb-grafana/read_jkbms.sh
```

## 5. Enable and start

```bash
systemctl enable --now jkbms-collector
systemctl enable --now inverter-collector@ttyUSB0
systemctl enable --now inverter-collector@ttyUSB1
```

## 6. Verify

```bash
systemctl status jkbms-collector 'inverter-collector@*'
journalctl -u jkbms-collector -f
journalctl -u 'inverter-collector@*' -f
```

You should see one publish per device roughly every `INTERVAL` seconds, and the
same MQTT topics as before (`battery/JKBMS1`, `inverter/easun`, `inverter/sp24`)
flowing into Telegraf → InfluxDB → Grafana.

## Logs

Everything goes to the systemd journal — no log files. Services are tagged via
`SyslogIdentifier`: `jkbms` for the BMS, `inverter-<port>` (e.g.
`inverter-ttyUSB0`) for each inverter.

**Quick combined view across all devices** — `install.sh` puts `jk-bms-logs` on
your PATH (may need `sudo` to read the system journal):

```bash
jk-bms-logs                 # last 24h: warnings + errors, BMS + all inverters
jk-bms-logs -p err          # errors only
jk-bms-logs -s "2 days ago" # custom window
jk-bms-logs -f              # follow live
jk-bms-logs -h              # help
```

Or hit journald directly:

```bash
# By unit
journalctl -u jkbms-collector -f
journalctl -u 'inverter-collector@*' --since "24 hours ago"

# By tag (identifier)
journalctl -t jkbms -t inverter-ttyUSB0 --since today

# Only problems (see severity table below)
journalctl -u jkbms-collector -p warning --since "24 hours ago"
```

**Severity levels** the collectors emit (filter with `-p <level>`, which shows
that level *and* more severe):

| Level | When the collectors use it |
|-------|----------------------------|
| `err` (3) | fatal misconfig (e.g. no batteries configured) |
| `warning` (4) | a single read/publish failed, or no inverter detected yet |
| `notice` (5) | startup events (inverter detected / forced) |
| `info` (6) | default for the mpp-solar / jkbms tool output |

**Retention** is bounded by a system-wide journald drop-in installed at
`/etc/systemd/journald.conf.d/10-jk-bms.conf`: persistent storage, `200M` max on
disk, `30day` max age — far more than the 24h you need. Check usage with
`journalctl --disk-usage`; edit the drop-in to tune.

## Updating later

`install.sh` is idempotent: it refreshes the collector script and unit files,
**never overwrites** `/etc/jk-bms/collector.env`, and
restarts any services that are currently running. So to ship changes:

```bash
cd /path/to/jk-bms
sudo ./deploy/update.sh      # git pull --ff-only, then re-run install.sh
```

Or, if you updated the working copy by other means, just re-run
`sudo ./deploy/install.sh`. If you changed config, restart manually:

```bash
sudo systemctl restart jkbms-collector 'inverter-collector@*'
```

## Uninstall

Stop, disable, and remove all collector services and the installed script:

```bash
sudo ./deploy/uninstall.sh            # keeps /etc/jk-bms config
sudo ./deploy/uninstall.sh --purge    # also removes /etc/jk-bms config
```

This does not restore the old cron jobs — re-add them manually if you want them.

## Rollback

To temporarily stop without uninstalling:

```bash
systemctl disable --now jkbms-collector inverter-collector@ttyUSB0 inverter-collector@ttyUSB1
```

then restore the cron lines.

## Notes / possible follow-ups

- **Stable serial names:** USB ports can re-enumerate on reboot. The collector
  re-detects the inverter type by AC power each startup, so a swap is handled,
  but a `udev` rule giving fixed `/dev/inverter-easun` style names would make the
  unit instances deterministic.
- **Two-tier (live + long-term) data:** deferred — planned as an InfluxDB
  downsampling task from a short-retention high-res bucket to a long-retention
  aggregated bucket.
