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
  * 
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

# BLE usage

* `cp ble/jkbms_config.conf.example jkbms_config.conf`
* Set the value as your need in `jkbms_config.conf`
* Crontab settings
`*  *  *  *  *  root /bin/bash -c /PATH_TO_THIS_DIR/ble/read_jkbms.sh >> /var/log/read_jkbms.log`

# EAsun inverter usage

* `cp easun/easun_config.conf.example easun_config.conf`
* Set the value as your need in `easun_config.conf`
* Crontab settings
  `*  *  *  *  *  root /bin/bash -c /PATH_TO_THIS_DIR/easun/read_easun.sh >> /var/log/read_easun.log`