#include <Servo.h>

// Pin Definitions
#define TRIGGER_PIN 2
#define ECHO_PIN 3
#define RED_LED_PIN 4
#define BLUE_LED_PIN 5
#define SERVO_PIN 6
#define BUZZER_PIN 12
#define GATE_CLOSED_POS 0
#define GATE_OPEN_POS 90

// Alert Types
enum AlertType
{
  NONE,
  PAYMENT_PENDING,
  TAMPERING
};

// Global Variables for Alerts
AlertType currentAlert = NONE;
unsigned long alertStartTime = 0;
unsigned long lastBlinkTime = 0;
unsigned long lastBeepTime = 0;

// Alert Timings
#define BLINK_INTERVAL_PAYMENT 300
#define BEEP_INTERVAL_PAYMENT 600
#define BEEP_DURATION_PAYMENT 150
#define BLINK_INTERVAL_TAMPER 150
#define BEEP_INTERVAL_TAMPER 300
#define BEEP_DURATION_TAMPER 100

// Distance Sensor Variables
unsigned long lastDistanceSendTime = 0;
#define DISTANCE_SEND_INTERVAL 200

Servo barrierServo;
bool isGateOpen = false;

// --- Function Prototypes ---
// Declare functions
void startAlert(AlertType type);
void stopAlertAction();
void openGateAction();
void closeGateAction();
void handleAlerts();
float getDistanceCm();
void sendDistanceData();
// --- End Function Prototypes ---

void setup()
{
  Serial.begin(9600);
  pinMode(TRIGGER_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(RED_LED_PIN, OUTPUT);
  pinMode(BLUE_LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);

  barrierServo.attach(SERVO_PIN);
  closeGateAction();             // Ensure gate is closed and lights are set correctly at startup
  digitalWrite(BUZZER_PIN, LOW); // Ensure buzzer is off at startup

  Serial.println("MSG:Gate Controller Ready.");
  Serial.println("MSG:Commands: '0'-Close, '1'-Open, '2'-PaymentAlert, '3'-TamperAlert, 'S'-StopAlert");
}

void loop()
{
  handleSerialCommands();
  handleAlerts();
  sendDistanceData();
}

void handleSerialCommands()
{
  if (Serial.available() > 0)
  {
    char cmd = Serial.read();
    Serial.print("MSG:Received command: ");
    Serial.println(cmd);

    switch (cmd)
    {
    case '0':
      stopAlertAction(); // Stop any ongoing alert
      closeGateAction();
      break;
    case '1':
      stopAlertAction(); // Stop any ongoing alert
      openGateAction();
      break;
    case '2':
      startAlert(PAYMENT_PENDING); // Call startAlert
      break;
    case '3':
      startAlert(TAMPERING); // Call startAlert
      break;
    case 'S':
      stopAlertAction();
      // Restore LED state based on gate position after stopping alert
      if (isGateOpen)
      {
        digitalWrite(BLUE_LED_PIN, HIGH);
        digitalWrite(RED_LED_PIN, LOW);
      }
      else
      {
        digitalWrite(RED_LED_PIN, HIGH);
        digitalWrite(BLUE_LED_PIN, LOW);
      }
      break;
    default:
      Serial.println("MSG:Unknown command.");
      break;
    }
  }
}

void openGateAction()
{
  barrierServo.write(GATE_OPEN_POS);
  isGateOpen = true;
  // Only change LEDs if no alert is active
  if (currentAlert == NONE)
  {
    digitalWrite(BLUE_LED_PIN, HIGH);
    digitalWrite(RED_LED_PIN, LOW);
    tone(BUZZER_PIN, 3000); // Try 3000 Hz
    delay(1000);
    noTone(BUZZER_PIN);
    delay(1000);
  }
  Serial.println("MSG:Gate Opened");
}

void closeGateAction()
{
  barrierServo.write(GATE_CLOSED_POS);
  isGateOpen = false;
  // Only change LEDs if no alert is active
  if (currentAlert == NONE)
  {
    digitalWrite(RED_LED_PIN, HIGH);
    digitalWrite(BLUE_LED_PIN, LOW);
    tone(BUZZER_PIN, 3000); // Try 3000 Hz
    delay(1000);
    noTone(BUZZER_PIN);
    delay(1000);
  }
  
  Serial.println("MSG:Gate Closed");
}

// Function to start an alert
void startAlert(AlertType type)
{
  // Ensure the buzzer is off before starting a new pattern
  digitalWrite(BUZZER_PIN, LOW);
  currentAlert = type;
  alertStartTime = millis();
  lastBlinkTime = millis();
  lastBeepTime = millis();

  // Turn off default LEDs and let handleAlerts control them for the alert
  digitalWrite(RED_LED_PIN, LOW);
  digitalWrite(BLUE_LED_PIN, LOW);

  Serial.print("MSG:ALERT STARTED: ");
  if (type == PAYMENT_PENDING)
    Serial.println("Payment Pending");
  if (type == TAMPERING)
    Serial.println("Tampering Detected");
}

void stopAlertAction()
{
  if (currentAlert != NONE)
  {
    currentAlert = NONE;
    digitalWrite(BUZZER_PIN, LOW); // Ensure buzzer is off
    // Re-apply correct LED state based on gate position
    if (isGateOpen)
    {
      digitalWrite(BLUE_LED_PIN, HIGH);
      digitalWrite(RED_LED_PIN, LOW);
    }
    else
    {
      digitalWrite(RED_LED_PIN, HIGH);
      digitalWrite(BLUE_LED_PIN, LOW);
    }
    Serial.println("MSG:Alert Stopped.");
  }
}

void handleAlerts()
{
  if (currentAlert == NONE)
    return; // No active alert, do nothing

  unsigned long currentTime = millis();

  // Handle LED blinking and buzzer for PAYMENT_PENDING alert
  if (currentAlert == PAYMENT_PENDING)
  {
    // LED blinking
    if (currentTime - lastBlinkTime >= BLINK_INTERVAL_PAYMENT)
    {
      lastBlinkTime = currentTime;
      digitalWrite(RED_LED_PIN, !digitalRead(RED_LED_PIN)); // Toggle red LED
      digitalWrite(BLUE_LED_PIN, LOW);                      // Ensure blue LED is off during this alert
    }

    // Buzzer beeping pattern
    if (currentTime - lastBeepTime >= BEEP_INTERVAL_PAYMENT)
    {
      lastBeepTime = currentTime;
      tone(BUZZER_PIN, 3000); // Play a tone (e.g., 1000 Hz)
      // The `if (digitalRead(BUZZER_PIN) == HIGH && ...)` block below will turn it off after BEEP_DURATION_PAYMENT
    }
    // Turn off buzzer after duration
    if (digitalRead(BUZZER_PIN) == HIGH && (currentTime - lastBeepTime >= BEEP_DURATION_PAYMENT))
    {
      noTone(BUZZER_PIN); // Stop the tone
    }
  }
  // Handle LED blinking and buzzer for TAMPERING alert
  else if (currentAlert == TAMPERING)
  {
    // LED blinking
    if (currentTime - lastBlinkTime >= BLINK_INTERVAL_TAMPER)
    {
      lastBlinkTime = currentTime;
      digitalWrite(RED_LED_PIN, !digitalRead(RED_LED_PIN)); // Toggle red LED
      digitalWrite(BLUE_LED_PIN, LOW);                      // Ensure blue LED is off during this alert
    }

    // Buzzer beeping pattern
    if (currentTime - lastBeepTime >= BEEP_INTERVAL_TAMPER)
    {
      lastBeepTime = currentTime;
      tone(BUZZER_PIN, 2000); // Play a different tone (e.g., 2000 Hz for warning)
    }
    // Turn off buzzer after duration
    if (digitalRead(BUZZER_PIN) == HIGH && (currentTime - lastBeepTime >= BEEP_DURATION_TAMPER))
    {
      noTone(BUZZER_PIN); // Stop the tone
    }
  }
}

float getDistanceCm()
{
  digitalWrite(TRIGGER_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIGGER_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIGGER_PIN, LOW);

  // Added a timeout to pulseIn to prevent indefinite blocking if no echo is received
  long duration = pulseIn(ECHO_PIN, HIGH, 25000); // 25000 microseconds = 25ms timeout (approx 4.3 meters)

  if (duration == 0)
  {
    return 999.99; // Return a value indicating out of range or no detection
  }
  float distance_cm = (duration * 0.0343) / 2.0;
  return distance_cm;
}

void sendDistanceData()
{
  if (millis() - lastDistanceSendTime >= DISTANCE_SEND_INTERVAL)
  {
    lastDistanceSendTime = millis();
    float distance = getDistanceCm();
    Serial.print("DIST:");
    Serial.println(distance, 2); // Print distance with 2 decimal places
  }
}
