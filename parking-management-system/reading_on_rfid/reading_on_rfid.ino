#include <SPI.h>
#include <MFRC522.h>

#define RST_PIN 9
#define SS_PIN 10

MFRC522 mfrc522(SS_PIN, RST_PIN);
MFRC522::MIFARE_Key key;
MFRC522::StatusCode card_status;

void setup() {
  Serial.begin(9600);
  SPI.begin();
  mfrc522.PCD_Init();
  Serial.println(F("PCD Ready to read Numberplate and Balance!"));
}

void loop() {
  // Prepare the key for authentication
  for (byte i = 0; i < 6; i++) {
    key.keyByte[i] = 0xFF;
  }

  // Look for new cards
  if (!mfrc522.PICC_IsNewCardPresent()) {
    return;
  }

  // Select one of the cards
  if (!mfrc522.PICC_ReadCardSerial()) {
    return;
  }

  Serial.println(F("\n*** Data from PICC ***\n"));

  // Read Numberplate from block 2
  Serial.print(F("Numberplate: "));
  String numberplate = readBlock(2);
  Serial.println(numberplate);

  // Read Balance from block 4
  Serial.print(F("Balance:     "));
  String balance = readBlock(4);
  Serial.println(balance);

  Serial.println(F("\n***********************\n"));
  delay(1000);

  // Halt PICC
  mfrc522.PICC_HaltA();
  // Stop encryption on PCD
  mfrc522.PCD_StopCrypto1();
}

String readBlock(byte blockNumber) {
  // Authenticate using key A on the specified block
  card_status = mfrc522.PCD_Authenticate(MFRC522::PICC_CMD_MF_AUTH_KEY_A, blockNumber, &key, &(mfrc522.uid));
  if (card_status != MFRC522::STATUS_OK) {
    Serial.print(F("Authentication failed for block "));
    Serial.print(blockNumber);
    Serial.print(F(": "));
    Serial.println(mfrc522.GetStatusCodeName(card_status));
    return ""; // Return an empty string to indicate failure
  }

  byte buffer[18];
  byte bufferSize = sizeof(buffer);

  // Read data from the block
  card_status = mfrc522.MIFARE_Read(blockNumber, buffer, &bufferSize);
  if (card_status != MFRC522::STATUS_OK) {
    Serial.print(F("Reading failed from block "));
    Serial.print(blockNumber);
    Serial.print(F(": "));
    Serial.println(mfrc522.GetStatusCodeName(card_status));
    return ""; // Return an empty string to indicate failure
  }

  String value = "";
  for (uint8_t i = 0; i < 16; i++) {
    value += (char)buffer[i];
  }
  value.trim();
  return value;
}
