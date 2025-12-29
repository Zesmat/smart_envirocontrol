import customtkinter as ctk
import serial
import threading
import time
import sqlite3
import numpy as np
import csv 
import speech_recognition as sr 
import pyttsx3  # Required for Jarvis Voice
from sklearn.svm import SVR
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from datetime import datetime
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# --- SYSTEM CONFIGURATION ---
SERIAL_PORT = 'COM7'  # <--- CHECK YOUR PORT
BAUD_RATE = 9600
DB_NAME = 'smart_home_data.db'
AI_THRESHOLD = 27.0   # Fixed Limit

# --- THEME ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue") 

class SmartHomeApp(ctk.CTk):
    """Smart EnviroControl dashboard (CustomTkinter).

    Responsibilities:
        - UI: sidebar (status, voice, export) + main area (KPI cards + plots).
        - Serial: read sensor CSV lines and write control bytes to Arduino.
        - Storage: log readings into SQLite (`smart_home_data.db`).
        - AI: train a small SVR model on recent heat-index values and forecast.
        - Voice: wake-word ("Jarvis") + command recognition with TTS feedback.

    Threading:
        - `serial_loop()` runs on a daemon thread.
        - `unified_voice_loop()` runs on a daemon thread.
        - UI updates from threads use `self.after(...)`.
    """

    def __init__(self):
        """Initialize app window, widgets, state, and background threads.

        Sets up:
            - Window geometry and layout (grid weights).
            - Speech recognizer and voice state machine.
            - Sidebar + main dashboard area.
            - In-memory buffers used for plotting.

        Side effects:
            Starts background daemon threads for serial and voice handling.
        """
        super().__init__()

        # Window Setup
        self.title("Smart Home AI - Ultimate Edition")
        self.geometry("1280x850")
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Voice & Control State
        # Shared recognizer for wake word + commands.
        self.recognizer = sr.Recognizer()
        self.ai_enabled = True 
        self.manual_override_status = "None"
        
        # Audio State Machine Flags
        # Voice state machine:
        #   - "WAKE": short listens to detect the wake word.
        #   - "CMD": longer listen to capture the full command.
        self.voice_mode = "WAKE" 
        # Global run flag used by background loops.
        self.running = True 
        # Latest AI Prediction Cache
        self.latest_ai_pred = 0.0

        # UI Setup
        # Build widgets before starting threads that update UI.
        self.setup_sidebar()
        self.setup_main_area()

        # Data Lists
        # Buffers for plotting the last N points.
        self.x_data = []    
        self.y_temp = []    
        self.y_hum = []     
        self.y_light = []   
        
        # Start Threads
        # Serial loop handles sensor ingestion + DB logging + control output.
        threading.Thread(target=self.serial_loop, daemon=True).start()
        # Voice loop holds a single mic stream to prevent device conflicts.
        threading.Thread(target=self.unified_voice_loop, daemon=True).start()

    def setup_sidebar(self):
        """Build the left sidebar UI.

        Creates:
            - App title
            - Connection status
            - Control mode display
            - Voice button + usage hint
            - Export button
            - Fixed AI trigger threshold display
        """
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        
        # Logo
        ctk.CTkLabel(self.sidebar, text="EnviroControl AI", font=ctk.CTkFont(size=24, weight="bold")).grid(row=0, column=0, padx=20, pady=(40, 20))
        
        # Connection Status
        self.status_label = ctk.CTkLabel(self.sidebar, text="● DISCONNECTED", text_color="#E74C3C", font=ctk.CTkFont(size=14))
        self.status_label.grid(row=1, column=0, padx=20, pady=5)

        # Fan Status
        ctk.CTkLabel(self.sidebar, text="CONTROL MODE:", font=ctk.CTkFont(size=12, weight="bold")).grid(row=2, column=0, padx=20, pady=(20, 5))
        self.mode_label = ctk.CTkLabel(self.sidebar, text="AI AUTOMATIC", text_color="#2ECC71", font=ctk.CTkFont(size=14, weight="bold"))
        self.mode_label.grid(row=3, column=0, padx=20, pady=5)

        # Voice Button
        # Button can force command mode, but also serves as a visual status indicator.
        self.btn_voice = ctk.CTkButton(self.sidebar, text="🎙️ Initializing...", command=self.force_wake, fg_color="#5B2C6F", hover_color="#9B59B6")
        self.btn_voice.grid(row=4, column=0, padx=20, pady=(30, 10))
        
        # Instructions Label
        self.lbl_voice_hint = ctk.CTkLabel(self.sidebar, text="Say 'Jarvis' to wake", font=ctk.CTkFont(size=10), text_color="gray")
        self.lbl_voice_hint.grid(row=5, column=0)

        # Export Button
        ctk.CTkButton(self.sidebar, text="💾 Export Data", command=self.export_csv, fg_color="#27AE60").grid(row=6, column=0, padx=20, pady=(30, 10))

        # Threshold Display
        ctk.CTkLabel(self.sidebar, text=f"AI Trigger Fixed:\n> {AI_THRESHOLD}°C", font=("Arial", 12, "bold"), text_color="gray").grid(row=7, column=0, padx=20, pady=(40, 0))

    def setup_main_area(self):
        """Build the main dashboard area (KPI cards + plot tabs)."""
        self.main_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.main_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.main_frame.grid_rowconfigure(1, weight=1)

        # Cards
        self.card_temp = self.create_card(0, "🌡️ Temp (Live)", "00.0 °C", "#FF5733") 
        self.card_hum = self.create_card(1, "💧 Humidity", "00.0 %", "#3498DB")     
        self.card_light = self.create_card(2, "☀️ Light Level", "000", "#F1C40F")   
        self.card_ai = self.create_card(3, "🧠 AI Forecast", "--.- °C", "#9B59B6") 

        # Tabs
        self.tab_view = ctk.CTkTabview(self.main_frame)
        self.tab_view.grid(row=1, column=0, columnspan=4, padx=5, pady=20, sticky="nsew")
        self.ax_temp, self.canvas_temp = self.create_graph(self.tab_view.add("Temperature"), "Temperature Trend", "#FF5733")
        self.ax_hum, self.canvas_hum = self.create_graph(self.tab_view.add("Humidity"), "Humidity Trend", "#3498DB")
        self.ax_light, self.canvas_light = self.create_graph(self.tab_view.add("Light"), "Light Trend", "#F1C40F")

    def create_card(self, col, title, value, color):
        """Create a KPI card and return the label used for dynamic updates.

        Args:
            col: Column index in the main grid.
            title: Display title.
            value: Initial value text.
            color: Text color for the value.

        Returns:
            The value label widget (CTkLabel).
        """
        frame = ctk.CTkFrame(self.main_frame, fg_color="#2b2b2b", corner_radius=15)
        frame.grid(row=0, column=col, padx=10, pady=10, sticky="ew")
        ctk.CTkLabel(frame, text=title, font=("Roboto Medium", 14), text_color="#aaaaaa").pack(pady=(15,5))
        lbl = ctk.CTkLabel(frame, text=value, font=("Roboto", 32, "bold"), text_color=color)
        lbl.pack(pady=(0,20))
        return lbl

    def create_graph(self, parent, title, color):
        """Create an embedded matplotlib graph inside a Tk container.

        Args:
            parent: Container (tab/frame) to host the canvas.
            title: Logical graph title (kept for readability/extensibility).
            color: Line color.

        Returns:
            (ax, canvas) tuple for updating/redrawing.
        """
        fig = Figure(figsize=(5, 3), dpi=100)
        fig.patch.set_facecolor('#242424')
        ax = fig.add_subplot(111)
        ax.set_facecolor('#242424')
        ax.tick_params(colors='white', labelsize=8)
        ax.grid(True, color='#404040', linestyle='--', linewidth=0.5)
        ax.plot([], [], color=color, linewidth=2)
        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        return ax, canvas

    # --- THE "FRESH" SPEAK FUNCTION ---
    def speak(self, text):
        """
        Speak a short response using TTS (pyttsx3) and also print to console.

        Design choice:
            Re-initializes the TTS engine per call to avoid the common issue
            where a long-lived engine instance gets stuck after first use.

        Args:
            text: Message to speak.
        """
        print(f"JARVIS: {text}")
        try:
            # Re-initialize engine locally to clear any stuck state
            engine = pyttsx3.init()
            
            # Re-apply settings
            voices = engine.getProperty('voices')
            for voice in voices:
                if "David" in voice.name or "Male" in voice.name:
                    engine.setProperty('voice', voice.id)
                    break
            engine.setProperty('rate', 170)
            
            # Speak and wait (Blocking is fine here as we are in a thread)
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            print(f"TTS Error: {e}")
    def voice_status_report(self):
        try:
            # Get latest data (last item in list)
            if len(self.y_temp) > 0:
                t = self.y_temp[-1]
                h = self.y_hum[-1]
                msg = f"Current temperature is {t} degrees. Humidity is {h} percent. AI systems are functioning normally."
                self.speak(msg)
            else:
                self.speak("System is initializing.Please wait.")
        except:
            self.speak("I cannot access sensor data right now.")

    def voice_explain_decision(self):
            try:
                # 1. Check for Manual Override first
                if not self.ai_enabled:
                    self.speak("I am currently in Manual Override mode per your voice command.")
                    return

                # 2. Check Data
                if len(self.y_temp) > 0:
                    t = self.y_temp[-1]
                    h = self.y_hum[-1]
                    
                    # 3. CALCULATE HEAT INDEX (The "Feels Like" Temp)
                    # This matches the logic in run_ai_prediction
                    heat_index = t + 0.55 * (1 - (h/100)) * (t - 14.4)
                    
                    # 4. EXPLAIN BASED ON HEAT INDEX, NOT RAW TEMP
                    if self.latest_ai_pred > AI_THRESHOLD:
                        self.speak(f"The fan is ON. Although the current heat index is {heat_index:.1f}, the AI predicts it will rise to {self.latest_ai_pred:.1f}, which is unsafe.")
                    else:
                        self.speak(f"The fan is OFF. The heat index is {heat_index:.1f} degrees, which is within the safe range.")
                else:
                    self.speak("I don't have enough data to explain yet.")
                    
            except Exception as e:
                print(f"Explain Error: {e}")
                self.speak("I am calculating the environmental variables.")
            
    def voice_shutdown(self):
        self.speak("Emergency protocol initiated. Shutting down all actuators.")
        self.ser.write(b'N') # Fan Auto/Off (Safety)
        time.sleep(0.5)
        self.ser.write(b'l') # Lights OFF
        self.ai_enabled = False # Stop AI from turning them back on
        self.manual_override_status = "None"
        self.btn_voice.configure(text="⚠️ SHUTDOWN", fg_color="gray")
    # --- UNIFIED VOICE LOOP ---
    def unified_voice_loop(self):
        """Run wake-word detection and command listening on one mic thread.

        Why this exists:
            SpeechRecognition can crash or deadlock if multiple threads compete
            for microphone access. Keeping a single thread owning the mic stream
            avoids those conflicts.

        State machine:
            - WAKE: short listens; looks for "jarvis".
            - CMD: longer listen; parses commands like fan on/off, auto, lights.

        UI updates:
            Updates voice button text/color and hint label to reflect the active
            state (idle listening, command listening, processing, etc.).
        """
        time.sleep(3) 
        self.btn_voice.configure(text="🎙️ Waiting for 'Jarvis'...", fg_color="#5B2C6F")
        
        while self.running:
            try:
                # Device 1 = Laptop Mic.
                with sr.Microphone(device_index=1) as source:
                    
                    # Recognition tuning: sensitivity and silence detection.
                    self.recognizer.energy_threshold = 250
                    self.recognizer.pause_threshold = 0.5 
                    
                    while self.running:
                        try:
                            # --- MODE 1: WAITING FOR JARVIS ---
                            if self.voice_mode == "WAKE":
                                # Short timeouts keep the loop responsive.
                                self.btn_voice.configure(text="🎙️ Waiting for 'Jarvis'...", fg_color="#5B2C6F")
                                self.lbl_voice_hint.configure(text="Say 'Jarvis' to wake", text_color="gray")
                                
                                audio = self.recognizer.listen(source, timeout=2, phrase_time_limit=2)
                                phrase = self.recognizer.recognize_google(audio).lower()
                                
                                if "jarvis" in phrase:
                                    print("✅ JARVIS HEARD!")
                                    self.speak("Yes?") 
                                    self.voice_mode = "CMD" 
                                    
                            # --- MODE 2: LISTENING FOR COMMAND ---
                            elif self.voice_mode == "CMD":
                                # Command mode uses a longer timeout for complete phrases.
                                self.btn_voice.configure(text="🔴 LISTENING...", fg_color="#E74C3C")
                                self.lbl_voice_hint.configure(text="Say: 'Turn on fan' or 'Lights off'", text_color="#E74C3C")
                                
                                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=5)
                                self.btn_voice.configure(text="Processing...", fg_color="#F39C12")
                                
                                command = self.recognizer.recognize_google(audio).lower()
                                print(f"Command: {command}")
                                
                                # --- COMMAND LOGIC ---
                                if "on" in command and "fan" in command:
                                    # Manual override: forces proactive cooling.
                                    self.ai_enabled = False
                                    self.manual_override_status = "ON"
                                    self.mode_label.configure(text="VOICE OVERRIDE", text_color="#F39C12")
                                    self.speak("Fan turned ON.")
                                    self.btn_voice.configure(text="✅ Fan ON", fg_color="#27AE60")
                                    
                                elif "off" in command and "fan" in command:
                                    # Return to AI automatic mode.
                                    self.ai_enabled = True
                                    self.manual_override_status = "None"
                                    self.mode_label.configure(text="AI AUTOMATIC", text_color="#2ECC71")
                                    self.speak("Fan OFF. Auto Mode.")
                                    self.btn_voice.configure(text="✅ Fan OFF", fg_color="#27AE60")

                                elif "auto" in command or "reset" in command:
                                    # Explicit reset to AI automatic mode.
                                    self.ai_enabled = True
                                    self.manual_override_status = "None"
                                    self.mode_label.configure(text="AI AUTOMATIC", text_color="#2ECC71")
                                    self.speak("Auto Mode Engaged.")
                                    self.btn_voice.configure(text="✅ Auto Mode", fg_color="#27AE60")
                                
                                # --- LIGHT COMMANDS ---
                                elif "light" in command:
                                    # Light control commands are forwarded over serial.
                                    if "on" in command:
                                        self.ser.write(b'L')
                                        self.speak("Lights turned ON.")
                                        self.btn_voice.configure(text="✅ Lights ON", fg_color="#F1C40F")
                                    elif "off" in command:
                                        self.ser.write(b'l')
                                        self.speak("Lights turned OFF.")
                                        self.btn_voice.configure(text="✅ Lights OFF", fg_color="#27AE60")
                                # 1. STATUS REPORT
                                elif "status" in command or "report" in command:
                                    self.voice_status_report()
                                    self.btn_voice.configure(text="📊 Reporting", fg_color="#3498DB")

                                # 2. EXPLAIN DECISION (WHY?)
                                elif "why" in command or "reason" in command:
                                    self.voice_explain_decision()
                                    self.btn_voice.configure(text="🤔 Explaining", fg_color="#9B59B6")

                                # 3. SHUTDOWN / GOODNIGHT
                                elif "shut down" in command or "goodbye" in command or "leave" in command:
                                    self.voice_shutdown()
                                else:
                                    # Fallback when speech is recognized but no supported command matches.
                                    self.speak("I didn't catch that.")
                                    self.btn_voice.configure(text="❓ Unknown", fg_color="gray")

                                # Reset to Wake Mode
                                time.sleep(1)
                                self.voice_mode = "WAKE"

                        except sr.WaitTimeoutError:
                            if self.voice_mode == "CMD":
                                self.voice_mode = "WAKE"
                                self.btn_voice.configure(text="❌ Timed Out", fg_color="gray")
                                time.sleep(1)
                        except sr.UnknownValueError:
                            pass
                        except Exception as e:
                            print(f"Inner Loop Error: {e}")
                            break 
            except Exception as e:
                print(f"Mic Error: {e}")
                self.btn_voice.configure(text="❌ Mic Error", fg_color="red")
                time.sleep(3)

    def force_wake(self):
        """Force the voice state machine into command mode.

        Triggered by the sidebar button as a manual alternative to saying
        the wake word.
        """
        self.voice_mode = "CMD"

    def export_csv(self):
        """Export all rows in the `sensor_data` table to a CSV file.

        Output:
            Writes `sensor_log_HHMMSS.csv` in the current working directory.

        Side effects:
            Updates the export button appearance on success.
        """
        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sensor_data")
            with open(f"sensor_log_{datetime.now().strftime('%H%M%S')}.csv", 'w', newline='') as f:
                csv.writer(f).writerows(cursor.fetchall())
            conn.close()
            self.btn_export.configure(text="✅ Saved!", fg_color="#27AE60")
        except: pass   

    # --- FIXED AI PREDICTION ---
    def run_ai_prediction(self):
        """Train an SVR model on recent heat-index values and forecast ahead.

        Data source:
            Reads up to the last 60 (temp, humid) readings from SQLite.

        Model:
            StandardScaler + linear SVR.

        Returns:
            - "Gathering..." if not enough history.
            - "Error" on failure.
            - Otherwise: formatted prediction string like "28.3 °C (Feels Like)".
        """
        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            # Select BOTH temp and humid for Heat Index
            cursor.execute("SELECT temp, humid FROM sensor_data ORDER BY id DESC LIMIT 60")
            data = cursor.fetchall()
            conn.close()

            if len(data) < 10: return "Gathering..."
            
            # HEAT INDEX CALCULATION
            heat_indices = []
            for t, h in data:
                # Simple heat-index approximation (used as the model target).
                hi = t + 0.55 * (1 - (h/100)) * (t - 14.4)
                heat_indices.append(hi)

            y = np.array(heat_indices[::-1]).reshape(-1, 1) 
            x = np.array(range(len(y))).reshape(-1, 1)
            
            model = make_pipeline(StandardScaler(), SVR(kernel='linear', C=1.0, epsilon=0.01))
            model.fit(x, y.ravel())
            
            pred = model.predict([[len(y)+60]])[0]
            return f"{pred:.1f} °C (Feels Like)"
        except: return "Error"

    def serial_loop(self):
        """Read serial sensor data, log to DB, run AI, and send control bytes.

        Incoming serial format:
            `<temp_c>,<humidity_pct>,<light_adc>`

        Control bytes sent back:
            - `P`: proactive cooling ON
            - `N`: normal

        Threading:
            Runs in a daemon thread; schedules UI updates via `self.after(...)`.
        """
        conn = sqlite3.connect(DB_NAME)
        conn.execute('CREATE TABLE IF NOT EXISTS sensor_data (id INTEGER PRIMARY KEY, timestamp DATETIME, temp REAL, humid REAL, light INTEGER)')
        conn.close()

        try:
            # Open the configured serial port.
            self.ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
            time.sleep(2) 
            self.status_label.configure(text="● SYSTEM ONLINE", text_color="#2ECC71")
        except: return

        while self.running:
            # Only read if bytes are available.
            if self.ser.in_waiting:
                try:
                    line = self.ser.readline().decode().strip()
                    parts = line.split(',')
                    if len(parts) == 3:
                        t, h, l = parts
                        ts = datetime.now().strftime('%H:%M:%S')
                        # Persist sample to SQLite.
                        conn = sqlite3.connect(DB_NAME)
                        conn.execute("INSERT INTO sensor_data (timestamp, temp, humid, light) VALUES (?,?,?,?)", (ts, t, h, l))
                        conn.commit()
                        conn.close()

                        ai_res = self.run_ai_prediction()

                        if self.ai_enabled:
                            try:
                                pred = float(ai_res.split(' ')[0])
                                if pred > AI_THRESHOLD:
                                    # Predicts too hot -> proactively cool.
                                    self.ser.write(b'P')
                                else:
                                    # Otherwise remain in normal mode.
                                    self.ser.write(b'N')
                            except: pass
                        else:
                            if self.manual_override_status == "ON":
                                # Manual override forces proactive cooling.
                                self.ser.write(b'P') 
                        
                        # Schedule UI update on the Tk main thread.
                        self.after(0, self.update_dashboard, t, h, l, ai_res)
                except: pass

    def update_dashboard(self, t, h, l, ai):
        """Update KPI cards, append plot buffers, and redraw graphs."""
        # Update KPI cards.
        self.card_temp.configure(text=f"{t} °C")
        self.card_hum.configure(text=f"{h} %")
        self.card_light.configure(text=f"{l}")
        self.card_ai.configure(text=ai)
        
        # Append new point to buffers.
        self.x_data.append(datetime.now().strftime('%H:%M:%S'))
        self.y_temp.append(float(t))
        self.y_hum.append(float(h))
        self.y_light.append(int(l))
        
        # Keep a rolling window of the last 60 samples.
        if len(self.x_data) > 60:
            self.x_data.pop(0); self.y_temp.pop(0); self.y_hum.pop(0); self.y_light.pop(0)

        self.update_single_graph(self.ax_temp, self.canvas_temp, self.y_temp, '#FF5733')
        self.update_single_graph(self.ax_hum, self.canvas_hum, self.y_hum, '#3498DB')
        self.update_single_graph(self.ax_light, self.canvas_light, self.y_light, '#F1C40F')

    def update_single_graph(self, ax, canvas, y, c):
        """Redraw a single matplotlib graph with current buffered data."""
        ax.clear(); ax.set_facecolor('#242424'); ax.grid(True, linestyle='--', linewidth=0.5)
        ax.plot(range(len(self.x_data)), y, color=c, linewidth=2)
        step = 10
        if len(self.x_data) > step:
            # Decimate x tick labels to reduce clutter.
            idx = list(range(0, len(self.x_data), step))
            ax.set_xticks(idx); ax.set_xticklabels([self.x_data[i] for i in idx], rotation=30, ha='right', color='white')
        else:
            ax.set_xticks(range(len(self.x_data))); ax.set_xticklabels(self.x_data, rotation=30, ha='right', color='white')
        ax.tick_params(colors='white')
        canvas.draw()

if __name__ == "__main__":
    app = SmartHomeApp()
    app.mainloop()