#!/usr/bin/bash

INPUT_NAME="$1"
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
  COMMAND="mpp-solar -p /dev/${INPUT_NAME} -P PI30 --getstatus  -q 192.168.10.4 -T inverter/${INVERTER} -o json_mqtt"
  #echo "$COMMAND"
  eval "$COMMAND"
  sleep 25
  eval "$COMMAND"
fi
