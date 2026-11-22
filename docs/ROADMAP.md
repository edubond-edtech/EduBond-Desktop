# Development roadmap

## v0.1 — first working prototype (this release)

- Offline PySide6 app: student screen (EN/AR, RTL, timer, score, animations, sounds), teacher dashboard (lessons, question banks, students and classes, devices, effects, reports)
- USB serial transport with discovery, identification, acks and retries, heartbeat, auto-reconnect and de-duplication
- Input firmware (4 buttons and/or touch pads, illuminated buttons, mapping, raw mode); output firmware (WS2812B effects, buzzer melodies, 2 motors)
- Full hardware simulation; SQLite storage; CSV and HTML reports; automated tests

## Games

- **Game 1 «رحلة إلى مكة»** — done (v0.1): plate board, route map, Arabic projector screen, festival audio.
- Games 2+ — to be specified by the teacher one by one; each plugs in as a new `Activity` plus a device role.
- Ideas for Game 1: two teams racing on two strips; printable word-sticker sheets per sentence; per-sentence picture hints.

## v0.2 — classroom hardening (next 4–6 weeks)

- Validate on real hardware (TESTING.md §3) and tune debounce, touch thresholds and latency
- Signed installers: PyInstaller + Inno Setup (Windows), notarised `.dmg` (macOS)
- Teacher PIN to leave the student screen; database backup and restore button
- Question images and audio prompts for younger students; larger option pictures
- Protocol version check that refuses incompatible firmware with a clear message
- OTA-free firmware updater inside the app (esptool bundled)

## v0.3 — multiple students and competitions

- One input box per student or team; map `device_id → student` in the Lesson tab
- **Buzzer race** activity: first correct press wins; leaderboard; per-team LED colour
- **LED racing** activity: each correct answer advances the team's segment on the strip (`progress` command already supported)
- Class-wide quiz mode: everyone answers, and the strip shows the class percentage

## v0.4 — wireless transports

Both plug into the existing `Transport` / `DiscoverySource` interfaces. No activity code changes.

- **BLE**: ✅ done for the journey board (NimBLE Nordic UART on the ESP32, `bleak` on the PC). Next: BLE in the other firmware projects, and multiple boards per classroom (naming by device ID)
- **Wi-Fi (local, no internet)**: the PC runs a WebSocket server on the classroom LAN, or an ESP32 acts as an access point; mDNS discovery `_edukit._tcp`
- Battery-powered input boxes (ESP32-C3 + LiPo, deep sleep between lessons)

## v0.5 — sensor and science activities

- New `role: "sensor"` devices: temperature, light, distance, sound level, pH
- Events `sensor_reading` with units; evaluator type `range` (e.g. "make the light level reach 500 lux")
- Activities: physical puzzles (arrange cards with RFID-free colour sensors), maths games with dice or rotary encoders, timing experiments
- Live charts on the student screen

## v1.0 — EduBond integration and scale

- Export and sync of results to EduBond when a network is available (offline-first; queued sync, conflict-free append-only results)
- Curriculum-aligned question bank packs (JSON import already supported), shared between schools
- Multi-classroom management, teacher accounts, per-student mastery tracking
- Custom PCB for input and output boxes, enclosure design, CE/FCC pre-compliance
- Accessibility: large-print mode, screen-reader labels, colour-blind-safe palettes, switch-access input
