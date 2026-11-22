# Testing procedures

## 1. Automated tests (no hardware)

```bash
cd desktop
pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen python -m pytest -q        # Windows PowerShell: $env:QT_QPA_PLATFORM="offscreen"; python -m pytest -q
```

| File | What it covers |
|---|---|
| `test_protocol.py` | NDJSON framing, partial reads, ESP32 boot noise, overflow recovery, message validation |
| `test_hardware.py` | Discovery and identification, ack/nack, retries, heartbeat loss, unplug/replug auto-reconnect, event de-duplication, arming rules, configurable mapping, role pinning, **SerialTransport with real threads** against a fake serial port, port-open failure |
| `test_evaluator.py` | Single, multi (partial credit), numeric with tolerance, timeout |
| `test_effects.py` | Every effect renders; preset colours; brightness; expiry |
| `test_quiz_flow.py` | End-to-end: simulated buttons → evaluation → green/red LED commands → buzzer → DB; timeouts; stale and duplicate presses; running with **no hardware at all**; mid-question reconnect re-arms; custom effect profile; manual advance |
| `test_repository.py` | CRUD and validation, cascades, bank import/export round-trip, CSV and HTML reports |
| `test_ui_smoke.py` | Headless GUI: dashboard → lesson → simulated presses and keyboard → finish → reports; Arabic RTL; all tabs render |

| `test_journey_buttons.py` | Game 1 buttons design: buttons armed on the map ESP32, correct → green step, wrong → red step back, double and stale presses, reaching Makkah, fallback to a separate button box, board restart re-arm, red step-back rendering, speech phrases |
| `test_journey.py` | Game 1: fixed firmware key, plate events, win/fail, map advance/fail/festival, retry after a wrong order, a fix made during feedback, clear-before-next-sentence, step-back and next modes, PC overriding a wrong firmware verdict, no-board play, board reconnect, firmware↔PC resistor table match, scrambled projector order |

Expected result: **all tests pass** (98 at the time of writing). Game 1 hardware checks are in [GAME1_JOURNEY.md §8](GAME1_JOURNEY.md#8-hardware-validation-needs-the-physical-kit).

Firmware compile check (needs a one-time toolchain download):

```bash
for d in journey_controller input_controller output_controller puzzle_controller map_controller; do (cd firmware/$d && pio run); done
```

## 2. Manual software test (simulation mode, Windows and macOS)

| # | Step | Expected |
|---|---|---|
| S1 | Start `python run.py` | Dashboard opens; "Simulated hardware" dock on the right; Lesson tab shows both controllers green ("sim") |
| S2 | Lesson → Start lesson | Student screen "What is 5 + 3?"; simulated strip breathes blue; buttons A–D lit |
| S3 | Click simulated button **C** | Green "Correct!" banner; strip green wipe; score 1; correct sound |
| S4 | Wait 3 s | Question 2 appears automatically; strip back to blue |
| S5 | Press **B** (wrong) | Red banner "The answer is A"; card A highlighted green, B red; strip blinks red |
| S6 | Press keys `1`–`4` or click a card | Same as hardware buttons |
| S7 | Untick "USB cable connected" on the input controller mid-question; tick it again | Status dot turns red; after ≤ 3 s it is green again and the buttons are re-armed |
| S8 | Wait for the timer to expire | Orange "Time is up!"; response recorded as timeout |
| S9 | Click **عربي / EN** | Layout mirrors right-to-left; Arabic text and Arabic-Indic digits |
| S10 | Finish or End | Stars and final score; Results tab shows the session with per-question answers |
| S11 | Questions → Add question (with Arabic text and an image) → Start lesson | New question shown with its image |
| S12 | Results → Export answers / summary / printable report | CSV opens in Excel with Arabic names intact; HTML report opens in the browser |
| S13 | Feedback effects → change "Correct" to rainbow and Save → answer correctly | Rainbow on the strip |
| S14 | Close and reopen the app | Questions, students, settings and results persist |

## 3. Hardware validation (requires the physical kit)

These items **cannot be verified without hardware** and were not run during development.

| # | Test | Procedure | Pass criteria |
|---|---|---|---|
| H1 | Firmware boot | Flash; `pio device monitor` | `{"type":"hello",...}` line after reset; status LED blinks slowly |
| H2 | Discovery | Start EduKit with both boards plugged in | Both **online** within 5 s; correct firmware version; latency < 30 ms |
| H3 | Button wiring | Devices → Test with a lesson; press A, B, C, D | Each press selects the right answer; button LEDs light for available options |
| H4 | Debounce | Press each button 20 times quickly during one question | Exactly **one** answer is recorded per question |
| H5 | Lock-out / double press | Hammer two buttons at once | Only the first press counts; the other is ignored |
| H6 | Touch pads | Input method = Touch; touch each pad through 2 mm acrylic | Reliable detection; no false triggers in 5 min idle; adjust sensitivity if needed |
| H7 | Mapping | Map #1→D … #4→A, Apply, unplug/replug | Mapping persists across reset (NVS) and is applied after reconnect |
| H8 | LED effects | Devices → Test feedback (each button) | Animation matches the on-screen preview; colours correct (strip type GRB) |
| H9 | Power | Celebrate at max brightness for 1 min | No brown-out reset; PSU and strip stay cool |
| H10 | Buzzer / motor | Answer wrong with "Vibrate" enabled | Melody audible; motor pulses ≈ 0.4 s |
| H11 | Hot-unplug | Pull the input USB cable mid-question, reconnect after 10 s | App shows *lost*, keeps running (on-screen answers work), reconnects and re-arms |
| H12 | Output unplug | Pull the output cable, answer, reconnect | No crash; next feedback appears on the strip after reconnect |
| H13 | Latency | Film the screen and strip at 60 fps while pressing | Press → strip change < 150 ms |
| H14 | Endurance | Run a 10-question lesson 10 times in a row | No missed or duplicated answers; no memory growth in Activity Monitor / Task Manager |
| H15 | OS matrix | Repeat H2, H3, H8 and H11 on Windows 11 and macOS (Intel and Apple Silicon) | Same results; ports `COMx` and `/dev/cu.*` detected |

Record results in a copy of this table with the date, OS, board type, USB chip and firmware version.

### Troubleshooting

- **The device never comes online.** Check the cable carries data, and that no other program (Arduino serial monitor, Cura, …) holds the port. Close `pio device monitor` before starting EduKit. On Windows, check the COM port in Device Manager.
- **"no hello (not an EduKit device?)" in the log.** The board runs other firmware, or the baud rate differs. Reflash it.
- **Wrong colours (red and green swapped).** Some strips are RGB rather than GRB. Change `NEO_GRB` to `NEO_RGB` in the output firmware.
- **Random touches.** Raise *Touch sensitivity*, shorten the pad wires, and send `calibrate` with hands off.
