# Server side — MQTT → Telegraf → InfluxDB → Grafana

This is the **data side**. It runs on the box that stores and visualises the
metrics, not on the box that reads the hardware (that's the client — see
[../deploy/README.md](../deploy/README.md)). The client publishes to MQTT;
Telegraf consumes those topics and writes them to InfluxDB, which Grafana reads.

```
client (deploy/) ── MQTT ──> Telegraf ──> InfluxDB ──> Grafana
                              (this box / these configs)
```

## Telegraf configs

Drop these into `/etc/telegraf/telegraf.d/` (one file per measurement):

| File | MQTT topic | InfluxDB bucket | Measurement |
|------|-----------|-----------------|-------------|
| [telegraf/battery.conf](telegraf/battery.conf) | `battery/#` | `batteries` | `battery` |
| [telegraf/inverter.conf](telegraf/inverter.conf) | `inverter_easun/#` | `inverter_easun` | `inverter_easun` |

Each file is self-contained: an `mqtt_consumer` input and an `influxdb_v2`
output. Set the InfluxDB `urls`, `token`, `organization`, and `bucket` to match
your install before starting Telegraf. `battery.conf` also renames the JK-BMS
JSON fields to short Grafana-friendly names (`V`, `SOC`, `Temp1`, …) and drops
the unused per-cell/resistance fields.

## 1. InfluxDB 2

```bash
sudo apt install influxdb2
# Restore a backup to /var/lib/influxdb/.influxdbv2 if you have one.
# Do NOT run `influxd` as root or another user first — it creates a fresh
# .influxdbv2 in that user's home directory.
sudo service influxdb start
sudo systemctl enable influxdb
sudo systemctl status influxdb
```

Then create a bucket named `batteries` (and `inverter_easun`) in the InfluxDB UI
or CLI, and generate an API token for Telegraf.

## 2. Telegraf

```bash
sudo apt install telegraf
sudo cp telegraf/battery.conf telegraf/inverter.conf /etc/telegraf/telegraf.d/
# edit each to set your InfluxDB url / token / org / bucket
sudo systemctl restart telegraf
sudo systemctl enable telegraf
```

Generate a fresh base config to diff against if needed:

```bash
telegraf config -input-filter mqtt_consumer -output-filter influxdb_v2 > telegraf.conf
```

## 3. Grafana

Add InfluxDB as a data source (Flux or InfluxQL) pointing at the buckets above,
then build dashboards on the `battery` and `inverter_easun` measurements.

## Prerequisites note

The client publishes via `mpp-solar` / `jkbms` (`pip install mppsolar[ble]`).
Pre-reqs on Debian/Ubuntu: `sudo apt-get install python3-pip libglib2.0-dev`.
See [../deploy/README.md](../deploy/README.md) for the collector setup.
