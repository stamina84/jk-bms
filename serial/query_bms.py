#!/usr/bin/env python3

import serial

ser = serial.Serial(
        port='/dev/ttyUSB0',
        baudrate = 115200,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        bytesize=serial.EIGHTBITS,
        timeout=1
)

print('Requesting update...')
ser.write(bytes.fromhex("4E5700130000000006030000000000006800000129"))