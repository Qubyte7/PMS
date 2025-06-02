#include <Servo.h>

#define TRIGGER_PIN 15  // D8 (GPIO15) for Wemos D1 Mini
#define ECHO_PIN 13     // D7 (GPIO13) for Wemos D1 Mini
#define SERVO_PIN 2     // D4 (GPIO2) for Wemos D1 Mini

Servo barrierServo;

void setup() {
  Serial.begin(115200);
  pinMode(TRIGGER_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  barrierServo.attach(SERVO_PIN);
  barrierServo.write(0); // Start closed
}

void loop() {
  // Send ultrasonic pulse
  digitalWrite(TRIGGER_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIGGER_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIGGER_PIN, LOW);

  // Read echo
  long duration = pulseIn(ECHO_PIN, HIGH);
  float distance_cm = (duration * 0.0343) / 2.0;
  Serial.println(distance_cm);

  // Control servo from serial input
  if (Serial.available()) {
    char cmd = Serial.read();
    if (cmd == '1') {
      barrierServo.write(180); // Open
    } else if (cmd == '0') {
      barrierServo.write(0); // Close
    }
  }

  delay(50);
}









