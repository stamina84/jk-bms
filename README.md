# JK-BMS + inverter monitoring

Reads **JK-BMS** battery packs over BLE and **Easun / SP24** inverters over
serial, publishes the metrics to MQTT, and stores them in InfluxDB for Grafana
dashboards.

```
JK-BMS (BLE)  ─┐
               ├─> collectors ──MQTT──> Telegraf ──> InfluxDB ──> Grafana
inverters     ─┘   (deploy/)            (server/)
 (serial)
```

The repo is split into the two machines involved:

| Dir | Side | What it is |
|-----|------|------------|
| **[deploy/](deploy/README.md)** | **client** | Long-running systemd collectors that read the hardware and publish to MQTT — plus install / update / uninstall scripts and a manual serial reader. |
| **[server/](server/README.md)** | **server** | Telegraf configs and the InfluxDB / Grafana setup that consume MQTT and store/visualise the data. |

(Client and server are often the same physical box, but the configuration is
kept separate.)

## Quick start

- **Collecting data** (the box wired to the batteries/inverters):
  see **[deploy/README.md](deploy/README.md)**. The installer prompts for your
  MQTT broker and battery MACs, so no local config lives in this repo.
- **Storing & charting data** (Telegraf → InfluxDB → Grafana):
  see **[server/README.md](server/README.md)**.
- **Manual serial debugging** of a single pack:
  see **[deploy/serial/README.md](deploy/serial/README.md)**.
