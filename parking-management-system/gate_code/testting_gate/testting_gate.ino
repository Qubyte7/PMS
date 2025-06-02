// Pin Definitions (consistent with your gate_updated.ino)
#define RED_LED_PIN 4
#define BLUE_LED_PIN 5
#define BUZZER_PIN 12

void setup() {
  Serial.begin(9600); // Initialize serial communication for debugging
  pinMode(RED_LED_PIN, OUTPUT);
  pinMode(BLUE_LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);

  // Ensure everything is off at startup
  digitalWrite(RED_LED_PIN, LOW);
  digitalWrite(BLUE_LED_PIN, LOW);
  digitalWrite(BUZZER_PIN, LOW); // For passive buzzer, ensure no tone is playing
  noTone(BUZZER_PIN); // Explicitly stop any potential tone
  Serial.println("LED and Buzzer Test Sketch Ready.");
}

void loop() {
  Serial.println("--- Starting Test Sequence ---");

  // Test Red LED
  Serial.println("Testing Red LED (Pin 4) - ON");
  digitalWrite(RED_LED_PIN, HIGH);
  delay(1000); // Keep on for 1 second
  Serial.println("Testing Red LED (Pin 4) - OFF");
  digitalWrite(RED_LED_PIN, LOW);
  delay(500);

  // Test Blue LED
  Serial.println("Testing Blue LED (Pin 5) - ON");
  digitalWrite(BLUE_LED_PIN, HIGH);
  delay(1000); // Keep on for 1 second
  Serial.println("Testing Blue LED (Pin 5) - OFF");
  digitalWrite(BLUE_LED_PIN, LOW);
  delay(500);

  // Test Buzzer - Simple Beep (like gate opening)
  Serial.println("Testing Buzzer - Simple Beep (Pin 11)");
  tone(BUZZER_PIN, 2000); // Play 1000 Hz tone
  delay(300);            // For 300 milliseconds
  noTone(BUZZER_PIN);    // Stop tone
  delay(500);
  tone(BUZZER_PIN, 2000); // Play 1000 Hz tone again
  delay(300);
  noTone(BUZZER_PIN);
  delay(1000); // Pause before next test

  // Test Buzzer - Warning Pattern (like denied access)
  Serial.println("Testing Buzzer - Warning Pattern (Pin 11)");
  for (int i = 0; i < 4; i++) { // Four rapid, higher-pitched beeps
    tone(BUZZER_PIN, 2000); // Play 2000 Hz tone
    delay(150);
    noTone(BUZZER_PIN);
    delay(150);
  }
  delay(1000); // Pause before repeating sequence

  Serial.println("--- Test Sequence Complete ---");
  delay(2000); // Long pause before repeating the entire sequence
}
