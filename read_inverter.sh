#!/usr/bin/bash

INPUT_NAME="$1"
# Set MQTT_BROKER in the environment (e.g. export MQTT_BROKER=10.0.0.5).
MQTT_BROKER="${MQTT_BROKER:-localhost}"
ACTIVE_POWER=$(mpp-solar -p /dev/${INPUT_NAME} -P PI30 --getsettings | grep ac_output_active_power)
#echo "${ACTIVE_POWER}"

INVERTER=""

set - $ACTIVE_POWER
for word in "$@"
do
  # You can setup multiple inverter based on active power
  if [ "$word" = "2400" ]; then
    INVERTER="easun"
  fi
  if [ "$word" = "3000" ]; then
    INVERTER="sp24"
  fi
done

if [ ! "$INVERTER" = "" ]; then
  #echo "${INVERTER}"
  COMMAND="mpp-solar -p /dev/${INPUT_NAME} -P PI30 --getstatus  -q ${MQTT_BROKER} -T inverter/${INVERTER} -o json_mqtt"
  #echo "$COMMAND"
  eval "$COMMAND"
  sleep 25
  eval "$COMMAND"
fi
