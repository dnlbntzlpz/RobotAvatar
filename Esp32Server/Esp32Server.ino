#include <WiFi.h>
#include <ESP32Servo.h>

// Wi-Fi / Server settings
#include "secret.h"     // define WIFI_SSID, WIFI_PASS, SERVER_HOST, SERVER_PORT

// ================================================================
// WiFi / TCP
// ================================================================
static const char* ssid     = WIFI_SSID;
static const char* password = WIFI_PASS;

static const uint16_t SERVER_PORT = 12345;
WiFiServer server(SERVER_PORT);

// ================================================================
// Servos / Pins
// ================================================================
Servo servo1, servo2, servo3, servo4, servo5, servo6;

// Pins (keep your current mapping)
static const int PIN_S1 = 3;    // Left arm top
static const int PIN_S2 = 4;    // Left arm bottom
static const int PIN_S3 = 21;   // Right arm top
static const int PIN_S4 = 20;   // Right arm bottom
static const int PIN_S5 = 10;   // Gesture servo 5
static const int PIN_S6 = 5;    // Gesture servo 6

// ================================================================
// Pose presets (easy to tune)
// ================================================================
static const int L_CENTER_1 = 90,  L_CENTER_2 = 90;
static const int R_CENTER_3 = 90,  R_CENTER_4 = 90;

// Left arm presets (L1..L5)
static const int L1_A = 90,  L1_B = 90;
static const int L2_A = 65,  L2_B = 55;
static const int L3_A = 140, L3_B = 40;
static const int L4_A = 40,  L4_B = 140;
static const int L5_A = 135, L5_B = 115;

// Right arm presets (R1..R5)
static const int R1_A = 90,  R1_B = 90;
static const int R2_A = 125, R2_B = 125;
static const int R3_A = 160, R3_B = 30;
static const int R4_A = 30,  R4_B = 160;
static const int R5_A = 65,  R5_B = 65;

// Gesture “home” (release / neutral)
static const int G_HOME_5 = 90;
static const int G_HOME_6 = 150;

// Gesture A “press”
static const int G_A_5 = 70;
static const int G_A_6 = 180;

// Gesture B “press”
static const int G_B_5 = 110;
static const int G_B_6 = 180;

// How long to hold a “press” before releasing (ms)
static const uint32_t GESTURE_PRESS_MS = 1000; // tune 120–250

// ================================================================
// Helpers: safe write
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
  servo5.write(clampDeg(s5));
  servo6.write(clampDeg(s6));
}


// ================================================================
// Non-blocking gesture sequencer
// (so we NEVER delay() and block WiFi)
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
        // Release to home
        moveGesture(G_HOME_5, G_HOME_6);
        st = GestureSeqState::IDLE;
      }
    }
  }

  bool busy() const { return st != GestureSeqState::IDLE; }
};

GestureSequencer gseq;

// ================================================================
// Command parsing
// ================================================================
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
// Apply arm gestures
// ================================================================
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


// ================================================================
// Gesture commands A,A and B,B
// - A,A: momentary press (every time command is A,A)
// - B,B: “press on both edges” (R1,L1->B,B and B,B->R1,L1)
// ================================================================
void handleGestureCommand(const String& cmd) {
  static bool lastB = false;

  const bool isA = (cmd == "A,A");
  const bool isB = (cmd == "B,B");

  // If a press sequence is currently running, ignore new presses
  // (prevents spam if GUI sends same command repeatedly)
  if (gseq.busy()) {
    lastB = isB;
    return;
  }

  // A: press each time we see A,A
  if (isA) {
    gseq.startPress(G_A_5, G_A_6);
    return;
  }

  // B: press on BOTH edges (enter/exit)
  if (isB != lastB) {
    gseq.startPress(G_B_5, G_B_6);
  }

  lastB = isB;
}

// ================================================================
// Setup / WiFi
// ================================================================
void setup() {
  Serial.begin(115200);
  delay(200);

  servo1.attach(PIN_S1);
  servo2.attach(PIN_S2);
  servo3.attach(PIN_S3);
  servo4.attach(PIN_S4);
  servo5.attach(PIN_S5);
  servo6.attach(PIN_S6);

  // Initial pose
  moveLeftArm(L_CENTER_1, L_CENTER_2);
  moveRightArm(R_CENTER_3, R_CENTER_4);
  moveGesture(G_HOME_5, G_HOME_6);

  WiFi.mode(WIFI_STA);
  WiFi.disconnect(true);
  delay(150);

  WiFi.begin(ssid, password);
  Serial.print("Connecting WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    Serial.print(".");
    delay(250);
  }
  Serial.println("\n✅ WiFi connected");
  Serial.print("IP: ");
  Serial.println(WiFi.localIP());

  server.begin();
  Serial.printf("✅ TCP server started on port %u\n", SERVER_PORT);
}

// ================================================================
// Main loop
// ================================================================
void loop() {
  WiFiClient client = server.available();
  if (!client) {
    // even without client, keep gesture sequencer alive
    gseq.update();
    delay(1);
    return;
  }

  client.setNoDelay(true);
  Serial.println("💻 Client connected");

  while (client.connected()) {
    // Always update sequencer (non-blocking press/release)
    gseq.update();

    if (!client.available()) {
      delay(1);
      continue;
    }

    String data = client.readStringUntil('\n');
    data.trim();
    if (data.length() == 0) continue;

    Serial.print("📩 ");
    Serial.println(data);

    // 1) Handle A,A / B,B gesture presses
    handleGestureCommand(data);

    // 2) Handle R#,L# locomotion / arms
    int gR = 0, gL = 0;
    if (parseRL(data, gR, gL)) {
      // ignore 0 = "no change" if you’re using that
      if (gL != 0) applyLeftGesture(gL);
      if (gR != 0) applyRightGesture(gR);
    }
  }

  client.stop();
  Serial.println("❌ Client disconnected");
}