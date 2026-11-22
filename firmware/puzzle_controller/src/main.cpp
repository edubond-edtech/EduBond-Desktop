/*
 * EduKit — Game 1 «رحلة إلى مكة» — WORD-PLATE BOARD firmware (role "puzzle")
 *
 * Six sockets. Every plate carries one resistor; each socket is a voltage
 * divider read by an ADC1 pin:
 *
 *     3V3 ── [plate resistor Rp] ──┬── ADC pin        V = 3.3 · 10k / (10k + Rp)
 *                                  ├── 10 kΩ ── GND   (empty socket -> 0 V)
 *                                  └── 100 nF ── GND
 *
 *   plate 1  2 kΩ    ≈ 2.75 V      plate 4  20 kΩ   ≈ 1.10 V
 *   plate 2  4.7 kΩ  ≈ 2.24 V      plate 5  47 kΩ   ≈ 0.58 V
 *   plate 3  12 kΩ   ≈ 1.50 V      plate 6  120 kΩ  ≈ 0.25 V
 *
 * FIXED ANSWER KEY: socket k expects plate k (EXPECTED_PLATE[] below). The
 * plates look identical to the students; the teacher writes word k of the
 * sentence on plate k, recognising the plates with their own key. The PC only
 * arms the board with the question id and the number of words (2..6). The
 * student lays the cards, then presses the SEND button: the firmware reads
 * sockets 1..n, compares them with the fixed key and sends "puzzle_result"
 * (win / fail). A card left in a socket beyond n makes the answer wrong.
 * Pressing SEND with a socket 1..n still empty sends "puzzle_incomplete".
 * Plate insert/remove events are also reported live.
 *
 * Sockets (ADC1 only, so Wi-Fi can be added later):
 *   socket 1 GPIO36 (VP) · 2 GPIO39 (VN) · 3 GPIO34 · 4 GPIO35 · 5 GPIO32 · 6 GPIO33
 *   Socket 1 = first word of the sentence = right-most socket (Arabic reads right-to-left).
 *   SEND button GPIO27 -> button -> GND (internal pull-up). Optional lamp in the button GPIO26.
 *   Status LED GPIO2. Optional local buzzer GPIO25.
 * Links: USB serial AND Bluetooth LE (Nordic UART Service, "EduKit-PUZZLE_01").
 * Protocol: docs/PROTOCOL.md + docs/GAME1_JOURNEY.md (NDJSON, 115200 baud).
 */
#include <Arduino.h>
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


#ifndef EDUKIT_DEVICE_ID
#define EDUKIT_DEVICE_ID "PUZZLE_01"
#endif
#define FW_VERSION "1.1.0"
#define PROTO_VERSION 1
#define BAUD 115200
#define STATUS_LED 2
#define BUZZER_PIN 25
#define SUBMIT_PIN 27
#define SUBMIT_LAMP_PIN 26
#define SUBMIT_DEBOUNCE_MS 40
#define NUM_SOCKETS 6
#define NUM_PLATES 6
#define RX_LINE_MAX 768
#define MAX_PENDING 10
#define RETRY_MS 300
#define MAX_TRIES 15
#define SAMPLE_MS 20
#define PC_TIMEOUT_MS 7000
#define EMPTY_BELOW_MV 150

static const uint8_t SOCKET_PINS[NUM_SOCKETS] = {36, 39, 34, 35, 32, 33};
// Must match desktop/edukit/hardware/plates.py (checked by a unit test).
static const uint32_t PLATE_RES_OHM[NUM_PLATES] = {2000, 4700, 12000, 20000, 47000, 120000};
static const uint32_t RREF_OHM = 10000;
// Fixed key: plate expected in each socket (socket 1 = first word).
static const uint8_t EXPECTED_PLATE[NUM_SOCKETS] = {1, 2, 3, 4, 5, 6};
static const uint32_t VCC_MV = 3300;

// ------------------------------------------------------------------ config
struct Config {
  char deviceId[24];
  uint16_t plateMv[NUM_PLATES];  // reference voltage per plate (theoretical or learned)
  uint16_t toleranceMv;
  uint16_t settleMs;    // a socket reading must be stable this long
  uint16_t completeMs;  // board must stay full this long before judging
  bool clickSound;
} cfg;
Preferences prefs;

uint16_t theoreticalMv(uint8_t plate) { return (uint16_t)((VCC_MV * RREF_OHM) / (RREF_OHM + PLATE_RES_OHM[plate])); }

void loadConfig() {
  prefs.begin("edukit_pz", true);
  strlcpy(cfg.deviceId, prefs.getString("id", EDUKIT_DEVICE_ID).c_str(), sizeof(cfg.deviceId));
  for (uint8_t p = 0; p < NUM_PLATES; p++) {
    char key[6];
    snprintf(key, sizeof(key), "pm%u", p);
    cfg.plateMv[p] = prefs.getUShort(key, theoreticalMv(p));
  }
  cfg.toleranceMv = prefs.getUShort("tol", 140);
  cfg.settleMs = prefs.getUShort("set", 250);
  cfg.completeMs = prefs.getUShort("cmp", 600);
  cfg.clickSound = prefs.getBool("clk", true);
  prefs.end();
}

void saveConfig() {
  prefs.begin("edukit_pz", false);
  prefs.putString("id", cfg.deviceId);
  for (uint8_t p = 0; p < NUM_PLATES; p++) {
    char key[6];
    snprintf(key, sizeof(key), "pm%u", p);
    prefs.putUShort(key, cfg.plateMv[p]);
  }
  prefs.putUShort("tol", cfg.toleranceMv);
  prefs.putUShort("set", cfg.settleMs);
  prefs.putUShort("cmp", cfg.completeMs);
  prefs.putBool("clk", cfg.clickSound);
  prefs.end();
}

// ------------------------------------------------------------------ state
struct Socket {
  int8_t stable;     // plate number 1..6, 0 = empty, -1 = unknown resistor
  int8_t candidate;
  uint32_t candSince;
  uint16_t lastMv;
} sock[NUM_SOCKETS];

char bootId[9];
uint32_t seqCounter = 0;
uint32_t lastPcMsgMs = 0;
uint32_t lastSampleMs = 0;

bool armed = false;
bool needClear = false;
char questionId[32] = "";
uint8_t expected[NUM_SOCKETS];
uint8_t expectedCount = 0;
bool judged = false;  // result already sent for the current full board

struct Pending { bool used; uint32_t seq; uint32_t lastSent; uint8_t tries; String line; };
Pending pending[MAX_PENDING];

// ------------------------------------------------------------------ output
void sendDoc(JsonDocument &d) { String out; serializeJson(d, out); sendLine(out); }

void sendHello() {
  JsonDocument d;
  d["type"] = "hello";
  d["device_id"] = cfg.deviceId;
  d["role"] = "puzzle";
  d["fw"] = FW_VERSION;
  d["proto"] = PROTO_VERSION;
  d["boot_id"] = bootId;
  JsonObject caps = d["caps"].to<JsonObject>();
  caps["sockets"] = NUM_SOCKETS;
  caps["plates"] = NUM_PLATES;
  caps["detect"] = "resistor";
  caps["submit_button"] = true;
  caps["ble"] = true;
  sendDoc(d);
}

void sendAck(int32_t id) { JsonDocument d; d["type"] = "ack"; d["id"] = id; sendDoc(d); }
void sendNack(int32_t id, const char *e) { JsonDocument d; d["type"] = "nack"; d["id"] = id; d["error"] = e; sendDoc(d); }
void sendLog(const char *level, const String &msg) { JsonDocument d; d["type"] = "log"; d["level"] = level; d["msg"] = msg; sendDoc(d); }

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

void click(uint16_t freq, uint16_t ms) {
  if (cfg.clickSound) tone(BUZZER_PIN, freq, ms);
}

// ------------------------------------------------------------------ sensing
uint16_t readMv(uint8_t s) {
  uint32_t sum = 0;
  for (int k = 0; k < 8; k++) sum += analogReadMilliVolts(SOCKET_PINS[s]);
  return sum / 8;
}

int8_t classify(uint16_t mv) {
  if (mv < EMPTY_BELOW_MV) return 0;
  int8_t best = -1;
  uint16_t bestDiff = 0xFFFF;
  for (uint8_t p = 0; p < NUM_PLATES; p++) {
    uint16_t diff = mv > cfg.plateMv[p] ? mv - cfg.plateMv[p] : cfg.plateMv[p] - mv;
    if (diff < bestDiff) { bestDiff = diff; best = p + 1; }
  }
  return bestDiff <= cfg.toleranceMv ? best : -1;
}

void emitBoardState() {
  JsonDocument d;
  d["event"] = "board_state";
  d["state"] = needClear ? "clear_required" : "ready";
  d["question_id"] = questionId;
  queueEvent(d);
}

bool boardEmpty() {
  for (auto &s : sock) if (s.stable != 0) return false;
  return true;
}

void onSocketChanged(uint8_t s, int8_t oldPlate, int8_t newPlate) {
  if (oldPlate > 0) {
    JsonDocument d;
    d["event"] = "plate_removed";
    d["socket"] = s + 1;
    queueEvent(d);
  }
  if (newPlate > 0) {
    JsonDocument d;
    d["event"] = "plate_inserted";
    d["socket"] = s + 1;
    d["plate"] = newPlate;
    d["mv"] = sock[s].lastMv;
    queueEvent(d);
    click(1800, 25);
  } else if (newPlate < 0) {
    JsonDocument d;
    d["event"] = "plate_unknown";  // resistor out of tolerance: bad contact or wrong plate
    d["socket"] = s + 1;
    d["mv"] = sock[s].lastMv;
    queueEvent(d);
  }
  judged = false;  // any change allows a new judgement once the board is full again
  if (needClear && boardEmpty()) {
    needClear = false;
    emitBoardState();
  }
}

void judge() {  // called when the SEND button is pressed
  if (!armed || expectedCount == 0) return;
  if (needClear) { emitBoardState(); click(220, 250); return; }  // cards of the previous sentence still on the board
  JsonDocument d;
  d["question_id"] = questionId;
  bool full = true;
  for (uint8_t s = 0; s < expectedCount; s++) if (sock[s].stable <= 0) { full = false; break; }
  if (!full) {
    d["event"] = "puzzle_incomplete";
    JsonArray missing = d["missing"].to<JsonArray>();
    for (uint8_t s = 0; s < expectedCount; s++) if (sock[s].stable <= 0) missing.add(s + 1);
    queueEvent(d);
    click(330, 120);
    return;
  }
  if (judged) return;  // same arrangement already sent; change a card to send again
  judged = true;
  uint8_t inPlace = 0;
  bool extra = false;
  d["event"] = "puzzle_result";
  JsonArray placed = d["placed"].to<JsonArray>();
  JsonArray exp = d["expected"].to<JsonArray>();
  for (uint8_t s = 0; s < expectedCount; s++) {
    placed.add(sock[s].stable);
    exp.add(expected[s]);
    if (sock[s].stable == expected[s]) inPlace++;
  }
  for (uint8_t s = expectedCount; s < NUM_SOCKETS; s++)
    if (sock[s].stable != 0) { extra = true; placed.add(sock[s].stable); }  // a card where no word belongs
  d["in_place"] = inPlace;
  d["extra_cards"] = extra;
  bool win = inPlace == expectedCount && !extra;
  d["result"] = win ? "win" : "fail";
  queueEvent(d);
  armed = false;  // one judgement per question; the PC re-arms for a retry
  if (win) click(1319, 120); else click(220, 250);
}

struct { bool stable, lastRaw; uint32_t changedAt; } submitBtn = {false, false, 0};

void scanSubmit() {
  uint32_t now = millis();
  bool raw = digitalRead(SUBMIT_PIN) == LOW;
  if (raw != submitBtn.lastRaw) { submitBtn.lastRaw = raw; submitBtn.changedAt = now; }
  if (raw != submitBtn.stable && now - submitBtn.changedAt >= SUBMIT_DEBOUNCE_MS) {
    submitBtn.stable = raw;
    if (raw) {
      JsonDocument d;
      d["event"] = "submit_pressed";
      queueEvent(d);
      judge();
    }
  }
}

void scanSockets() {
  uint32_t now = millis();
  if (now - lastSampleMs < SAMPLE_MS) return;
  lastSampleMs = now;
  for (uint8_t s = 0; s < NUM_SOCKETS; s++) {
    uint16_t mv = readMv(s);
    sock[s].lastMv = mv;
    int8_t c = classify(mv);
    if (c != sock[s].candidate) { sock[s].candidate = c; sock[s].candSince = now; }
    if (c != sock[s].stable && now - sock[s].candSince >= cfg.settleMs) {
      int8_t old = sock[s].stable;
      sock[s].stable = c;
      onSocketChanged(s, old, c);
    }
  }
}

// ------------------------------------------------------------------ commands
void handleCommand(JsonDocument &doc) {
  const char *cmd = doc["command"] | "";
  bool hasId = doc["id"].is<int32_t>();
  int32_t id = doc["id"] | -1;

  if (!strcmp(cmd, "ack")) {
    uint32_t seq = doc["seq"] | 0;
    for (auto &p : pending) if (p.used && p.seq == seq) p.used = false;
    return;
  }
  if (!strcmp(cmd, "identify")) {
    sendHello();
  } else if (!strcmp(cmd, "ping")) {
  } else if (!strcmp(cmd, "arm")) {
    int n = doc["sockets"] | NUM_SOCKETS;  // number of words in this sentence
    if (n < 1 || n > NUM_SOCKETS) { if (hasId) sendNack(id, "sockets must be 1..6"); return; }
    const char *qid = doc["question_id"] | "";
    bool newQuestion = strcmp(qid, questionId) != 0;
    strlcpy(questionId, qid, sizeof(questionId));
    expectedCount = n;
    for (uint8_t s = 0; s < NUM_SOCKETS; s++) expected[s] = EXPECTED_PLATE[s];
    JsonArrayConst exp = doc["expected"].as<JsonArrayConst>();  // advanced override (normally omitted)
    if (!exp.isNull() && exp.size() == (size_t)n) {
      uint8_t i = 0;
      for (JsonVariantConst v : exp) expected[i++] = (uint8_t)constrain(v.as<int>(), 1, NUM_PLATES);
    }
    if (newQuestion) needClear = !boardEmpty();  // cards of the previous sentence must be taken out first
    judged = false;  // a re-arm (retry) allows the same arrangement to be sent again
    armed = true;
    if (hasId) sendAck(id);
    emitBoardState();
    return;
  } else if (!strcmp(cmd, "disarm")) {
    armed = false;
  } else if (!strcmp(cmd, "configure")) {
    if (doc["tolerance_mv"].is<int>()) cfg.toleranceMv = constrain((int)doc["tolerance_mv"], 40, 400);
    if (doc["settle_ms"].is<int>()) cfg.settleMs = constrain((int)doc["settle_ms"], 50, 3000);
    if (doc["complete_ms"].is<int>()) cfg.completeMs = constrain((int)doc["complete_ms"], 0, 5000);
    if (doc["click_sound"].is<bool>()) cfg.clickSound = doc["click_sound"];
    saveConfig();
  } else if (!strcmp(cmd, "learn_plate")) {
    // Put plate P in socket S, then send {"command":"learn_plate","plate":P,"socket":S}
    int p = doc["plate"] | 0, s = doc["socket"] | 1;
    if (p < 1 || p > NUM_PLATES || s < 1 || s > NUM_SOCKETS) { if (hasId) sendNack(id, "plate 1..6, socket 1..6"); return; }
    uint16_t mv = readMv(s - 1);
    if (mv < EMPTY_BELOW_MV) { if (hasId) sendNack(id, "socket is empty"); return; }
    cfg.plateMv[p - 1] = mv;
    saveConfig();
    sendLog("info", String("plate ") + p + " learned at " + mv + " mV");
  } else if (!strcmp(cmd, "reset_calibration")) {
    for (uint8_t p = 0; p < NUM_PLATES; p++) cfg.plateMv[p] = theoreticalMv(p);
    saveConfig();
  } else if (!strcmp(cmd, "read_raw")) {
    JsonDocument d;
    d["event"] = "raw_readings";
    JsonArray mv = d["mv"].to<JsonArray>();
    JsonArray pl = d["plates"].to<JsonArray>();
    for (uint8_t s = 0; s < NUM_SOCKETS; s++) { mv.add(sock[s].lastMv); pl.add(sock[s].stable); }
    queueEvent(d);
  } else if (!strcmp(cmd, "set_id")) {
    const char *nid = doc["new_id"] | "";
    if (!*nid || strlen(nid) >= sizeof(cfg.deviceId)) { if (hasId) sendNack(id, "invalid new_id"); return; }
    strlcpy(cfg.deviceId, nid, sizeof(cfg.deviceId));
    saveConfig();
    if (hasId) sendAck(id);
    sendHello();
    return;
  } else {
    if (hasId) sendNack(id, "unknown command");
    return;
  }
  if (hasId) sendAck(id);
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
void setup() {
  Serial.setRxBufferSize(1024);
  Serial.begin(BAUD);
  pinMode(STATUS_LED, OUTPUT);
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);  // 0..~3.1 V range
  loadConfig();
  snprintf(bootId, sizeof(bootId), "%08lx", (unsigned long)esp_random());
  for (uint8_t s = 0; s < NUM_SOCKETS; s++) {
    sock[s] = {0, 0, millis(), 0};
  }
  pinMode(SUBMIT_PIN, INPUT_PULLUP);
  pinMode(SUBMIT_LAMP_PIN, OUTPUT);
  bleBegin(cfg.deviceId);  // advertises as "EduKit-<device id>"
  sendHello();
}

void loop() {
  readSerial();
  scanSockets();
  scanSubmit();
  retransmit();
  uint32_t now = millis();
  bool pcAlive = lastPcMsgMs && now - lastPcMsgMs < PC_TIMEOUT_MS;
  bool on = pcAlive ? (armed && !needClear ? true : (now / 400) % 2) : (now / 900) % 2;
  digitalWrite(STATUS_LED, on);
  digitalWrite(SUBMIT_LAMP_PIN, armed && !needClear ? HIGH : LOW);  // lamp in the SEND button: ready for an answer
  delay(1);
}
