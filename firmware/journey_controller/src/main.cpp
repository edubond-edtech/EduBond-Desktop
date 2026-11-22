/*
 * EduKit — Game 1 «رحلة إلى مكة» — journey firmware, three board variants (see platformio.ini):
 *   touch_input : board 1 — 4 capacitive answer pads only. Role "input", id INPUT_01.
 *                 A=GPIO27 (T7), B=GPIO14 (T6), C=GPIO13 (T4), D=GPIO4 (T0).
 *   led_map     : board 2 — WS2812B route strip only, DIN on GPIO26. Role "map", id MAP_01.
 *   led_map_c3  : board 2 on an ESP32-C3 (CH340 USB) — strip DIN on GPIO7. Role "map", id MAP_01.
 *   esp32dev    : the original single board (strip on GPIO18 + buttons + touch). Role "map", JOURNEY_01.
 * Board: ESP32 Dev Module (ESP32-WROOM-32). Each variant keeps its settings in its own NVS
 * namespace, so re-flashing a board with another variant never inherits the old device id.
 *
 * The PC shows a multiple-choice question; it "arms" the buttons. The first
 * press of an allowed button is sent to the PC (answer_selected, retransmitted
 * until acknowledged) and the buttons lock until the next question.
 * Correct -> PC sends path_advance (one green step towards Makkah).
 * Wrong   -> PC sends path_back (one red step back) or path_fail at the start.
 * Rendering mirrors desktop/edukit/feedback/route.py.
 *
 * Links: USB serial AND Bluetooth LE (Nordic UART Service, name "EduKit-JOURNEY_01"),
 * same JSON protocol on both. The PC app connects over BLE by default.
 *
 * Wiring (docs/GAME1_JOURNEY.md):
 *   LED strip (3-pin 5 V WS2812B: +5V / DIN / GND)  DIN <- GPIO18 via 330 Ω
 *   Answers can be mechanical buttons, capacitive TOUCH pads, or both (configure input_type):
 *            button (to GND)   touch pad (copper/foil, no resistor)
 *     A أ    GPIO32            GPIO27 (T7)
 *     B ب    GPIO33            GPIO14 (T6)
 *     C ج    GPIO25            GPIO13 (T4)
 *     D د    GPIO26            GPIO4  (T0)
 *   Touch pads are calibrated at power-up: keep hands off for 1 s.
 *   Button A (أ, red)    GPIO32 -> button -> GND   (internal pull-up)
 *   Button B (ب, blue)   GPIO33 -> button -> GND
 *   Button C (ج, green)  GPIO25 -> button -> GND
 *   Button D (د, yellow) GPIO26 -> button -> GND
 *   Button lamps (optional) GPIO16 / 17 / 21 / 22 (via transistor for 5-12 V lamps)
 *   Buzzer (optional) GPIO23 · on-board status LED GPIO2
 *   Strip power from a 5 V supply; GND of supply, strip and ESP32 joined.
 */
#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <NimBLEDevice.h>

// ------------------------------------------------------------------ Bluetooth LE (Nordic UART Service)
// The same newline-delimited JSON as USB, carried over BLE: the PC writes to RX, the board notifies on TX.
#define NUS_SERVICE_UUID "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
#define NUS_RX_UUID "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  // PC -> board (write)
#define NUS_TX_UUID "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  // board -> PC (notify)
static NimBLECharacteristic *bleTx = nullptr;
static volatile bool bleConnected = false;
static volatile uint16_t bleMtu = 23;
static uint8_t bleRing[2048];
static volatile uint16_t bleHead = 0, bleTail = 0;
static portMUX_TYPE bleMux = portMUX_INITIALIZER_UNLOCKED;

class BleServerCB : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer *s, ble_gap_conn_desc *desc) override { bleConnected = true; bleMtu = 23; }
  void onDisconnect(NimBLEServer *s) override { bleConnected = false; NimBLEDevice::startAdvertising(); }
  void onMTUChange(uint16_t mtu, ble_gap_conn_desc *desc) override { bleMtu = mtu; }
};

class BleRxCB : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic *c) override {
    std::string v = c->getValue();
    portENTER_CRITICAL(&bleMux);
    for (char ch : v) {
      uint16_t next = (bleHead + 1) % sizeof(bleRing);
      if (next == bleTail) break;  // full: drop (the PC retries commands)
      bleRing[bleHead] = (uint8_t)ch;
      bleHead = next;
    }
    portEXIT_CRITICAL(&bleMux);
  }
};

int bleReadByte() {
  int c = -1;
  portENTER_CRITICAL(&bleMux);
  if (bleTail != bleHead) { c = bleRing[bleTail]; bleTail = (bleTail + 1) % sizeof(bleRing); }
  portEXIT_CRITICAL(&bleMux);
  return c;
}

void bleBegin(const char *deviceId) {
  String name = String("EduKit-") + deviceId;
  NimBLEDevice::init(name.c_str());
  NimBLEDevice::setPower(ESP_PWR_LVL_P9);
  NimBLEDevice::setMTU(247);
  NimBLEServer *server = NimBLEDevice::createServer();
  server->setCallbacks(new BleServerCB());
  NimBLEService *svc = server->createService(NUS_SERVICE_UUID);
  bleTx = svc->createCharacteristic(NUS_TX_UUID, NIMBLE_PROPERTY::NOTIFY);
  NimBLECharacteristic *rx = svc->createCharacteristic(NUS_RX_UUID, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);
  rx->setCallbacks(new BleRxCB());
  svc->start();
  NimBLEAdvertising *adv = NimBLEDevice::getAdvertising();
  adv->addServiceUUID(NUS_SERVICE_UUID);
  adv->setScanResponse(true);  // the name goes in the scan response
  adv->start();
}

void bleSend(const String &line) {
  if (!bleConnected || !bleTx) return;
  size_t chunk = bleMtu > 23 ? bleMtu - 3 : 20;
  const uint8_t *p = (const uint8_t *)line.c_str();
  size_t len = line.length();
  for (size_t off = 0; off < len; off += chunk) {
    size_t n = min(chunk, len - off);
    bleTx->setValue(p + off, n);
    bleTx->notify();
    if (off + n < len) delay(4);  // let the stack drain between chunks
  }
}

// Every protocol line goes to USB and (when connected) BLE.
void sendLine(const String &line) {
  Serial.print(line);
  Serial.print('\n');
  bleSend(line + "\n");
}

// ---- board variant (chosen per PlatformIO env) ----
//   EDUKIT_TOUCH_ONLY : board 1 = the 4 touch answer pads only        -> role "input"
//   EDUKIT_LED_ONLY   : board 2 = the LED route strip only (GPIO 26)  -> role "map"
//   (neither)         : the original single board with strip + buttons + touch
#if defined(EDUKIT_TOUCH_ONLY)
#define HAS_STRIP 0
#define HAS_BUTTONS 0
#define HAS_TOUCH 1
#define DEVICE_ROLE "input"
#define NVS_NS "edukit_in"
#ifndef EDUKIT_DEVICE_ID
#define EDUKIT_DEVICE_ID "INPUT_01"
#endif
#elif defined(EDUKIT_LED_ONLY)
#define HAS_STRIP 1
#define HAS_BUTTONS 0
#define HAS_TOUCH 0
#define DEVICE_ROLE "map"
#define NVS_NS "edukit_map"
#ifndef LED_PIN
#define LED_PIN 26
#endif
#ifndef EDUKIT_DEVICE_ID
#define EDUKIT_DEVICE_ID "MAP_01"
#endif
#else
#define HAS_STRIP 1
#define HAS_BUTTONS 1
#define HAS_TOUCH 1
#define DEVICE_ROLE "map"
#define NVS_NS "edukit"
#ifndef EDUKIT_DEVICE_ID
#define EDUKIT_DEVICE_ID "JOURNEY_01"
#endif
#endif
#define FW_VERSION "1.1.0"
#define PROTO_VERSION 1
#define BAUD 115200
#ifndef LED_PIN
#define LED_PIN 18
#endif
#ifndef BUZZER_PIN
#define BUZZER_PIN 23  // -1 = no buzzer (e.g. ESP32-C3, which has no GPIO23)
#endif
#define TOUCH_SAMPLE_MS 10
#define TOUCH_DEBOUNCE_MS 40
#define TOUCH_MIN_DROP 6  // ignore tiny changes (unconnected pins, noise)
static const int8_t TOUCH_PINS[4] = {27, 14, 13, 4};  // answer 1(A)=GPIO27 T7, 2(B)=GPIO14 T6, 3(C)=GPIO13 T4, 4(D)=GPIO4 T0 (as wired on the board)
enum InputType : uint8_t { IN_BUTTONS = 0, IN_TOUCH = 1, IN_BOTH = 2 };
#define NUM_BUTTONS 4
#define DEBOUNCE_MS 30
#define LOCKOUT_MS 400
#define MAX_PENDING 8
#define RETRY_MS 300
#define MAX_TRIES 15
static const int8_t BUTTON_PINS[NUM_BUTTONS] = {32, 33, 25, 26};
static const int8_t LAMP_PINS[NUM_BUTTONS] = {16, 17, 21, 22};
static const char *BUTTON_LABELS[NUM_BUTTONS] = {"A", "B", "C", "D"};
#ifndef STATUS_LED
#define STATUS_LED 2  // -1 = none
#endif
#define MAX_LEDS 300
#define MAX_STEPS 20
#define RX_LINE_MAX 768
#define FRAME_MS 20
#define PC_TIMEOUT_MS 7000

// chip-portable helpers (the ESP32-C3 has no touch sensor and no GPIO23)
inline void buzTone(uint16_t f) { if (BUZZER_PIN >= 0) tone(BUZZER_PIN, f); }
inline void buzOff() { if (BUZZER_PIN >= 0) noTone(BUZZER_PIN); }
inline uint16_t readPad(int i) {
#if HAS_TOUCH
  return touchRead(TOUCH_PINS[i]);
#else
  (void)i;
  return 0;
#endif
}

struct RGB { uint8_t r, g, b; };
static const RGB TRAIL = {0, 200, 60};
static const RGB GOLD = {255, 170, 0};
static const RGB FUTURE_STATION = {60, 60, 60};
static const RGB HINT = {0, 0, 28};
static const RGB HEAD = {255, 255, 255};
static const RGB FAIL_RED = {255, 0, 0};
static const RGB BLACK = {0, 0, 0};

// ------------------------------------------------------------------ config
struct Config {
  char deviceId[24];
  uint16_t numLeds;
  uint8_t steps;
  uint8_t brightness;
  uint8_t nWaypoints;
  uint16_t waypoints[MAX_STEPS + 1];
  InputType inputType;
  uint8_t touchSensitivity;  // % drop from the calibrated baseline that counts as a touch
} cfg;
Preferences prefs;

void loadConfig() {
  prefs.begin(NVS_NS, true);
  strlcpy(cfg.deviceId, prefs.getString("id", EDUKIT_DEVICE_ID).c_str(), sizeof(cfg.deviceId));
  cfg.numLeds = prefs.getUShort("leds", 60);
  cfg.steps = prefs.getUChar("steps", 6);
  cfg.brightness = prefs.getUChar("bri", 150);
  cfg.nWaypoints = prefs.getUChar("nwp", 0);
  if (cfg.nWaypoints > MAX_STEPS + 1) cfg.nWaypoints = 0;
  if (cfg.nWaypoints) prefs.getBytes("wp", cfg.waypoints, sizeof(uint16_t) * cfg.nWaypoints);
  cfg.inputType = (InputType)prefs.getUChar("in", IN_BOTH);
  cfg.touchSensitivity = prefs.getUChar("tsen", 20);
  prefs.end();
  if (cfg.inputType > IN_BOTH) cfg.inputType = IN_BOTH;
  if (cfg.numLeds < 2 || cfg.numLeds > MAX_LEDS) cfg.numLeds = 60;
  if (cfg.steps < 1 || cfg.steps > MAX_STEPS) cfg.steps = 6;
}

void saveConfig() {
  prefs.begin(NVS_NS, false);
  prefs.putString("id", cfg.deviceId);
  prefs.putUShort("leds", cfg.numLeds);
  prefs.putUChar("steps", cfg.steps);
  prefs.putUChar("bri", cfg.brightness);
  prefs.putUChar("nwp", cfg.nWaypoints);
  if (cfg.nWaypoints) prefs.putBytes("wp", cfg.waypoints, sizeof(uint16_t) * cfg.nWaypoints);
  prefs.putUChar("in", cfg.inputType);
  prefs.putUChar("tsen", cfg.touchSensitivity);
  prefs.end();
}

Adafruit_NeoPixel strip(60, LED_PIN, NEO_GRB + NEO_KHZ800);

// ------------------------------------------------------------------ route
enum Mode : uint8_t { M_PATH, M_ADVANCE, M_BACK, M_FAIL, M_FESTIVAL, M_OFF };
struct State { Mode mode; int step; int toStep; uint32_t started; uint32_t duration; } st = {M_PATH, 0, 0, 0, 0};

int posOf(int step) {
  step = constrain(step, 0, (int)cfg.steps);
  if (cfg.nWaypoints == cfg.steps + 1) return constrain((int)cfg.waypoints[step], 0, cfg.numLeds - 1);
  return (int)lroundf(step * (cfg.numLeds - 1) / (float)cfg.steps);
}

bool isStation(int i) {
  for (int k = 0; k <= cfg.steps; k++) if (posOf(k) == i) return true;
  return false;
}

RGB scale(RGB c, float f) {
  f = constrain(f, 0.0f, 1.0f);
  return {(uint8_t)(c.r * f), (uint8_t)(c.g * f), (uint8_t)(c.b * f)};
}

float breathe(uint32_t t, uint32_t period) { return 0.5f - 0.5f * cosf(2 * PI * (t % period) / (float)period); }

uint32_t hash32(uint32_t n) {  // same as effects._hash
  n = (n ^ 61) ^ (n >> 16);
  n = n + (n << 3);
  n ^= n >> 4;
  n *= 0x27D4EB2D;
  n ^= n >> 15;
  return n;
}

RGB px[MAX_LEDS];

void renderPath(int step, uint32_t now) {
  int p = posOf(step), dest = posOf(cfg.steps);
  for (int i = 0; i < cfg.numLeds; i++) {
    RGB c = i <= p ? TRAIL : HINT;
    if (isStation(i)) c = i <= p ? GOLD : FUTURE_STATION;
    if (i == dest) c = scale(GOLD, 0.3f + 0.7f * breathe(now, 2000));
    if (i == p) c = scale(HEAD, 0.45f + 0.55f * breathe(now, 900));
    px[i] = c;
  }
}

void setPath(int step) { st = {M_PATH, step, step, millis(), 0}; }

void renderFrame() {
  uint32_t now = millis();
  uint32_t t = now - st.started;
  if (st.duration && t >= st.duration && (st.mode == M_ADVANCE || st.mode == M_BACK || st.mode == M_FAIL || st.mode == M_FESTIVAL)) {
    setPath(st.toStep);
    t = 0;
  }
  int n = cfg.numLeds;
  switch (st.mode) {
    case M_OFF:
      for (int i = 0; i < n; i++) px[i] = BLACK;
      break;
    case M_PATH:
      renderPath(st.step, now);
      break;
    case M_ADVANCE: {
      int a = posOf(st.step), b = posOf(st.toStep);
      float frac = min(1.0f, t / max(1.0f, st.duration * 0.8f));
      float head = a + (b - a) * frac;
      renderPath(st.step, now);
      int lo = b >= a ? a : (int)ceilf(head), hi = b >= a ? (int)head : a;
      for (int i = max(0, lo); i <= min(n - 1, hi); i++) px[i] = TRAIL;
      int h = (int)lroundf(head);
      for (int k = 0; k < 3; k++) {
        int j = b >= a ? h - k : h + k;
        if (j < 0 || j >= n) continue;
        static const float F[3] = {1.0f, 0.45f, 0.15f};
        px[j] = k == 0 ? HEAD : scale(TRAIL, 1.0f - F[k] / 2);
      }
      break;
    }
    case M_BACK: {  // red step back: lost segment blinks red, red head slides back
      int a = posOf(st.step), b = posOf(st.toStep);
      float frac = min(1.0f, t / max(1.0f, st.duration * 0.8f));
      int h = (int)lroundf(a + (b - a) * frac);
      renderPath(st.toStep, now);
      bool on = (t / 200) % 2 == 0;
      for (int i = min(a, b) + 1; i <= max(a, b) && i < n; i++) px[i] = on ? FAIL_RED : HINT;
      if (h >= 0 && h < n) px[h] = FAIL_RED;
      break;
    }
    case M_FAIL:
      renderPath(st.step, now);
      if ((t / 250) % 2 == 0)
        for (int i = 0; i <= posOf(st.step); i++) px[i] = FAIL_RED;
      break;
    case M_FESTIVAL: {
      int dest = posOf(cfg.steps);
      for (int i = 0; i < n; i++) {
        RGB c = ((i + t / 120) % 4) < 2 ? TRAIL : GOLD;
        if (hash32((t / 80) * 131 + i * 7) % 7 == 0) c = HEAD;
        if (abs(i - dest) <= 2) c = ((t / 200) % 2 == 0) ? HEAD : GOLD;
        px[i] = c;
      }
      break;
    }
  }
  float bf = cfg.brightness / 255.0f;
  for (int i = 0; i < n; i++) {
    RGB c = scale(px[i], bf);
    strip.setPixelColor(i, strip.Color(c.r, c.g, c.b));
  }
  strip.show();
}

// ------------------------------------------------------------------ buzzer
struct Note { uint16_t f, ms; };
static const Note MEL_CORRECT[] = {{660, 100}, {880, 100}, {1320, 220}};
static const Note MEL_INCORRECT[] = {{220, 180}, {0, 40}, {180, 300}};
static const Note MEL_FESTIVAL[] = {{523, 180}, {659, 180}, {784, 180}, {1047, 360}, {0, 60}, {988, 180}, {880, 180}, {784, 360},
                                    {0, 60}, {659, 180}, {784, 180}, {880, 180}, {1047, 300}, {0, 60}, {1175, 180}, {1047, 180}, {1319, 600}};
static const Note MEL_TICK[] = {{1200, 30}};
const Note *mel = nullptr;
uint8_t melLen = 0, melIdx = 0;
uint32_t noteStart = 0;

void startMelody(const Note *m, uint8_t len) {
  mel = m; melLen = len; melIdx = 0; noteStart = millis();
  if (m[0].f) buzTone(m[0].f); else buzOff();
}

void updateBuzzer() {
  if (!mel || millis() - noteStart < mel[melIdx].ms) return;
  if (++melIdx >= melLen) { buzOff(); mel = nullptr; return; }
  noteStart = millis();
  if (mel[melIdx].f) buzTone(mel[melIdx].f); else buzOff();
}

// ------------------------------------------------------------------ protocol
char bootId[9];
uint32_t lastPcMsgMs = 0;

void sendDoc(JsonDocument &d) {
  String out;
  serializeJson(d, out);
  sendLine(out);
}

const char *inputTypeName() {
  if (!HAS_BUTTONS) return HAS_TOUCH ? "touch" : "none";
  if (!HAS_TOUCH) return "buttons";
  return cfg.inputType == IN_BUTTONS ? "buttons" : cfg.inputType == IN_TOUCH ? "touch" : "both";
}

void sendHello() {
  JsonDocument d;
  d["type"] = "hello";
  d["device_id"] = cfg.deviceId;
  d["role"] = DEVICE_ROLE;
  d["fw"] = FW_VERSION;
  d["proto"] = PROTO_VERSION;
  d["boot_id"] = bootId;
  JsonObject caps = d["caps"].to<JsonObject>();
  if (HAS_STRIP) { caps["leds"] = cfg.numLeds; caps["steps"] = cfg.steps; }
  caps["buzzer"] = BUZZER_PIN >= 0;
  if (HAS_BUTTONS || HAS_TOUCH) caps["buttons"] = NUM_BUTTONS;  // number of answer choices A-D
  caps["button_leds"] = (bool)HAS_BUTTONS;
  caps["touch"] = (bool)HAS_TOUCH;
  caps["ble"] = true;
  if (HAS_BUTTONS || HAS_TOUCH) caps["input_type"] = inputTypeName();
  sendDoc(d);
}

void sendAck(int32_t id) { JsonDocument d; d["type"] = "ack"; d["id"] = id; sendDoc(d); }
void sendNack(int32_t id, const char *e) { JsonDocument d; d["type"] = "nack"; d["id"] = id; d["error"] = e; sendDoc(d); }

// ------------------------------------------------------------------ buttons
struct Btn { bool stable, lastRaw; uint32_t changedAt; } btn[NUM_BUTTONS];
struct Pad { bool stable, lastRaw; uint32_t changedAt; uint32_t base; uint16_t value; uint32_t lastDrift; } pad[NUM_BUTTONS];
uint32_t lastTouchSample = 0;

bool useButtons() { return HAS_BUTTONS && cfg.inputType != IN_TOUCH; }
bool useTouch() { return HAS_TOUCH && (!HAS_BUTTONS || cfg.inputType != IN_BUTTONS); }

void calibrateTouch() {
  if (!HAS_TOUCH) return;
  for (int i = 0; i < NUM_BUTTONS; i++) {
    uint32_t sum = 0;
    for (int k = 0; k < 16; k++) { sum += readPad(i); delay(2); }
    pad[i].base = sum / 16;
    pad[i].value = pad[i].base;
    pad[i].stable = pad[i].lastRaw = false;
  }
}

// ESP32 touch values DROP when a finger is near the pad.
bool padTouched(int i) {
  uint16_t v = readPad(i);
  pad[i].value = v;
  uint32_t base = pad[i].base;
  uint32_t drop = v < base ? base - v : 0;
  bool touched = drop >= TOUCH_MIN_DROP && drop * 100 >= base * cfg.touchSensitivity;
  // Follow slow drift (humidity, temperature) ONLY while the pad is clearly untouched, and slowly:
  // one small step every 500 ms (time constant ~8 s), so a finger is never absorbed into the baseline.
  bool clearlyIdle = drop * 200 < base * cfg.touchSensitivity;  // less than half the threshold
  uint32_t now = millis();
  if (clearlyIdle && now - pad[i].lastDrift >= 500) {
    pad[i].lastDrift = now;
    pad[i].base = (base * 15 + v + 8) / 16;
  }
  return touched;
}
bool armed = false;
bool allowed[NUM_BUTTONS];
char questionId[32] = "";
uint32_t armDeadline = 0;
uint32_t lastAccepted = 0;
uint32_t seqCounter = 0;
struct Pending { bool used; uint32_t seq; uint32_t lastSent; uint8_t tries; String line; };
Pending pending[MAX_PENDING];

void setLamps(int only = -2) {  // -2: lamps follow "allowed" while armed; >=0: only that lamp
  if (!HAS_BUTTONS) return;  // the lamps sit beside the push buttons
  for (int i = 0; i < NUM_BUTTONS; i++) {
    bool on = only >= 0 ? i == only : (armed && allowed[i]);
    digitalWrite(LAMP_PINS[i], on ? HIGH : LOW);
  }
}

void queueEvent(JsonDocument &d) {
  d["type"] = "event";
  d["device_id"] = cfg.deviceId;
  d["seq"] = ++seqCounter;
  String line;
  serializeJson(d, line);
  int slot = -1;
  for (int i = 0; i < MAX_PENDING; i++) if (!pending[i].used) { slot = i; break; }
  if (slot < 0) {
    uint32_t oldest = UINT32_MAX;
    for (int i = 0; i < MAX_PENDING; i++) if (pending[i].seq < oldest) { oldest = pending[i].seq; slot = i; }
  }
  pending[slot] = {true, seqCounter, millis(), 1, line};
  sendLine(line);
}

void retransmit() {
  uint32_t now = millis();
  for (auto &p : pending) {
    if (!p.used || now - p.lastSent < RETRY_MS) continue;
    if (p.tries >= MAX_TRIES) { p.used = false; continue; }
    p.tries++;
    p.lastSent = now;
    sendLine(p.line);
  }
}

void onPress(int i) {
  uint32_t now = millis();
  if (!armed || !allowed[i]) return;
  if (lastAccepted && now - lastAccepted < LOCKOUT_MS) return;
  lastAccepted = now;
  armed = false;  // exactly one answer per question
  setLamps(i);
  JsonDocument d;
  d["event"] = "answer_selected";
  d["question_id"] = questionId;
  d["selected_answer"] = BUTTON_LABELS[i];
  d["channel"] = i;
  queueEvent(d);
  if (mel == nullptr) startMelody(MEL_TICK, 1);
}

void scanButtons() {
  uint32_t now = millis();
  for (int i = 0; i < NUM_BUTTONS; i++) {
    if (!useButtons()) continue;
    bool raw = digitalRead(BUTTON_PINS[i]) == LOW;
    if (raw != btn[i].lastRaw) { btn[i].lastRaw = raw; btn[i].changedAt = now; }
    if (raw != btn[i].stable && now - btn[i].changedAt >= DEBOUNCE_MS) {
      btn[i].stable = raw;
      if (raw) onPress(i);
    }
  }
  if (useTouch() && now - lastTouchSample >= TOUCH_SAMPLE_MS) {
    lastTouchSample = now;
    for (int i = 0; i < NUM_BUTTONS; i++) {
      bool raw = padTouched(i);
      if (raw != pad[i].lastRaw) { pad[i].lastRaw = raw; pad[i].changedAt = now; }
      if (raw != pad[i].stable && now - pad[i].changedAt >= TOUCH_DEBOUNCE_MS) {
        pad[i].stable = raw;
        if (raw) onPress(i);
      }
    }
  }
  if (armed && armDeadline && (int32_t)(now - armDeadline) > 0) { armed = false; setLamps(); }  // safety auto-disarm
}

void handleCommand(JsonDocument &doc) {
  const char *cmd = doc["command"] | "";
  bool hasId = doc["id"].is<int32_t>();
  int32_t id = doc["id"] | -1;
  const char *err = nullptr;

  if (!strcmp(cmd, "ack") && !hasId) {  // PC acknowledges one of our events
    uint32_t seq = doc["seq"] | 0;
    for (auto &p : pending) if (p.used && p.seq == seq) p.used = false;
    return;
  }
  if (!strcmp(cmd, "identify")) {
    sendHello();
  } else if (!strcmp(cmd, "ping")) {
  } else if (!strcmp(cmd, "arm")) {
    strlcpy(questionId, doc["question_id"] | "", sizeof(questionId));
    JsonArrayConst opts = doc["options"].as<JsonArrayConst>();
    for (int i = 0; i < NUM_BUTTONS; i++) allowed[i] = opts.isNull();
    for (JsonVariantConst v : opts) {
      const char *lbl = v.as<const char *>();
      for (int i = 0; lbl && i < NUM_BUTTONS; i++) if (!strcasecmp(lbl, BUTTON_LABELS[i])) allowed[i] = true;
    }
    uint32_t timeoutS = doc["timeout_s"] | 0;
    armDeadline = timeoutS ? millis() + timeoutS * 1000UL + 2000UL : 0;
    armed = true;
    setLamps();
  } else if (!strcmp(cmd, "disarm")) {
    armed = false;
    setLamps();
  } else if (!strcmp(cmd, "path_back")) {
    st = {M_BACK, doc["from"] | 0, doc["to"] | 0, millis(), (uint32_t)(doc["duration_ms"] | 1800)};
  } else if (!strcmp(cmd, "calibrate")) {
    calibrateTouch();
  } else if (!strcmp(cmd, "read_touch") && HAS_TOUCH) {
    JsonDocument e;
    e["event"] = "touch_readings";
    JsonArray val = e["values"].to<JsonArray>();
    JsonArray bas = e["baselines"].to<JsonArray>();
    JsonArray tch = e["touched"].to<JsonArray>();
    for (int i = 0; i < NUM_BUTTONS; i++) { val.add(readPad(i)); bas.add(pad[i].base); tch.add(pad[i].stable); }
    e["input_type"] = inputTypeName();
    e["sensitivity"] = cfg.touchSensitivity;
    queueEvent(e);
  } else if (!strcmp(cmd, "configure")) {
    const char *it = doc["input_type"] | "";
    if (!strcmp(it, "buttons")) cfg.inputType = IN_BUTTONS;
    else if (!strcmp(it, "touch")) cfg.inputType = IN_TOUCH;
    else if (!strcmp(it, "both")) cfg.inputType = IN_BOTH;
    if (doc["touch_sensitivity"].is<int>()) cfg.touchSensitivity = constrain((int)doc["touch_sensitivity"], 3, 90);
    if (doc["num_leds"].is<int>()) {
      cfg.numLeds = constrain((int)doc["num_leds"], 2, MAX_LEDS);
      if (HAS_STRIP) { strip.clear(); strip.show(); strip.updateLength(cfg.numLeds); }
    }
    if (doc["steps"].is<int>()) cfg.steps = constrain((int)doc["steps"], 1, MAX_STEPS);
    if (doc["brightness"].is<int>()) cfg.brightness = constrain((int)doc["brightness"], 1, 255);
    if (doc["waypoints"].is<JsonArrayConst>()) {
      JsonArrayConst wp = doc["waypoints"].as<JsonArrayConst>();
      cfg.nWaypoints = 0;
      for (JsonVariantConst v : wp) if (cfg.nWaypoints <= MAX_STEPS) cfg.waypoints[cfg.nWaypoints++] = constrain(v.as<int>(), 0, MAX_LEDS - 1);
    }
    saveConfig();
  } else if (!strcmp(cmd, "path_set")) {
    setPath(doc["step"] | 0);
  } else if (!strcmp(cmd, "path_advance")) {
    st = {M_ADVANCE, doc["from"] | 0, doc["to"] | 0, millis(), (uint32_t)(doc["duration_ms"] | 1800)};
  } else if (!strcmp(cmd, "path_fail")) {
    int s = doc["step"] | 0;
    st = {M_FAIL, s, s, millis(), (uint32_t)(doc["duration_ms"] | 1500)};
  } else if (!strcmp(cmd, "festival")) {
    st = {M_FESTIVAL, cfg.steps, cfg.steps, millis(), (uint32_t)(doc["duration_ms"] | 10000)};
  } else if (!strcmp(cmd, "stop") || !strcmp(cmd, "play_effect")) {
    st = {M_OFF, st.step, st.step, millis(), 0};
    mel = nullptr;
    buzOff();
  } else if (!strcmp(cmd, "buzz")) {
    const char *p = doc["pattern"] | "";
    if (!strcmp(p, "correct")) startMelody(MEL_CORRECT, 3);
    else if (!strcmp(p, "incorrect")) startMelody(MEL_INCORRECT, 3);
    else if (!strcmp(p, "festival")) startMelody(MEL_FESTIVAL, sizeof(MEL_FESTIVAL) / sizeof(Note));
    else if (!strcmp(p, "tick")) startMelody(MEL_TICK, 1);
    else err = "unknown pattern";
  } else if (!strcmp(cmd, "set_id")) {
    const char *nid = doc["new_id"] | "";
    if (!*nid || strlen(nid) >= sizeof(cfg.deviceId)) err = "invalid new_id";
    else { strlcpy(cfg.deviceId, nid, sizeof(cfg.deviceId)); saveConfig(); if (hasId) sendAck(id); sendHello(); return; }
  } else {
    err = "unknown command";
  }
  if (!hasId) return;
  if (err) sendNack(id, err); else sendAck(id);
}

struct LineReader {  // one per link (USB, BLE) so their bytes never interleave
  char buf[RX_LINE_MAX];
  size_t len = 0;
  bool discarding = false;
  void feed(char c) {
    if (c == '\n') {
      if (!discarding && len) {
        JsonDocument doc;
        if (!deserializeJson(doc, buf, len) && doc.is<JsonObject>()) {
          lastPcMsgMs = millis();
          handleCommand(doc);
        }
      }
      len = 0;
      discarding = false;
    } else if (c != '\r') {
      if (len < RX_LINE_MAX - 1) buf[len++] = c; else discarding = true;
    }
  }
};
LineReader usbReader, bleReader;

void readSerial() {
  while (Serial.available()) usbReader.feed((char)Serial.read());
  int c;
  int budget = 512;
  while (budget-- > 0 && (c = bleReadByte()) >= 0) bleReader.feed((char)c);
}

// ------------------------------------------------------------------ main
uint32_t lastFrame = 0;

void setup() {
  Serial.setRxBufferSize(1024);
  Serial.begin(BAUD);
  if (STATUS_LED >= 0) pinMode(STATUS_LED, OUTPUT);
  loadConfig();
  if (HAS_STRIP) {
    strip.updateLength(cfg.numLeds);
    strip.begin();
    strip.clear();
    strip.show();
  }
  snprintf(bootId, sizeof(bootId), "%08lx", (unsigned long)esp_random());
  for (int i = 0; i < NUM_BUTTONS; i++) {
    if (HAS_BUTTONS) {  // the LED-only board uses GPIO 26 for the strip, so never touch these pins there
      pinMode(BUTTON_PINS[i], INPUT_PULLUP);
      pinMode(LAMP_PINS[i], OUTPUT);
    }
    btn[i] = {false, false, 0};
    allowed[i] = false;
  }
  setLamps(-1);
  calibrateTouch();  // hands off the pads during power-up
  bleBegin(cfg.deviceId);  // advertises as "EduKit-<device id>"
  // self-test: travel the whole route once, then rest at Indonesia
  st = {M_ADVANCE, 0, cfg.steps, millis(), 1500};
  sendHello();
}

void loop() {
  readSerial();
  scanButtons();
  retransmit();
  uint32_t now = millis();
  if (now - lastFrame >= FRAME_MS) {
    lastFrame = now;
    if (HAS_STRIP) renderFrame();
    if (st.mode == M_PATH && st.step == cfg.steps && now < 4000) setPath(0);  // end of boot self-test
  }
  updateBuzzer();
  bool pcAlive = lastPcMsgMs && now - lastPcMsgMs < PC_TIMEOUT_MS;
  if (STATUS_LED >= 0) digitalWrite(STATUS_LED, pcAlive ? HIGH : (now / 700) % 2);
  delay(1);
}
