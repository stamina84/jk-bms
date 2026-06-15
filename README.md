# Telegraf, influxdb config

* install influxdb2
  * `sudo apt install influxdb2`
  * Restore backup to `/var/lib/influxdb/.influxdbv2` if there is.
  * Important to not start with `influxd` with root or other user, that will create a new `.influxdbv2` dir in home directory
  * `sudo service influxdb start`
  * `sudo systemctl enable influxdb`
  * `sudo systemctl status influxdb`
* Create a new bucket `batteries` in influxdb
* install telegraf
* configure telegraf
  * `sudo su`
  * `cd /etc/telegraf/telegraf.d/`
  * `touch my_config_telegraf.conf`
  * `nano my_config_telegraf.conf`
* Install mpp-solar
  * Clone jb-blance mpp-solar git repo
  * Run `pip install mppsolar[ble]`
  * Pre-re tips:
    * install python3
    * `sudo apt-get install python3-pip libglib2.0-dev`
```
telegraf config -input-filter mqtt_consumer -output-filter influxdb_v2 > telegraf.conf
cat telegraf.conf
```

# Serial usage

* Open 2 terminal windows
* terminal #1
  * run `python3 serial/read_bms.py`
* terminal #2
  * run `watch python3 serial/query_bms.py`

# Collecting BMS / inverter data

Run the collectors as long-running **systemd services** — auto-start on boot,
restart-on-crash, journald logging, and configurable sampling for both the
JK-BMS (BLE) and the inverters (serial).

See **[deploy/README.md](deploy/README.md)** for the full
install / update / uninstall guide. The installer prompts for your MQTT broker
and battery MACs, so no local config lives in this repo.