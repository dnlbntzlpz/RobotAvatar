#include <WiFi.h>
#include <ESP32Servo.h>
#include <Wire.h>
#include <U8g2lib.h>

#include "secret.h"  // must define WIFI_SSID and WIFI_PASS

// ================================================================
// OLED (SH1106 128x64 I2C)
// ================================================================
U8G2_SH1106_128X64_NONAME_F_HW_I2C oled(U8G2_R0, /* reset=*/ U8X8_PIN_NONE);

// ================================================================
// WiFi / TCP
// ================================================================
static const char* ssid     = WIFI_SSID;
static const char* password = WIFI_PASS;

static const uint16_t SERVER_PORT = 12345;   // must match your GUI
WiFiServer server(SERVER_PORT);

// ================================================================
// Servos / Pins (KEEP OR CHANGE TO MATCH YOUR BOARD)
// ================================================================
Servo servo1, servo2, servo3, servo4, servo5, servo6;

// Your current mapping (verify these are valid pins on your ESP32 board!)
static const int PIN_S1 = 3;
static const int PIN_S2 = 4;
static const int PIN_S3 = 21;
static const int PIN_S4 = 20;
static const int PIN_S5 = 10;
static const int PIN_S6 = 5;

// ================================================================
// Arm presets (same values you had)
// ================================================================
static const int L1_A = 90,  L1_B = 90;
static const int L2_A = 65,  L2_B = 55;
static const int L3_A = 140, L3_B = 40;
static const int L4_A = 40,  L4_B = 140;
static const int L5_A = 135, L5_B = 115;

static const int R1_A = 90,  R1_B = 90;
static const int R2_A = 125, R2_B = 125;
static const int R3_A = 160, R3_B = 30;
static const int R4_A = 30,  R4_B = 160;
static const int R5_A = 65,  R5_B = 65;

// Gesture “home” (neutral)
static const int G_HOME_5 = 90;
static const int G_HOME_6 = 150;

// Gesture A press angles
static const int G_A_5 = 70;
static const int G_A_6 = 180;

// Gesture B press angles
static const int G_B_5 = 110;
static const int G_B_6 = 180;

// How long to hold the press before releasing (ms)
static const uint32_t GESTURE_PRESS_MS = 1000; // 120–250 recommended

// ================================================================
// OLED / Status variables
// ================================================================
String lastCmd = "-";
String lastGestureInfo = "-";

int s5_now = G_HOME_5;
int s6_now = G_HOME_6;

volatile uint32_t pktCount = 0;
uint32_t pktCountLast = 0;
uint32_t pktRate = 0;

uint32_t lastPktMs = 0;
bool guiConnected = false;

// ================================================================
// Helpers
// ================================================================
static inline int clampDeg(int x) { return constrain(x, 0, 180); }

void moveLeftArm(int a, int b) {
  servo1.write(clampDeg(a));
  servo2.write(clampDeg(b));
}

void moveRightArm(int a, int b) {
  servo3.write(clampDeg(a));
  servo4.write(clampDeg(b));
}

void moveGesture(int s5, int s6) {
  s5 = clampDeg(s5);
  s6 = clampDeg(s6);

  servo5.write(s5);
  servo6.write(s6);

  s5_now = s5;
  s6_now = s6;
}

void applyLeftGesture(int g) {
  switch (g) {
    case 1: moveLeftArm(L1_A, L1_B); break;
    case 2: moveLeftArm(L2_A, L2_B); break;
    case 3: moveLeftArm(L3_A, L3_B); break;
    case 4: moveLeftArm(L4_A, L4_B); break;
    case 5: moveLeftArm(L5_A, L5_B); break;
    default: break;
  }
}

void applyRightGesture(int g) {
  switch (g) {
    case 1: moveRightArm(R1_A, R1_B); break;
    case 2: moveRightArm(R2_A, R2_B); break;
    case 3: moveRightArm(R3_A, R3_B); break;
    case 4: moveRightArm(R4_A, R4_B); break;
    case 5: moveRightArm(R5_A, R5_B); break;
    default: break;
  }
}

bool parseRL(const String& data, int& outR, int& outL) {
  int commaIndex = data.indexOf(',');
  if (commaIndex < 0) return false;

  String rightCmd = data.substring(0, commaIndex);
  String leftCmd  = data.substring(commaIndex + 1);
  rightCmd.trim();
  leftCmd.trim();

  if (!rightCmd.startsWith("R") || !leftCmd.startsWith("L")) return false;

  outR = rightCmd.substring(1).toInt();
  outL = leftCmd.substring(1).toInt();
  return true;
}

// ================================================================
// Non-blocking gesture sequencer (no delay())
// ================================================================
enum class GestureSeqState : uint8_t { IDLE, PRESSING };

struct GestureSequencer {
  GestureSeqState st = GestureSeqState::IDLE;
  uint32_t t0 = 0;

  void startPress(int s5, int s6) {
    moveGesture(s5, s6);
    t0 = millis();
    st = GestureSeqState::PRESSING;
  }

  void update() {
    if (st == GestureSeqState::PRESSING) {
      if (millis() - t0 >= GESTURE_PRESS_MS) {
        moveGesture(G_HOME_5, G_HOME_6); // release
        st = GestureSeqState::IDLE;
      }
    }
  }

  bool busy() const { return st != GestureSeqState::IDLE; }
};

GestureSequencer gseq;

// ================================================================
// Gesture commands: "A,A" and "B,B"
// A,A -> press each time it appears
// B,B -> press on BOTH edges (enter and exit)
// ================================================================
void handleGestureCommand(const String& cmd) {
  static bool lastB = false;

  const bool isA = (cmd == "A,A");
  const bool isB = (cmd == "B,B");

  // OLED info (simple)
  if (isA) lastGestureInfo = "A";
  else if (isB) lastGestureInfo = "B";
  else lastGestureInfo = "-";

  // If currently doing press/release, ignore new presses
  if (gseq.busy()) {
    lastB = isB;
    return;
  }

  // A: momentary press
  if (isA) {
    gseq.startPress(G_A_5, G_A_6);
    return;
  }

  // B: press on both edges
  if (isB != lastB) {
    gseq.startPress(G_B_5, G_B_6);
    lastGestureInfo = "B(edge)";
  }

  lastB = isB;
}

// ================================================================
// OLED dashboard (single screen)
// ================================================================
void drawOLED() {
  oled.clearBuffer();
  oled.setFont(u8g2_font_6x10_tf);

  String wifiLine;
  if (WiFi.status() == WL_CONNECTED) {
    wifiLine = "WiFi: OK  " + String(WiFi.RSSI()) + "dBm";
  } else {
    wifiLine = "WiFi: CONNECTING";
  }
  oled.drawStr(0, 10, wifiLine.c_str());

  String ipLine = "IP: " + WiFi.localIP().toString();
  oled.drawStr(0, 20, ipLine.c_str());

  String guiLine = String("GUI: ") + (guiConnected ? "ON " : "OFF") + " " + String(pktRate) + "/s";
  oled.drawStr(0, 30, guiLine.c_str());

  String cmdLine = "CMD: " + lastCmd;
  oled.drawStr(0, 40, cmdLine.c_str());

  String gestLine = "GEST: " + lastGestureInfo;
  oled.drawStr(0, 50, gestLine.c_str());

  uint32_t age = (lastPktMs == 0) ? 0 : (millis() - lastPktMs);
  String sLine = "S5:" + String(s5_now) + " S6:" + String(s6_now); // + " Age:" + String(age)
  oled.drawStr(0, 60, sLine.c_str());

  oled.sendBuffer();
}

void serviceUI() {
  static uint32_t lastOled = 0;
  static uint32_t lastRateTick = 0;

  uint32_t now = millis();

  // packets/sec every 1s
  if (now - lastRateTick >= 1000) {
    lastRateTick = now;
    pktRate = pktCount - pktCountLast;
    pktCountLast = pktCount;
  }

  // OLED refresh every 200ms
  if (now - lastOled >= 200) {
    lastOled = now;
    drawOLED();
  }
}

// ================================================================
// Setup / Loop
// ================================================================
void setup() {
  Serial.begin(115200);
  delay(100);

  Wire.begin(); // if you need custom pins: Wire.begin(SDA, SCL);
  oled.begin();
  oled.clearBuffer();
  oled.setFont(u8g2_font_6x10_tf);
  oled.drawStr(0, 12, "Booting...");
  oled.sendBuffer();

  // Servos
  servo1.attach(PIN_S1);
  servo2.attach(PIN_S2);
  servo3.attach(PIN_S3);
  servo4.attach(PIN_S4);
  servo5.attach(PIN_S5);
  servo6.attach(PIN_S6);

  // Home pose
  moveLeftArm(90, 90);
  moveRightArm(90, 90);
  moveGesture(G_HOME_5, G_HOME_6);

  WiFi.mode(WIFI_STA);
  WiFi.disconnect(true);
  delay(150);

  WiFi.begin(ssid, password);

  // Show connecting on OLED
  while (WiFi.status() != WL_CONNECTED) {
    drawOLED();
    delay(150);
  }

  server.begin();
  drawOLED();
}

void loop() {
  // periodic OLED + pkt rate
  static uint32_t lastOled = 0;
  static uint32_t lastRateTick = 0;
  uint32_t now = millis();

  if (now - lastRateTick >= 1000) {
    lastRateTick = now;
    pktRate = pktCount - pktCountLast;
    pktCountLast = pktCount;
  }

  if (now - lastOled >= 200) {
    lastOled = now;
    drawOLED();
  }

  // keep press sequencer alive
  serviceUI();
  gseq.update();

  WiFiClient client = server.available();
  if (!client) {
    delay(1);
    return;
  }

  client.setNoDelay(true);
  guiConnected = true;
  drawOLED();

  while (client.connected()) {
    serviceUI();
    gseq.update();

    if (!client.available()) {
      delay(1);
      continue;
    }

    String data = client.readStringUntil('\n');
    data.trim();
    if (data.length() == 0) continue;

    // stats
    lastCmd = data;
    pktCount++;
    lastPktMs = millis();

    // gestures
    handleGestureCommand(data);

    // arms
    int gR = 0, gL = 0;
    if (parseRL(data, gR, gL)) {
      if (gL != 0) applyLeftGesture(gL);
      if (gR != 0) applyRightGesture(gR);
    }
  }

  client.stop();
  guiConnected = false;
  drawOLED();
}