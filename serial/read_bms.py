#!/usr/bin/env python3

import os
import serial
from datetime import datetime

def store_data(d_s):
	os.system('clear')
#	print(data)
	j = d_s.find('06000179')+8
	if j > 0:
#		print('-------------------------')
		length = 2 * int(d_s[j:j+2],16)
		#print(length)
		celldata = d_s[j+2:j+length+2]
#		print(celldata)
		j=j+length+2
		t0 = int(d_s[j+2:j+6],16)
		if not t0 or t0 > 99 or t0 < -99: t0=0
		t1 = int(d_s[j+8:j+12],16)
		if not t1 or t1 > 99 or t1 < -99: t1=0
		t2 = int(d_s[j+14:j+18],16)
		if not t2 or t2 > 99 or t2 < -99: t2=0
		dcv = int(d_s[j+20:j+24],16) / 100
		if not dcv: dcv=-1
		sign = int(d_s[j+26:j+27],16)
		if sign == 8: sign = 1
		else: sign = -1
		dcc_correction = '0'

        if sign >= 8:
            # Case charge: first hex increased by 8
            dcc_correction = str(sign - 8)
            sign = 1
        else: sign = -1
#       print(d_s[j+26:j+30], '26-30')
#       print(d_s[j+30:j+31], '30-31')
#       print('corrected', dcc_correction + d_s[j+27:j+30])
        dcc = sign * int(dcc_correction + d_s[j+27:j+30],16) / 100
		if dcc == '': dcc=99
		soc = int(d_s[j+32:j+34],16)
		if not soc: soc=-1
		cyc = int(d_s[j+40:j+44],16)
		if not cyc: cyc=-1
		alm = int(d_s[j+62:j+66],16)
		if alm == '': alm=255
		sts = int(d_s[j+68:j+72],16)
		if not sts: sts=255
		bal = int(d_s[j+68+96:j+68+98],16)
		if bal == '': bal=9
		j=2
		v01 = int(celldata[j:j+4],16) / 1000
		if not v01: v01=0
		v02 = int(celldata[j+6:j+10],16) /1000
		if not v02: v02=0
		v03 = int(celldata[j+12:j+16],16) /1000
		if not v03: v03=0
		v04 = int(celldata[j+18:j+22],16) /1000
		if not v04: v04=0
		v05 = int(celldata[j+24:j+28],16) /1000
		if not v05: v05=0
		v06 = int(celldata[j+30:j+34],16) /1000
		if not v06: v06=0
		v07 = int(celldata[j+36:j+40],16) /1000
		if not v07: v07=0
		v08 = int(celldata[j+42:j+46],16) /1000
		if not v08: v08=0
		#v09 = int(celldata[j+48:j+52],16) /1000
		#if not v09: v09=0
		#v10 = int(celldata[j+54:j+58],16) /1000
		#if not v10: v10=0
		#v11 = int(celldata[j+60:j+64],16) /1000
		#if not v11: v11=0
		#v12 = int(celldata[j+66:j+70],16) /1000
		#if not v12: v12=0
		#v13 = int(celldata[j+72:j+76],16) /1000
		#if not v13: v13=0
		#v14 = int(celldata[j+78:j+82],16) /1000
		#if not v14: v14=0
		#v15 = int(celldata[j+84:j+88],16) /1000
		#if not v15: v15=0
		#v16 = int(celldata[j+90:j+94],16) /1000
		#if not v16: v16=0

		record = v01,v02,v03,v04,v05,v06,v07,v08
		print('voltages: ', record)
		print('t0:', t0,'C')
		print('t1:', t1,'C')
		print('t2:', t2,'C')
		print('VOLTAGE:', dcv,'V')
		print('CURRENT:', dcc,'A')
#		print('sign:', sign)
		print('POWER:', round(dcv*dcc,2), 'W')
		print('SOC:', soc, '%')
		print('ALARM:', alm)
		print('sts', sts)
        print('cyc',cyc)
        if not dcc == 0 and sign == 1: print('Estimate hour 100%:',round((280-soc*280/100)/dcc,1),'h')
        if not dcc == 0 and sign == -1: print('Estimate hour 0%:',round((-1 * soc*280/100)/dcc,1),'h')

ser = serial.Serial(
        port='/dev/ttyUSB0',
        baudrate = 115200,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        bytesize=serial.EIGHTBITS,
        timeout=0.1
)

receive = 0
data = ''
while 1:
	x = ser.read(1)
	if x:
		c = hex(int.from_bytes(x,byteorder='big'))[2:].zfill(2).upper()
		if receive == 4:
			data = data+c
			lng = lng-1
			if lng == 0:
				receive = 0
				store_data(data)
				data = ''
		if receive == 3:
			lng = int(lng+c,16) - 2
			receive = 4
			data = data+c
		if receive == 2:
			lng = c
			receive = 3
			data = '4E57'+lng
		if receive == 1:
			if c == '57':
				receive = 2
			else:
				receive = 0
		if receive == 0:
			if c == '4E':
				receive = 1