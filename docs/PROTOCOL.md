# EduKit device protocol — version 1

## Transport and framing

- USB serial (CDC, CP210x or CH340 bridge), **115200 baud, 8N1**.
- One **JSON object per line**, UTF-8, terminated by `\n` (`\r` is ignored). Maximum 1024 bytes per line on the PC and 768 bytes on the devices. Longer lines are discarded up to the next newline.
- Lines that are not JSON objects (for example the ESP32 ROM boot banner) are ignored as "noise".
- **Bluetooth LE** (implemented in `journey_controller`): Nordic UART Service. The PC writes lines to RX (`6E400002-…`, write without response, split into MTU−3 byte chunks) and the device notifies on TX (`6E400003-…`). The framing is identical, so the decoder reassembles lines across BLE packets. PC side: `desktop/edukit/comms/ble_transport.py` (bleak).
- The same framing will be used unchanged for a future Wi-Fi (WebSocket or TCP) transport.

## Message classes

| Direction | Discriminator | Purpose |
|---|---|---|
| PC → device | `"command"` (+ `"id"`) | Command; the device must reply with `ack` or `nack` carrying the same `id` |
| PC → device | `"command":"ack"`, `"seq"` | Acknowledges a device event; no reply |
| device → PC | `"type":"hello"` | Identification (on boot and on `identify`) |
| device → PC | `"type":"event"` + `"seq"` | Input event; retransmitted every 300 ms until acked (maximum 15 tries) |
| device → PC | `"type":"ack"` / `"nack"` + `"id"` | Command result |
| device → PC | `"type":"log"` | Diagnostic text shown in the Devices tab |

`id` is a positive integer chosen by the PC. `seq` is a counter kept by the device that restarts at 1 on each boot. The PC removes duplicate events by `(boot_id, seq)`.

## Handshake and liveness

```
PC opens port  (ESP32 auto-resets because of DTR/RTS)
device → {"type":"hello","device_id":"INPUT_01","role":"input","fw":"1.0.0","proto":1,"boot_id":"9f3c11a0",
          "caps":{"channels":4,"buttons":true,"touch":true,"button_leds":true,"mode":"answer"}}
PC     → {"id":1,"command":"identify"}           (re-sent every 1 s until hello; port abandoned after 5 s)
PC     → {"id":7,"command":"ping","device_id":"INPUT_01"}      every 2 s
device → {"type":"ack","id":7}
```

The PC marks the device **lost** after 6.5 s with no traffic, closes the port, and rescans every 3 s. The device's status LED blinks slowly when the PC has been silent for more than 7 s, and stays solid while connected.

## Input controller (`role: "input"`)

### Commands

| command | parameters | effect |
|---|---|---|
| `arm` | `question_id` (string), `options` (array of labels, e.g. `["A","B","C","D"]`), `timeout_s` (optional) | Accept **one** answer from the listed options; lights those buttons |
| `disarm` | – | Stop accepting answers; button LEDs off |
| `configure` | `mapping` `{"0":"A","1":"B",…}`, `channels` (1–8), `input_type` `buttons\|touch\|both`, `mode` `answer\|raw`, `debounce_ms`, `lockout_ms`, `touch_sensitivity` (% change) | Saved to flash (NVS) |
| `set_button_leds` | `states` `[true,false,…]` | Manual control of the illuminated buttons |
| `calibrate` | – | Re-measure the touch-pad baselines (keep hands off) |
| `set_id` | `new_id` | Rename the device, e.g. `INPUT_02`; it then sends a new hello |
| `identify`, `ping` | – | – |

### Events

```json
{"type":"event","device_id":"INPUT_01","seq":17,"t_ms":51234,
 "event":"answer_selected","question_id":"Q001","selected_answer":"C","channel":2}
```

In `raw` mode (for non-quiz activities) the device reports every press and release:
`{"type":"event","event":"input_pressed","channel":0,"label":"A",…}` and `input_released`.

The PC replies to every event with `{"command":"ack","seq":17}`.

## Output controller (`role: "output"`)

| command | parameters |
|---|---|
| `play_effect` | `effect`, `color`, `color2`, `brightness` 0–255 (capped by `max_brightness`), `duration_ms` (0 = until replaced), `speed` 1–10, `value` 0–1 |
| `progress` | `value` 0–1, `color`, `color2`, `brightness` — a fill bar (races, timers) |
| `buzz` | `pattern`: `correct\|incorrect\|partial\|timeout\|celebrate\|tick`, or `freq` + `duration_ms` |
| `motor` | `channel` 0–1, `speed` 0–255, `duration_ms`, `pulse_ms` (optional on/off pulsing) |
| `stop` | Stops LEDs, buzzer and motors |
| `configure` | `num_leds` (1–300), `max_brightness`, `buzzer_enabled`, `motors_enabled` (saved to NVS) |
| `set_id`, `identify`, `ping` | as above |

**Effects:** `off, solid, blink, breathe, wipe, chase, rainbow, sparkle, progress, celebrate`.
**Presets** fill in defaults when parameters are left out: `correct` (green wipe, 3 s), `incorrect` (red blink, 3 s), `partial` (yellow breathe, 3 s), `waiting` (blue breathe, until replaced), `timeout` (orange blink, 2 s), `celebrate` (rainbow + white sparkles, 5 s).
**Colours:** a name (`red green blue yellow orange purple pink cyan white off`), `"#rrggbb"`, or `[r,g,b]`.

Example (from the specification) with the reliability fields added:

```json
{"id":42,"device_id":"OUTPUT_01","command":"play_effect","effect":"correct","color":"green","duration_ms":3000}
{"type":"ack","id":42}
```

An unknown command or effect returns `{"type":"nack","id":42,"error":"unknown effect"}`. The device never crashes on bad input.

## Game 1 devices (`role: "puzzle"`, `role: "map"`)

The word-plate board and the LED route map use the same framing and reliability rules. Their commands and events are listed in [GAME1_JOURNEY.md §5](GAME1_JOURNEY.md#5-protocol-additions).

## Versioning

`hello.proto` carries the protocol version. Additions to this version must be backwards-compatible: devices ignore unknown fields and nack unknown commands. A breaking change bumps `proto`. The v0.1 app records the version and shows it in the Devices tab; refusing incompatible firmware with a clear message is planned for v0.2 (see ROADMAP).
