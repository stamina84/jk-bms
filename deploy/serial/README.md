# Manual serial BMS reader (diagnostic)

A standalone, two-terminal tool for reading a JK-BMS directly over its **UART
serial** link (`/dev/ttyUSB0`, 115200 baud) — separate from the BLE
`jkbms-collector.sh` pipeline. Useful for poking at a pack on the bench or
debugging without MQTT/Telegraf. It prints to the screen; it does **not**
publish anywhere.

Two terminals:

```bash
# Terminal 1 — decode and print the live frame
python3 read_bms.py

# Terminal 2 — repeatedly send the "request update" frame to the BMS
watch python3 query_bms.py
```

`query_bms.py` writes the fixed request frame; `read_bms.py` parses the reply
(cell voltages, temps, current, SOC, cycles, …) and clears/redraws the screen.
Adjust the `port=` in both files if your adapter isn't on `/dev/ttyUSB0`.

> For normal data collection use the BLE collector instead
> ([../README.md](../README.md)) — this script is only a manual fallback.
