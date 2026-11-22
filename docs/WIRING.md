# Wiring and GPIO assignments

Both controllers use an **ESP32-WROOM-32 DevKit v1** (30- or 38-pin). Pins were chosen to avoid strapping pins (GPIO0, 2*, 5, 12, 15), flash pins (GPIO6–11) and input-only pins (GPIO34–39) for anything that needs a pull-up or an output. (*GPIO2 is used only for the on-board status LED.)

## Input controller (`firmware/input_controller`)

| Channel | Answer | Push button | Touch pad | Button LED |
|---|---|---|---|---|
| 0 | A | GPIO25 | GPIO32 (T9) | GPIO16 |
| 1 | B | GPIO26 | GPIO33 (T8) | GPIO17 |
| 2 | C | GPIO18 | GPIO27 (T7) | GPIO21 |
| 3 | D | GPIO19 | GPIO14 (T6) | GPIO22 |
| 4 | E (expansion) | GPIO4 | – | – |
| 5 | F (expansion) | GPIO13 | – | – |
| – | status | – | – | GPIO2 (on-board) |

The answer for each channel is set in software (Devices tab → *Button → answer*) and saved on the ESP32.

### Push buttons (active-low, internal pull-up — no resistors needed)

```
            ESP32                         Arcade button (A)
        ┌──────────┐                    ┌───────────────┐
        │   GPIO25 ├────────────────────┤ NO        COM ├────┐
        │          │                    └───────────────┘    │
        │      GND ├─────────────────────────────────────────┴── common GND bus
        └──────────┘          (repeat for B=GPIO26, C=GPIO18, D=GPIO19)
```

### Illuminated buttons (optional)

12 V arcade-button lamps must **not** be driven directly. Use 5 V LED buttons or a small NPN or MOSFET stage:

```
GPIO16 ──[1 kΩ]──┐
                 B  2N2222 / BC337         +5V ──[LED button lamp (+)]
                 E ── GND                         [lamp (−)] ── C (collector)
```

For a single low-current 3 mm LED (≤ 8 mA), a direct `GPIO ──[330 Ω]── LED ── GND` is fine.

### Capacitive touch pads

Use copper tape or a PCB pad of 3×3 cm or more under 1–3 mm of acrylic or cardboard. Connect each pad directly to its touch pin with a wire **under 30 cm** (shielded or kept away from mains wiring). Select *Capacitive touch pads* or *Buttons + touch* in the Devices tab. The firmware calibrates the pads at power-up (keep hands off for one second) and tracks slow drift. Raise *Touch sensitivity* if touches are missed, and lower it if there are false triggers.

```
GPIO32 (T9) ─────────── copper pad "A"      (no resistor, no ground connection)
```

## Output controller (`firmware/output_controller`)

| Function | GPIO | Notes |
|---|---|---|
| WS2812B DIN | GPIO18 | 330 Ω series resistor; 74AHCT125 level shifter recommended |
| Buzzer | GPIO25 | Passive piezo buzzer through an NPN transistor (LEDC tone) |
| Motor 0 | GPIO26 | Logic-level MOSFET (e.g. AO3400 / IRLZ44N) + flyback diode |
| Motor 1 | GPIO27 | Same as motor 0 |
| Status LED | GPIO2 | On-board |

### WS2812B strip

```
  5 V PSU (≥ 3 A for 30 LEDs at full white; 60 mA per LED)
   +5V ───────────────┬──────────────────────────────► strip +5V
                      │  1000 µF / 10 V electrolytic across +5V/GND at the strip
   GND ───────────────┴───────────┬──────────────────► strip GND
                                  │
  ESP32 GND ──────────────────────┘   (common ground is mandatory)
  ESP32 GPIO18 ──► 74AHCT125 (1A→1Y, 1OE→GND, VCC=5V) ──[330 Ω]──► strip DIN
```

- Without a level shifter, most strips still work with 3.3 V data on short runs. If you skip it, add the 330 Ω resistor and keep the first LED within 50 cm of the ESP32.
- **Do not power the strip from the ESP32's 5 V pin** beyond about 10 LEDs at low brightness. The software brightness cap (*Max brightness*, default 200/255) limits current.
- Inject power at both ends for strips longer than 60 LEDs.

### Buzzer

```
GPIO25 ──[1 kΩ]── B  NPN (2N2222)     +5V ── buzzer(+)   buzzer(−) ── C
                      E ── GND
```

A **passive** buzzer plays the melodies. An active buzzer only beeps at one pitch.

### Vibration or DC motor

```
GPIO26 ──[100 Ω]── Gate  MOSFET (AO3400)     +5V ── motor(+)   motor(−) ── Drain
                   Source ── GND             1N4148/1N5819 across the motor (cathode to +5V)
                   [10 kΩ gate-to-GND pull-down]
```

## Power and USB

- Each ESP32 is powered and connected to the PC through its own USB cable. Use data-capable cables; many charge-only cables will not show a serial port.
- The LED strip's 5 V supply shares **GND** with the ESP32, but its +5 V must not back-feed into USB.
- Both boards need USB-serial drivers: CP210x (Silicon Labs) or CH340/CH9102 (WCH). macOS 13+ and Windows 10/11 include drivers for most boards.
