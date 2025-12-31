# Smart EnviroControl

A small “smart environment control” system:

- **Node A (sensor + actuators)** reads temperature/humidity (DHT11) + LDR light, controls a fan + a light, and sends sensor data over serial.
- **Node B (gateway)** bridges Node A <-> Laptop over USB serial.
- **Python Dashboard** (`dashboard.py`) shows live cards + charts with timestamps, stores readings in SQLite, and supports **voice commands (“Jarvis”)** to control the fan/lights and trigger scene modes.

---

## Repository layout

- `dashboard.py` — Desktop UI dashboard (CustomTkinter + Matplotlib) with logging + AI control.
- `check_db.py` — Utility to inspect the SQLite database schema and latest readings.
- `arduino/sketchnodeA/sketchnodeA.ino` — Arduino sketch for Node A (sensors + fan/light control).
- `arduino/sketchnodeB/sketchnodeB.ino` — Arduino sketch for Node B (serial gateway).
- `cache/` — (Generated) cached MP3 files for fast TTS responses.

---

## System overview (data + control)

### Sensor data format
Node A transmits one line every ~0.5s in this exact format:

```
<temp_c>,<humidity_pct>,<light_adc>
```

Example:

```
25.3,48.0,612
```

Node B forwards that line to the laptop over USB serial.

### Control commands (single-byte)
The dashboard (or voice control) sends a **single byte command** back over serial:

- `P` = **Fan override ON** (fan forced ON)
- `N` = **Fan override OFF** (fan forced OFF)
- `L` = **Lights ON** (voice override)
- `l` = **Lights OFF** (voice override)
- `A` = **Global reset** (fan override OFF + light auto)

Node B forwards the byte to Node A.

Note (current behavior):
- In the provided Node A sketch, the fan does **not** have a built-in temperature auto mode; it runs only when overridden by `P` and turns off with `N`/`A`.
- The light has an auto mode when not overridden: ON if `light_adc < 500`.

Dashboard fan logic (current):
- Uses a “learned” temperature threshold (starts at 27°C) with a safety hysteresis band (0.5°C) to reduce rapid toggling.
- Voice can nudge the threshold within 18°C–32°C using “hot/warm” (cooler) and “cold/freezing” (warmer).

### Database schema
When you run the dashboard, it creates a local SQLite DB named `smart_home_data.db` with:

- Table: `sensor_data(id, timestamp, temp, humid, light)`

### Dashboard UI (current)
- Hero cards: Temperature, Humidity, Light, Fan state
- Insights strip: rolling averages over the last 60 samples
- Tabbed charts: Temperature/Humidity/Light with live timestamp labels on the x-axis
- Sidebar includes a “JARVIS FEED” showing last heard phrase + last action

---

## Hardware requirements

### Node A
- Arduino (commonly UNO/Nano-compatible)
- DHT11 sensor
- LDR (photoresistor) + resistor (voltage divider)
- Fan (use a transistor/MOSFET driver + flyback diode if needed; do **not** power a fan directly from an Arduino pin)
- Light/LED/relay module (depending on your load)
- Jumper wires

Node A pin definitions (from `sketchnodeA.ino`):

- DHT11 data: `D2`
- LDR analog: `A0`
- Fan PWM: `D3`
- Light digital: `D7`
- SoftwareSerial to Node B: `RX=D10`, `TX=D11`

### Node B
- Arduino (UNO/Nano-compatible)

Node B pin definitions (from `sketchnodeB.ino`):

- SoftwareSerial to Node A: `RX=D2`, `TX=D3`
- USB serial to laptop: `Serial` (via USB)

### Wiring between Node A and Node B
Cross-connect the SoftwareSerial lines:

- Node A `TX (D11)` -> Node B `RX (D2)`
- Node A `RX (D10)` <- Node B `TX (D3)`
- Common ground: Node A `GND` <-> Node B `GND`

---

## Arduino setup

1. Open `sketchnodeA.ino` in Arduino IDE.
2. Install the **DHT sensor library** (Adafruit DHT recommended).
   - Arduino IDE: **Tools → Manage Libraries…**
   - Search and install:
     - `DHT sensor library` (Adafruit)
     - `Adafruit Unified Sensor` (dependency)
3. Select the correct board + port for **Node A**.
4. Upload.

Repeat for `sketchnodeB.ino` for **Node B**.

### Quick sanity check (built into Node A)
On boot, Node A briefly flashes the **light**. This is a wiring test.

---

## Python (Windows) setup

### Prerequisites
- Windows 10/11
- Python 3.9+ (3.10+ recommended)

### Create a virtual environment (recommended)
From the project folder:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Notes:
- `sqlite3` is part of Python’s standard library (no install needed).
- If any installs fail on your machine, upgrade pip first (above) and ensure you’re on a supported Python version.
- Voice commands in `dashboard.py` require `SpeechRecognition` and an audio backend (`PyAudio` is included in `requirements.txt`).
- The dashboard uses `edge-tts` (neural TTS) and `pygame` for audio playback.
  - On first run, the app may generate and store cached MP3 files under `cache/` for instant responses.
  - Both Speech-to-Text (Google via SpeechRecognition) and Edge TTS typically require an internet connection.

Microphone note:
- `dashboard.py` currently uses a fixed microphone index (`device_index=1`). If voice recognition isn’t working, change the device index to match your system.

---

## Running the dashboard

1. Plug **Node B** into the laptop via USB.
2. Find the COM port in Windows Device Manager (Ports (COM & LPT)).
3. Open `dashboard.py` and set:

- `SERIAL_PORT = 'COM7'` (change to your actual port)

4. Run:

```powershell
python dashboard.py
```

### Voice commands
The dashboard continuously listens for the wake word **“Jarvis”**.

After it wakes, supported commands include:
- Scene modes: “study”, “cinema” / “movie”, “sleep” / “goodnight”
- Fan: “fan on”, “fan off”, “auto”
- Preference: “hot” / “warm” (lowers the learned temperature threshold), “cold” / “freezing” (raises the learned temperature threshold)
- Lights: “light on/off” or “lamp on/off”
- Info: “status”, “time” / “clock”
- Chat: “hello”, “thanks”, “who (are you)”
- Safety: “shut down”

What you should see:
- Status in the sidebar should turn to **SYSTEM ONLINE** if serial connects.
- Live sensor values update.
- The DB file `smart_home_data.db` is created/updated.

---

## Exporting CSV

In the dashboard, click **SAVE DATA**.

- Output file name: `log.csv`
- Output rows: all rows from `sensor_data`

---

## Inspect the database

After running the dashboard at least once:

```powershell
python check_db.py
```

This prints:
- Table schema
- Latest 10 readings

---

## Troubleshooting

### Dashboard shows “ERROR: COMx”
- Make sure **Node B** is plugged in.
- Verify the COM port in Windows Device Manager.
- Close Arduino Serial Monitor (it can lock the port).
- Try unplugging/replugging the USB cable.

### Nothing updates / graphs stay empty
- Confirm Node B is uploaded and running.
- Confirm Node A and Node B are wired correctly (TX/RX crossed + common GND).
- Open Arduino Serial Monitor on **Node B** briefly to see if you receive CSV lines like `25.3,48.0,612`.

### DHT11 reads NaN / “Failed to read from DHT sensor!”
- Check DHT11 wiring and power.
- Try increasing the delay in Node A loop (DHT11 can be finicky if read too frequently).

### Fan or light doesn’t switch
- Re-check driver hardware (transistor/MOSFET/relay) and power supply.
- Note: Arduino pins cannot power motors/fans directly.

### Voice doesn’t work
- Check `device_index` in `dashboard.py` (microphone selection).
- Ensure you have a working audio input device and internet connectivity for SpeechRecognition (Google) + Edge TTS.

---


