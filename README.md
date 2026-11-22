# EduKit — offline interactive hardware classroom (ESP32)

A reusable educational hardware platform. A desktop app (Windows and macOS) runs lessons and stores everything locally in SQLite. An **ESP32 input controller** reads push buttons or capacitive touch pads. An **ESP32 output controller** drives a WS2812B LED strip, a buzzer and motors. No internet, RFID or NFC is needed, and a built-in **simulation mode** runs the whole system without hardware.

```
 Student presses C ─▶ INPUT_01 ─USB/JSON─▶ PC evaluates "5+3 = C ✔" ─USB/JSON─▶ OUTPUT_01 green wipe + melody
                                              └─▶ score, progress, SQLite results, reports
```

## Games

| Game | Hardware | Guide |
|---|---|---|
| **1 — «رحلة إلى مكة» (Journey to Makkah)**: Arabic multiple-choice questions on the projector, answered with 4 physical buttons or touch pads on a **Bluetooth** board. Correct → spoken praise + one green LED step towards Makkah; wrong → one red step back; arrival → LED festival + nasheed/duaa | **One ESP32** `JOURNEY_01`: LED route map + 4 buttons (alternative: resistor word plates `PUZZLE_01` + `MAP_01`) | [docs/GAME1_JOURNEY.md](docs/GAME1_JOURNEY.md) |
| Multiple-choice quiz (platform demo) | 4-button box `INPUT_01` + LED strip `OUTPUT_01` | this README |

## Quick start (no hardware needed)

```bash
cd desktop
python3 -m venv .venv && source .venv/bin/activate     # Windows: py -3.12 -m venv .venv; .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Open the **🕋 رحلة إلى مكة** tab and press **ابدأ الرحلة إلى مكة**. Answer with the simulated buttons أ ب ج د in the dock on the right, or click the answers on screen.
For the quiz demo, click **▶ Start lesson** and press the simulated A–D buttons (or keys `A`–`D` / `1`–`4`). For hardware setup, see [docs/INSTALL.md](docs/INSTALL.md).

**Sending it to schools:** double-click `build_windows.bat` on any Windows PC to get **`EduKit-Setup.exe`**, an ordinary installer with no Python needed. See [docs/INSTALL.md](docs/INSTALL.md#standalone-program-for-schools-no-python-on-the-classroom-pc).

## What's in the box

| Path | Contents |
|---|---|
| `desktop/edukit/` | PySide6 application: `comms/` (protocol + transports), `hardware/` (device link, manager, simulator), `activities/`, `evaluation/`, `feedback/`, `data/` (SQLite, reports), `ui/` |
| `desktop/tests/` | 125 automated tests (protocol, reliability, quiz and journey flows, database, headless UI) |
| `firmware/journey_controller/` | **Game 1 (default): one ESP32 = LED route map + 4 answer buttons** |
| `firmware/puzzle_controller/` | Game 1 alternative: plate board with 6 resistor-coded sockets, fixed answer key, win/fail on the last plate |
| `firmware/map_controller/` | Game 1 alternative: map-only ESP32 (used with the plate board) |
| `firmware/input_controller/` | Quiz box: 4 (up to 8) buttons/touch pads, debounce, mapping, illuminated buttons |
| `firmware/output_controller/` | Quiz LEDs: WS2812B effects, buzzer melodies, 2 motor outputs |
| `sample_data/journey_mcq_ar.json` | 10 Arabic multiple-choice questions for Game 1 |
| `sample_data/journey_arrange_ar.json` | 10 Arabic sentences for the plate version (3–6 words) |
| `sample_data/questions.json` | 10 bilingual (EN/AR) quiz questions |
| `docs/` | [Architecture](docs/ARCHITECTURE.md) · [Protocol](docs/PROTOCOL.md) · [Wiring & GPIO](docs/WIRING.md) · [BOM](docs/BOM.md) · [Database](docs/DATABASE.md) · [Install](docs/INSTALL.md) · [Testing](docs/TESTING.md) · [Roadmap](docs/ROADMAP.md) |

## New in this version (teacher guide in Arabic: [docs/TEACHER_GUIDE_AR.md](docs/TEACHER_GUIDE_AR.md))

- **EduBond identity:** logo, «EB» app icon and brand colours (purple `#7B3E98`, yellow `#FFCA3A`, teal `#26B6A8`).
- **Bilingual interface:** Arabic by default, English from ⚙️ Settings.
- **Device / competition types:** multiple choice (available), word arrangement (plate board), reading aloud and handwriting (coming soon, with settings).
- **Teams** inside classes; play as a team, one student or the whole class.
- **Date-range reports** with every test listed under each student, exported to Excel.
- **Picture or video** above the question, including from the Excel import.
- **30 Arabic-only multiple-choice questions** for the Indonesian grade-1 Arabic curriculum.

- **Curriculum tree:** curriculum → subject → unit → lesson → questions (multiple choice, true/false, word arrangement), each question with an optional picture shown large on the projector.
- **Excel import/export** (Arabic templates with instructions) for students (name, birth date, national ID, school year, class) and for questions. One file can create a whole curriculum.
- **Event sounds:** import or **record with the microphone** a sound for start, new question, correct, wrong, timeout, win and lose.
- **Win/lose:** an optional question limit makes the team lose if Makkah is not reached in time.
- **Bluetooth device search and «ربط» (pair):** only paired boards connect automatically.

## Features (v0.1 prototype)

- **Student screen:** large bilingual questions with right-to-left Arabic and Arabic-Indic digits, images, colour-coded answer cards matching the physical buttons, a countdown, score and progress, animated feedback, offline sounds, and an end-of-quiz star rating.
- **Teacher dashboard:**
  - Lesson launcher with quiz settings (timers, auto-advance, shuffle, show answer).
  - Question banks by subject and grade, with an editor for options, the correct answer(s), timer, points, image and explanation, plus JSON import/export.
  - Classes and students.
  - Devices: live status, latency, role selection, button mapping, touch settings, LED count and brightness cap, a test panel, rename, and a communication log.
  - Feedback-effect editor with a live LED preview.
  - Results: per-student performance and per-session answers, exported as CSV or printable HTML.
- **Hardware link:**
  - Automatic USB discovery, `hello` identification, command acks with retries, and heartbeat.
  - Auto-reconnect that re-arms the buttons mid-question.
  - Duplicate-event protection at the firmware, link and activity levels.
  - Lessons keep working with no devices connected.
- **Modular design:** an activity registry, pluggable evaluators, a transport/discovery interface ready for BLE and Wi-Fi, and generic firmware (`raw` input mode and parametrised effects), so new activities need no reflashing.

## Verified vs. requires hardware

| Verified during development | Not yet verifiable without the physical kit |
|---|---|
| All 125 automated tests pass on macOS (Python 3.12, PySide6 6.12) | Plate resistor readings on the real ADC, connector contact quality, settle timing |
| Button and touch-pad electrical behaviour, debounce tuning, touch thresholds |
| Full lesson flow in the real GUI in simulation mode (EN and AR) | WS2812B colour order, timing and power on a real strip |
| Serial transport with real reader threads against a simulated ESP32 on a fake port | Real USB enumeration, ESP32 auto-reset timing and COM-port naming on Windows |
| All five firmware projects **compile** for ESP32 (PlatformIO, Arduino core 2.0.17) | Firmware behaviour on the board, buzzer and motor drive, end-to-end latency |
| | Windows run of the desktop app (the code is cross-platform but was exercised on macOS only) |

The hardware validation checklist is in [docs/TESTING.md §3](docs/TESTING.md).
