/*
 * EduKit — ESP32 INPUT controller firmware
 *
 * Reads up to 8 channels (4 populated in the prototype). Each channel can be a
 * push button (to GND, internal pull-up), a capacitive touch pad, or both.
 * Talks NDJSON over USB serial at 115200 baud — see docs/PROTOCOL.md.
 *
 * Features: hello/identify, command ack/nack, event sequence numbers with
 * retransmission until the PC acks, debouncing, repeat lock-out, one answer per
 * "arm", configurable channel->answer mapping (saved in NVS), illuminated
 * buttons, raw mode for non-quiz activities, PC-link status LED.
 *
 * Default wiring (ESP32-WROOM-32 DevKit v1) — see docs/WIRING.md:
 *   ch  label  button  touch        button LED
 *   0   A      GPIO25  GPIO32 (T9)  GPIO16
 *   1   B      GPIO26  GPIO33 (T8)  GPIO17
 *   2   C      GPIO18  GPIO27 (T7)  GPIO21
 *   3   D      GPIO19  GPIO14 (T6)  GPIO22
 *   4   E      GPIO4   -            -        (expansion)
 *   5   F      GPIO13  -            -        (expansion)
 *   status LED GPIO2 (on-board)
 */
#include <Arduino.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include "soc/soc_caps.h"

#ifndef EDUKIT_DEVICE_ID
#define EDUKIT_DEVICE_ID "INPUT_01"
#endif
#define FW_VERSION "1.0.0"
#define PROTO_VERSION 1
#define BAUD 115200
#define STATUS_LED 2
#define MAX_CH 8
#define RX_LINE_MAX 768
#define MAX_PENDING 8
#define RETRY_MS 300
#define MAX_TRIES 15
#define PC_TIMEOUT_MS 7000

struct ChannelPins { int8_t button; int8_t touch; int8_t led; };
static const ChannelPins PINS[MAX_CH] = {
  {25, 32, 16}, {26, 33, 17}, {18, 27, 21}, {19, 14, 22},
  {4, -1, -1},  {13, -1, -1}, {-1, -1, -1}, {-1, -1, -1},
};

enum InputType : uint8_t { IN_BUTTONS = 0, IN_TOUCH = 1, IN_BOTH = 2 };
enum Mode : uint8_t { MODE_ANSWER = 0, MODE_RAW = 1 };

// ---------------------------------------------------------------- config (NVS)
struct Config {
  char deviceId[24];
  uint8_t channels;
  char labels[MAX_CH][4];
  InputType inputType;
  Mode mode;
  uint16_t debounceMs;
  uint16_t lockoutMs;
  uint8_t touchSensitivity;  // % change from baseline that counts as a touch
} cfg;

Preferences prefs;

void loadConfig() {
  prefs.begin("edukit", true);
  String id = prefs.getString("id", EDUKIT_DEVICE_ID);
  strlcpy(cfg.deviceId, id.c_str(), sizeof(cfg.deviceId));
  cfg.channels = prefs.getUChar("ch", 4);
  for (uint8_t i = 0; i < MAX_CH; i++) {
    char key[6];
    snprintf(key, sizeof(key), "l%u", i);
    char def[2] = {(char)('A' + i), 0};
    String l = prefs.getString(key, def);
    strlcpy(cfg.labels[i], l.c_str(), sizeof(cfg.labels[i]));
  }
  cfg.inputType = (InputType)prefs.getUChar("in", IN_BUTTONS);
  cfg.mode = (Mode)prefs.getUChar("mode", MODE_ANSWER);
  cfg.debounceMs = prefs.getUShort("deb", 30);
  cfg.lockoutMs = prefs.getUShort("lock", 400);
  cfg.touchSensitivity = prefs.getUChar("tsen", 30);
  prefs.end();
  if (cfg.channels < 1 || cfg.channels > MAX_CH) cfg.channels = 4;
}

void saveConfig() {
  prefs.begin("edukit", false);
  prefs.putString("id", cfg.deviceId);
  prefs.putUChar("ch", cfg.channels);
  for (uint8_t i = 0; i < MAX_CH; i++) {
    char key[6];
    snprintf(key, sizeof(key), "l%u", i);
    prefs.putString(key, cfg.labels[i]);
  }
  prefs.putUChar("in", cfg.inputType);
  prefs.putUChar("mode", cfg.mode);
  prefs.putUShort("deb", cfg.debounceMs);
  prefs.putUShort("lock", cfg.lockoutMs);
  prefs.putUChar("tsen", cfg.touchSensitivity);
  prefs.end();
}

// ------------------------------------------------------------------ runtime
struct ChState { bool stable; bool lastRaw; uint32_t changedAt; uint32_t touchBase; };
ChState ch[MAX_CH];

char bootId[9];
uint32_t seqCounter = 0;
uint32_t lastAcceptedMs = 0;
uint32_t lastPcMsgMs = 0;

bool armed = false;
char questionId[32] = "";
bool allowed[MAX_CH];
uint32_t armDeadline = 0;  // 0 = none
bool buttonLed[MAX_CH];

struct Pending { bool used; uint32_t seq; uint32_t lastSent; uint8_t tries; String line; };
Pending pending[MAX_PENDING];

char lineBuf[RX_LINE_MAX];
size_t lineLen = 0;
bool discarding = false;

// ------------------------------------------------------------------ output
void sendDoc(JsonDocument &doc) {
  serializeJson(doc, Serial);
  Serial.print('\n');
}

void sendHello() {
  JsonDocument d;
  d["type"] = "hello";
  d["device_id"] = cfg.deviceId;
  d["role"] = "input";
  d["fw"] = FW_VERSION;
  d["proto"] = PROTO_VERSION;
  d["boot_id"] = bootId;
  JsonObject caps = d["caps"].to<JsonObject>();
  caps["channels"] = cfg.channels;
  caps["buttons"] = true;
#if SOC_TOUCH_SENSOR_NUM > 0
  caps["touch"] = true;
#else
  caps["touch"] = false;
#endif
  caps["button_leds"] = true;
  caps["mode"] = cfg.mode == MODE_RAW ? "raw" : "answer";
  sendDoc(d);
}

void sendAck(int32_t id) {
  JsonDocument d;
  d["type"] = "ack";
  d["id"] = id;
  sendDoc(d);
}

void sendNack(int32_t id, const char *err) {
  JsonDocument d;
  d["type"] = "nack";
  d["id"] = id;
  d["error"] = err;
  sendDoc(d);
}

void sendLog(const char *level, const char *msg) {
  JsonDocument d;
  d["type"] = "log";
  d["level"] = level;
  d["msg"] = msg;
  sendDoc(d);
}

// Queue an event: sent now and retransmitted until the PC acks its seq.
void queueEvent(JsonDocument &d) {
  d["type"] = "event";
  d["device_id"] = cfg.deviceId;
  d["seq"] = ++seqCounter;
  d["t_ms"] = millis();
  String line;
  serializeJson(d, line);
  int slot = -1;
  for (int i = 0; i < MAX_PENDING; i++) if (!pending[i].used) { slot = i; break; }
  if (slot < 0) {  // queue full: drop the oldest
    uint32_t oldest = UINT32_MAX;
    for (int i = 0; i < MAX_PENDING; i++) if (pending[i].seq < oldest) { oldest = pending[i].seq; slot = i; }
  }
  pending[slot] = {true, seqCounter, millis(), 1, line};
  Serial.print(line);
  Serial.print('\n');
}

void retransmit() {
  uint32_t now = millis();
  for (int i = 0; i < MAX_PENDING; i++) {
    Pending &p = pending[i];
    if (!p.used || now - p.lastSent < RETRY_MS) continue;
    if (p.tries >= MAX_TRIES) { p.used = false; continue; }  // give up; PC is gone
    p.tries++;
    p.lastSent = now;
    Serial.print(p.line);
    Serial.print('\n');
  }
}

// ------------------------------------------------------------------ LEDs
void applyButtonLeds() {
  for (uint8_t i = 0; i < MAX_CH; i++)
    if (PINS[i].led >= 0) digitalWrite(PINS[i].led, buttonLed[i] ? HIGH : LOW);
}

void setAllButtonLeds(bool on) {
  for (uint8_t i = 0; i < MAX_CH; i++) buttonLed[i] = on && i < cfg.channels;
  applyButtonLeds();
}

// ------------------------------------------------------------------ inputs
bool useButtons() { return cfg.inputType == IN_BUTTONS || cfg.inputType == IN_BOTH; }
bool useTouch() { return cfg.inputType == IN_TOUCH || cfg.inputType == IN_BOTH; }

void calibrateTouch() {
#if SOC_TOUCH_SENSOR_NUM > 0
  for (uint8_t i = 0; i < MAX_CH; i++) {
    if (PINS[i].touch < 0) continue;
    uint32_t sum = 0;
    for (int k = 0; k < 16; k++) { sum += touchRead(PINS[i].touch); delay(2); }
    ch[i].touchBase = sum / 16;
  }
#endif
}

bool readRaw(uint8_t i) {
  bool pressed = false;
  if (useButtons() && PINS[i].button >= 0) pressed |= digitalRead(PINS[i].button) == LOW;
#if SOC_TOUCH_SENSOR_NUM > 0
  if (useTouch() && PINS[i].touch >= 0 && ch[i].touchBase > 0) {
    uint32_t v = touchRead(PINS[i].touch);
    uint32_t base = ch[i].touchBase;
    uint32_t diff = v > base ? v - base : base - v;  // ESP32 drops, S2/S3 rise when touched
    bool touched = diff * 100 > base * cfg.touchSensitivity;
    if (!touched) ch[i].touchBase = (base * 31 + v) / 32;  // follow slow drift (humidity, temperature)
    pressed |= touched;
  }
#endif
  return pressed;
}

int labelIndex(const char *label) {
  for (uint8_t i = 0; i < cfg.channels; i++) if (strcasecmp(cfg.labels[i], label) == 0) return i;
  return -1;
}

void onPress(uint8_t i) {
  uint32_t now = millis();
  if (lastAcceptedMs && now - lastAcceptedMs < cfg.lockoutMs) return;  // repeat guard
  if (cfg.mode == MODE_RAW) {
    lastAcceptedMs = now;
    JsonDocument d;
    d["event"] = "input_pressed";
    d["channel"] = i;
    d["label"] = cfg.labels[i];
    queueEvent(d);
    return;
  }
  if (!armed || !allowed[i]) return;
  lastAcceptedMs = now;
  armed = false;  // exactly one answer per question
  for (uint8_t k = 0; k < MAX_CH; k++) buttonLed[k] = (k == i);
  applyButtonLeds();
  JsonDocument d;
  d["event"] = "answer_selected";
  d["question_id"] = questionId;
  d["selected_answer"] = cfg.labels[i];
  d["channel"] = i;
  queueEvent(d);
}

void scanInputs() {
  uint32_t now = millis();
  for (uint8_t i = 0; i < cfg.channels; i++) {
    bool raw = readRaw(i);
    if (raw != ch[i].lastRaw) { ch[i].lastRaw = raw; ch[i].changedAt = now; }
    if (raw != ch[i].stable && now - ch[i].changedAt >= cfg.debounceMs) {
      ch[i].stable = raw;
      if (raw) onPress(i);
      if (cfg.mode == MODE_RAW && !raw) {
        JsonDocument d;
        d["event"] = "input_released";
        d["channel"] = i;
        d["label"] = cfg.labels[i];
        queueEvent(d);
      }
    }
  }
}

// ------------------------------------------------------------------ commands
void handleCommand(JsonDocument &doc) {
  const char *cmd = doc["command"] | "";
  bool hasId = doc["id"].is<int32_t>();
  int32_t id = doc["id"] | -1;

  if (!strcmp(cmd, "ack")) {  // PC acknowledges one of our events
    uint32_t seq = doc["seq"] | 0;
    for (int i = 0; i < MAX_PENDING; i++) if (pending[i].used && pending[i].seq == seq) pending[i].used = false;
    return;
  }
  if (!strcmp(cmd, "identify")) {
    sendHello();
  } else if (!strcmp(cmd, "ping")) {
    // ack below
  } else if (!strcmp(cmd, "arm")) {
    strlcpy(questionId, doc["question_id"] | "", sizeof(questionId));
    JsonArrayConst opts = doc["options"].as<JsonArrayConst>();
    for (uint8_t i = 0; i < MAX_CH; i++) allowed[i] = opts.isNull() && i < cfg.channels;
    for (JsonVariantConst v : opts) {
      int idx = labelIndex(v.as<const char *>() ? v.as<const char *>() : "");
      if (idx >= 0) allowed[idx] = true;
    }
    uint32_t timeoutS = doc["timeout_s"] | 0;
    armDeadline = timeoutS ? millis() + timeoutS * 1000UL + 2000UL : 0;  // grace; PC is authoritative
    armed = true;
    for (uint8_t i = 0; i < MAX_CH; i++) buttonLed[i] = allowed[i];
    applyButtonLeds();
  } else if (!strcmp(cmd, "disarm")) {
    armed = false;
    setAllButtonLeds(false);
  } else if (!strcmp(cmd, "set_button_leds")) {
    JsonArrayConst st = doc["states"].as<JsonArrayConst>();
    uint8_t i = 0;
    for (JsonVariantConst v : st) if (i < MAX_CH) buttonLed[i++] = v.as<bool>();
    applyButtonLeds();
  } else if (!strcmp(cmd, "configure")) {
    JsonObjectConst map = doc["mapping"].as<JsonObjectConst>();
    for (JsonPairConst kv : map) {
      int chIdx = atoi(kv.key().c_str());
      const char *label = kv.value().as<const char *>();
      if (chIdx >= 0 && chIdx < MAX_CH && label && strlen(label) < sizeof(cfg.labels[0])) strlcpy(cfg.labels[chIdx], label, sizeof(cfg.labels[0]));
    }
    if (doc["channels"].is<int>()) cfg.channels = constrain((int)doc["channels"], 1, MAX_CH);
    const char *it = doc["input_type"] | "";
    if (!strcmp(it, "buttons")) cfg.inputType = IN_BUTTONS;
    else if (!strcmp(it, "touch")) cfg.inputType = IN_TOUCH;
    else if (!strcmp(it, "both")) cfg.inputType = IN_BOTH;
    const char *mode = doc["mode"] | "";
    if (!strcmp(mode, "raw")) cfg.mode = MODE_RAW;
    else if (!strcmp(mode, "answer")) cfg.mode = MODE_ANSWER;
    if (doc["debounce_ms"].is<int>()) cfg.debounceMs = constrain((int)doc["debounce_ms"], 5, 500);
    if (doc["lockout_ms"].is<int>()) cfg.lockoutMs = constrain((int)doc["lockout_ms"], 0, 10000);
    if (doc["touch_sensitivity"].is<int>()) cfg.touchSensitivity = constrain((int)doc["touch_sensitivity"], 3, 90);
    saveConfig();
    if (useTouch()) calibrateTouch();
  } else if (!strcmp(cmd, "set_id")) {
    const char *nid = doc["new_id"] | "";
    if (!*nid || strlen(nid) >= sizeof(cfg.deviceId)) { if (hasId) sendNack(id, "invalid new_id"); return; }
    strlcpy(cfg.deviceId, nid, sizeof(cfg.deviceId));
    saveConfig();
    if (hasId) sendAck(id);
    sendHello();
    return;
  } else if (!strcmp(cmd, "calibrate")) {
    calibrateTouch();
  } else {
    if (hasId) sendNack(id, "unknown command");
    return;
  }
  if (hasId) sendAck(id);
}

void readSerial() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      if (!discarding && lineLen > 0) {
        lineBuf[lineLen] = 0;
        JsonDocument doc;
        DeserializationError err = deserializeJson(doc, lineBuf, lineLen);
        if (!err && doc.is<JsonObject>()) {
          lastPcMsgMs = millis();
          handleCommand(doc);
        } else {
          sendLog("warn", "bad json");
        }
      }
      lineLen = 0;
      discarding = false;
    } else if (c != '\r') {
      if (lineLen < RX_LINE_MAX - 1) lineBuf[lineLen++] = c;
      else discarding = true;  // over-long line: drop it
    }
  }
}

void updateStatusLed() {
  uint32_t now = millis();
  bool pcAlive = lastPcMsgMs && now - lastPcMsgMs < PC_TIMEOUT_MS;
  // solid = PC connected; slow blink = waiting for PC; fast blink = armed
  bool on = pcAlive ? (armed ? (now / 150) % 2 : true) : (now / 700) % 2;
  digitalWrite(STATUS_LED, on);
}

// ------------------------------------------------------------------ main
void setup() {
  Serial.setRxBufferSize(1024);
  Serial.begin(BAUD);
  pinMode(STATUS_LED, OUTPUT);
  loadConfig();
  for (uint8_t i = 0; i < MAX_CH; i++) {
    if (PINS[i].button >= 0) pinMode(PINS[i].button, INPUT_PULLUP);
    if (PINS[i].led >= 0) { pinMode(PINS[i].led, OUTPUT); digitalWrite(PINS[i].led, LOW); }
    ch[i] = {false, false, 0, 0};
    allowed[i] = false;
    buttonLed[i] = false;
  }
  snprintf(bootId, sizeof(bootId), "%08lx", (unsigned long)esp_random());
  calibrateTouch();
  // lamp test so a teacher can see every button LED works
  setAllButtonLeds(true);
  delay(250);
  setAllButtonLeds(false);
  sendHello();
}

void loop() {
  readSerial();
  scanInputs();
  retransmit();
  if (armed && armDeadline && (int32_t)(millis() - armDeadline) > 0) {  // safety auto-disarm
    armed = false;
    setAllButtonLeds(false);
  }
  updateStatusLed();
  delay(1);
}
