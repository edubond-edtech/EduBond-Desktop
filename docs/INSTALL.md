# Installation

Everything installs and runs **offline** once the packages are downloaded. To set up a classroom PC with no internet, copy the wheel cache or a PyInstaller build to it.

## 1. Desktop application

Requirements: Python **3.10–3.13** (developed and tested on 3.12). Windows 10/11 (x64) or macOS 12+ (Intel or Apple Silicon).

### macOS

```bash
cd desktop
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

### Windows (PowerShell)

```powershell
cd desktop
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

On first start, EduKit creates its data folder and loads the 10 demo questions, the class "Class 3A" and 6 students:

| OS | Data folder |
|---|---|
| macOS | `~/Library/Application Support/EduKit/` |
| Windows | `%APPDATA%\EduKit\` |

The folder holds `edukit.sqlite3`, `images/` and `sounds/`. Override it with `--data-dir PATH` or the `EDUKIT_HOME` environment variable.

Useful flags: `--simulate` (simulator on), `--serial` / `--no-serial` (USB on/off this run), `--no-ble` (Bluetooth off this run), `--ble-selftest REPORT` (Bluetooth check), `--debug`.

### Standalone program for schools (no Python on the classroom PC)

**Windows: `EduKit-Setup-0.1.0.exe`.** This is a normal installer: Next → Next → Finish, with Start menu and desktop shortcuts, and no admin rights needed. You must build it once on any Windows 10/11 PC, because a Windows program cannot be built on a Mac:

1. On the build PC (only this one, not the classroom PCs), install:
   - Python 3.12 from python.org, ticking **Add python.exe to PATH**
   - Inno Setup 6 from https://jrsoftware.org/isdl.php
2. Copy the whole `ToMakkahKit` folder to that PC and **double-click `build_windows.bat`**. It takes about 5 minutes the first time and needs internet only for this step.
3. Explorer opens `desktop\dist\` with:
   - `installer\EduKit-Setup-0.1.0.exe`: **send this file** (USB stick, email, shared drive). About 50 MB.
   - `EduKit-portable.zip`: a no-install alternative. Unzip it and double-click `EduKit.exe`.

**No Windows PC?** Put the project on GitHub, open **Actions → build-edukit → Run workflow**, and download *EduKit-Windows* from the finished run. The workflow (`.github/workflows/build.yml`) runs the tests, builds the installer, and also builds the Mac app.

**macOS: `EduKit.app`.**

```bash
cd desktop
../.venv/bin/pyinstaller --noconfirm packaging/edukit.spec      # -> dist/EduKit.app
```

To send it, zip it with `ditto -c -k --keepParent dist/EduKit.app EduKit-macOS.zip`. The app is not signed, so on the receiving Mac open it the first time with **right-click → Open → Open**. For signing and notarisation (no warning at all), see ROADMAP v0.2.

**What the installer does and doesn't do:**

- It installs the program only. Lessons, students, results and chosen audio live in `%APPDATA%\EduKit` (Windows) or `~/Library/Application Support/EduKit` (Mac). They **survive uninstalling and upgrading**, so a new version can be installed over the old one.
- Windows SmartScreen may say "Windows protected your PC" because the installer is not code-signed. Click **More info → Run anyway**. A code-signing certificate (about $100–300 a year) removes this warning.
- The USB driver for the ESP32 boards (CP210x or CH340) is not included. Windows 10/11 usually installs it automatically; otherwise see §2.

## 2. USB drivers

| Board chip | macOS | Windows |
|---|---|---|
| CP2102/CP2104 (Silicon Labs) | Built into macOS 11+ | Windows Update, or the "CP210x VCP" driver from silabs.com |
| CH340/CH9102 (WCH) | Built into macOS 12+ | "CH341SER" driver from wch-ic.com |

To check, plug in the board. On macOS a `/dev/cu.usbserial-*` or `/dev/cu.wchusbserial*` device appears (`ls /dev/cu.*`). On Windows a *COMx* port appears under *Ports* in Device Manager.

## 3. Flashing the firmware

### Option A — PlatformIO CLI (recommended)

```bash
pip install platformio              # once
cd firmware/input_controller
pio run -t upload                   # builds + flashes; add  --upload-port /dev/cu.usbserial-0001  or  COM5
pio device monitor                  # optional: should print {"type":"hello",...}
cd ../output_controller
pio run -t upload
```

Flash each board separately (or connect one at a time) so the uploads don't go to the wrong port. Libraries (ArduinoJson 7.2.1, Adafruit NeoPixel 1.12.3) are fetched automatically on the first build.

If the upload stalls at `Connecting....`, hold the board's **BOOT** button until writing starts.

### Option B — Arduino IDE 2

1. Install *esp32 by Espressif Systems* (2.0.x or 3.x both work) from the Boards Manager.
2. Install the libraries **ArduinoJson** (7.x) and **Adafruit NeoPixel**.
3. Copy `firmware/input_controller/src/main.cpp` into a new sketch named `input_controller.ino`. Do the same for the output controller.
4. Board: *ESP32 Dev Module*; upload.

### Device IDs

The defaults are `INPUT_01` and `OUTPUT_01` (set with `-DEDUKIT_DEVICE_ID` in `platformio.ini`). To give several boxes unique IDs without reflashing, send `{"id":1,"command":"set_id","new_id":"INPUT_02"}` from a serial monitor, or use **Devices → Rename** in the app. The new ID is stored in flash.

## 4. First run with hardware

**Bluetooth (default):** power the ESP32 (USB charger, power bank or the 5 V supply), start EduKit, and allow Bluetooth when macOS asks. The board connects by itself within about 15 s. USB serial and the simulator are off by default; turn them on in **Devices** if needed.

**USB (optional):**

1. Plug in both ESP32s and start EduKit.
2. Go to **Devices** and make sure *USB serial* is ticked. Within about 5 s both controllers show **online** with their firmware version and latency.
3. Optionally untick *Simulation mode*, so the simulated controllers don't compete for the roles. Alternatively, pin real devices under *Devices used in lessons*.
4. Press the **Test feedback** buttons. The strip should show each animation.
5. Start a lesson from **Lesson**.
