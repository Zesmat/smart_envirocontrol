#include "DHT.h"
#include <SoftwareSerial.h>

// --- PINS ---
#define DHTPIN 2
#define DHTTYPE DHT11
#define LDR_PIN A0
#define FAN_PIN 3      
#define LIGHT_PIN 7    
#define RELAY_ON  LOW  
#define RELAY_OFF HIGH
// Communication to Node B: RX=10, TX=11
SoftwareSerial nodeB_Serial(10, 11); 

DHT dht(DHTPIN, DHTTYPE);


bool fanOverride = false;
bool lightOverride = false; 

void setup() {
  // Initialize both serial channels:
  //  - Serial: USB debugging to laptop
  //  - nodeB_Serial: SoftwareSerial link to Node B gateway
  Serial.begin(9600);       // For laptop debugging
  nodeB_Serial.begin(9600); // For talking to Node B
  dht.begin();
  
  pinMode(FAN_PIN, OUTPUT);
  pinMode(LIGHT_PIN, OUTPUT);
  
  // Test Cycle: Turn everything ON for 2 seconds to check wiring
  // This helps verify power, relays, and pin mapping before runtime logic.
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
  // 2. LISTEN FOR COMMANDS (Fan + Lights)
  // Commands arrive from Node B (which forwards from the Python dashboard).
  if (nodeB_Serial.available()) {
      char cmd = nodeB_Serial.read();
      
      if (cmd == 'P') { // Proactive Cooling
        fanOverride = true;
      } 
      else if (cmd == 'N') { // Normal Mode
        fanOverride = false;
      }
      else if (cmd == 'L') { // Light ON (Voice)
        lightOverride = true;
      }
      else if (cmd == 'l') { // Light OFF (Voice) - lowercase 'L'
        lightOverride = false;
      }
  }
  // 3. ACTUATOR LOGIC (FAN)
  // If AI/dashboard predicts high temperature it can force fanOverride.
  if (fanOverride) {
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
  // 4. ACTUATOR LOGIC - LIGHTS
  // Light control supports:
  //   - Voice override (L / l)
  //   - Auto mode based on LDR threshold
  // If voice says ON ('L'), turn on.
  // OR if it's dark (< 300) and voice didn't force it OFF, turn on.
  bool shouldLightBeOn = false;
  if (lightOverride) {
        // CASE A: Voice said "Turn On" -> Force ON
        shouldLightBeOn = true;
    } else {
        // CASE B: Voice said "Turn Off" (or nothing) -> Auto Sensor Mode
        // Adjust '300' if needed. 
        // < 300 Usually means Dark. > 600 Usually means Bright.
        if (lightVal < 500) { 
          shouldLightBeOn = true;
        }
    }
  if (shouldLightBeOn) {
      digitalWrite(LIGHT_PIN, RELAY_ON);
  } else {
      digitalWrite(LIGHT_PIN, RELAY_OFF);
  }
  // 5. TRANSMIT SENSOR VALUES
  // Format (CSV): temp,humidity,light
  nodeB_Serial.print(t); 
  nodeB_Serial.print(","); 
  nodeB_Serial.print(h); 
  nodeB_Serial.print(","); 
  nodeB_Serial.println(lightVal);

  // 6. DEBUG (USB Serial Monitor)
  Serial.print("Data to Hub: ");
  Serial.print(t); Serial.print(","); 
  Serial.print(h); Serial.print(","); 
  Serial.println(lightVal);

  delay(1000); // Send data every second
}