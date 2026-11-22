# EduKit architecture

EduKit is an offline classroom platform: a desktop app runs the lesson logic; ESP32 controllers handle physical input (buttons and touch pads) and physical feedback (LED strip, buzzer, motors). Everything runs on one computer with no internet.

## 1. Technology choice

| Option | Strengths | Weaknesses for this project | Verdict |
|---|---|---|---|
| **PySide6 (Qt 6, Python)** | Native widgets on Windows and macOS; mature `pyserial`; built-in SQLite; Qt Multimedia for sound; full RTL/Arabic text shaping; one language for the logic, the hardware layer and the tests; easy for school IT and student developers to extend | Larger bundle (~120 MB with PyInstaller); Python start-up time of 1–2 s | **Selected** |
| Electron | Web UI skills; rich animation | Serial support needs native modules (`serialport`) that must be rebuilt for each Electron version; ~150 MB; split JS main/renderer makes the device layer harder to test | Runner-up |
| Tauri | Small binaries; Rust safety | Two languages (Rust + JS) for a small team; serial and BLE plugins less mature; slower iteration | Not chosen |
| Flutter Desktop | Polished UI | Serial/BLE desktop plugins are community-maintained and uneven on Windows and macOS; Dart ecosystem is thin for hardware | Not chosen |

The hardware layer, activity engine, evaluation, feedback and storage are **pure Python with no Qt imports**. That keeps them unit-testable, and they could later run headless (for example on a Raspberry Pi classroom hub) or behind a different UI.

## 2. Layers

```
┌───────────────────────────────────────────────────────────────────────────┐
│ UI (PySide6)  edukit/ui                                                   │
│  Student screen · Teacher dashboard (lesson, questions, students,         │
│  devices, effects, reports) · Simulator dock                              │
├─────────────── Qt adapters: QtScheduler, MainThreadDispatcher, BusBridge ─┤
│ Session controller   edukit/core/session.py                               │
├──────────────────────────┬──────────────────────┬─────────────────────────┤
│ Activity engine          │ Evaluation engine    │ Feedback engine         │
│ activities/base.py       │ evaluation/          │ feedback/engine.py      │
│ activities/quiz.py (mcq) │ evaluator.py         │ feedback/effects.py     │
├──────────────────────────┴──────────────────────┴─────────────────────────┤
│ Hardware device manager   hardware/manager.py  (discovery, roles,         │
│                           reconnect, safe send)                           │
│ DeviceLink                hardware/link.py     (hello, ack/retry,         │
│                           heartbeat, event de-duplication)                │
├───────────────────────────────────────────────────────────────────────────┤
│ Communication layer   comms/protocol.py (NDJSON) · comms/transport.py     │
│   SerialTransport (USB)  ·  SimTransport (simulator)  ·  [BLE] · [Wi-Fi]  │
├───────────────────────────────────────────────────────────────────────────┤
│ Local database & reporting   data/schema.sql · repository.py · reports.py │
└───────────────────────────────────────────────────────────────────────────┘
          ▲ USB serial 115200 baud, newline-delimited JSON ▼
  ESP32 INPUT controller                     ESP32 OUTPUT controller
  firmware/input_controller                  firmware/output_controller
```

| Requested module | Implementation |
|---|---|
| 1. Question & activity engine | `activities/` with `Activity` base, `@register_activity` registry, `QuizActivity` |
| 2. Student & teacher interfaces | `ui/student_view.py`, `ui/teacher/*` |
| 3. Answer evaluation engine | `evaluation/evaluator.py`: pluggable evaluators per question type (single, multi with partial credit, true/false, numeric with tolerance) |
| 4. Hardware device manager | `hardware/manager.py`, `hardware/link.py` |
| 5. Communication layer | `comms/` |
| 6. Feedback & animation engine | `feedback/engine.py` (outcome → command profile), `feedback/effects.py` (effect catalogue + renderer shared with the firmware) |
| 7. Local database & reporting | `data/` |

## 3. Key design decisions

**The PC owns the educational logic; devices are generic.** The input controller only knows "armed for question Q001, options A–D". In `raw` mode it reports every press and release. The output controller renders parametrised effects (`effect`, `color`, `brightness`, `duration_ms`, `speed`, `value`). New activities (races, sequences, sensor labs) therefore need no firmware change.

**Roles, not ports.** Activities send to the role `"input"` or `"output"`, or to a specific `device_id`. They never send to a COM port. The teacher can pin a role to a specific device. Otherwise the first online device with that role is used. `send_all(role, …)` reaches every device with a role, for example several LED towers.

**Reliability lives in DeviceLink**, so every transport gets it for free:
- Every command has an `id` and is retried (default: 3 attempts, 500 ms apart) until the device sends `ack` or `nack`.
- Every device event has a `seq`. The PC always acks it, and the device retransmits until it gets the ack. The PC drops duplicates by `(boot_id, seq)`, so a lost ack never produces a double answer.
- Heartbeat: the PC pings every 2 s. A device that is silent for 6.5 s is marked `lost`, its port is closed, and the manager rescans every 3 s, so it reconnects automatically when the cable comes back.
- A device that reboots sends a new `boot_id`. The active quiz re-arms the input controller as soon as it is back online.

**Duplicate-answer protection runs at three levels:**
1. Firmware: debounce (30 ms), a repeat lock-out (400 ms), and only one answer per `arm`.
2. Link: sequence-number de-duplication.
3. Activity: answers are accepted only in the `ASKING` state and only for the current `question_id`; stale or late events are counted and ignored.

**Disconnected hardware never blocks a lesson.** `DeviceManager.send` returns `None` when no device is available. The quiz continues with on-screen and keyboard answers, and the status dots show what is missing.

**Threading.** Serial reader threads and the manager's poll thread publish to a thread-safe `EventBus`. The Qt `MainThreadDispatcher` moves input events to the GUI thread before they reach the activity, so all lesson state changes happen on one thread. Timers use the `Scheduler` abstraction: `QtScheduler` in the app, `ManualScheduler` in tests, which makes timeouts deterministic.

**Simulation is the real protocol.** `SimulatedInputDevice` and `SimulatedOutputDevice` speak the same JSON as the firmware, including hello, acks and sequence numbers. Messages go through the real encoder, so simulation mode exercises the whole stack. The simulator's LED strip uses the same effect algorithms as the firmware.

## 4. Quiz state machine

```
READY ──start──▶ ASKING ──answer / timeout──▶ FEEDBACK ──(auto after N s | teacher "Next")──▶ ASKING …
                   │  arm input, LEDs "waiting"     disarm, LEDs outcome,                        │
                   │                                record response                             ▼
                   └───────────────────────── teacher "End" ──▶ STOPPED          last question ─▶ FINISHED (celebrate)
```

## 5. Adding things later

- **A new activity type:** subclass `Activity`, decorate it with `@register_activity`, and implement `start`, `stop`, `handle_input` and `snapshot`. Use `configure mode=raw` for free-form button input and `play_effect` or `progress` for output. Add a student view for it.
- **A new transport (BLE or Wi-Fi):** implement `Transport` and `DiscoverySource`, then call `DeviceManager.add_source(...)`. See [ROADMAP.md](ROADMAP.md).
- **A new device type** (for example a sensor box): send `hello` with a new role or capabilities, emit `type:"event"` messages, and accept commands. The link layer needs no change.
