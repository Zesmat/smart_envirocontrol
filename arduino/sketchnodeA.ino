#include "DHT.h"
#include <SoftwareSerial.h>

// --- PINS ---
#define DHTPIN 2
#define DHTTYPE DHT11
#define LDR_PIN A0
#define FAN_PIN 3      
#define LIGHT_PIN 7    

// Communication to Node B: RX=10, TX=11
SoftwareSerial nodeB_Serial(10, 11); 

DHT dht(DHTPIN, DHTTYPE);

bool aiOverride = false;

void setup() {
  Serial.begin(9600);       // For laptop debugging
  nodeB_Serial.begin(9600); // For talking to Node B
  dht.begin();
  
  pinMode(FAN_PIN, OUTPUT);
  pinMode(LIGHT_PIN, OUTPUT);
  
  // Test Cycle: Turn everything ON for 2 seconds to check wiring
  digitalWrite(LIGHT_PIN, HIGH); 
  analogWrite(FAN_PIN, 255);
  delay(2000);
  digitalWrite(LIGHT_PIN, LOW);
  analogWrite(FAN_PIN, 0);
  
  Serial.println("Node A Online");
}

void loop() {
  // 1. Read all sensors
  float t = dht.readTemperature();
  float h = dht.readHumidity();
  int lightVal = analogRead(LDR_PIN);

  // 2. Safety check: If DHT11 fails, don't send garbage
  if (isnan(t) || isnan(h)) {
    Serial.println("Failed to read from DHT sensor!");
    return;
  }
  if (nodeB_Serial.available()) {
      char cmd = nodeB_Serial.read();
      
      if (cmd == 'P') {
        aiOverride = true;
        Serial.println("Command Received: PROACTIVE COOLING (AI)");
      } 
      else if (cmd == 'N') {
        aiOverride = false;
        Serial.println("Command Received: Normal Mode");
      }
    }
    // 3. ACTUATOR LOGIC
  if (aiOverride) {
      // If AI says it will get hot, turn fan ON immediately
      analogWrite(FAN_PIN, 255); 
    } 
    else {
      // Normal Logic: Only turn on if ALREADY hot (> 28)
      if (t > 27) { 
        analogWrite(FAN_PIN, 255); 
      } else { 
        analogWrite(FAN_PIN, 0); 
      }
    }
  if (lightVal > 600) { 
    digitalWrite(LIGHT_PIN, HIGH); 
  } else { 
    digitalWrite(LIGHT_PIN, LOW); 
  }

  // 4. TRANSMIT (Corrected to 3 values for Python Dashboard)
  nodeB_Serial.print(t); 
  nodeB_Serial.print(","); 
  nodeB_Serial.print(h); 
  nodeB_Serial.print(","); 
  nodeB_Serial.println(lightVal);

  // 5. DEBUG (To your Node A Serial Monitor)
  Serial.print("Data to Hub: ");
  Serial.print(t); Serial.print(","); 
  Serial.print(h); Serial.print(","); 
  Serial.println(lightVal);

  delay(1000); // Send data every second
}