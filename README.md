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

# Running as systemd services (recommended)

Instead of the cron jobs below, you can run the collectors as long-running
systemd services (auto-start, restart-on-crash, journald logs, no cron
one-minute limit). See [deploy/README.md](deploy/README.md).

# BLE usage

* `cp ble/jkbms_config.conf.example jkbms_config.conf`
* Set the value as your need in `jkbms_config.conf`
* Crontab settings
* `sudo nano /etc/crontab`
`*  *  *  *  *  root /bin/bash -c /PATH_TO_THIS_DIR/ble/read_jkbms.sh >> /var/log/read_jkbms.log`

# Inverter usage

* `cp easun/easun_config.conf.example easun_config.conf`
  * TODO ignore the input path
* Set the value as your need in `easun_config.conf`
* Crontab settings
* `sudo nano /etc/crontab`
  * `*  *  *  *  *  root /bin/bash -c "/PATH_TO_THIS_DIR/read_inverter.sh ttyUSB0" >> /var/log/read_inverter_usb0.log`