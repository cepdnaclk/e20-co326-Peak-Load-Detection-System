#include <Arduino.h>

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
unsigned long relayTripTime = 0;
unsigned long lastPrintTime = 0;
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
  if      (isPeak)                              digitalWrite(LED_RED,    HIGH);
  else if (powerW > PEAK_THRESHOLD_W * 0.75f)  digitalWrite(LED_YELLOW, HIGH);
  else                                          digitalWrite(LED_GREEN,  HIGH);
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
void handleSerial() {
  if (!Serial.available()) return;

  char cmd = toupper(Serial.read());

  switch (cmd) {
    case 'A':
      demoMode   = 0;
      demoOffset = 0.0f;
      winIdx = 0; winCount = 0;  // Reset window for clean auto detection
      Serial.println(">> AUTO MODE — using real ACS712 sensor readings");
      break;

    case 'N':
      demoMode   = 1;
      demoOffset = 0.0f;
      Serial.println(">> NORMAL MODE — forcing green LED, relay ON");
      setRelay(true, "Demo: normal mode");
      break;

    case 'W':
      demoMode   = 2;
      demoOffset = PEAK_THRESHOLD_W * 0.85f;  // just below threshold
      Serial.println(">> WARNING MODE — forcing yellow LED");
      break;

    case 'P':
      demoMode   = 3;
      demoOffset = PEAK_THRESHOLD_W * 2.0f;   // well above threshold
      Serial.println(">> PEAK MODE — forcing peak detection + relay trip + red LED");
      break;

    case 'R':
      demoMode   = 0;
      demoOffset = 0.0f;
      setRelay(true, "Manual restore");
      relayTripTime = 0;
      winIdx = 0; winCount = 0;
      Serial.println(">> RELAY RESTORED — back to auto mode");
      break;

    case 'M':
      printMenu();
      break;

    default:
      break;
  }
}

// ============================================================
//  SETUP
// ============================================================
void setup() {
  Serial.begin(115200);

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
  delay(1000);
  setRelay(true, "Startup");

  Serial.println("============================================");
  Serial.println("  Peak Load Detection System — Group 25");
  Serial.println("  DEMO MODE ENABLED");
  Serial.println("============================================");
  printMenu();
}

// ============================================================
//  LOOP
// ============================================================
void loop() {
  handleSerial();

  unsigned long now = millis();
  if (now - lastPrintTime < 2000) return;
  lastPrintTime = now;

  // Read real sensor
  float current = readCurrentAmps();
  float powerW  = calcPower(current);

  // ---- BUTTON RAMP ----
  bool buttonHeld = (digitalRead(BUTTON_PIN) == LOW);
  if (buttonHeld) {
    buttonRampW += BUTTON_RAMP_STEP;
    if (buttonRampW > BUTTON_RAMP_MAX) buttonRampW = BUTTON_RAMP_MAX;
  } else {
    buttonRampW -= BUTTON_DECAY_STEP;
    if (buttonRampW < 0.0f) buttonRampW = 0.0f;
  }
  powerW += buttonRampW;

  float displayPower = powerW + demoOffset;
  bool  isPeak  = false;
  String status;

  if (demoMode == 1) {
    isPeak = false;
    status = "NORMAL (demo)";
    updateLEDs(0.0f, false);

  } else if (demoMode == 2) {
    isPeak = false;
    status = "WARNING (demo)";
    digitalWrite(LED_GREEN,  LOW);
    digitalWrite(LED_YELLOW, HIGH);
    digitalWrite(LED_RED,    LOW);

  } else if (demoMode == 3) {
    isPeak = true;
    status = "PEAK DETECTED (demo)";
    updateLEDs(displayPower, true);
    if (relayOn) {
      setRelay(false, "Demo: forced peak");
      relayTripTime = now;
    }

  } else {
    // AUTO mode — real sensor + button
    status = detectPeak(displayPower, isPeak);
    updateLEDs(displayPower, isPeak);

    if (isPeak && relayOn) {
      setRelay(false, "Peak detected — " + status);
      relayTripTime = now;
    }
    if (!relayOn && !isPeak) {
      if (relayTripTime > 0 && (now - relayTripTime > RELAY_RESTORE_MS)) {
        setRelay(true, "Auto-restore after peak cleared");
        relayTripTime = 0;
      }
    }
    if (isPeak) relayTripTime = now;
  }

  // Print readings
  Serial.println("--------------------------------------------");
  Serial.print  ("  Button  : ");
  Serial.println(buttonHeld ? "HELD" : "open");
  Serial.print  ("  Ramp    : "); Serial.print(buttonRampW, 2); Serial.println(" W added");
  Serial.print  ("  Power   : "); Serial.print(displayPower, 3); Serial.println(" W");
  Serial.print  ("  Current : "); Serial.print(current, 3);      Serial.println(" A");
  Serial.print  ("  Status  : "); Serial.println(status);
  Serial.print  ("  Relay   : "); Serial.println(relayOn ? "ON  (fan running)" : "OFF (fan stopped)");
  Serial.println("--------------------------------------------");
  
  // Parseable JSON output for Python reader
  Serial.print("[POWER] Power: ");
  Serial.print(displayPower, 2);
  Serial.print(" W | State: ");
  if (isPeak) {
    Serial.print("PEAK");
  } else if (displayPower > PEAK_THRESHOLD_W * 0.75f) {
    Serial.print("WARNING");
  } else {
    Serial.print("NORMAL");
  }
  Serial.print(" | Relay: ");
  Serial.println(relayOn ? "ON" : "OFF");
}