#!/usr/bin/env python3
#
# Long-running JK *inverter*-BMS collector for one RS485 serial port.
#
# For the JK inverter BMS (PB series, e.g. the 150A JK-PB2A16S15P "v19"). Its
# RS485-1 port, with UART1 set to "000 - 4G-GPS Common protocol V4.2", speaks the
# native JK "NW" protocol (frames start 0x4E 0x57) at 115200 baud -- the same
# protocol the manual deploy/serial/read_bms.py decodes, but this is a
# productionised version: any cell count, all scalars, MQTT publish, a read-only
# debug mode, and journald-friendly logging.
#
# mpp-solar can NOT read this port (its jk485=0x55AA, jk232=0xDD, jk02=BLE
# framings don't match 0x4E57), which is why this is a dedicated reader.
#
# It publishes a flat JSON payload to  battery/<name>/mpp-solar  -- byte-identical
# in shape/topic to what the BLE `jkbms -o json_mqtt` collector emits -- so the
# server-side battery.conf Telegraf pipeline consumes it with no change.
# battery.conf maps cells 01..16 (V_nn / R_nn) and excludes 17..32.
#
# The CAN port is left untouched for the inverter link -- this path is RS485 only.
#
# Usage:
#   jkpb-collector.py <ttyUSBx>            # normal: read -> MQTT, loop
#   jkpb-collector.py <ttyUSBx> --debug    # DEBUG: decode -> screen only, never
#   DEBUG=1 jkpb-collector.py <ttyUSBx>    #        publishes (safe to run by hand)
#
# Config (env, see collector.env):
#   MQTT_BROKER        broker host/IP (default localhost)
#   MQTT_PORT          broker port (default 1883)
#   JKPB_NAME          topic suffix -> battery/<name>/mpp-solar (default jkpb).
#                      Per-port override JKPB_<port> wins (e.g. JKPB_ttyUSB2=pb1).
#   JKPB_BAUD          serial baud (default 115200)
#   JKPB_INTERVAL      seconds between reads (default 30; falls back to INTERVAL)
#   JKPB_READ_TIMEOUT  seconds to wait for a full frame (default 5)
#   JKPB_CAPACITY_AH   FALLBACK rated pack capacity in Ah. The capacity is read
#                      from the frame (register 0xAA) and always wins; this is
#                      only used if the firmware doesn't report it. Blank = omit.
#   DEBUG              1 (or --debug) for read-only screen output, no MQTT.

import json
import os
import sys
import time

# --- leveled logging via journald severity prefixes (SyslogLevelPrefix=yes) ---
def _log(level, msg): print(f"<{level}>{msg}", file=sys.stderr, flush=True)
def notice(msg): _log(5, msg)   # normal but significant
def warn(msg):   _log(4, msg)   # warning
def err(msg):    _log(3, msg)   # error

try:
    import serial  # pyserial (installed as an mpp-solar dependency)
except ImportError:
    err("pyserial not installed -- run: pip install pyserial")
    sys.exit(1)

# --- config -------------------------------------------------------------------
def env(name, default=None):
    v = os.environ.get(name)
    return v if v not in (None, "") else default

if len(sys.argv) < 2:
    err("usage: jkpb-collector.py <ttyUSBx> [--debug]")
    sys.exit(2)

PORT = sys.argv[1]
DEBUG = ("--debug" in sys.argv[2:]) or (env("DEBUG", "0") not in ("0", "false", ""))

BROKER   = env("MQTT_BROKER", "localhost")
MQTT_PORT = int(env("MQTT_PORT", "1883"))
BAUD     = int(env("JKPB_BAUD", "115200"))
INTERVAL = int(env("JKPB_INTERVAL", env("INTERVAL", "30")))
READ_TIMEOUT = float(env("JKPB_READ_TIMEOUT", "5"))
CAPACITY_AH = env("JKPB_CAPACITY_AH")  # optional
CAPACITY_AH = float(CAPACITY_AH) if CAPACITY_AH else None

# name -> topic suffix; per-port override (JKPB_<port>) wins
NAME = env(f"JKPB_{PORT}", env("JKPB_NAME", "jkpb"))
TOPIC = f"battery/{NAME}/mpp-solar"

# The fixed "read all data" request frame for the 4G-GPS / NW protocol (same one
# deploy/serial/query_bms.py sends). We send it, then read the reply.
REQUEST = bytes.fromhex("4E5700130000000006030000000000006800000129")

# Register id -> payload byte length, for the dynamic data block that starts at
# offset 11 (after 4E57 + length(2) + terminal(4) + cmd + source + type). 0x79
# (cell voltages) is length-prefixed and handled separately. These registers are
# emitted contiguously and in ascending order, ending at 0x8C; the settings that
# follow (0x8E+) are not needed here, so the walk stops at the first unknown id.
REG_SIZES = {
    0x80: 2,  # power-tube (MOS) temperature
    0x81: 2,  # battery box temperature  -> battery_t1
    0x82: 2,  # battery temperature      -> battery_t2
    0x83: 2,  # total voltage (10 mV)
    0x84: 2,  # current (10 mA, 0x8000 bit = charging)
    0x85: 1,  # remaining SOC (%)
    0x86: 1,  # number of temperature sensors
    0x87: 2,  # cycle count
    0x89: 4,  # total cycle capacity (Ah)
    0x8A: 2,  # number of battery strings
    0x8B: 2,  # warning/alarm bitmask
    0x8C: 2,  # status bitmask (charge/discharge/balance MOS)
}
# Settings block (0x8E..0xAA). We publish none of these, but we need their sizes
# to walk past them and reach the rated pack capacity at 0xAA. Sizes verified
# against a real 16S JK-PB frame; the walk stops at the first unknown id, so a
# firmware that inserts a different register simply loses the capacity field.
REG_SIZES.update({
    0x8E: 2, 0x8F: 2, 0x90: 2, 0x91: 2, 0x92: 2, 0x93: 2, 0x94: 2, 0x95: 2,
    0x96: 2, 0x97: 2, 0x98: 2, 0x99: 2, 0x9A: 2, 0x9B: 2, 0x9C: 2, 0x9D: 1,
    0x9E: 2, 0x9F: 2, 0xA0: 2, 0xA1: 2, 0xA2: 2, 0xA3: 2, 0xA4: 2, 0xA5: 2,
    0xA6: 2, 0xA7: 2, 0xA8: 2, 0xA9: 1, 0xAA: 4,
})

def _temp(raw):
    # JK NW temperature encoding: 0..100 = 0..100 C; >100 = negative.
    return raw if raw <= 100 else -(raw - 100)

# A real response is far larger than the 21-byte request; use this to reject the
# request echo that half-duplex RS485 adapters feed back on RX (the echo also
# starts 0x4E57, so it would otherwise be mistaken for a reply).
MIN_RESPONSE = 40

def read_frame(ser):
    """Send the request and read one complete 0x4E57 frame. Returns bytes or
    None on timeout. Length field = number of bytes after the 2 start bytes, so
    total frame = length + 2. Skips the request echo and any short/garbage
    frame."""
    ser.reset_input_buffer()
    deadline = time.monotonic() + READ_TIMEOUT
    buf = bytearray()
    next_poll = 0.0
    while time.monotonic() < deadline:
        # (Re)send the poll about once a second, but ONLY while the line has
        # been completely silent: a single lost request would otherwise waste
        # the whole window. Re-polling once bytes are arriving would collide
        # with the in-flight reply on the half-duplex bus.
        now = time.monotonic()
        if not buf and now >= next_poll:
            ser.write(REQUEST)
            next_poll = now + 1.0
        chunk = ser.read(320)
        if chunk:
            buf.extend(chunk)
        while True:
            start = buf.find(b"\x4E\x57")
            if start < 0 or len(buf) - start < 4:
                break
            length = (buf[start + 2] << 8) | buf[start + 3]
            total = length + 2
            if len(buf) - start < total:
                break  # frame not fully in yet -- read more
            cand = bytes(buf[start:start + total])
            del buf[:start + total]           # consume up to and incl. this frame
            if total >= MIN_RESPONSE and cand != REQUEST:
                return cand                    # a real reply
            # else: request echo / too short -> keep scanning what's left
    return None

def parse_frame(frame):
    """Register-walk a 0x4E57 frame into a flat dict of mpp-solar-style fields."""
    if len(frame) < 12 or frame[0] != 0x4E or frame[1] != 0x57:
        raise ValueError("bad frame header")

    d = {}
    cells = []
    i = 11  # data block start (0x79 sits here)
    # tolerate an off-by position: if 0x79 isn't at 11, hunt for it
    if frame[i] != 0x79:
        j = frame.find(b"\x79", 4)
        if j > 0:
            i = j

    while i < len(frame) - 2:
        reg = frame[i]; i += 1
        if reg == 0x79:
            L = frame[i]; i += 1
            block = frame[i:i + L]; i += L
            for k in range(0, len(block) - 2, 3):
                mv = (block[k + 1] << 8) | block[k + 2]
                cells.append(mv / 1000.0)
            continue
        size = REG_SIZES.get(reg)
        if size is None:
            break  # reached the settings section we don't need
        raw = int.from_bytes(frame[i:i + size], "big"); i += size
        if   reg == 0x80: d["mos_temp"]   = _temp(raw)
        elif reg == 0x81: d["battery_t1"] = _temp(raw)
        elif reg == 0x82: d["battery_t2"] = _temp(raw)
        elif reg == 0x83: d["battery_voltage"] = round(raw / 100.0, 2)
        elif reg == 0x84:
            if raw & 0x8000:                       # charging
                current = (raw & 0x7FFF) / 100.0
            else:                                  # discharging
                current = -raw / 100.0
            d["_current"] = round(current, 2)
        elif reg == 0x85: d["percent_remain"] = raw
        elif reg == 0x87: d["cycle_count"] = raw
        elif reg == 0x89: d["cycle_capacity"] = round(raw / 1000.0, 2)
        elif reg == 0x8B: d["_warnings"] = raw
        elif reg == 0x8C: d["_status"] = raw
        elif reg == 0xAA:
            # Rated pack capacity (Ah). Sanity-check it: if the settings-block
            # walk ever desynced, a wild value must not reach the metrics.
            if 1 <= raw <= 2000:
                d["nominal_capacity"] = raw
            break  # last field we publish -- skip the rest of the frame

    # --- derived, cell-based fields ------------------------------------------
    for n, v in enumerate(cells, start=1):
        d[f"voltage_cell{n:02d}"] = round(v, 3)
    if cells:
        d["average_cell_voltage"] = round(sum(cells) / len(cells), 3)
        d["delta_cell_voltage"] = round(max(cells) - min(cells), 3)

    # --- derived, current/power/capacity -------------------------------------
    current = d.pop("_current", None)
    if current is not None:
        # Signed current: + charging, - discharging (= charge - discharge).
        # `or 0.0` / the >0/<0 guards avoid a cosmetic -0.0 when current is 0 A.
        d["current"] = round(current, 2) or 0.0
        d["current_charge"] = round(current, 2) if current > 0 else 0.0
        d["current_discharge"] = round(-current, 2) if current < 0 else 0.0
        if "battery_voltage" in d:
            d["battery_power"] = round(d["battery_voltage"] * current, 2) or 0.0

    # Rated capacity comes from the frame (0xAA). JKPB_CAPACITY_AH is only a
    # fallback for firmware that doesn't report it, so the measured value always
    # wins and no configured figure has to be undone later.
    cap = d.get("nominal_capacity") or CAPACITY_AH
    if cap:
        d["nominal_capacity"] = cap
        if "percent_remain" in d:
            d["capacity_remain"] = round(d["percent_remain"] / 100.0 * cap, 2)

    return d

def print_debug(d):
    print("\033[2J\033[H", end="")  # clear screen
    print(f"JK-PB @ /dev/{PORT}  ->  (DEBUG: not publishing)  topic would be: {TOPIC}")
    print("-" * 56)
    cellkeys = sorted(k for k in d if k.startswith("voltage_cell"))
    for k in cellkeys:
        print(f"  {k:22s} {d[k]:.3f} V")
    for k in ("average_cell_voltage", "delta_cell_voltage", "battery_voltage",
              "current", "current_charge", "current_discharge", "battery_power",
              "percent_remain", "cycle_count", "cycle_capacity",
              "mos_temp", "battery_t1", "battery_t2",
              "capacity_remain", "nominal_capacity", "_warnings", "_status"):
        if k in d:
            print(f"  {k:22s} {d[k]}")

def main():
    if DEBUG:
        notice(f"DEBUG mode: reading /dev/{PORT} ({BAUD}) read-only -- NOT publishing to MQTT")
        client = None
    else:
        try:
            import paho.mqtt.client as mqtt  # installed as an mpp-solar dependency
        except ImportError:
            err("paho-mqtt not installed -- run: pip install paho-mqtt")
            sys.exit(1)
        # paho-mqtt 2.x requires an explicit callback API version; 1.x has no
        # CallbackAPIVersion. We only publish, so VERSION2 is fine either way.
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except (AttributeError, TypeError):
            client = mqtt.Client()  # paho-mqtt 1.x
        client.connect_async(BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()
        notice(f"reading /dev/{PORT} ({BAUD}) -> {TOPIC} @ {BROKER}:{MQTT_PORT}")

    try:
        ser = serial.Serial(port=f"/dev/{PORT}", baudrate=BAUD, bytesize=8,
                            parity="N", stopbits=1, timeout=0.2)
    except serial.SerialException as e:
        err(f"cannot open /dev/{PORT}: {e}")
        sys.exit(1)

    try:
        while True:
            start = time.monotonic()
            try:
                frame = read_frame(ser)
                if frame is None:
                    warn(f"no frame within {READ_TIMEOUT}s on /dev/{PORT}")
                else:
                    data = parse_frame(frame)
                    if not data.get("voltage_cell01"):
                        warn(f"frame parsed but no cell data on /dev/{PORT} "
                             f"({len(frame)} bytes) -- wrong protocol/mode?")
                    elif DEBUG:
                        print_debug(data)
                    else:
                        client.publish(TOPIC, json.dumps(data), qos=0)
            except Exception as e:  # keep the loop alive across transient errors
                warn(f"read/parse error on /dev/{PORT}: {e}")

            remainder = INTERVAL - (time.monotonic() - start)
            if remainder > 0:
                time.sleep(remainder)
    except KeyboardInterrupt:
        # Ctrl-C on a manual/debug run: exit quietly instead of dumping a
        # traceback. systemd stops the service with SIGTERM, which is silent.
        notice("interrupted -- stopping")
    finally:
        ser.close()
        if client is not None:
            client.loop_stop()
            client.disconnect()

if __name__ == "__main__":
    main()
