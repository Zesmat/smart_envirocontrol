import customtkinter as ctk
import serial
import threading
import time
import sqlite3
import numpy as np
import csv 
import speech_recognition as sr 
import pyttsx3 
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
AI_THRESHOLD = 27.0   

# --- MODERN THEME COLORS ---
COLOR_BG = "#0F172A"       # Deep Slate Background
COLOR_SIDEBAR = "#1E293B"  # Lighter Slate Sidebar
COLOR_CARD = "#334155"     # Card Surface
COLOR_PRIMARY = "#3B82F6"  # Bright Blue
COLOR_SUCCESS = "#10B981"  # Emerald Green
COLOR_WARNING = "#F59E0B"  # Amber/Orange
COLOR_DANGER = "#EF4444"   # Red
COLOR_ACCENT = "#8B5CF6"   # Violet (Jarvis)
COLOR_TEXT = "#F8FAFC"     # Off-White Text
COLOR_SUBTEXT = "#94A3B8"  # Muted Text

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue") 

class SmartHomeApp(ctk.CTk):
    def __init__(self):

        super().__init__()

        # Window Setup
        self.title("EnviroControl AI | Ultimate Edition")
        self.geometry("1400x900")
        self.configure(fg_color=COLOR_BG) # Set main background
        
        # Grid Layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # State Variables
        self.recognizer = sr.Recognizer()
        self.ai_enabled = True 
        self.manual_override_status = "None"
        self.voice_mode = "WAKE" 
        self.running = True 
        self.latest_ai_pred = 0.0 

        # Data Lists
        self.x_data = []    
        self.y_temp = []    
        self.y_hum = []     
        self.y_light = []   

        # UI Setup
        self.setup_sidebar()
        self.setup_main_area()

        # Start Threads
        threading.Thread(target=self.serial_loop, daemon=True).start()
        threading.Thread(target=self.unified_voice_loop, daemon=True).start()

    def setup_sidebar(self):
        """Create and lay out the left sidebar UI.

        The sidebar contains:
        - App title/logo area
        - Connection status indicator (offline/online)
        - Current operating mode indicator (AI automatic vs voice override)
        - Voice interface button + hint text for wake word
        - Threshold display used by the AI control logic
        - Export button to save DB rows to a CSV log file

        This method only constructs widgets and places them in the grid.
        """
        self.sidebar = ctk.CTkFrame(self, width=280, corner_radius=0, fg_color=COLOR_SIDEBAR)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(8, weight=1) # Spacer at bottom
        
        # 1. App Title / Logo Area
        self.logo_label = ctk.CTkLabel(
            self.sidebar, 
            text="ENVIRO\nCONTROL AI", 
            font=("Segoe UI", 28, "bold"), 
            text_color=COLOR_PRIMARY
        )
        self.logo_label.grid(row=0, column=0, padx=20, pady=(50, 10))
        
        # 2. Connection Status Pill
        self.status_frame = ctk.CTkFrame(self.sidebar, fg_color=COLOR_BG, corner_radius=20)
        self.status_frame.grid(row=1, column=0, padx=20, pady=(0, 30))
        self.status_label = ctk.CTkLabel(
            self.status_frame, 
            text="● SYSTEM OFFLINE", 
            font=("Segoe UI", 12, "bold"), 
            text_color=COLOR_DANGER
        )
        self.status_label.pack(padx=15, pady=5)

        # 3. Mode Section
        self.lbl_mode_title = ctk.CTkLabel(self.sidebar, text="OPERATING MODE", font=("Segoe UI", 12, "bold"), text_color=COLOR_SUBTEXT)
        self.lbl_mode_title.grid(row=2, column=0, padx=20, pady=(10, 0), sticky="w")
        
        self.mode_card = ctk.CTkFrame(self.sidebar, fg_color=COLOR_CARD, corner_radius=10)
        self.mode_card.grid(row=3, column=0, padx=20, pady=(5, 20), sticky="ew")
        self.mode_label = ctk.CTkLabel(
            self.mode_card, 
            text="🤖 AI AUTOMATIC", 
            font=("Segoe UI", 16, "bold"), 
            text_color=COLOR_SUCCESS
        )
        self.mode_label.pack(pady=15)

        # 4. Voice Command Section (The Big Button)
        self.lbl_voice_title = ctk.CTkLabel(self.sidebar, text="VOICE INTERFACE", font=("Segoe UI", 12, "bold"), text_color=COLOR_SUBTEXT)
        self.lbl_voice_title.grid(row=4, column=0, padx=20, pady=(10, 0), sticky="w")

        self.btn_voice = ctk.CTkButton(
            self.sidebar, 
            text="🎙️ INITIALIZING...", 
            command=self.force_wake, 
            font=("Segoe UI", 16, "bold"),
            fg_color=COLOR_ACCENT, 
            hover_color="#7C3AED",
            height=60,
            corner_radius=12
        )
        self.btn_voice.grid(row=5, column=0, padx=20, pady=(10, 5), sticky="ew")
        
        self.lbl_voice_hint = ctk.CTkLabel(self.sidebar, text="Say 'Jarvis' to wake", font=("Segoe UI", 12), text_color=COLOR_SUBTEXT)
        self.lbl_voice_hint.grid(row=6, column=0, padx=20, pady=(0, 20))

        # 5. Threshold Info
        self.lbl_thresh = ctk.CTkLabel(self.sidebar, text=f"AI TRIGGER: > {AI_THRESHOLD}°C", font=("Segoe UI", 14, "bold"), text_color=COLOR_SUBTEXT)
        self.lbl_thresh.grid(row=7, column=0, padx=20, pady=20)

        # 6. Footer / Export
        self.btn_export = ctk.CTkButton(
            self.sidebar, 
            text="💾 SAVE DATA LOG", 
            command=self.export_csv, 
            fg_color=COLOR_CARD, 
            hover_color=COLOR_PRIMARY,
            text_color="white",
            height=40
        )
        self.btn_export.grid(row=9, column=0, padx=20, pady=30, sticky="ew")

    def setup_main_area(self):
        """Create and lay out the main dashboard area (KPIs + charts).

        Builds:
        - Four KPI “hero cards” (temperature, humidity, light level, AI prediction)
        - A tabbed chart section with three Matplotlib plots embedded in Tk

        The charts are updated continuously via `update_dashboard`, which is scheduled
        from the serial thread using `after(...)` to keep UI updates thread-safe.
        """
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, padx=30, pady=30, sticky="nsew")
        
        # Grid Layout for Cards
        self.main_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.main_frame.grid_rowconfigure(1, weight=1)

        # --- HERO CARDS ---
        # We create 4 cards for KPIs
        self.card_temp = self.create_hero_card(0, "TEMPERATURE", "00.0 °C", "🌡️", COLOR_DANGER) 
        self.card_hum = self.create_hero_card(1, "HUMIDITY", "00.0 %", "💧", COLOR_PRIMARY)     
        self.card_light = self.create_hero_card(2, "LIGHT LEVEL", "000", "☀️", COLOR_WARNING)   
        self.card_ai = self.create_hero_card(3, "AI PREDICTION", "--.- °C", "🧠", COLOR_ACCENT) 

        # --- CHARTS AREA ---
        # Styled TabView
        self.tab_view = ctk.CTkTabview(
            self.main_frame, 
            fg_color=COLOR_SIDEBAR, 
            segmented_button_fg_color=COLOR_BG,
            segmented_button_selected_color=COLOR_PRIMARY,
            segmented_button_selected_hover_color=COLOR_PRIMARY,
            corner_radius=15,
            height=500
        )
        self.tab_view.grid(row=1, column=0, columnspan=4, padx=0, pady=30, sticky="nsew")
        
        # Create Tabs
        self.ax_temp, self.canvas_temp = self.create_graph(self.tab_view.add("  TEMPERATURE TREND  "), COLOR_DANGER)
        self.ax_hum, self.canvas_hum = self.create_graph(self.tab_view.add("  HUMIDITY TREND  "), COLOR_PRIMARY)
        self.ax_light, self.canvas_light = self.create_graph(self.tab_view.add("  LIGHT TREND  "), COLOR_WARNING)

    def create_hero_card(self, col, title, value, icon, color):
        """Create a KPI “hero card” widget and return its value label.

        Args:
            col: Grid column index within the main KPI row.
            title: Label shown as the card title (e.g., TEMPERATURE).
            value: Initial value text shown (e.g., "00.0 °C").
            icon: Emoji/icon prefix displayed next to the title.
            color: Text color used for the value.

        Returns:
            The CTkLabel used to display the live-updating value, so callers can
            later call `.configure(text=...)` when new data arrives.
        """
        card = ctk.CTkFrame(self.main_frame, fg_color=COLOR_SIDEBAR, corner_radius=15)
        card.grid(row=0, column=col, padx=10, pady=0, sticky="ew")
        
        # Title Row
        title_lbl = ctk.CTkLabel(card, text=f"{icon}  {title}", font=("Segoe UI", 12, "bold"), text_color=COLOR_SUBTEXT)
        title_lbl.pack(pady=(20, 5), padx=20, anchor="w")
        
        # Value Row
        value_lbl = ctk.CTkLabel(card, text=value, font=("Segoe UI", 36, "bold"), text_color=color)
        value_lbl.pack(pady=(0, 20), padx=20, anchor="w")
        
        return value_lbl

    def create_graph(self, parent, color):
        """Create a themed Matplotlib plot embedded inside a Tk container.

        Args:
            parent: The tab/frame widget that will host the graph canvas.
            color: Line color for the plotted series.

        Returns:
            A tuple `(ax, canvas)` where:
            - `ax` is the Matplotlib axes used for drawing
            - `canvas` is the TkAgg canvas used to display the figure in the UI

        Notes:
            The axes are styled to match the CustomTkinter dark theme.
        """
        fig = Figure(figsize=(5, 3), dpi=100)
        fig.patch.set_facecolor(COLOR_SIDEBAR) # Match Tab Background
        
        ax = fig.add_subplot(111)
        ax.set_facecolor(COLOR_SIDEBAR) # Match Plot Background
        
        # Style the axes
        ax.tick_params(colors=COLOR_SUBTEXT, labelsize=9)
        ax.spines['bottom'].set_color(COLOR_SUBTEXT)
        ax.spines['left'].set_color(COLOR_SUBTEXT)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        
        # Grid
        ax.grid(True, color=COLOR_CARD, linestyle='-', linewidth=1, alpha=0.5)
        
        # Initial Line
        ax.plot([], [], color=color, linewidth=3, marker='o', markersize=0) # Thicker, cleaner line
        
        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)
        return ax, canvas

    # --- SPEECH ENGINE ---
    def speak(self, text):
        """Speak text using offline text-to-speech (TTS) and also print it.

        This method:
        - Prints the assistant response to the console as `JARVIS: ...`
        - Attempts to initialize `pyttsx3` and speak the given text aloud

        Args:
            text: The phrase to speak.

        Failure behavior:
            If the TTS engine fails to initialize or speak, the error is printed
            and the application continues running.
        """
        print(f"JARVIS: {text}")
        try:
            engine = pyttsx3.init()
            voices = engine.getProperty('voices')
            for voice in voices:
                if "David" in voice.name or "Male" in voice.name:
                    engine.setProperty('voice', voice.id)
                    break
            engine.setProperty('rate', 170)
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            print(f"TTS Error: {e}")

    # --- VOICE HELPER FUNCTIONS ---
    def voice_status_report(self):
        """Speak a short status report based on the latest buffered sensor values.

        Reads the most recent temperature and humidity values from the in-memory
        buffers (`self.y_temp`, `self.y_hum`) and speaks a human-friendly summary.

        Notes:
            If no data has arrived yet (buffers empty), Jarvis reports that the
            system is still initializing.
        """
        try:
            if len(self.y_temp) > 0:
                t = self.y_temp[-1]
                h = self.y_hum[-1]
                self.speak(f"Current temperature is {t} degrees. Humidity is {h} percent. All systems nominal.")
            else:
                self.speak("System is initializing. Please wait.")
        except:
            self.speak("I cannot access sensor data right now.")

    def voice_explain_decision(self):
        """Explain the current AI/override decision in natural language.

        Behavior:
        - If AI is disabled, explains that Manual Override is active.
        - Otherwise, computes a simple “current heat index” estimate from the latest
          buffered temperature/humidity, and compares it to `self.latest_ai_pred`.
        - Speaks a rationale for why the fan is (or is not) expected to run.

        Failure behavior:
            Falls back to a short response if data is missing or an exception occurs.
        """
        try:
            if not self.ai_enabled:
                self.speak("I am currently in Manual Override mode per your voice command.")
                return

            if len(self.y_temp) > 0:
                t = self.y_temp[-1]
                h = self.y_hum[-1]
                current_hi = t + 0.55 * (1 - (h/100)) * (t - 14.4)
                
                if self.latest_ai_pred > AI_THRESHOLD:
                    self.speak(f"The fan is ON. Although current heat index is {current_hi:.1f}, the AI predicts a rise to {self.latest_ai_pred:.1f}, which is unsafe.")
                else:
                    self.speak(f"The fan is OFF. The AI predicts a safe heat index of {self.latest_ai_pred:.1f}.")
            else:
                self.speak("I am still gathering data.")
                
        except Exception as e:
            print(f"Explain Error: {e}")
            self.speak("I am calculating.")
            
    def voice_shutdown(self):
        """Enter a shutdown mode: stop AI automation and send safe-off commands.

        This method:
        - Speaks an emergency/shutdown message
        - Sends serial commands to turn the fan OFF (`b'N'`) and lights OFF (`b'l'`)
        - Disables AI control locally (`self.ai_enabled = False`)
        - Updates UI labels/buttons to reflect shutdown state

        Important:
            This is a local UI + serial action; it does not terminate the process.
        """
        self.speak("Emergency protocol initiated. Shutting down.")
        self.ser.write(b'N') 
        time.sleep(0.5)
        self.ser.write(b'l') 
        self.ai_enabled = False 
        self.manual_override_status = "None"
        self.btn_voice.configure(text="⚠️ SHUTDOWN MODE", fg_color=COLOR_CARD, text_color=COLOR_DANGER)
        self.mode_label.configure(text="⚠️ SHUTDOWN", text_color=COLOR_DANGER)

    # --- UNIFIED VOICE LOOP ---
    def unified_voice_loop(self):
        """Run the always-on voice assistant loop (wake word + command mode).

        This is designed to be executed in a dedicated daemon thread. It owns the
        microphone and implements a simple two-state voice mode machine:

        - `WAKE`: listens for the wake word “jarvis” (short timeout/phrase limit)
        - `CMD`: listens for a command and executes actions, then returns to `WAKE`

        Supported commands (simple keyword checks):
        - Fan: "fan on", "fan off", "auto"/"reset"
        - Lights: "light on", "light off" (sends `b'L'` / `b'l'` over serial)
        - Info: "status"/"report", "why"/"reason"
        - Safety: "shut down"/"goodbye" (calls `voice_shutdown`)

        UI behavior:
            Updates the sidebar voice button and hint label to show current state.

        Error handling:
            - `WaitTimeoutError` returns the system to WAKE mode
            - `UnknownValueError` is ignored (silence/noise)
            - Other exceptions are printed and may break out to reinitialize mic
        """
        time.sleep(3) 
        self.btn_voice.configure(text="🎙️ WAITING FOR 'JARVIS'", fg_color=COLOR_ACCENT)
        
        while self.running:
            try:
                with sr.Microphone(device_index=1) as source:
                    self.recognizer.energy_threshold = 150  
                    self.recognizer.dynamic_energy_threshold = True 
                    self.recognizer.pause_threshold = 0.6 
                    
                    while self.running:
                        try:
                            # --- MODE 1: WAKE ---
                            if self.voice_mode == "WAKE":
                                self.btn_voice.configure(text="🎙️ WAITING FOR 'JARVIS'", fg_color=COLOR_ACCENT)
                                self.lbl_voice_hint.configure(text="Say 'Jarvis' to wake", text_color=COLOR_SUBTEXT)
                                
                                audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=2)
                                phrase = self.recognizer.recognize_google(audio).lower()
                                
                                if "jarvis" in phrase:
                                    print("✅ JARVIS HEARD!")
                                    self.speak("Yes?") 
                                    self.voice_mode = "CMD" 
                                    
                            # --- MODE 2: COMMAND ---
                            elif self.voice_mode == "CMD":
                                self.btn_voice.configure(text="🔴 LISTENING...", fg_color=COLOR_DANGER)
                                self.lbl_voice_hint.configure(text="Say: 'Status', 'Why', 'Fan On'...", text_color=COLOR_DANGER)
                                
                                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=5)
                                self.btn_voice.configure(text="⏳ PROCESSING...", fg_color=COLOR_WARNING)
                                
                                command = self.recognizer.recognize_google(audio).lower()
                                print(f"Command: {command}")
                                
                                if "on" in command and "fan" in command:
                                    self.ai_enabled = False
                                    self.manual_override_status = "ON"
                                    self.mode_label.configure(text="⚡ VOICE OVERRIDE", text_color=COLOR_WARNING)
                                    self.speak("Fan turned ON.")
                                    self.btn_voice.configure(text="✅ COMMAND EXECUTED", fg_color=COLOR_SUCCESS)
                                    
                                elif "off" in command and "fan" in command:
                                    self.ai_enabled = True
                                    self.manual_override_status = "None"
                                    self.mode_label.configure(text="🤖 AI AUTOMATIC", text_color=COLOR_SUCCESS)
                                    self.speak("Fan OFF. Returning to Auto Mode.")
                                    self.btn_voice.configure(text="✅ COMMAND EXECUTED", fg_color=COLOR_SUCCESS)

                                elif "auto" in command or "reset" in command:
                                    self.ai_enabled = True
                                    self.manual_override_status = "None"
                                    self.mode_label.configure(text="🤖 AI AUTOMATIC", text_color=COLOR_SUCCESS)
                                    self.speak("Auto Mode Engaged.")
                                    self.btn_voice.configure(text="✅ COMMAND EXECUTED", fg_color=COLOR_SUCCESS)
                                
                                elif "light" in command:
                                    if "on" in command:
                                        self.ser.write(b'L')
                                        self.speak("Lights turned ON.")
                                        self.btn_voice.configure(text="✅ LIGHTS ON", fg_color=COLOR_SUCCESS)
                                    elif "off" in command:
                                        self.ser.write(b'l')
                                        self.speak("Lights turned OFF.")
                                        self.btn_voice.configure(text="✅ LIGHTS OFF", fg_color=COLOR_SUCCESS)

                                elif "status" in command or "report" in command:
                                    self.voice_status_report()
                                    self.btn_voice.configure(text="📊 REPORTING", fg_color=COLOR_PRIMARY)
                                    
                                elif "why" in command or "reason" in command:
                                    self.voice_explain_decision()
                                    self.btn_voice.configure(text="🤔 EXPLAINING", fg_color=COLOR_PRIMARY)
                                    
                                elif "shut down" in command or "goodbye" in command:
                                    self.voice_shutdown()
                                
                                else:
                                    self.speak("I didn't catch that.")
                                    self.btn_voice.configure(text="❓ UNKNOWN COMMAND", fg_color=COLOR_CARD)

                                time.sleep(1)
                                self.voice_mode = "WAKE"

                        except sr.WaitTimeoutError:
                            if self.voice_mode == "CMD":
                                self.voice_mode = "WAKE"
                                self.btn_voice.configure(text="❌ TIMED OUT", fg_color=COLOR_CARD)
                                time.sleep(1)
                        except sr.UnknownValueError:
                            pass
                        except Exception as e:
                            print(f"Loop Error: {e}")
                            break 
            except Exception as e:
                print(f"Mic Error: {e}")
                self.btn_voice.configure(text="❌ MIC ERROR", fg_color=COLOR_DANGER)
                time.sleep(3)

    def force_wake(self):
        """Force the voice system into command-listening mode.

        This is bound to the sidebar voice button so the user can manually trigger
        command listening without speaking the wake word.
        """
        self.voice_mode = "CMD"

    def export_csv(self):
        """Export the full `sensor_data` table to a timestamped CSV file.

        Reads all rows from the SQLite database (`DB_NAME`) table `sensor_data` and
        writes them into a new CSV file named like `sensor_log_HHMMSS.csv`.

        UI behavior:
            Temporarily changes the export button text/color to indicate success,
            then restores it after a short delay.

        Failure behavior:
            Swallows exceptions (silent fail) to avoid interrupting the UI.
        """
        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sensor_data")
            with open(f"sensor_log_{datetime.now().strftime('%H%M%S')}.csv", 'w', newline='') as f:
                csv.writer(f).writerows(cursor.fetchall())
            conn.close()
            self.btn_export.configure(text="✅ LOG SAVED", fg_color=COLOR_SUCCESS)
            self.after(2000, lambda: self.btn_export.configure(text="💾 SAVE DATA LOG", fg_color=COLOR_CARD))
        except: pass

    def run_ai_prediction(self):
        """Train a simple model on recent history and forecast “feels like” heat index.

        Pulls the latest 60 `(temp, humid)` samples from the DB and computes a heat
        index-like value for each. Then fits a linear SVR model and forecasts a
        future value.

        Returns:
            A user-facing string for the UI card, e.g. `"27.8 °C (Feels Like)"`, or:
            - `"GATHERING..."` if insufficient data
            - `"Error"` if an exception occurs

        Notes:
            This function does not directly control actuators; `serial_loop` consumes
            its numeric output to decide whether to send `b'P'`/`b'N'`.
        """
        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT temp, humid FROM sensor_data ORDER BY id DESC LIMIT 60")
            data = cursor.fetchall()
            conn.close()

            if len(data) < 10: return "GATHERING..."
            
            heat_indices = []
            for t, h in data:
                hi = t + 0.55 * (1 - (h/100)) * (t - 14.4)
                heat_indices.append(hi)

            y = np.array(heat_indices[::-1]).reshape(-1, 1) 
            x = np.array(range(len(y))).reshape(-1, 1)
            
            model = make_pipeline(StandardScaler(), SVR(kernel='linear', C=1.0, epsilon=0.1))
            model.fit(x, y.ravel())
            
            pred = model.predict([[len(y)+60]])[0]
            return f"{pred:.1f} °C (Feels Like)"
        except: return "Error"

    def serial_loop(self):
        """Continuously read sensor data from serial, log to DB, run AI, and control outputs.

        This method is intended to run in a dedicated daemon thread.

        Responsibilities:
        - Ensure the SQLite table `sensor_data` exists
        - Open the serial port and update the connection status UI
        - Read incoming lines formatted as `temp,humid,light`
        - Insert readings into SQLite with a timestamp
        - Compute an AI prediction string via `run_ai_prediction`
        - If AI is enabled, parse the numeric prediction and send:
          - `b'P'` if prediction > `AI_THRESHOLD`
          - `b'N'` otherwise
        - If AI is disabled and manual override is ON, force `b'P'`
        - Schedule UI updates via `after(0, self.update_dashboard, ...)`

        Failure behavior:
            Most exceptions are swallowed to keep the loop running.
        """
        conn = sqlite3.connect(DB_NAME)
        conn.execute('CREATE TABLE IF NOT EXISTS sensor_data (id INTEGER PRIMARY KEY, timestamp DATETIME, temp REAL, humid REAL, light INTEGER)')
        conn.close()

        try:
            self.ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
            time.sleep(2) 
            self.status_label.configure(text="● SYSTEM ONLINE", text_color=COLOR_SUCCESS)
        except: return

        while self.running:
            if self.ser.in_waiting:
                try:
                    line = self.ser.readline().decode().strip()
                    parts = line.split(',')
                    if len(parts) == 3:
                        t, h, l = parts
                        ts = datetime.now().strftime('%H:%M:%S')
                        conn = sqlite3.connect(DB_NAME)
                        conn.execute("INSERT INTO sensor_data (timestamp, temp, humid, light) VALUES (?,?,?,?)", (ts, t, h, l))
                        conn.commit()
                        conn.close()

                        ai_res = self.run_ai_prediction()

                        if self.ai_enabled:
                            try:
                                pred = float(ai_res.split(' ')[0])
                                self.latest_ai_pred = pred 
                                if pred > AI_THRESHOLD:
                                    self.ser.write(b'P')
                                else:
                                    self.ser.write(b'N')
                            except: pass
                        else:
                            if self.manual_override_status == "ON":
                                self.ser.write(b'P') 
                        
                        self.after(0, self.update_dashboard, t, h, l, ai_res)
                except: pass

    def update_dashboard(self, t, h, l, ai):
        """Update UI labels, buffers, and plots with the latest sensor reading.

        Args:
            t: Temperature reading (string or numeric) from serial.
            h: Humidity reading (string or numeric) from serial.
            l: Light reading (string or numeric) from serial.
            ai: The AI prediction string returned by `run_ai_prediction`.

        Behavior:
        - Updates the four KPI cards
        - Appends values to rolling buffers (up to 60 points)
        - Triggers redraw of the three trend graphs

        Threading:
            This is scheduled onto the Tk main thread via `after(...)`.
        """
        # Update Hero Cards
        self.card_temp.configure(text=f"{t} °C")
        self.card_hum.configure(text=f"{h} %")
        self.card_light.configure(text=f"{l}")
        self.card_ai.configure(text=ai)
        
        # Buffer Data
        self.x_data.append(datetime.now().strftime('%H:%M:%S'))
        self.y_temp.append(float(t))
        self.y_hum.append(float(h))
        self.y_light.append(int(l))
        
        if len(self.x_data) > 60:
            self.x_data.pop(0); self.y_temp.pop(0); self.y_hum.pop(0); self.y_light.pop(0)

        # Update Graphs
        self.update_single_graph(self.ax_temp, self.canvas_temp, self.y_temp, COLOR_DANGER)
        self.update_single_graph(self.ax_hum, self.canvas_hum, self.y_hum, COLOR_PRIMARY)
        self.update_single_graph(self.ax_light, self.canvas_light, self.y_light, COLOR_WARNING)

    def update_single_graph(self, ax, canvas, y, c):
        """Redraw a single trend graph using the current buffered x/y values.

        Args:
            ax: Matplotlib axes object to clear and redraw.
            canvas: TkAgg canvas associated with the figure (used to render).
            y: Y-axis data series (list of numbers).
            c: Color for the line and fill.

        Behavior:
        - Clears the axes and re-applies theme styling
        - Plots a line + subtle fill for a “cyber” look
        - Decimates x-axis ticks for readability
        - Calls `canvas.draw()` to render the updated figure
        """
        ax.clear()
        ax.set_facecolor(COLOR_SIDEBAR) # Keep graph background blended
        
        # Add subtle grid
        ax.grid(True, color=COLOR_CARD, linestyle='-', linewidth=1, alpha=0.3)
        
        # Plot Line
        ax.plot(range(len(self.x_data)), y, color=c, linewidth=2.5)
        
        # Fill area under line for "Cyber" look
        ax.fill_between(range(len(self.x_data)), y, color=c, alpha=0.1)

        # Clean Spines
        ax.spines['bottom'].set_color(COLOR_SUBTEXT)
        ax.spines['left'].set_color(COLOR_SUBTEXT)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.tick_params(colors=COLOR_SUBTEXT)
        
        # Ticks (Decimate)
        step = 10
        if len(self.x_data) > step:
            idx = list(range(0, len(self.x_data), step))
            ax.set_xticks(idx); ax.set_xticklabels([self.x_data[i] for i in idx], rotation=0, ha='center', color=COLOR_SUBTEXT)
        else:
            ax.set_xticks(range(len(self.x_data))); ax.set_xticklabels(self.x_data, rotation=0, ha='center', color=COLOR_SUBTEXT)
            
        canvas.draw()

if __name__ == "__main__":
    app = SmartHomeApp()
    app.mainloop()