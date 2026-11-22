# Game 1 — «رحلة إلى مكة» (Journey to Makkah)

The projector shows an Arabic multiple-choice question. A student answers with one of **four physical buttons** (أ ب ج د). The **same ESP32** also drives the **LED route map**:

- **Correct:** the PC speaks a praise phrase in Arabic, and the travellers move **one green step** towards Makkah.
- **Wrong:** the PC speaks, and the travellers go **one step back with a red animation**. At the start of the route the route just flashes red.

When the team reaches Makkah, the map plays an LED festival and the PC speakers play the nasheed or duaa the teacher chose. The duaa also appears on screen.

```
                        ┌──────────── ESP32 Dev Module  "JOURNEY_01" ────────────┐
 PC (EduKit)  ◀──USB──▶ │  4 buttons (A/B/C/D)  →  answer_selected               │
 projector + speakers   │  WS2812B strip on the map  ←  path_advance / path_back │
                        └────────────────────────────────────────────────────────┘
```

> **Alternative layout (still supported):** resistor-coded word plates on a separate board (`PUZZLE_01`) plus a map-only ESP32 (`MAP_01`). It is described in §1–§3 (plates) below. The game picks the layout from the question type: multiple-choice questions use the buttons, word-arrangement sentences use the plates.

## Current layout: two ESP32 boards (touch board + LED board)

The kit now uses **two boards**, both built from `firmware/journey_controller` (one source, separate PlatformIO environments). Board 1 is an ESP32 Dev Module; board 2 is currently an **ESP32-C3**:

| Board | Env | Device id / BLE name | Role | Wiring |
|---|---|---|---|---|
| **1: touch answers** | `touch_input` | `INPUT_01` / «EduKit-INPUT_01» | `input` | Pad 1 (أ/A) → **GPIO27** · pad 2 (ب/B) → **GPIO14** · pad 3 (ج/C) → **GPIO13** · pad 4 (د/D) → **GPIO4**. Copper/foil pads wired directly, with no resistor and no GND |
| **2: LED route** | `led_map` | `MAP_01` / «EduKit-MAP_01» | `map` | Strip **DIN → GPIO26** (330 Ω in series) · strip +5V and GND to a 5 V supply · **common GND with the ESP32** |
| **2: LED route on ESP32-C3** (in use now) | `led_map_c3` | `MAP_01` / «EduKit-MAP_01» | `map` | Strip **DIN → GPIO7 (IO7)** (330 Ω in series) · strip +5V and GND to a 5 V supply · **common GND with the C3**. The C3 has no buzzer pin and no touch sensor |

```
cd firmware/journey_controller
pio run -e touch_input -t upload --upload-port <port of board 1>
pio run -e led_map     -t upload --upload-port <port of board 2>   # ESP32 Dev Module, strip on GPIO26
pio run -e led_map_c3  -t upload --upload-port <port of board 2>   # ESP32-C3, strip on GPIO7
```

- No app setting is needed. The game arms the answers on the `input` board, because the `map` board reports no `buttons` capability, and sends `path_advance` / `path_back` / `festival` to the `map` board.
- Pair **both** boards in **🔌 الأجهزة ← 🔍 بحث ← 🔗 ربط**.
- Each variant stores its settings in its own NVS namespace (`edukit_in` / `edukit_map`), so a board that previously ran the combined firmware does not keep the old id `JOURNEY_01`.
- The touch board reports `{"buttons":4,"touch":true,"button_leds":false,"input_type":"touch"}`. The LED board reports `{"leds":60,"steps":6,"touch":false,"button_leds":false}`. Configure the number of LEDs, steps and brightness on the LED board, and the touch sensitivity and calibration on the touch board.
- The combined single-board firmware (env `esp32dev`, `JOURNEY_01`, §A) is still available.

## Connection: Bluetooth (default) or USB

The board talks to the PC over **Bluetooth Low Energy**, so no cable to the computer is needed. USB is only used to flash the firmware and as an optional fallback.

- The board advertises as **«EduKit-JOURNEY_01»** using the Nordic UART Service (UUID `6E400001-B5A3-F393-E0A9-E50E24DCCA9E`; RX `…0002` write, TX `…0003` notify). It carries **exactly the same JSON lines** as USB.
- **EduKit connects automatically** when the board is powered and in range (about 10 m), and reconnects after a drop. **Devices → Bluetooth LE** shows the boards in range.
- **Powering the board without a PC cable:** a USB phone charger or power bank into the ESP32's USB port, or 5 V from the strip's supply into the **VIN/5V** pin (with common GND).
- **macOS:** the first launch asks *"EduKit would like to use Bluetooth"*; click **Allow**. If you clicked "Don't Allow", re-enable it in **System Settings → Privacy & Security → Bluetooth → EduKit**.
- **Windows 10/11:** works with the built-in Bluetooth (or any Bluetooth 4.0+ USB dongle). There is nothing to pair; EduKit connects directly.
- **Both USB and Bluetooth on:** if the same board is reachable both ways, EduKit keeps the first link and ignores the second, so they never fight.
- **Self-test:** `EduKit --ble-selftest report.txt` (on macOS: `open -W -a EduKit --args --ble-selftest ~/Desktop/ble.txt`) connects, sends test commands, waits for a button press and writes a report.
- **Verified on the real board:** connected over Bluetooth in about 11 s, MTU 247, every command acknowledged, round-trip time ≈ 65 ms.

## A. Wiring — combined single board, map + buttons (`firmware/journey_controller`, env `esp32dev`)

Board: **ESP32 Dev Module** (ESP32-WROOM-32 DevKit). Strip: **3-pin 5 V addressable RGB strip** (WS2812B / SK6812 type, pins **+5V · DIN · GND**).

| Function | ESP32 pin | Notes |
|---|---|---|
| LED strip **DIN** | **GPIO18** | Through a 330 Ω resistor. A 74AHCT125 level shifter is recommended for long cables |
| Button **A** (أ, red) | **GPIO32** | Other leg of the button to **GND** (internal pull-up, no resistor needed) |
| Button **B** (ب, blue) | **GPIO33** | → GND |
| Button **C** (ج, green) | **GPIO25** | → GND |
| Button **D** (د, yellow) | **GPIO26** | → GND |
| **Touch pad A** (أ) — pad 1 | **GPIO27** (T7) | Copper tape or foil, about 4×4 cm. Wire it directly: no resistor, no GND |
| **Touch pad B** (ب) — pad 2 | **GPIO14** (T6) | |
| **Touch pad C** (ج) — pad 3 | **GPIO13** (T4) | |
| **Touch pad D** (د) — pad 4 | **GPIO4** (T0) | |
| Button lamps (optional) | GPIO16 / 17 / 21 / 22 | Lit while the question is open; only the pressed one stays lit. Use a transistor for 5–12 V lamps |
| Buzzer (optional) | GPIO23 | Short click on each press |
| Status LED | GPIO2 (on-board) | Solid when the PC is connected, blinking when not |

```
   5 V power supply (≥ 3 A for 60 LEDs)                       ESP32 Dev Module
   +5V ──────────────────────┬──────────────► strip +5V
                             │ 1000 µF
   GND ──────────────────────┴──────┬───────► strip GND
                                    └───────── GND ─────────┐
   strip DIN ◄──[330 Ω]──────────────────────────── GPIO18  │
                                                            │
   [A] GPIO32 ──o o── GND ──────────────────────────────────┤
   [B] GPIO33 ──o o── GND ──────────────────────────────────┤
   [C] GPIO25 ──o o── GND ──────────────────────────────────┤
   [D] GPIO26 ──o o── GND ──────────────────────────────────┘
   touch pads (optional): GPIO27 ── pad 1 (A) · GPIO14 ── pad 2 (B) · GPIO13 ── pad 3 (C) · GPIO4 ── pad 4 (D)
   ESP32 powered from the PC's USB cable (also the data link)
```

- **Buttons, touch pads, or both:** choose in **الخريطة والأزرار والصوت → طريقة الإجابة** (default: both). The pads have their own pins, so you can fit arcade buttons and touch pads at the same time, for example a touch pad printed under each answer colour on the map.
- **Touch pads:** keep wires **under 30 cm** and away from the LED-strip wires. Pads work through 1–3 mm of plastic, acrylic, cardboard or a laminated sticker. The board measures the pads at power-up, so keep hands off for one second, or press **معايرة اللمس**. Use **قراءة قيم اللمس** to see the live values. An untouched pad reads a steady value (about 100 on the test board); a finger on a foil pad drops it by well over 20 % (the default threshold). If touches are missed, lower **حساسية اللمس**; if there are false touches, raise it.
- **Common GND is required:** the strip's power supply GND must be connected to the ESP32 GND.
- **Power:** do not power more than ~10 LEDs from the ESP32's 5V/VIN pin. Use a separate 5 V supply for the strip. The software brightness cap (default 150/255) limits the current.
- **Strip direction:** LED 0 (the end with the DIN arrow) is at **Indonesia** and the last LED is at **Makkah**. If the cities are not evenly spaced along the strip, set each station's LED number in the app (**الخريطة والأزرار والصوت → أضواء المحطات**).
- **Colours:** if red and green are swapped (some strips are RGB rather than GRB), change `NEO_GRB` to `NEO_RGB` at the `Adafruit_NeoPixel strip(...)` line.
- **Flashing:**

```bash
cd firmware/journey_controller && pio run -t upload
```

In the Arduino IDE, choose the board "ESP32 Dev Module" and install the libraries ArduinoJson 7 and Adafruit NeoPixel.

### Bill of materials (combined version)

| Qty | Part | ≈ USD |
|---|---|---|
| 1 | ESP32 Dev Module (ESP32-WROOM-32 DevKit) | 6 |
| 4 | 30 mm arcade buttons, red / blue / green / yellow (optionally illuminated) | 8 |
| 1 | 5 V 3-pin WS2812B strip, 60 LEDs | 8 |
| 1 | 5 V 3–4 A power supply + DC jack, 1000 µF capacitor, 330 Ω resistor | 8 |
| 1 | Printed route map (A1/A0) on foam board + button box | 12 |
| 1 | USB data cable | 2 |
| | **Total** | **≈ 44** |

### Protocol (combined device)

`hello`: `{"type":"hello","device_id":"JOURNEY_01","role":"map","caps":{"leds":60,"steps":6,"buzzer":true,"buttons":4,"button_leds":true,"touch":true,"ble":true,"input_type":"both"}}`

| PC → ESP32 | Effect |
|---|---|
| `arm {question_id, options:["A","B","C","D"], timeout_s}` | Buttons accept **one** press; their lamps light |
| `disarm` | Buttons locked |
| `configure {input_type: buttons\|touch\|both, touch_sensitivity}` | Answer input method (saved in flash) |
| `calibrate` · `read_touch` | Re-measure the touch pads · reply with a `touch_readings` event `{values, baselines, touched}` |
| `path_set {step}` · `path_advance {from,to,duration_ms}` · `path_back {from,to,duration_ms}` · `path_fail {step}` · `festival {duration_ms}` · `configure {num_leds,steps,waypoints,brightness}` · `buzz {pattern}` · `stop` | Route map, same as `map_controller` |

| ESP32 → PC | |
|---|---|
| `{"type":"event","event":"answer_selected","question_id":"J001","selected_answer":"C","channel":2,"seq":5}` | Retransmitted every 300 ms until the PC acks `{"command":"ack","seq":5}` |

Debounce is 30 ms and the repeat lock-out is 400 ms. The board accepts one answer per `arm`, and the PC ignores late or stale presses.

### Speech and sounds on the PC

Priority for each event:

1. The teacher's recorded file (MP3/WAV), if one was chosen.
2. A spoken Arabic phrase from the operating system's offline voice.
3. A built-in tone.

- **macOS:** includes the Arabic voice «Majed».
- **Windows 10/11:** install the free Arabic speech voice under **Settings → Time & Language → Speech → Add voices → العربية**. This needs internet once; after that it works offline.
- **Phrases:** editable in **الخريطة والأزرار والصوت → النطق بالعربية**. The defaults are «أحسنت! إجابة صحيحة», «إجابة خاطئة، رجعنا خطوة إلى الوراء» and «مبارك! وصلنا إلى مكة المكرمة». You can optionally have the question and options read aloud.

### Hardware checks (combined version — need the physical kit)

| # | Test | Pass criteria |
|---|---|---|
| B1 | Power the board, start EduKit | `JOURNEY_01` online **via ble** with `buttons: 4`; the strip runs its self-test, then rests at Indonesia |
| B2 | Press A, B, C, D on one question each | Each press selects the right answer on screen; only the first press counts |
| B2t | Touch pads A–D (input method «اللمس فقط») | Each touch registers once; no false touches in 5 min idle |
| B3 | Hammer one button 20× | Exactly one answer recorded |
| B4 | Correct answer | Spoken praise + green comet to the next station on strip and screen |
| B5 | Wrong answer after step 1 | Spoken phrase + red step back on strip and screen |
| B6 | Reach Makkah | LED festival + chosen nasheed/duaa + duaa on screen |
| B7 | Unplug USB mid-question, reconnect | App keeps running; buttons re-armed after reconnect |
| B8 | 1 min festival at full brightness | No ESP32 reset; supply and strip stay cool |

---

## 1. Alternative: how the word plates work

- All plates **look the same** to the students. Each one hides a resistor between its two plug pins.
- The answer key is **fixed in the firmware**: socket 1 expects plate 1, socket 2 expects plate 2, and so on (`EXPECTED_PLATE[]` in `firmware/puzzle_controller/src/main.cpp`).
- For each sentence, the teacher writes **word 1 on plate 1, word 2 on plate 2, …**, using a whiteboard sticker or a clip-on word card. The teacher recognises the plates with their own key: a hidden mark, or the **Teacher key** readout in the app (plug any plate into any socket and the app shows its number; the projector never does).
- The projector shows the words in a **scrambled** order with no numbers or colours, so the students must actually read the sentence.
- **Socket 1 is the right-most socket**, because Arabic reads right to left. Socket 1 holds the first word.

| Plate | Resistor (5 % or better) | Voltage at ADC (Rref 10 kΩ, 3.3 V) | Measured on PUZZLE_01 |
|---|---|---|---|
| 1 | 2 kΩ | ≈ 2.75 V | 2.75 V |
| 2 | 4.7 kΩ | ≈ 2.24 V | 2.26 V |
| 3 | 12 kΩ | ≈ 1.50 V | 1.52 V |
| 4 | 20 kΩ | ≈ 1.10 V | 1.11 V |
| 5 | 47 kΩ | ≈ 0.58 V | 0.59 V |
| 6 | 120 kΩ | ≈ 0.25 V | 0.26 V |
| empty | – | 0 V (< 0.15 V) |

The closest pair (47k / 120k) is 325 mV apart, more than twice the 140 mV match tolerance. A unit test checks that the firmware table matches `desktop/edukit/hardware/plates.py`.

## 2. Wiring — word-card board (`firmware/puzzle_controller`, `PUZZLE_01`, BLE «EduKit-PUZZLE_01»)

**How a round works:** the PC shows «رتّب الكلمات التالية في جملة مفيدة» with the words shuffled, and arms the board with the number of words *n* (2–6). The students lay the cards in places 1..*n*, place 1 being the right-most, then press **SEND**. The board reads the cards and sends `puzzle_result`. The PC decides correct or wrong, speaks, and moves the map board one green step forward or one red step back.
- **A card in a place beyond *n*** makes the answer wrong.
- **SEND with an empty place 1..*n*** sends `puzzle_incomplete`. The projector then shows «ضعوا كل البطاقات أولًا» with the empty places, and nothing is recorded.
- **After a judgement the board disarms.** On a retry the PC re-arms it, and the students fix the cards and press SEND again.
- **The cards are linked over Bluetooth like the other boards.** Pair it in **🔌 الأجهزة**.


Use an ESP32-WROOM-32 DevKit. Only **ADC1** pins are used, so Wi-Fi can be added later.

| Socket | ESP32 pin | Position on the board |
|---|---|---|
| 1 (first word) | GPIO36 (VP) | right-most |
| 2 | GPIO39 (VN) | |
| 3 | GPIO34 | |
| 4 | GPIO35 | |
| 5 | GPIO32 | |
| 6 (last word) | GPIO33 | left-most |
| status LED | GPIO2 (on-board) | |
| **SEND button** | **GPIO27** → button → **GND** | internal pull-up, no resistor. Judging happens **only** when it is pressed |
| lamp in the SEND button (optional) | GPIO26 | on while the board waits for an answer (use a transistor for a 5–12 V lamp) |
| click buzzer (optional) | GPIO25 | |

Each socket (repeat 6×):

```
                 socket contact A ─────────── 3V3
  ┌──────────┐
  │  PLATE   │  resistor Rp between the plate's two pins
  └──────────┘
                 socket contact B ──┬──────── GPIO36 (socket 1)
                                    ├─[10 kΩ]─ GND     (Rref, 1 %)
                                    └─[100 nF]─ GND    (noise filter)
```

- **Connectors.** Any 2-pin keyed connector works: 2-pin JST-XH, DC barrel jack and plug, 3.5 mm mono jack, or a pair of banana plugs. The plug must be **polarity-proof**: the circuit is a resistor, so polarity doesn't matter electrically, but each plate must fit every socket.
- An empty socket reads 0 V through Rref, so the board always knows which sockets are empty.
- Put the resistor inside the plate (heat-shrink, then glue). The plates must be indistinguishable from the outside.
- **Calibration (optional).** If a plate reads near a boundary, place plate *P* in socket *S* and send `{"id":1,"command":"learn_plate","plate":P,"socket":S}`. The measured voltage is stored in flash. `reset_calibration` restores the theoretical values.

## 3. Wiring — route map (`firmware/map_controller`)

| Function | ESP32 pin |
|---|---|
| WS2812B DIN | GPIO18 (330 Ω series; 74AHCT125 recommended) |
| buzzer (optional) | GPIO25 |
| status LED | GPIO2 |

- Lay the strip along the route on the printed map. **LED 0 is at Indonesia** and the last LED is at **Makkah**.
- Power: 60 LEDs × 60 mA ≈ 3.6 A at full white. Use a 5 V / 4 A supply, a common GND with the ESP32, and a 1000 µF capacitor across the strip. The brightness cap (default 150/255) keeps the real draw near 1.5 A.
- **Stations.** By default the stations are spread evenly. If the map's cities are not evenly spaced, enter the LED number of each station in **رحلة إلى مكة → الخريطة واللوحة والصوت → أضواء المحطات** (for example `0,9,20,31,40,51,59`). You need one number per station: *steps + 1*.

On the strip, the route still to travel is faint blue, the travelled route is green, passed stations are gold, the travellers are a pulsing white light, and Makkah pulses gold. A correct answer moves the light forward like a comet. A wrong answer flashes the travelled route red. Arrival triggers a green/gold chase with white sparkles while Makkah flashes.

## 4. Bill of materials (additional to the core kit)

| Qty | Part | ≈ USD |
|---|---|---|
| 2 | ESP32-WROOM-32 DevKit (board + map) | 12 |
| 6 | Identical plates (MDF/acrylic 8×5 cm) with a 2-pin plug | 6 |
| 6 | Resistors 2k, 4.7k, 12k, 20k, 47k, 120k | 0.5 |
| 6 | Matching 2-pin sockets on the board | 3 |
| 6 + 6 | 10 kΩ 1 % (Rref) + 100 nF capacitors | 0.5 |
| 6 | Whiteboard stickers or clip-on word cards | 3 |
| 1 | WS2812B strip, 60 LEDs (1 m @ 60/m or 2 m @ 30/m) | 8 |
| 1 | 5 V 4 A supply, DC jack, 1000 µF capacitor, 330 Ω, 74AHCT125 | 9 |
| 1 | Printed route map (A1/A0, Indonesia → Makkah), foam board | 10 |
| 1 | Passive buzzer + 2N2222 (optional, map or board) | 0.5 |
| | **Total** | **≈ 53** |

## 5. Protocol additions

Roles: `"puzzle"` (board) and `"map"` (route). The framing, acks, retries and heartbeat are the same as in [PROTOCOL.md](PROTOCOL.md).

**PC → board**

| command | parameters |
|---|---|
| `arm` | `question_id`, `sockets` (number of words, 1–6). Optional advanced `expected` overrides the fixed key. A new `question_id` while plates are still in → `board_state: clear_required` |
| `disarm` | – |
| `configure` | `tolerance_mv` (default 140), `settle_ms` (250), `complete_ms` (600), `click_sound` |
| `learn_plate` | `plate`, `socket` (calibration) |
| `reset_calibration`, `read_raw`, `identify`, `ping`, `set_id` | |

**Board → PC (events, acked by seq)**

```json
{"type":"event","event":"plate_inserted","socket":3,"plate":5,"mv":668,...}
{"type":"event","event":"plate_removed","socket":3,...}
{"type":"event","event":"plate_unknown","socket":2,"mv":1220,...}
{"type":"event","event":"board_state","state":"ready|clear_required","question_id":"Q101",...}
{"type":"event","event":"puzzle_result","question_id":"Q101","placed":[1,2,3,5,4,6],
 "expected":[1,2,3,4,5,6],"in_place":4,"result":"fail",...}
{"type":"event","event":"raw_readings","mv":[...],"plates":[...],...}
```

A result is sent each time the first *n* sockets become full and stay full for `complete_ms`. Any later change allows a new result, so the team can pull plates out and try again. The PC re-checks every result itself, and a result for an old `question_id` is ignored.

**PC → map:** `configure {num_leds, steps, waypoints, brightness}`, `path_set {step}`, `path_advance {from, to, duration_ms}`, `path_fail {step, duration_ms}`, `festival {duration_ms}`, `buzz {pattern}`, `stop`.

## 6. Game rules and teacher settings

| Setting | Default |
|---|---|
| Correct answers needed to reach Makkah | 6 (one per station: إندونيسيا، ماليزيا، الهند، عُمان، اليمن، جدة، مكة المكرمة) |
| On a wrong answer | Move to another question (or retry the same one) |
| Step back on a wrong answer | **On**: one red step back |
| Feedback time | 4 s |
| Timer per sentence | Off (each sentence has its own time when enabled) |
| Shuffle sentences | On; the sentences repeat in a new order until the team reaches Makkah |
| Answer on screen when no board is connected | On (click the words in order) |
| Festival length on the map | 20 s |
| Audio | Built-in tunes, or teacher-chosen MP3/WAV/M4A for festival, correct and wrong (copied into the app folder, plays offline) |

Results are saved per session, with the team name, every attempt, the placement and the time. They appear in **Results & reports**.

## 7. دليل المعلم السريع

1. وصّل لوحة الرحلة (الخريطة والأزرار الأربعة) بالحاسوب بكابل USB، ثم افتح البرنامج وانتقل إلى تبويب **«🕋 رحلة إلى مكة»**.
2. في تبويب **«الأسئلة»** أضف أسئلتك بالضغط على «＋ سؤال اختيار (٤ أزرار)»: اكتب السؤال والخيارات الأربعة وحدّد الإجابة الصحيحة. الألوان تطابق الأزرار: أ أحمر، ب أزرق، ج أخضر، د أصفر.
3. في تبويب **«الخريطة والأزرار والصوت»** يمكنك:
   - اختيار ملف النشيد أو الدعاء الذي يُشغَّل عند الوصول إلى مكة؛
   - تعديل العبارات التي ينطقها الحاسوب بعد كل إجابة.
4. في **«بدء الرحلة»** اكتب اسم الفريق واختر عدد المحطات، ثم اضغط **«ابدأ الرحلة إلى مكة»**، ويُفضَّل تفعيل ملء الشاشة على جهاز العرض.
5. يظهر السؤال على الشاشة ويضغط الطالب أحد الأزرار:
   - الإجابة الصحيحة: يقول الحاسوب «أحسنت!» وتتقدّم الأضواء خطوة خضراء نحو مكة.
   - الإجابة الخاطئة: ترجع الأضواء خطوة حمراء إلى الوراء وتظهر الإجابة الصحيحة على الشاشة.
6. عند الوصول إلى مكة يبدأ احتفال الأضواء ويُشغَّل الصوت الذي اخترته، ويظهر على الشاشة الدعاء: «رَبَّنَا تَقَبَّلْ مِنَّا إِنَّكَ أَنتَ السَّمِيعُ الْعَلِيمُ».

(نسخة البطاقات البديلة: أضف «جملة ترتيب (بطاقات)»، واكتب الكلمة ١ على البطاقة ١ وهكذا، واستعمل «مفتاح المعلم» لمعرفة أرقام البطاقات.)

## 8. Hardware validation (needs the physical kit)

| # | Test | Pass criteria |
|---|---|---|
| J1 | Boot both boards, start EduKit | `PUZZLE_01` and `MAP_01` online in Devices; the map runs a self-test sweep, then rests at Indonesia |
| J2 | Plug each plate into each socket (36 combinations) | The Teacher key shows the right plate number every time; no `plate_unknown` |
| J3 | Wiggle a plate while it is seated | No insert/remove flicker (settle 250 ms); raise `settle_ms` if needed |
| J4 | Correct sentence | Result arrives about 0.6 s after the last plate; green banner; travellers advance on strip and screen |
| J5 | Wrong order, then fix it by re-plugging | Red flash; the corrected attempt is accepted without restarting |
| J6 | Next sentence with plates still in | Screen asks to remove the plates; nothing is judged until the board is empty |
| J7 | Reach Makkah | LED festival on the map + the chosen audio on the PC speakers + duaa on screen |
| J8 | Unplug the board mid-game, reconnect | Game continues (on-screen entry), then the board re-arms automatically |
| J9 | Power: festival at full brightness for 1 min | No ESP32 reset; supply and strip stay cool |
| J10 | Projector check from the back of the class | Words readable; plates on screen give no hint of their number |
