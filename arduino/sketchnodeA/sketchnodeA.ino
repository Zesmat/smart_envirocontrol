  #include "DHT.h"
  #include <SoftwareSerial.h>

  // --- PINS ---
  #define DHTPIN 2
  #define DHTTYPE DHT11
  #define LDR_PIN A0
  #define FAN_PIN 3      
  #define LIGHT_PIN 7    

  // RELAY LOGIC (Swap HIGH/LOW if your light is backwards)
  #define RELAY_ON  LOW  
  #define RELAY_OFF HIGH   

  SoftwareSerial nodeB_Serial(10, 11); 
  DHT dht(DHTPIN, DHTTYPE);

  // 0=Auto, 1=Force ON, 2=Force OFF
  int lightState = 0; 
  bool fanOverride = false;

  void setup() {
    Serial.begin(9600);       
    nodeB_Serial.begin(9600); 
    dht.begin();
    
    pinMode(FAN_PIN, OUTPUT);
    pinMode(LIGHT_PIN, OUTPUT);
    
    // Quick startup flash
    digitalWrite(LIGHT_PIN, RELAY_ON);
    delay(200);
    digitalWrite(LIGHT_PIN, RELAY_OFF);
  }

  void loop() {
    float t = dht.readTemperature();
    float h = dht.readHumidity();
    int lightVal = analogRead(LDR_PIN);

    if (nodeB_Serial.available()) {
        char cmd = nodeB_Serial.read();
        
        // FAN COMMANDS
        if (cmd == 'P') { fanOverride = true; } 
        
        // LIGHT COMMANDS
        else if (cmd == 'L') { lightState = 1; } // Force ON
        else if (cmd == 'l') { lightState = 2; } // Force OFF
        
        // AUTO COMMANDS
        else if (cmd == 'N') { 
          fanOverride = false; 
          // DO NOT RESET LIGHTS HERE! This fixes the loop bug.
        }
        else if (cmd == 'A') { 
          fanOverride = false; 
          lightState = 0; // Global Reset
        }
    }

    // FAN LOGIC
    if (fanOverride) { 
        analogWrite(FAN_PIN, 255); 
      } else { 
        analogWrite(FAN_PIN, 0); 
      }
        // LIGHT LOGIC
    if (lightState == 1) { digitalWrite(LIGHT_PIN, RELAY_ON); } 
    else if (lightState == 2) { digitalWrite(LIGHT_PIN, RELAY_OFF); } 
    else {
        // Auto Mode
        if (lightVal < 500) { digitalWrite(LIGHT_PIN, RELAY_ON); } 
        else { digitalWrite(LIGHT_PIN, RELAY_OFF); }
    }

    // Send Data
    nodeB_Serial.print(t); nodeB_Serial.print(","); 
    nodeB_Serial.print(h); nodeB_Serial.print(","); 
    nodeB_Serial.println(lightVal);
    delay(500); // Faster Loop
  }