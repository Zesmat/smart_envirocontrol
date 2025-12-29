#include <SoftwareSerial.h>

// RX = Pin 2 (Connect to Node A TX), TX = Pin 3 (Connect to Node A RX)
SoftwareSerial nodeA_Serial(2, 3); 

void setup() {
  Serial.begin(9600);      // To Laptop USB
  nodeA_Serial.begin(9600); // To Node A
  
  Serial.println("--- Node B Gateway Online ---");
}

void loop() {
// 1. UPLOAD: Forward Sensor Data (Node A -> Laptop)
  // We use Serial.write() to pass the raw data (including newlines) instantly
  if (nodeA_Serial.available()) {
    Serial.write(nodeA_Serial.read());
  }

  // 2. DOWNLOAD: Forward AI Commands (Laptop -> Node A)
  // This is the NEW part that allows the AI to control the Fan
  if (Serial.available()) {
    nodeA_Serial.write(Serial.read());
  }
}