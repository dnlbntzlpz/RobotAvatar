#include <WiFi.h>
#include <ESP32Servo.h>

// Wi-Fi / Server settings
#include "secret.h"     // define WIFI_SSID, WIFI_PASS, SERVER_HOST, SERVER_PORT

//Function Declaration
void handleGestureCommand(const String& cmd);

// ================================================================
// ⚙️ CONFIGURACIÓN WiFi
// ================================================================
const char* ssid = WIFI_SSID;
const char* password = WIFI_PASS;

WiFiServer server(12345);

// ================================================================
// ⚙️ CONFIGURACIÓN DE SERVOS
// ================================================================
Servo servo1, servo2, servo3, servo4, servo5, servo6;

// Pines asignados
const int pin1 = 13;  // Left Joystick - Top Servo
const int pin2 = 12;  // Left Joystick - Bottom Servo
const int pin3 = 25;  // Right Joystick - Top Servo
const int pin4 = 26;  // Right Joystick - Bottom Servo
const int pin5 = 27;  // Right Action Button Servo
const int pin6 = 14;  // Left Select Button Servo

// Servo Homes:

// ================================================================
// 🦾 FUNCIONES DE MOVIMIENTO
// ================================================================
void moverBrazoIzquierdo(int serv1, int serv2) {
  servo1.write(constrain(serv1, 0, 180));
  servo2.write(constrain(serv2, 0, 180));
  Serial.printf("Brazo IZQUIERDO → [%d, %d]\n", serv1, serv2);
}

void moverBrazoDerecho(int serv3, int serv4) {
  servo3.write(constrain(serv3, 0, 180));
  servo4.write(constrain(serv4, 0, 180));
  Serial.printf("Brazo DERECHO → [%d, %d]\n", serv3, serv4);
}

void moverGesto(int serv5, int serv6) { 
  servo5.write(constrain(serv5, 0, 180));
  delay(500);
  servo6.write(constrain(serv6, 0, 180));
  Serial.printf("Gesto → [%d, %d]\n", serv5, serv6);
}

// ================================================================
// 🔧 SETUP
// ================================================================
void setup() {
  Serial.begin(115200);
  delay(500);

  servo1.attach(pin1);
  servo2.attach(pin2);
  servo3.attach(pin3);
  servo4.attach(pin4);
  servo5.attach(pin5);
  servo6.attach(pin6);

  // Posición inicial
  moverBrazoIzquierdo(90, 90);
  moverBrazoDerecho(90, 90);
  moverGesto(90, 150);

  // Conexión WiFi
  WiFi.begin(ssid, password);
  Serial.print("Conectando a WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    Serial.print(".");
  }

  Serial.println("\n✅ Conectado a WiFi");
  Serial.print("IP del ESP32: ");
  Serial.println(WiFi.localIP());

  server.begin();
  Serial.println("Servidor TCP iniciado ✅");
}

// ================================================================
// 🔁 LOOP PRINCIPAL
// ================================================================
void loop() {
  WiFiClient client = server.available();

  if (client) {
    Serial.println("💻 Cliente conectado");

    while (client.connected()) {
      if (client.available()) {
        String data = client.readStringUntil('\n');
        data.trim();
        if (data.length() == 0) continue;

        Serial.print("📩 Datos recibidos: ");
        Serial.println(data);

        // Handle gesture servos FIRST
        handleGestureCommand(data);

        // Esperamos formato "R#,L#"
        int commaIndex = data.indexOf(',');
        if (commaIndex == -1) {
          client.println("Error: formato inválido");
          continue;
        }

        String rightCmd = data.substring(0, commaIndex);
        String leftCmd  = data.substring(commaIndex + 1);

        // --- BRAZO IZQUIERDO (L1–L5) ---
        if (leftCmd.startsWith("L")) {
          int gestureL = leftCmd.substring(1).toInt();

          // Ignorar si es L0 (sin cambio)
          if (gestureL == 0) {
            continue;
          }

          switch (gestureL) {
            case 1: moverBrazoIzquierdo(90, 90); /* client.println("L1 OK Quieto"); */ break;
            case 2: moverBrazoIzquierdo(65, 55);    /* client.println("L2 OK Arriba"); */ break;
            case 3: moverBrazoIzquierdo(140, 40);  /* client.println("L3 OK Izquierda"); */ break;
            case 4: moverBrazoIzquierdo(40, 140);  /* client.println("L4 OK Derecha"); */ break;
            case 5: moverBrazoIzquierdo(135,115); /* client.println("L5 OK Atrás"); */ break;
            default: /* client.println("L Error gesto inválido"); */ break;
          }
        }

        // --- BRAZO DERECHO (R1–R5) ---
        if (rightCmd.startsWith("R")) {
          int gestureR = rightCmd.substring(1).toInt();

          // Ignorar si es R0 (sin cambio)
          if (gestureR == 0) {
            continue;
          }

          switch (gestureR) {
            case 1: moverBrazoDerecho(90,90);   /* client.println("R1 OK Centro"); */ break;
            case 2: moverBrazoDerecho(125,125);   /* client.println("R2 OK Arriba"); */ break;
            case 3: moverBrazoDerecho(160,30);     /* client.println("R3 OK Izquierda"); */ break;
            case 4: moverBrazoDerecho(30,160);    /* client.println("R4 OK Derecha"); */ break;
            case 5: moverBrazoDerecho(65,65);       /* client.println("R5 OK Abajo"); */ break;
            default: /* client.println("R Error gesto inválido"); */ break;
          }
        }
      }
    }

    client.stop();
    Serial.println("❌ Cliente desconectado");
  }
}

//FUNCTIONS:
void handleGestureCommand(const String& cmd) {
  if (cmd == "A,A") {
    // Gesture A
    moverGesto(80, 180);
  }
  else if (cmd == "B,B") {
    // Gesture B
    moverGesto(100, 180);
  }
  else {
    // No gesture active → return to neutral
    moverGesto(90, 150);
  }
}