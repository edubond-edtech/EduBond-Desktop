/*
 * EduKit — ESP32 OUTPUT controller firmware
 *
 * Drives a WS2812B strip, a passive buzzer and up to two vibration motors
 * from parametrised JSON commands (NDJSON over USB serial, 115200 baud).
 * Effects mirror desktop/edukit/feedback/effects.py so the on-screen
 * simulator matches the real strip.
 *
 * Default wiring (ESP32-WROOM-32 DevKit v1) — see docs/WIRING.md:
 *   GPIO18  WS2812B DIN (via 330 Ω, ideally 74AHCT125 level shifter)
 *   GPIO25  passive buzzer (via NPN transistor)
 *   GPIO26  motor 0 (via logic-level MOSFET + flyback diode)
 *   GPIO27  motor 1
 *   GPIO2   on-board status LED
 */
#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <ArduinoJson.h>
#include <Preferences.h>

#ifndef EDUKIT_DEVICE_ID
#define EDUKIT_DEVICE_ID "OUTPUT_01"
#endif
#define FW_VERSION "1.0.0"
#define PROTO_VERSION 1
#define BAUD 115200
#define LED_PIN 18
#define BUZZER_PIN 25
#define STATUS_LED 2
#define RX_LINE_MAX 768
#define MAX_LEDS 300
#define FRAME_MS 20
#define PC_TIMEOUT_MS 7000

static const int8_t MOTOR_PINS[2] = {26, 27};
#define BUZZER_LEDC_CH 0
#define MOTOR_LEDC_CH0 2

// ------------------------------------------------------------------ PWM helpers (core 2.x and 3.x)
#if ESP_ARDUINO_VERSION_MAJOR >= 3
void pwmInit(uint8_t pin, uint8_t ch, uint32_t freq, uint8_t res) { (void)ch; ledcAttach(pin, freq, res); }
void pwmWrite(uint8_t pin, uint8_t ch, uint32_t duty) { (void)ch; ledcWrite(pin, duty); }
void pwmTone(uint8_t pin, uint8_t ch, uint32_t f) { (void)ch; ledcWriteTone(pin, f); }
#else
void pwmInit(uint8_t pin, uint8_t ch, uint32_t freq, uint8_t res) { ledcSetup(ch, freq, res); ledcAttachPin(pin, ch); }
void pwmWrite(uint8_t pin, uint8_t ch, uint32_t duty) { (void)pin; ledcWrite(ch, duty); }
void pwmTone(uint8_t pin, uint8_t ch, uint32_t f) { (void)pin; ledcWriteTone(ch, f); }
#endif

// ------------------------------------------------------------------ config
struct Config {
  char deviceId[24];
  uint16_t numLeds;
  uint8_t maxBrightness;
  bool buzzerEnabled;
  bool motorsEnabled;
} cfg;
Preferences prefs;

void loadConfig() {
  prefs.begin("edukit", true);
  strlcpy(cfg.deviceId, prefs.getString("id", EDUKIT_DEVICE_ID).c_str(), sizeof(cfg.deviceId));
  cfg.numLeds = prefs.getUShort("leds", 30);
  cfg.maxBrightness = prefs.getUChar("maxb", 200);
  cfg.buzzerEnabled = prefs.getBool("buz", true);
  cfg.motorsEnabled = prefs.getBool("mot", true);
  prefs.end();
  if (cfg.numLeds < 1 || cfg.numLeds > MAX_LEDS) cfg.numLeds = 30;
}

void saveConfig() {
  prefs.begin("edukit", false);
  prefs.putString("id", cfg.deviceId);
  prefs.putUShort("leds", cfg.numLeds);
  prefs.putUChar("maxb", cfg.maxBrightness);
  prefs.putBool("buz", cfg.buzzerEnabled);
  prefs.putBool("mot", cfg.motorsEnabled);
  prefs.end();
}

Adafruit_NeoPixel strip(30, LED_PIN, NEO_GRB + NEO_KHZ800);

// ------------------------------------------------------------------ effects
enum Base : uint8_t { FX_OFF, FX_SOLID, FX_BLINK, FX_BREATHE, FX_WIPE, FX_CHASE, FX_RAINBOW, FX_SPARKLE, FX_PROGRESS, FX_CELEBRATE };
struct RGB { uint8_t r, g, b; };

struct Effect {
  Base base = FX_OFF;
  RGB color = {0, 0, 0};
  RGB color2 = {0, 0, 0};
  uint8_t brightness = 120;
  uint32_t durationMs = 0;
  uint8_t speed = 5;
  float value = 0;
  uint32_t startedMs = 0;
} fx;

struct NamedColor { const char *name; RGB c; };
static const NamedColor COLORS[] = {
  {"off", {0, 0, 0}},       {"black", {0, 0, 0}},     {"white", {255, 255, 255}}, {"red", {255, 0, 0}},
  {"green", {0, 255, 0}},   {"blue", {0, 60, 255}},   {"yellow", {255, 180, 0}},  {"orange", {255, 80, 0}},
  {"purple", {160, 0, 255}}, {"pink", {255, 40, 120}}, {"cyan", {0, 220, 255}},
};

bool parseColor(JsonVariantConst v, RGB &out) {
  if (v.is<JsonArrayConst>()) {
    JsonArrayConst a = v.as<JsonArrayConst>();
    if (a.size() != 3) return false;
    out = {(uint8_t)constrain((int)a[0], 0, 255), (uint8_t)constrain((int)a[1], 0, 255), (uint8_t)constrain((int)a[2], 0, 255)};
    return true;
  }
  const char *s = v.as<const char *>();
  if (!s) return false;
  if (s[0] == '#' && strlen(s) == 7) {
    uint32_t x = strtoul(s + 1, nullptr, 16);
    out = {(uint8_t)(x >> 16), (uint8_t)(x >> 8), (uint8_t)x};
    return true;
  }
  for (auto &nc : COLORS) if (!strcasecmp(nc.name, s)) { out = nc.c; return true; }
  return false;
}

struct Preset { const char *name; Base base; const char *color; uint32_t duration; };
static const Preset PRESETS[] = {
  {"correct", FX_WIPE, "green", 3000},   {"incorrect", FX_BLINK, "red", 3000}, {"partial", FX_BREATHE, "yellow", 3000},
  {"waiting", FX_BREATHE, "blue", 0},    {"timeout", FX_BLINK, "orange", 2000}, {"celebrate", FX_CELEBRATE, "white", 5000},
};
struct BaseName { const char *name; Base base; };
static const BaseName BASES[] = {
  {"off", FX_OFF}, {"solid", FX_SOLID}, {"blink", FX_BLINK}, {"breathe", FX_BREATHE}, {"wipe", FX_WIPE},
  {"chase", FX_CHASE}, {"rainbow", FX_RAINBOW}, {"sparkle", FX_SPARKLE}, {"progress", FX_PROGRESS}, {"celebrate", FX_CELEBRATE},
};

// Returns nullptr on success or an error string.
const char *startEffect(JsonDocument &d, const char *forcedName = nullptr) {
  const char *name = forcedName ? forcedName : (d["effect"] | "solid");
  Effect e;
  const char *defColor = "white";
  uint32_t defDuration = 0;
  bool found = false;
  for (auto &p : PRESETS) if (!strcasecmp(p.name, name)) { e.base = p.base; defColor = p.color; defDuration = p.duration; found = true; }
  if (!found) for (auto &b : BASES) if (!strcasecmp(b.name, name)) { e.base = b.base; found = true; }
  if (!found) return "unknown effect";
  JsonVariantConst cv = d["color"];
  if (cv.isNull() || !parseColor(cv, e.color)) { JsonDocument tmp; tmp.set(defColor); parseColor(tmp.as<JsonVariantConst>(), e.color); }
  if (!d["color2"].isNull()) parseColor(d["color2"], e.color2);
  e.brightness = min((int)(d["brightness"] | 120), (int)cfg.maxBrightness);
  e.durationMs = d["duration_ms"].is<uint32_t>() ? (uint32_t)d["duration_ms"] : defDuration;
  e.speed = constrain((int)(d["speed"] | 5), 1, 10);
  e.value = constrain((float)(d["value"] | 0.0f), 0.0f, 1.0f);
  e.startedMs = millis();
  fx = e;
  return nullptr;
}

uint32_t hash32(uint32_t n) {  // must match effects._hash
  n = (n ^ 61) ^ (n >> 16);
  n = n + (n << 3);
  n ^= n >> 4;
  n *= 0x27D4EB2D;
  n ^= n >> 15;
  return n;
}

RGB wheel(uint8_t pos) {
  pos = 255 - pos;
  if (pos < 85) return {(uint8_t)(255 - pos * 3), 0, (uint8_t)(pos * 3)};
  if (pos < 170) { pos -= 85; return {0, (uint8_t)(pos * 3), (uint8_t)(255 - pos * 3)}; }
  pos -= 170;
  return {(uint8_t)(pos * 3), (uint8_t)(255 - pos * 3), 0};
}

RGB scale(RGB c, float f) {
  f = constrain(f, 0.0f, 1.0f);
  return {(uint8_t)(c.r * f), (uint8_t)(c.g * f), (uint8_t)(c.b * f)};
}

void renderFrame() {
  uint32_t now = millis();
  if (fx.durationMs && now - fx.startedMs >= fx.durationMs) { fx = Effect(); fx.startedMs = now; }
  uint32_t t = now - fx.startedMs;
  uint32_t unit = max<uint32_t>(40, 1600 / fx.speed);
  uint16_t n = strip.numPixels();
  float bf = fx.brightness / 255.0f;
  for (uint16_t i = 0; i < n; i++) {
    RGB c = {0, 0, 0};
    switch (fx.base) {
      case FX_OFF: break;
      case FX_SOLID: c = fx.color; break;
      case FX_BLINK: c = ((t / max<uint32_t>(1, unit / 2)) % 2 == 0) ? fx.color : fx.color2; break;
      case FX_BREATHE: c = scale(fx.color, 0.15f + 0.85f * (0.5f - 0.5f * cosf(2 * PI * t / (unit * 4.0f)))); break;
      case FX_WIPE: { uint32_t lit = min<uint32_t>(n, t / max<uint32_t>(1, (unit * 2) / n) + 1); c = i < lit ? fx.color : fx.color2; break; }
      case FX_CHASE: c = ((i + t / max<uint32_t>(1, unit / 4)) % 3 == 0) ? fx.color : fx.color2; break;
      case FX_RAINBOW: c = wheel((i * 256 / n + (t * 256 / (unit * 4))) & 255); break;
      case FX_SPARKLE: c = (hash32((t / max<uint32_t>(1, unit / 4)) * 977 + i) % 6 == 0) ? fx.color : fx.color2; break;
      case FX_CELEBRATE: {
        uint32_t frame = t / max<uint32_t>(1, unit / 4);
        c = (hash32(frame * 131 + i * 7) % 5 == 0) ? RGB{255, 255, 255} : wheel((i * 256 / n + (t * 256 / (unit * 2))) & 255);
        break;
      }
      case FX_PROGRESS: c = (i < (uint16_t)roundf(fx.value * n)) ? fx.color : fx.color2; break;
    }
    c = scale(c, bf);
    strip.setPixelColor(i, strip.Color(c.r, c.g, c.b));
  }
  strip.show();
}

// ------------------------------------------------------------------ buzzer (non-blocking melodies)
struct Note { uint16_t f; uint16_t ms; };
static const Note MEL_CORRECT[] = {{660, 100}, {880, 100}, {1320, 220}};
static const Note MEL_INCORRECT[] = {{220, 180}, {0, 40}, {180, 300}};
static const Note MEL_PARTIAL[] = {{660, 120}, {740, 200}};
static const Note MEL_TIMEOUT[] = {{440, 120}, {0, 50}, {440, 120}, {0, 50}, {330, 300}};
static const Note MEL_CELEBRATE[] = {{523, 100}, {659, 100}, {784, 100}, {1047, 180}, {0, 50}, {784, 100}, {1047, 350}};
static const Note MEL_TICK[] = {{1200, 30}};
struct Melody { const char *name; const Note *notes; uint8_t len; };
#define MEL(n, a) {n, a, sizeof(a) / sizeof(a[0])}
static const Melody MELODIES[] = {MEL("correct", MEL_CORRECT), MEL("incorrect", MEL_INCORRECT), MEL("partial", MEL_PARTIAL),
                                  MEL("timeout", MEL_TIMEOUT), MEL("celebrate", MEL_CELEBRATE), MEL("tick", MEL_TICK)};
Note customNote[1];
const Note *melNotes = nullptr;
uint8_t melLen = 0, melIdx = 0;
uint32_t melNoteStart = 0;

void startMelody(const Note *notes, uint8_t len) {
  melNotes = notes; melLen = len; melIdx = 0; melNoteStart = millis();
  pwmTone(BUZZER_PIN, BUZZER_LEDC_CH, notes[0].f);
}

void updateBuzzer() {
  if (!melNotes) return;
  if (millis() - melNoteStart < melNotes[melIdx].ms) return;
  if (++melIdx >= melLen) { pwmTone(BUZZER_PIN, BUZZER_LEDC_CH, 0); melNotes = nullptr; return; }
  melNoteStart = millis();
  pwmTone(BUZZER_PIN, BUZZER_LEDC_CH, melNotes[melIdx].f);
}

// ------------------------------------------------------------------ motors
struct MotorRun { uint8_t speed; uint32_t until; uint16_t pulseMs; uint32_t started; } motors[2];

void updateMotors() {
  uint32_t now = millis();
  for (uint8_t m = 0; m < 2; m++) {
    uint8_t duty = 0;
    if (motors[m].until && (int32_t)(motors[m].until - now) > 0) {
      bool on = !motors[m].pulseMs || ((now - motors[m].started) / motors[m].pulseMs) % 2 == 0;
      duty = on ? motors[m].speed : 0;
    } else {
      motors[m].until = 0;
    }
    pwmWrite(MOTOR_PINS[m], MOTOR_LEDC_CH0 + m, duty);
  }
}

// ------------------------------------------------------------------ protocol
char bootId[9];
uint32_t lastPcMsgMs = 0;
char lineBuf[RX_LINE_MAX];
size_t lineLen = 0;
bool discarding = false;

void sendDoc(JsonDocument &d) { serializeJson(d, Serial); Serial.print('\n'); }

void sendHello() {
  JsonDocument d;
  d["type"] = "hello";
  d["device_id"] = cfg.deviceId;
  d["role"] = "output";
  d["fw"] = FW_VERSION;
  d["proto"] = PROTO_VERSION;
  d["boot_id"] = bootId;
  JsonObject caps = d["caps"].to<JsonObject>();
  caps["leds"] = cfg.numLeds;
  caps["max_brightness"] = cfg.maxBrightness;
  caps["buzzer"] = cfg.buzzerEnabled;
  caps["motors"] = cfg.motorsEnabled ? 2 : 0;
  JsonArray effects = caps["effects"].to<JsonArray>();
  for (auto &b : BASES) effects.add(b.name);
  sendDoc(d);
}

void sendAck(int32_t id) { JsonDocument d; d["type"] = "ack"; d["id"] = id; sendDoc(d); }
void sendNack(int32_t id, const char *e) { JsonDocument d; d["type"] = "nack"; d["id"] = id; d["error"] = e; sendDoc(d); }

void handleCommand(JsonDocument &doc) {
  const char *cmd = doc["command"] | "";
  bool hasId = doc["id"].is<int32_t>();
  int32_t id = doc["id"] | -1;
  const char *err = nullptr;

  if (!strcmp(cmd, "identify")) {
    sendHello();
  } else if (!strcmp(cmd, "ping") || !strcmp(cmd, "ack")) {
    if (!hasId) return;
  } else if (!strcmp(cmd, "play_effect")) {
    err = startEffect(doc);
  } else if (!strcmp(cmd, "progress")) {
    err = startEffect(doc, "progress");
  } else if (!strcmp(cmd, "stop")) {
    fx = Effect(); fx.startedMs = millis();
    melNotes = nullptr; pwmTone(BUZZER_PIN, BUZZER_LEDC_CH, 0);
    for (auto &m : motors) m.until = 0;
  } else if (!strcmp(cmd, "buzz")) {
    if (cfg.buzzerEnabled) {
      const char *pat = doc["pattern"] | "";
      bool ok = false;
      for (auto &m : MELODIES) if (!strcmp(m.name, pat)) { startMelody(m.notes, m.len); ok = true; }
      if (!ok && doc["freq"].is<int>()) {
        customNote[0] = {(uint16_t)constrain((int)doc["freq"], 20, 10000), (uint16_t)constrain((int)(doc["duration_ms"] | 200), 10, 5000)};
        startMelody(customNote, 1);
        ok = true;
      }
      if (!ok) err = "unknown pattern";
    }
  } else if (!strcmp(cmd, "motor")) {
    if (cfg.motorsEnabled) {
      int m = doc["channel"] | 0;
      if (m < 0 || m > 1) err = "invalid motor channel";
      else motors[m] = {(uint8_t)constrain((int)(doc["speed"] | 200), 0, 255), millis() + (uint32_t)(doc["duration_ms"] | 500),
                        (uint16_t)(doc["pulse_ms"] | 0), millis()};
    }
  } else if (!strcmp(cmd, "configure")) {
    if (doc["num_leds"].is<int>()) {
      cfg.numLeds = constrain((int)doc["num_leds"], 1, MAX_LEDS);
      strip.clear(); strip.show();
      strip.updateLength(cfg.numLeds);
    }
    if (doc["max_brightness"].is<int>()) cfg.maxBrightness = constrain((int)doc["max_brightness"], 1, 255);
    if (doc["buzzer_enabled"].is<bool>()) cfg.buzzerEnabled = doc["buzzer_enabled"];
    if (doc["motors_enabled"].is<bool>()) cfg.motorsEnabled = doc["motors_enabled"];
    saveConfig();
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

void readSerial() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      if (!discarding && lineLen) {
        JsonDocument doc;
        if (!deserializeJson(doc, lineBuf, lineLen) && doc.is<JsonObject>()) {
          lastPcMsgMs = millis();
          handleCommand(doc);
        }
      }
      lineLen = 0;
      discarding = false;
    } else if (c != '\r') {
      if (lineLen < RX_LINE_MAX - 1) lineBuf[lineLen++] = c; else discarding = true;
    }
  }
}

// ------------------------------------------------------------------ main
uint32_t lastFrame = 0;

void setup() {
  Serial.setRxBufferSize(1024);
  Serial.begin(BAUD);
  pinMode(STATUS_LED, OUTPUT);
  loadConfig();
  strip.updateLength(cfg.numLeds);
  strip.begin();
  strip.clear();
  strip.show();
  pwmInit(BUZZER_PIN, BUZZER_LEDC_CH, 2000, 10);
  pwmTone(BUZZER_PIN, BUZZER_LEDC_CH, 0);
  for (uint8_t m = 0; m < 2; m++) { pwmInit(MOTOR_PINS[m], MOTOR_LEDC_CH0 + m, 5000, 8); pwmWrite(MOTOR_PINS[m], MOTOR_LEDC_CH0 + m, 0); }
  snprintf(bootId, sizeof(bootId), "%08lx", (unsigned long)esp_random());
  // power-on self test: short rainbow so the teacher sees the strip works
  JsonDocument d;
  d["effect"] = "rainbow"; d["brightness"] = 60; d["duration_ms"] = 1200;
  startEffect(d);
  sendHello();
}

void loop() {
  readSerial();
  uint32_t now = millis();
  if (now - lastFrame >= FRAME_MS) { lastFrame = now; renderFrame(); }
  updateBuzzer();
  updateMotors();
  bool pcAlive = lastPcMsgMs && now - lastPcMsgMs < PC_TIMEOUT_MS;
  digitalWrite(STATUS_LED, pcAlive ? HIGH : (now / 700) % 2);
  delay(1);
}
