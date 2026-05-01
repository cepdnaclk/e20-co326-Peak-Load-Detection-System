// ============================================================
//  Peak Load Detection System — Group 25
//  ESP32 main.cpp  (Serial-Only Edition — No WiFi)
//
//  The ESP32 acts as a local sensor node:
//    1. Reads ACS712 current sensor → calculates power
//    2. Push-button (GPIO18) simulates peak load via ramp
//    3. Local peak detection (threshold + Z-score) for
//       immediate LED and relay response
//    4. Outputs JSON over Serial for Python Edge AI to read
//
//  Hardware:
//    ACS712 5A  → GPIO34 (ADC)
//    Relay      → GPIO26 (active-HIGH)
//    LED green  → GPIO15
//    LED yellow → GPIO16
//    LED red    → GPIO17
//    Button     → GPIO18 (INPUT_PULLUP, active-LOW)
//
//  Serial output (one JSON line every 2 seconds):
//    {"power_w":1.87,"current_a":0.374,"voltage_v":5.0,
//     "relay_on":true,"button_held":false,"ramp_w":0.00,
//     "status":"NORMAL"}
// ============================================================

#include <Arduino.h>
#include <ArduinoJson.h>

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
#define PEAK_THRESHOLD_W    2.0f
#define WARNING_RATIO       0.75f     // 1.5W warning zone (2.0 * 0.75)
#define WINDOW_SIZE         50
#define ZSCORE_CUTOFF       2.5f
#define RELAY_RESTORE_MS    8000      // 8 seconds cooldown
#define BUTTON_RAMP_MAX     2.5f      // Max watts added — must exceed 2.0W peak threshold
#define BUTTON_RAMP_STEP    0.30f     // 0.30W per 2s = clear WARNING→PEAK progression
#define BUTTON_DECAY_STEP   0.15f     // Watts removed per loop cycle on release

// ---- GLOBALS ----
float   windowBuf[WINDOW_SIZE];
int     winIdx      = 0;
int     winCount    = 0;
bool    relayOn     = true;
bool    peakActive  = false;
unsigned long relayTripTime  = 0;
unsigned long lastCycleTime  = 0;
float   buttonRampW = 0.0f;   // current simulated load from button

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
//  LOCAL PEAK DETECTION (for immediate LED/relay)
// ============================================================
const char* detectPeakLocal(float powerW, bool &isPeak) {
  bool thresh = (powerW > PEAK_THRESHOLD_W);
  bool zs     = zscoreDetect(powerW);  // still run to keep the window warm

  // LOCAL relay/LED uses THRESHOLD ONLY — z-score alone should not trip hardware.
  // The Python Edge AI ensemble handles statistical detection for the dashboard.
  isPeak = thresh;

  if (thresh && zs) return "THRESHOLD + Z-SCORE";
  if (thresh)       return "THRESHOLD";
  if (zs)           return "Z-SCORE (soft)";
  return "NORMAL";
}

// ============================================================
//  LED UPDATE
// ============================================================
void updateLEDs(float powerW, bool isPeak) {
  digitalWrite(LED_GREEN,  LOW);
  digitalWrite(LED_YELLOW, LOW);
  digitalWrite(LED_RED,    LOW);

  if      (isPeak)                                    digitalWrite(LED_RED,    HIGH);
  else if (powerW > PEAK_THRESHOLD_W * WARNING_RATIO) digitalWrite(LED_YELLOW, HIGH);
  else                                                 digitalWrite(LED_GREEN,  HIGH);
}

// ============================================================
//  RELAY CONTROL
// ============================================================
void setRelay(bool on, const char* reason) {
  relayOn = on;
  digitalWrite(RELAY_PIN, on ? HIGH : LOW);
  Serial.println("==========================================");
  Serial.print  ("  RELAY : ");
  Serial.println(on ? "ON  -- Load Active" : "OFF -- Load Cut");
  Serial.print  ("  Reason: "); Serial.println(reason);
  Serial.println("==========================================");
}

// ============================================================
//  SERIAL JSON OUTPUT
// ============================================================
void publishSerialJSON(float powerW, float currentA, bool buttonHeld, const char* status) {
  StaticJsonDocument<256> doc;
  doc["power_w"]     = serialized(String(powerW, 3));
  doc["current_a"]   = serialized(String(currentA, 4));
  doc["voltage_v"]   = SUPPLY_VOLTAGE;
  doc["relay_on"]    = relayOn;
  doc["button_held"] = buttonHeld;
  doc["ramp_w"]      = serialized(String(buttonRampW, 3));
  doc["status"]      = status;

  // Print as single JSON line for Python to parse
  serializeJson(doc, Serial);
  Serial.println();  // newline terminates the JSON line
}

// ============================================================
//  HANDLE SERIAL COMMANDS (from Python or Serial Monitor)
// ============================================================
void handleSerialCommands() {
  if (!Serial.available()) return;

  String cmd = Serial.readStringUntil('\n');
  cmd.trim();
  cmd.toUpperCase();

  if (cmd == "RELAY_ON" || cmd == "R") {
    if (!relayOn) {
      setRelay(true, "AI: peak cleared");
      relayTripTime = 0;
      peakActive = false;
      // Restore green LED — AI says we're back to normal
      digitalWrite(LED_RED,    LOW);
      digitalWrite(LED_YELLOW, LOW);
      digitalWrite(LED_GREEN,  HIGH);
    }
  }
  else if (cmd == "RELAY_OFF") {
    if (relayOn) {
      setRelay(false, "AI: peak detected");
      relayTripTime = millis();
      peakActive = true;
      // Light red LED — AI detected a peak
      digitalWrite(LED_GREEN,  LOW);
      digitalWrite(LED_YELLOW, LOW);
      digitalWrite(LED_RED,    HIGH);
    }
  }
  else if (cmd == "STATUS" || cmd == "S") {
    Serial.print("[INFO] Relay: "); Serial.print(relayOn ? "ON" : "OFF");
    Serial.print(" | Peak: "); Serial.print(peakActive ? "YES" : "NO");
    Serial.print(" | Ramp: "); Serial.print(buttonRampW, 2);
    Serial.println(" W");
  }
}


// ============================================================
//  SETUP
// ============================================================
void setup() {
  Serial.begin(115200);

  // Relay: set safe state before configuring pin
  digitalWrite(RELAY_PIN, HIGH);   // ON at startup
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
  Serial.println("  Peak Load Detection System -- Group 25");
  Serial.println("  Serial-Only Mode (No WiFi)");
  Serial.println("  Push button to simulate peak load");
  Serial.println("============================================");
}

// ============================================================
//  LOOP
// ============================================================
void loop() {
  // ---- Handle serial commands ----
  handleSerialCommands();

  // ---- 2-second cycle ----
  unsigned long now = millis();
  if (now - lastCycleTime < 2000) return;
  lastCycleTime = now;

  // ---- Read real sensor ----
  float current = readCurrentAmps();
  float powerW  = calcPower(current);

  // ---- BUTTON RAMP (peak simulation) ----
  bool buttonHeld = (digitalRead(BUTTON_PIN) == LOW);
  if (buttonHeld) {
    buttonRampW += BUTTON_RAMP_STEP;
    if (buttonRampW > BUTTON_RAMP_MAX) buttonRampW = BUTTON_RAMP_MAX;
  } else {
    buttonRampW -= BUTTON_DECAY_STEP;
    if (buttonRampW < 0.0f) buttonRampW = 0.0f;
  }
  powerW += buttonRampW;

  // ---- Local peak detection (immediate LED/relay response) ----
  bool isPeak = false;
  const char* reason = detectPeakLocal(powerW, isPeak);

  // Determine status string
  const char* status;
  if (isPeak) {
    status = "PEAK";
  } else if (powerW > PEAK_THRESHOLD_W * WARNING_RATIO) {
    status = "WARNING";
  } else {
    status = "NORMAL";
  }

  // ---- Update LEDs ----
  updateLEDs(powerW, isPeak);

  // ---- Handle relay logic ----
  if (isPeak && !peakActive) {
    // New peak detected — trip relay
    peakActive = true;
    if (relayOn) {
      setRelay(false, reason);
      relayTripTime = now;
    }
  }
  else if (!isPeak && peakActive) {
    // Peak cleared — start cooldown timer
    peakActive = false;
    relayTripTime = now;
  }

  // ---- Auto-restore relay after cooldown ----
  if (!relayOn && !peakActive && relayTripTime > 0) {
    if (now - relayTripTime >= RELAY_RESTORE_MS) {
      setRelay(true, "Cooldown expired");
      relayTripTime = 0;
    }
  }

  // ---- Output JSON over Serial for Python Edge AI ----
  publishSerialJSON(powerW, current, buttonHeld, status);
}