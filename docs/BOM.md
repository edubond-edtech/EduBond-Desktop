# Bill of materials — first prototype (one station)

Prices are indicative retail single-unit prices (USD, 2026) and vary by supplier and region.

## Input station

| Qty | Part | Notes | ≈ Unit |
|---|---|---|---|
| 1 | ESP32-WROOM-32 DevKit v1 (CP2102 or CH340) | Any classic ESP32 DevKit with touch pins | 6 |
| 4 | 30 mm arcade push button, momentary, **5 V LED** (red, blue, green, yellow) | Colours match the on-screen A/B/C/D cards | 2 |
| 4 | NPN transistor 2N2222 / BC337 + 1 kΩ resistor | Only for illuminated buttons | 0.10 |
| 4 | Copper-tape pads 40×40 mm (touch alternative) | Or PCB touch pads | 0.30 |
| 1 | Enclosure (3 mm acrylic / MDF / 3D-printed), 200×120×60 mm | Four 30 mm holes | 5 |
| 1 | Perfboard 5×7 cm, Dupont wires, screw terminals | | 2 |
| 1 | USB data cable (USB-A/C ↔ micro-USB/USB-C, per board) | Must carry data | 2 |

## Output station

| Qty | Part | Notes | ≈ Unit |
|---|---|---|---|
| 1 | ESP32-WROOM-32 DevKit v1 | | 6 |
| 1 | WS2812B LED strip, 30 LEDs (1 m @ 30/m, IP30) | 60/m also works; set the LED count in the Devices tab | 6 |
| 1 | 5 V 3 A power supply (barrel) + DC jack | 30 LEDs at full white ≈ 1.8 A | 6 |
| 1 | 74AHCT125 quad level shifter (DIP-14) | Recommended | 0.60 |
| 1 | 330 Ω resistor; 1000 µF 10 V capacitor | Strip protection | 0.30 |
| 1 | Passive piezo buzzer 12 mm + 2N2222 + 1 kΩ | | 0.50 |
| 1–2 | Coin vibration motor 3 V/5 V (or small DC motor) | Optional | 1 |
| 1–2 | AO3400 / IRLZ44N MOSFET, 1N5819 diode, 10 kΩ + 100 Ω | Per motor | 0.40 |
| 1 | Aluminium LED channel with diffuser, 1 m | Optional; looks much better in class | 4 |
| 1 | USB data cable | | 2 |

## Totals

| Configuration | ≈ Cost |
|---|---|
| Input station (4 illuminated buttons) | 25 USD |
| Output station (30-LED strip, buzzer, 1 motor) | 30 USD |
| **Complete prototype kit** | **≈ 55 USD** (excluding the PC) |

## Tools

Soldering iron, wire stripper, multimeter, hot-glue gun, step drill for 30 mm holes (or a laser cutter).

## Scaling notes

- A classroom with one buzzer box per student group uses one input ESP32 per box. Set unique IDs with the `set_id` command (`INPUT_01…INPUT_08`). A powered USB hub with 7+ ports handles up to about 7 devices. Wi-Fi or BLE will remove the cable count limit (see ROADMAP).
- For production, a custom PCB (ESP32-C3 or S3 module + CH340 + connectors) brings an input box to about 12 USD in volume.
