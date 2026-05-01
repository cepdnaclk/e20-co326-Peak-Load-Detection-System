// ============================================================
//  Peak Load Detection System — Group 25
//  ESP32 main.cpp  (WiFi + MQTT edition)
//
//  Hardware:
//    ACS712 5A  → GPIO34 (ADC)
//    Relay      → GPIO26 (active-LOW)
//    LED green  → GPIO15
//    LED yellow → GPIO16
//    LED red    → GPIO17
//    Button     → GPIO18 (INPUT_PULLUP)
//
//  MQTT topics:
//    Publish  → sensors/group25/peak/raw
//    Subscribe← commands/group25/peak/relay
// ============================================================

// ---- Increase PubSubClient packet buffer before including ----
#define MQTT_MAX_PACKET_SIZE 512

#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ---- WiFi Credentials ----
const char* WIFI_SSID     = "Dialog 4G 182";
const char* WIFI_PASSWORD = "2002@Ravindu";

// ---- MQTT Broker ----
const char* MQTT_BROKER = "broker.hivemq.com";
const int   MQTT_PORT   = 1883;
const char* CLIENT_ID   = "esp32-group25-peak";

// ---- MQTT Topics ----
const char* TOPIC_RAW   = "sensors/group25/peak/raw";
const char* TOPIC_RELAY = "commands/group25/peak/relay";

// ---- PINS ----
#define ACS712_PIN    34
#define RELAY_PIN     26
#define LED_GREEN     15    // D15
#define LED_YELLOW    16    // RX2
#define LED_RED       17    // TX2
#define BUTTON_PIN    18

// ---- ACS712 CONFIG ----
#define ACS712_SENSITIVITY  0.185f
#define ADC_RESOLUTION      4095.0f
#define ADC_VREF            3.3f
#define SUPPLY_VOLTAGE      5.0f
#define ADC_SAMPLES         100

// ---- DETECTION CONFIG ----
#define PEAK_THRESHOLD_W    1.5f
#define WINDOW_SIZE         50
#define ZSCORE_CUTOFF       2.5f
#define RELAY_RESTORE_MS    8000
#define BUTTON_RAMP_MAX     2.5f    // Max watts added at full press
#define BUTTON_RAMP_STEP    0.15f   // Watts added per loop cycle (every 2s)
#define BUTTON_DECAY_STEP   0.10f   // Watts removed per loop cycle on release

// ---- DEMO MODES ----
// 0 = Auto (sensor-driven)
// 1 = Force NORMAL
// 2 = Force WARNING
// 3 = Force PEAK
int demoMode = 0;
float demoOffset = 0.0f;   // extra power added in demo mode

// ---- GLOBALS ----
float   windowBuf[WINDOW_SIZE];
int     winIdx      = 0;
int     winCount    = 0;
bool    relayOn     = true;
unsigned long relayTripTime  = 0;
unsigned long lastPrintTime  = 0;
unsigned long lastMqttPub    = 0;
float   buttonRampW = 0.0f;   // current simulated load from button

// Latest sensor reading (shared between loop and MQTT publish)
float   lastCurrentA = 0.0f;
float   lastPowerW   = 0.0f;
bool    lastButtonHeld = false;

// ---- WiFi + MQTT clients ----
WiFiClient   wifiClient;
PubSubClient mqttClient(wifiClient);

// ============================================================
//  WiFi CONNECT
// ============================================================
void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.print("[WiFi] Connecting to ");
  Serial.print(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries < 30) {
    delay(500);
    Serial.print(".");
    tries++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println();
    Serial.print("[WiFi] Connected! IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println();
    Serial.println("[WiFi] Failed to connect — continuing without WiFi.");
  }
}

// ============================================================
//  MQTT CALLBACK (incoming relay commands from Python)
// ============================================================
void mqttCallback(char* topic, byte* payload, unsigned int length);

// Forward declare setRelay so mqttCallback can call it
void setRelay(bool on, String reason);

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  // Build null-terminated string from payload
  char msg[64] = {0};
  unsigned int copyLen = (length < sizeof(msg) - 1) ? length : sizeof(msg) - 1;
  memcpy(msg, payload, copyLen);
  Serial.print("[MQTT] Message on ");
  Serial.print(topic);
  Serial.print(": ");
  Serial.println(msg);

  if (strcmp(topic, TOPIC_RELAY) == 0) {
    if (strcmp(msg, "ON") == 0) {
      setRelay(true, "MQTT command");
      relayTripTime = 0;
      // ---- Fix: update LEDs immediately, not waiting for next loop tick ----
      updateLEDs(lastPowerW, false);   // relay restored → green
    } else if (strcmp(msg, "OFF") == 0) {
      setRelay(false, "MQTT command");
      relayTripTime = millis();
      // ---- Fix: update LEDs immediately, not waiting for next loop tick ----
      updateLEDs(lastPowerW, true);    // relay tripped → red
    }
  }
}

// ============================================================
//  MQTT CONNECT
// ============================================================
void connectMQTT() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (mqttClient.connected()) return;

  Serial.print("[MQTT] Connecting to ");
  Serial.print(MQTT_BROKER);
  Serial.print(":");
  Serial.println(MQTT_PORT);

  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);

  int tries = 0;
  while (!mqttClient.connected() && tries < 5) {
    if (mqttClient.connect(CLIENT_ID)) {
      Serial.println("[MQTT] Connected!");
      mqttClient.subscribe(TOPIC_RELAY);
      Serial.print("[MQTT] Subscribed to: ");
      Serial.println(TOPIC_RELAY);
    } else {
      Serial.print("[MQTT] Failed (rc=");
      Serial.print(mqttClient.state());
      Serial.println(") retrying...");
      delay(2000);
      tries++;
    }
  }
}

// ============================================================
//  PUBLISH RAW SENSOR DATA
// ============================================================
void publishRawData(float powerW, float currentA, bool buttonHeld) {
  if (!mqttClient.connected()) return;

  StaticJsonDocument<256> doc;
  doc["timestamp"]   = String(millis());
  doc["power_w"]     = serialized(String(powerW, 3));
  doc["current_a"]   = serialized(String(currentA, 4));
  doc["voltage_v"]   = 5.0;
  doc["button_held"] = buttonHeld;
  doc["ramp_w"]      = serialized(String(buttonRampW, 3));
  doc["relay_on"]    = relayOn;
  doc["group"]       = "group25";

  char buf[256];
  size_t n = serializeJson(doc, buf);
  bool ok = mqttClient.publish(TOPIC_RAW, buf, n);

  Serial.print("[MQTT] Published to ");
  Serial.print(TOPIC_RAW);
  Serial.print(" (");
  Serial.print(ok ? "OK" : "FAIL");
  Serial.println(")");
  Serial.print("       Payload: ");
  Serial.println(buf);
}

// ============================================================
//  READ SENSOR
// ============================================================
float readCurrentAmps() {
  long sum = 0;
  for (int i = 0; i < ADC_SAMPLES; i++) {
    sum += analogRead(ACS712_PIN);
    delayMicroseconds(200);
  }
  float avgADC  = (float)sum / ADC_SAMPLES;
  float voltage = (avgADC / ADC_RESOLUTION) * ADC_VREF;
  float mid     = 2.5f;
  float current = (voltage - mid) / ACS712_SENSITIVITY;
  return fabs(current);
}

float calcPower(float amps) {
  return SUPPLY_VOLTAGE * amps;
}

// ============================================================
//  Z-SCORE DETECTION
// ============================================================
bool zscoreDetect(float value) {
  windowBuf[winIdx % WINDOW_SIZE] = value;
  winIdx++;
  winCount = min((int)winIdx, WINDOW_SIZE);
  if (winCount < 10) return false;
  float sum = 0;
  for (int i = 0; i < winCount; i++) sum += windowBuf[i];
  float mean = sum / winCount;
  float sqSum = 0;
  for (int i = 0; i < winCount; i++) sqSum += pow(windowBuf[i] - mean, 2);
  float sd = sqrt(sqSum / winCount);
  if (sd < 0.0001f) return false;
  return ((value - mean) / sd) > ZSCORE_CUTOFF;
}

// ============================================================
//  COMBINED DETECTOR
// ============================================================
String detectPeak(float powerW, bool &isPeak) {
  bool thresh = (powerW > PEAK_THRESHOLD_W);
  bool zs     = zscoreDetect(powerW);
  isPeak = thresh || zs;
  if (thresh && zs) return "THRESHOLD + Z-SCORE";
  if (thresh)       return "THRESHOLD";
  if (zs)           return "Z-SCORE";
  return "NORMAL";
}

// ============================================================
//  LED UPDATE
// ============================================================
void updateLEDs(float powerW, bool isPeak) {
  digitalWrite(LED_GREEN,  LOW);
  digitalWrite(LED_YELLOW, LOW);
  digitalWrite(LED_RED,    LOW);
  if      (isPeak)                               digitalWrite(LED_RED,    HIGH);
  else if (powerW > PEAK_THRESHOLD_W * 0.867f)  digitalWrite(LED_YELLOW, HIGH);  // >1.3W
  else                                           digitalWrite(LED_GREEN,  HIGH);
}

// ============================================================
//  RELAY CONTROL
// ============================================================
void setRelay(bool on, String reason) {
  relayOn = on;
  digitalWrite(RELAY_PIN, on ? HIGH : LOW);   // Active-LOW relay
  Serial.println("==========================================");
  Serial.print  ("  RELAY : ");
  Serial.println(on ? "ON  — Load Active ✓" : "OFF — Load Cut ✗");
  Serial.print  ("  Reason: "); Serial.println(reason);
  Serial.println("==========================================");
}

// ============================================================
//  PRINT MENU
// ============================================================
void printMenu() {
  Serial.println();
  Serial.println("========= DEMO CONTROL MENU =========");
  Serial.println("  A = AUTO mode  (real sensor)");
  Serial.println("  N = NORMAL     (force green LED)");
  Serial.println("  W = WARNING    (force yellow LED)");
  Serial.println("  P = PEAK       (force peak + relay trip)");
  Serial.println("  R = RELAY ON   (manually restore relay)");
  Serial.println("  M = Show this menu again");
  Serial.println("=====================================");
  Serial.println();
}

// ============================================================
//  HANDLE SERIAL COMMANDS
// ============================================================
void handleSerialCommands() {
  if (!Serial.available()) return;

  String cmd = Serial.readStringUntil('\n');
  cmd.trim();
  cmd.toUpperCase();

  // Demo mode commands
  if (cmd == "AUTO" || cmd == "A") {
    demoMode   = 0;
    demoOffset = 0.0f;
    winIdx = 0; winCount = 0;
    Serial.println(">> AUTO MODE — using real ACS712 sensor readings");
  }
  else if (cmd == "NORMAL" || cmd == "N") {
    demoMode   = 1;
    demoOffset = 0.0f;
    Serial.println(">> NORMAL MODE — forcing green LED, relay ON");
  }
  else if (cmd == "WARNING" || cmd == "W") {
    demoMode   = 2;
    demoOffset = PEAK_THRESHOLD_W * 0.85f;
    Serial.println(">> WARNING MODE — forcing yellow LED");
  }
  else if (cmd == "PEAK" || cmd == "P") {
    demoMode   = 3;
    demoOffset = PEAK_THRESHOLD_W * 2.0f;
    Serial.println(">> PEAK MODE — forcing peak detection + relay trip + red LED");
  }

  // Legacy serial relay commands (kept for backward compat)
  else if (cmd == "RELAY_ON") {
    if (!relayOn) {
      setRelay(true, "Serial command");
      relayTripTime = 0;
    }
  }
  else if (cmd == "RELAY_OFF") {
    if (relayOn) {
      setRelay(false, "Serial command");
      relayTripTime = millis();
    }
  }

  // Menu
  else if (cmd == "MENU" || cmd == "M" || cmd == "HELP") {
    printMenu();
  }
}

// ============================================================
//  SETUP
// ============================================================
void setup() {
  Serial.begin(115200);

  // Relay: set safe state before configuring pin
  digitalWrite(RELAY_PIN, HIGH);   // OFF before pinMode (active-low)
  pinMode(RELAY_PIN,  OUTPUT);
  digitalWrite(RELAY_PIN, HIGH);

  pinMode(LED_GREEN,  OUTPUT);
  pinMode(LED_YELLOW, OUTPUT);
  pinMode(LED_RED,    OUTPUT);
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);

  digitalWrite(LED_GREEN, HIGH);   // Start green
  delay(500);
  setRelay(true, "Startup");

  Serial.println("============================================");
  Serial.println("  Peak Load Detection System — Group 25");
  Serial.println("  WiFi + MQTT Edition");
  Serial.println("============================================");
  printMenu();

  // WiFi + MQTT init
  connectWiFi();
  connectMQTT();
}

// ============================================================
//  LOOP
// ============================================================
void loop() {
  // ---- Handle WiFi / MQTT reconnection ----
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }
  if (!mqttClient.connected()) {
    connectMQTT();
  }
  mqttClient.loop();   // Process incoming MQTT messages

  // ---- Handle serial commands ----
  handleSerialCommands();

  // ---- 2-second publish cycle ----
  unsigned long now = millis();
  if (now - lastPrintTime < 2000) return;
  lastPrintTime = now;

  // Read real sensor
  float current = readCurrentAmps();
  float powerW  = calcPower(current);

  // ---- BUTTON RAMP (optional simulation) ----
  bool buttonHeld = (digitalRead(BUTTON_PIN) == LOW);
  if (buttonHeld) {
    buttonRampW += BUTTON_RAMP_STEP;
    if (buttonRampW > BUTTON_RAMP_MAX) buttonRampW = BUTTON_RAMP_MAX;
  } else {
    buttonRampW -= BUTTON_DECAY_STEP;
    if (buttonRampW < 0.0f) buttonRampW = 0.0f;
  }
  powerW += buttonRampW;

  // ---- Apply demo mode offset ----
  powerW += demoOffset;

  // ---- Update LEDs based on relay + power level ----
  if (!relayOn) {
    digitalWrite(LED_GREEN,  LOW);
    digitalWrite(LED_YELLOW, LOW);
    digitalWrite(LED_RED,    HIGH);
  }
  else if (powerW > PEAK_THRESHOLD_W * 0.867f) {
    digitalWrite(LED_GREEN,  LOW);
    digitalWrite(LED_YELLOW, HIGH);
    digitalWrite(LED_RED,    LOW);
  }
  else {
    digitalWrite(LED_GREEN,  HIGH);
    digitalWrite(LED_YELLOW, LOW);
    digitalWrite(LED_RED,    LOW);
  }

  // ---- Serial debug output (preserved) ----
  Serial.print("[SENSOR] Current: ");
  Serial.print(current, 3);
  Serial.print(" A | Power: ");
  Serial.print(powerW, 2);
  Serial.print(" W | Button: ");
  Serial.print(buttonHeld ? "HELD" : "free");
  Serial.print(" | Ramp: ");
  Serial.print(buttonRampW, 2);
  Serial.print(" W | Relay: ");
  Serial.println(relayOn ? "ON" : "OFF");

  // ---- Publish raw sensor data via MQTT ----
  publishRawData(powerW, current, buttonHeld);

  // ---- Cache latest values ----
  lastCurrentA   = current;
  lastPowerW     = powerW;
  lastButtonHeld = buttonHeld;
}