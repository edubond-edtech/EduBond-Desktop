/*
 * EduKit — Game 1 «رحلة إلى مكة» — LED ROUTE MAP firmware (role "map")
 *
 * A WS2812B strip laid along the route on the classroom map:
 * LED 0 = Indonesia ... last LED = Makkah. The PC moves the travellers one
 * station per correct arrangement and starts the festival on arrival.
 * Rendering mirrors desktop/edukit/feedback/route.py.
 *
 * Commands (NDJSON, 115200 baud — docs/GAME1_JOURNEY.md):
 *   configure    {num_leds, steps, waypoints:[led index per station], brightness}
 *   path_set     {step}
 *   path_advance {from, to, duration_ms}
 *   path_back    {from, to, duration_ms}   (wrong answer: red step back)
 *   path_fail    {step, duration_ms}
 *   festival     {duration_ms}
 *   buzz         {pattern: correct|incorrect|festival|tick}
 *   stop, identify, ping, set_id
 *
 * Wiring: GPIO18 -> 330 Ω -> strip DIN (74AHCT125 recommended), 5 V PSU,
 *         common GND, 1000 µF across the strip. Optional buzzer GPIO25.
 */
#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <ArduinoJson.h>
#include <Preferences.h>

#ifndef EDUKIT_DEVICE_ID
#define EDUKIT_DEVICE_ID "MAP_01"
#endif
#define FW_VERSION "1.0.0"
#define PROTO_VERSION 1
#define BAUD 115200
#define LED_PIN 18
#define BUZZER_PIN 25
#define STATUS_LED 2
#define MAX_LEDS 300
#define MAX_STEPS 20
#define RX_LINE_MAX 768
#define FRAME_MS 20
#define PC_TIMEOUT_MS 7000

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
} cfg;
Preferences prefs;

void loadConfig() {
  prefs.begin("edukit", true);
  strlcpy(cfg.deviceId, prefs.getString("id", EDUKIT_DEVICE_ID).c_str(), sizeof(cfg.deviceId));
  cfg.numLeds = prefs.getUShort("leds", 60);
  cfg.steps = prefs.getUChar("steps", 6);
  cfg.brightness = prefs.getUChar("bri", 150);
  cfg.nWaypoints = prefs.getUChar("nwp", 0);
  if (cfg.nWaypoints > MAX_STEPS + 1) cfg.nWaypoints = 0;
  if (cfg.nWaypoints) prefs.getBytes("wp", cfg.waypoints, sizeof(uint16_t) * cfg.nWaypoints);
  prefs.end();
  if (cfg.numLeds < 2 || cfg.numLeds > MAX_LEDS) cfg.numLeds = 60;
  if (cfg.steps < 1 || cfg.steps > MAX_STEPS) cfg.steps = 6;
}

void saveConfig() {
  prefs.begin("edukit", false);
  prefs.putString("id", cfg.deviceId);
  prefs.putUShort("leds", cfg.numLeds);
  prefs.putUChar("steps", cfg.steps);
  prefs.putUChar("bri", cfg.brightness);
  prefs.putUChar("nwp", cfg.nWaypoints);
  if (cfg.nWaypoints) prefs.putBytes("wp", cfg.waypoints, sizeof(uint16_t) * cfg.nWaypoints);
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
    case M_BACK: {  // red step back
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
  if (m[0].f) tone(BUZZER_PIN, m[0].f); else noTone(BUZZER_PIN);
}

void updateBuzzer() {
  if (!mel || millis() - noteStart < mel[melIdx].ms) return;
  if (++melIdx >= melLen) { noTone(BUZZER_PIN); mel = nullptr; return; }
  noteStart = millis();
  if (mel[melIdx].f) tone(BUZZER_PIN, mel[melIdx].f); else noTone(BUZZER_PIN);
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
  d["role"] = "map";
  d["fw"] = FW_VERSION;
  d["proto"] = PROTO_VERSION;
  d["boot_id"] = bootId;
  JsonObject caps = d["caps"].to<JsonObject>();
  caps["leds"] = cfg.numLeds;
  caps["steps"] = cfg.steps;
  caps["buzzer"] = true;
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
  } else if (!strcmp(cmd, "configure")) {
    if (doc["num_leds"].is<int>()) {
      cfg.numLeds = constrain((int)doc["num_leds"], 2, MAX_LEDS);
      strip.clear(); strip.show();
      strip.updateLength(cfg.numLeds);
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
  } else if (!strcmp(cmd, "path_back")) {
    st = {M_BACK, doc["from"] | 0, doc["to"] | 0, millis(), (uint32_t)(doc["duration_ms"] | 1800)};
  } else if (!strcmp(cmd, "path_fail")) {
    int s = doc["step"] | 0;
    st = {M_FAIL, s, s, millis(), (uint32_t)(doc["duration_ms"] | 1500)};
  } else if (!strcmp(cmd, "festival")) {
    st = {M_FESTIVAL, cfg.steps, cfg.steps, millis(), (uint32_t)(doc["duration_ms"] | 10000)};
  } else if (!strcmp(cmd, "stop") || !strcmp(cmd, "play_effect")) {
    st = {M_OFF, st.step, st.step, millis(), 0};
    mel = nullptr;
    noTone(BUZZER_PIN);
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
  snprintf(bootId, sizeof(bootId), "%08lx", (unsigned long)esp_random());
  // self-test: travel the whole route once, then rest at Indonesia
  st = {M_ADVANCE, 0, cfg.steps, millis(), 1500};
  sendHello();
}

void loop() {
  readSerial();
  uint32_t now = millis();
  if (now - lastFrame >= FRAME_MS) {
    lastFrame = now;
    renderFrame();
    if (st.mode == M_PATH && st.step == cfg.steps && now < 4000) setPath(0);  // end of boot self-test
  }
  updateBuzzer();
  bool pcAlive = lastPcMsgMs && now - lastPcMsgMs < PC_TIMEOUT_MS;
  digitalWrite(STATUS_LED, pcAlive ? HIGH : (now / 700) % 2);
  delay(1);
}
