#!/usr/bin/env python3
#
# Long-running JK *inverter*-BMS collector for one RS485 port -- MODBUS mode.
#
# Companion to jkpb-collector.py. Same BMS (PB series, e.g. JK-PB2A16S15P v19),
# same wire, different protocol: this speaks "JK BMS RS485 Modbus" (the app's
# UART protocol entry 013) instead of the 4G-GPS/NW (0x4E57) protocol.
#
# Why bother: the NW protocol has NO balance-current register at all. Its whole
# register map (0x79..0xC0, see docs JKSerial-TTL-20201217) carries only balance
# *settings* and one "balancer active" status bit. This protocol exposes live
# balance current, per-cell wire resistances, SOH, and BMS-computed power.
#
# Wiring / setup that this was verified against:
#   * app -> Settings -> UART1 Protocol No. = "013 - (9600) JK BMS RS485 modbus"
#   * the RJ45 that the 4G-GPS protocol previously used (RS485 pins 1/2 + 7/8)
#   * 9600 baud, Modbus RTU, slave address 15 -- NOT 1. The address appears to
#     be fixed per unit, so AUTO-DETECT is the default (see JKPBM_ADDR).
#
# Protocol notes (these cost some time to work out, so they are written down):
#   * Function 0x03 (read holding registers).
#   * The register address is a BYTE OFFSET, not a register index: CellVol0 is
#     at 0x1200 and CellVol1 at 0x1202. A read of N registers at address A
#     therefore returns the values at A, A+2, ... A+2(N-1).
#   * 64 registers (128 bytes) per read is accepted; larger is not.
#   * The USB adapter echoes transmitted bytes back on half-duplex, and the echo
#     is 8 bytes = 4 registers, so a naive parse silently shifts the whole block
#     by 4. Responses are located by scanning for a CRC-valid frame instead.
#   * 32-bit values are big-endian across the two registers.
#
# Register map from the JK "BMS RS485 Modbus V1.1" spec, cross-checked against
# syssi/esphome-jk-bms (esp32-jk-pb-modbus-example.yaml).
#
# Usage:
#   jkpb-modbus-collector.py <ttyUSBx>           # normal: read -> MQTT, loop
#   jkpb-modbus-collector.py <ttyUSBx> --debug   # decode -> screen, never publish
#   jkpb-modbus-collector.py <ttyUSBx> --probe   # one-shot read + full dump
#
# Config (env):
#   MQTT_BROKER / MQTT_PORT   broker (default localhost:1883)
#   JKPBM_NAME                topic suffix -> battery/<name>/mpp-solar
#                             (default jkpbm). Per-port JKPBM_<port> wins.
#   JKPBM_ADDR                modbus slave address; "auto" (default) scans 1-16
#   JKPBM_BAUD                serial baud (default 9600)
#   JKPB_INTERVAL / INTERVAL  seconds between reads (default 30)
#   DEBUG                     1 for screen-only mode

import json
import os
import struct
import sys
import time

def _log(level, msg): print(f"<{level}>{msg}", file=sys.stderr, flush=True)
def notice(msg): _log(5, msg)
def warn(msg):   _log(4, msg)
def err(msg):    _log(3, msg)

try:
    import serial
except ImportError:
    err("pyserial not installed -- run: pip install pyserial")
    sys.exit(1)

def env(name, default=None):
    v = os.environ.get(name)
    return v if v not in (None, "") else default

if len(sys.argv) < 2:
    err("usage: jkpb-modbus-collector.py <ttyUSBx> [--debug|--probe]")
    sys.exit(2)

PORT  = sys.argv[1]
FLAGS = sys.argv[2:]
PROBE = "--probe" in FLAGS
DEBUG = ("--debug" in FLAGS) or (env("DEBUG", "0") not in ("0", "false", ""))

BROKER    = env("MQTT_BROKER", "localhost")
MQTT_PORT = int(env("MQTT_PORT", "1883"))
BAUD      = int(env("JKPBM_BAUD", "9600"))
INTERVAL  = int(env("JKPB_INTERVAL", env("INTERVAL", "30")))
_addr     = env("JKPBM_ADDR", "auto")
ADDR      = None if _addr == "auto" else int(_addr)

NAME  = env(f"JKPBM_{PORT}", env("JKPBM_NAME", "jkpbm"))
TOPIC = f"battery/{NAME}/mpp-solar"

MAX_CELLS = 16

# --- modbus RTU ---------------------------------------------------------------
def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc

def _crc_ok(f):
    return len(f) >= 4 and crc16(f[:-2]) == (f[-2] | (f[-1] << 8))

def read_regs(ser, addr, reg, count, timeout=1.5):
    """Read `count` 16-bit values starting at byte-address `reg`.

    Returns the raw bytes, or None. The response is located by scanning for a
    CRC-valid frame so the half-duplex request echo cannot shift the parse.
    """
    q = bytes([addr, 0x03, reg >> 8, reg & 0xFF, count >> 8, count & 0xFF])
    c = crc16(q)
    q += bytes([c & 0xFF, c >> 8])
    ser.reset_input_buffer()
    ser.write(q)
    ser.flush()
    buf = bytearray()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        chunk = ser.read(128)
        if chunk:
            buf += chunk
        for st in range(0, max(0, len(buf) - 3)):
            if buf[st] != addr:
                continue
            fn = buf[st + 1] if st + 1 < len(buf) else None
            if fn == 0x83 and len(buf) - st >= 5 and _crc_ok(bytes(buf[st:st + 5])):
                return None                      # exception reply
            if fn == 0x03 and len(buf) - st >= 3:
                n = buf[st + 2]
                end = st + 3 + n + 2
                if len(buf) >= end and _crc_ok(bytes(buf[st:end])):
                    return bytes(buf[st + 3:st + 3 + n])
    return None

def detect_address(ser):
    """Find the slave address. JK ships these on 15, not the Modbus-usual 1."""
    for addr in [15, 1] + [a for a in range(2, 17) if a != 15]:
        # a one-register read of the first cell voltage: only the right address
        # produces a CRC-valid 0x03 reply, so this cannot false-positive
        if read_regs(ser, addr, 0x1200, 1, timeout=0.6) is not None:
            return addr
    return None

# --- decoding -----------------------------------------------------------------
class Block:
    """Holds the raw status blocks and indexes them by byte-address."""
    def __init__(self, blocks): self.blocks = blocks
    def raw(self, a, n):
        for base, v in self.blocks.items():
            off = a - base
            if 0 <= off <= len(v) - n:
                return v[off:off + n]
        raise KeyError(f"address 0x{a:04X} not in any block")
    def u16(self, a): return struct.unpack(">H", self.raw(a, 2))[0]
    def i16(self, a): return struct.unpack(">h", self.raw(a, 2))[0]
    def u32(self, a): return struct.unpack(">I", self.raw(a, 4))[0]
    def i32(self, a): return struct.unpack(">i", self.raw(a, 4))[0]
    def u8pair(self, a):
        r = self.raw(a, 2)
        return r[0], r[1]

def read_status(ser, addr):
    blocks = {}
    for base, count in ((0x1200, 64), (0x1280, 64)):
        v = read_regs(ser, addr, base, count)
        if v is None:
            return None
        blocks[base] = v
    return Block(blocks)

def parse(b):
    d = {}

    cells = [b.u16(0x1200 + 2 * i) for i in range(MAX_CELLS)]
    present = [(i + 1, mv) for i, mv in enumerate(cells) if mv]
    for n, mv in present:
        d[f"voltage_cell{n:02d}"] = round(mv / 1000.0, 3)
    for n, _ in present:
        r = b.u16(0x124A + 2 * (n - 1))
        if r:
            d[f"resistance_cell{n:02d}"] = round(r / 1000.0, 3)

    d["average_cell_voltage"] = round(b.u16(0x1244) / 1000.0, 3)
    d["delta_cell_voltage"]   = round(b.u16(0x1246) / 1000.0, 3)
    hi, lo = b.u8pair(0x1248)
    d["max_voltage_cell"] = hi + 1        # the BMS reports 0-based cell numbers
    d["min_voltage_cell"] = lo + 1

    d["mos_temp"]   = round(b.i16(0x128A) / 10.0, 1)
    d["battery_t1"] = round(b.i16(0x129C) / 10.0, 1)
    d["battery_t2"] = round(b.i16(0x129E) / 10.0, 1)

    d["battery_voltage"] = round(b.u32(0x1290) / 1000.0, 3)

    # Signed: + charging, - discharging (same convention as jkpb-collector.py).
    current = b.i32(0x1298) / 1000.0
    d["current"] = round(current, 2) or 0.0
    d["current_charge"]    = round(current, 2) if current > 0 else 0.0
    d["current_discharge"] = round(-current, 2) if current < 0 else 0.0

    # BatWatt is a magnitude; sign it from the current so the field means the
    # same thing it does in the NW collector.
    power = b.u32(0x1294) / 1000.0
    d["battery_power"] = round(power if current >= 0 else -power, 2) or 0.0

    # --- the fields this protocol exists for ---------------------------------
    d["balance_current"] = round(b.i16(0x12A4) / 1000.0, 3) or 0.0
    bal_status, soc = b.u8pair(0x12A6)
    d["balance_status"] = bal_status          # 0 off, 1 charging, 2 discharging
    d["balancing"] = 1 if bal_status else 0

    d["percent_remain"]   = soc
    d["capacity_remain"]  = round(b.i32(0x12A8) / 1000.0, 2)
    d["nominal_capacity"] = round(b.u32(0x12AC) / 1000.0, 2)
    d["cycle_count"]      = b.u32(0x12B0)
    d["cycle_capacity"]   = round(b.u32(0x12B4) / 1000.0, 2)
    soh, _precharge = b.u8pair(0x12B8)
    d["state_of_health"]  = soh
    d["alarm_bitmask"]    = b.u32(0x12A0)
    d["uptime"]           = b.u32(0x12BC)
    chg, dsg = b.u8pair(0x12C0)
    d["charge_enabled"]    = chg
    d["discharge_enabled"] = dsg
    return d

# --- output -------------------------------------------------------------------
BAL = {0: "off", 1: "charging", 2: "discharging"}

def print_debug(d, addr):
    print("\033[2J\033[H", end="")
    print(f"JK-PB (modbus, addr {addr}) @ /dev/{PORT}  ->  DEBUG, not publishing")
    print(f"topic would be: {TOPIC}")
    print("-" * 62)
    for k in sorted(k for k in d if k.startswith("voltage_cell")):
        n = k[-2:]
        r = d.get(f"resistance_cell{n}")
        mark = ""
        if d.get("max_voltage_cell") == int(n): mark = "  <- max"
        if d.get("min_voltage_cell") == int(n): mark = "  <- min"
        extra = f"   {r:.3f} mOhm" if r is not None else ""
        print(f"  {k:22s} {d[k]:.3f} V{extra}{mark}")
    print()
    for k in ("average_cell_voltage", "delta_cell_voltage", "battery_voltage",
              "current", "current_charge", "current_discharge", "battery_power",
              "balance_current", "balance_status", "balancing",
              "percent_remain", "capacity_remain", "nominal_capacity",
              "state_of_health", "cycle_count", "cycle_capacity",
              "mos_temp", "battery_t1", "battery_t2",
              "alarm_bitmask", "charge_enabled", "discharge_enabled", "uptime"):
        if k in d:
            v = d[k]
            if k == "balance_status":
                v = f"{v} ({BAL.get(v, '?')})"
            print(f"  {k:22s} {v}")

# --- main ---------------------------------------------------------------------
def main():
    global ADDR
    try:
        ser = serial.Serial(port=f"/dev/{PORT}", baudrate=BAUD, bytesize=8,
                            parity="N", stopbits=1, timeout=0.3)
    except serial.SerialException as e:
        err(f"cannot open /dev/{PORT}: {e}")
        sys.exit(1)

    if ADDR is None:
        ADDR = detect_address(ser)
        if ADDR is None:
            err(f"no modbus slave found on /dev/{PORT} @ {BAUD} -- is UART set to "
                f"'013 JK BMS RS485 modbus' and the cable on the RS485 jack?")
            ser.close()
            sys.exit(1)
        notice(f"found JK BMS at modbus address {ADDR} on /dev/{PORT} @ {BAUD}")


    if PROBE:
        b = read_status(ser, ADDR)
        ser.close()
        if b is None:
            err("read failed")
            sys.exit(1)
        print_debug(parse(b), ADDR)
        return

    client = None
    if DEBUG:
        notice(f"DEBUG mode: reading /dev/{PORT} ({BAUD}) -- NOT publishing to MQTT")
    else:
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            err("paho-mqtt not installed -- run: pip install paho-mqtt")
            sys.exit(1)
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except (AttributeError, TypeError):
            client = mqtt.Client()  # paho-mqtt 1.x
        client.connect_async(BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()
        notice(f"reading /dev/{PORT} ({BAUD}, addr {ADDR}) -> {TOPIC} @ {BROKER}:{MQTT_PORT}")


    try:
        while True:
            start = time.monotonic()
            try:
                b = read_status(ser, ADDR)
                if b is None:
                    warn(f"no valid modbus response on /dev/{PORT}")
                else:
                    data = parse(b)
                    if not data.get("voltage_cell01"):
                        warn(f"response decoded but no cell data on /dev/{PORT}")
                    elif DEBUG:
                        print_debug(data, ADDR)
                    else:
                        client.publish(TOPIC, json.dumps(data), qos=0)
            except Exception as e:  # keep the loop alive across transient errors
                warn(f"read/parse error on /dev/{PORT}: {e}")

            remainder = INTERVAL - (time.monotonic() - start)
            if remainder > 0:
                time.sleep(remainder)
    except KeyboardInterrupt:
        notice("interrupted -- stopping")
    finally:
        ser.close()
        if client is not None:
            client.loop_stop()
            client.disconnect()

if __name__ == "__main__":
    main()
