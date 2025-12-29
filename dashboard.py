import customtkinter as ctk
import serial
import threading
import time
import sqlite3
import numpy as np
import csv 
import speech_recognition as sr 
from sklearn.svm import SVR
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from datetime import datetime
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# --- SYSTEM CONFIGURATION ---
SERIAL_PORT = 'COM7'  # <--- CHECK THIS
BAUD_RATE = 9600
DB_NAME = 'smart_home_data.db'
AI_THRESHOLD = 27.0   # Fixed Limit

# --- THEME ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue") 

class SmartHomeApp(ctk.CTk):
    """Smart EnviroControl dashboard application.

    High-level responsibilities:
        - Build the CustomTkinter UI (sidebar + main area with graphs).
        - Manage background tasks:
            - Serial loop: read sensors, log to SQLite, send control bytes.
            - Voice loop: wake-word detection + command recognition.
        - Run a simple AI forecast (SVR) used to decide proactive cooling.

    Threading model:
        - GUI runs on the main thread (`mainloop`).
        - Serial + voice logic run in daemon threads.
        - GUI updates from worker threads are scheduled via `self.after(...)`.
    """

    def __init__(self):
        """Initialize runtime state, build UI, and start background threads.

        Initializes:
            - Window configuration (size, grid weights).
            - SpeechRecognition recognizer and voice state machine flags.
            - UI widgets for sidebar, cards, and plots.
            - In-memory data buffers used for plotting.

        Side effects:
            - Starts the serial background thread.
            - Starts the unified voice background thread.
        """
        super().__init__()

        # Window Setup
        self.title("Smart Home AI - Ultimate Edition")
        self.geometry("1280x850")
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Voice & Control State
        # Speech recognizer instance used for both wake word and commands.
        self.recognizer = sr.Recognizer()
        self.ai_enabled = True 
        self.manual_override_status = "None"
        
        # Audio State Machine Flags
        # Voice state machine: "WAKE" listens for the wake word; "CMD" listens for a command.
        self.voice_mode = "WAKE"  # Options: "WAKE" (Listening for Jarvis) or "CMD" (Listening for Command)
        # Global run flag used by background loops.
        self.running = True 

        # UI Setup
        # Build UI widgets before background threads start updating them.
        self.setup_sidebar()
        self.setup_main_area()

        # Data Lists
        # Plot data buffers; updated in `update_dashboard()`.
        self.x_data = []    
        self.y_temp = []    
        self.y_hum = []     
        self.y_light = []   
        
        # Start Threads
        # Serial loop: reads sensor lines, logs to DB, controls actuators.
        threading.Thread(target=self.serial_loop, daemon=True).start()
        
        # Start the UNIFIED Voice Thread (Solves the Crash)
        # Unified voice loop: keeps microphone stream in a single thread to avoid conflicts.
        threading.Thread(target=self.unified_voice_loop, daemon=True).start()

    def setup_sidebar(self):
        """Create the left sidebar UI.

        Adds:
            - App title label
            - Connection status label
            - Current control-mode label
            - Voice status/trigger button and hint label
            - Export button
            - Fixed AI trigger threshold label

        Notes:
            The voice button is primarily a visual indicator but also provides
            a manual trigger via `force_wake()`.
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

        # Voice Button (Visual Indicator Only)
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
        """Create the main dashboard area (KPI cards + tabbed plots).

        Layout:
            - Top row: four KPI cards (temperature, humidity, light, AI forecast).
            - Bottom: tab view hosting three matplotlib graphs.

        Side effects:
            Initializes matplotlib axes and canvases for later updates.
        """
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
        """Create a KPI card and return the label used to update its value.

        Args:
            col: Grid column index for the card.
            title: Card title text.
            value: Initial value text.
            color: Value label color.

        Returns:
            The `CTkLabel` displaying the changing numeric value.
        """
        # A card is a frame with a small title label and a large value label.
        frame = ctk.CTkFrame(self.main_frame, fg_color="#2b2b2b", corner_radius=15)
        frame.grid(row=0, column=col, padx=10, pady=10, sticky="ew")
        ctk.CTkLabel(frame, text=title, font=("Roboto Medium", 14), text_color="#aaaaaa").pack(pady=(15,5))
        lbl = ctk.CTkLabel(frame, text=value, font=("Roboto", 32, "bold"), text_color=color)
        lbl.pack(pady=(0,20))
        return lbl

    def create_graph(self, parent, title, color):
        """Create a matplotlib plot embedded into a CustomTkinter container.

        Args:
            parent: Tab/frame to host the graph.
            title: Plot title (kept for readability/extensibility).
            color: Line color for the plot.

        Returns:
            `(ax, canvas)` where `ax` is the matplotlib axes and `canvas` is
            the TkAgg canvas wrapper.
        """
        # Configure a dark-themed figure/axes and embed it in the UI.
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

    # --- THE MAGIC FIX: SINGLE THREAD FOR EVERYTHING ---
    def unified_voice_loop(self):
        """
        One thread to rule them all. No conflicts.
        Switches between 'WAKE' mode and 'CMD' mode seamlessly.

        Why single-threaded mic handling:
            SpeechRecognition microphone streams can conflict when multiple
            threads try to open/listen simultaneously. Keeping a single thread
            owning the stream avoids crashes and device-lock issues.

        State machine:
            - WAKE: short listens (responsive loop) looking for "jarvis".
            - CMD: longer listen to capture the full command.

        UI behavior:
            Updates the voice button text/color and hint label to reflect state.
        """
        time.sleep(3) # Let GUI load
        self.btn_voice.configure(text="🎙️ Waiting for 'Jarvis'...", fg_color="#5B2C6F")
        
        while self.running:
            try:
                # Device 1 = Laptop Mic. (Change index if needed)
                with sr.Microphone(device_index=1) as source:
                    
                    # 1. ADJUST SENSITIVITY ONCE
                    self.recognizer.energy_threshold = 300
                    self.recognizer.pause_threshold = 0.8 
                    
                    # 2. START LISTENING LOOP (Keep Stream Open)
                    while self.running:
                        try:
                            # --- MODE 1: WAITING FOR JARVIS ---
                            if self.voice_mode == "WAKE":
                                # Idle mode: keep loop responsive via short timeouts.
                                self.btn_voice.configure(text="🎙️ Waiting for 'Jarvis'...", fg_color="#5B2C6F")
                                self.lbl_voice_hint.configure(text="Say 'Jarvis' to wake", text_color="gray")
                                
                                # Short timeout (2s) to keep loop responsive
                                audio = self.recognizer.listen(source, timeout=2, phrase_time_limit=2)
                                phrase = self.recognizer.recognize_google(audio).lower()
                                
                                if "jarvis" in phrase:
                                    print("✅ JARVIS HEARD!")
                                    self.speak("Yes?") # Optional: Needs TTS
                                    self.voice_mode = "CMD" # SWITCH MODES
                                    
                            # --- MODE 2: LISTENING FOR COMMAND ---
                            elif self.voice_mode == "CMD":
                                # Active mode: allow more time to speak a full command.
                                self.btn_voice.configure(text="🔴 LISTENING NOW...", fg_color="#E74C3C")
                                self.lbl_voice_hint.configure(text="Say: 'Turn on fan' or 'Auto'", text_color="#E74C3C")
                                
                                # Longer timeout (5s) for full command
                                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=5)
                                self.btn_voice.configure(text="Processing...", fg_color="#F39C12")
                                
                                command = self.recognizer.recognize_google(audio).lower()
                                print(f"Command: {command}")
                                
                                # --- EXECUTE COMMAND ---
                                if "on" in command and "fan" in command:
                                    # Manual override: fan forced ON (proactive cooling).
                                    self.ai_enabled = False
                                    self.manual_override_status = "ON"
                                    self.mode_label.configure(text="VOICE OVERRIDE", text_color="#F39C12")
                                    self.speak("Fan ON.")
                                    self.btn_voice.configure(text="✅ Fan ON", fg_color="#27AE60")
                                    
                                elif "off" in command and "fan" in command:
                                    # Return to AI automatic mode.
                                    self.ai_enabled = True
                                    self.manual_override_status = "None"
                                    self.mode_label.configure(text="AI AUTOMATIC", text_color="#2ECC71")
                                    self.speak("Fan OFF (Auto).")
                                    self.btn_voice.configure(text="✅ Fan OFF", fg_color="#27AE60")

                                elif "auto" in command or "reset" in command:
                                    # Explicit reset to AI automatic mode.
                                    self.ai_enabled = True
                                    self.manual_override_status = "None"
                                    self.mode_label.configure(text="AI AUTOMATIC", text_color="#2ECC71")
                                    self.speak("Auto Mode.")
                                    self.btn_voice.configure(text="✅ Auto Mode", fg_color="#27AE60")
                                elif "light" in command:
                                    # Light control bytes are sent over serial.
                                    if "on" in command:
                                        self.ser.write(b'L') # Send 'L' to Arduino
                                        self.speak("Lights turned ON.")
                                        self.btn_voice.configure(text="✅ Lights ON", fg_color="#F1C40F") # Yellow color
                                    elif "off" in command:
                                        self.ser.write(b'l') # Send lowercase 'l' to Arduino
                                        self.speak("Lights turned OFF.")
                                        self.btn_voice.configure(text="✅ Lights OFF", fg_color="#27AE60")
                                
                                else:
                                    # Fallback when speech is understood but doesn't match supported commands.
                                    self.btn_voice.configure(text="❓ Unknown", fg_color="gray")

                                # Go back to sleep after command
                                time.sleep(2)
                                self.voice_mode = "WAKE"

                        except sr.WaitTimeoutError:
                            # This is normal. Just loop back.
                            if self.voice_mode == "CMD":
                                # If we timed out waiting for a command, go back to sleep
                                self.voice_mode = "WAKE"
                                self.btn_voice.configure(text="❌ Timed Out", fg_color="gray")
                                time.sleep(1)
                        
                        except sr.UnknownValueError:
                            # Heard noise but no words. Ignore.
                            pass
                        
                        except Exception as e:
                            print(f"Inner Loop Error: {e}")
                            # If stream breaks, break inner loop to re-open mic
                            break 
                            
            except Exception as e:
                print(f"Mic Connection Error: {e}")
                self.btn_voice.configure(text="❌ Mic Error", fg_color="red")
                time.sleep(3) # Wait before retrying

    def force_wake(self):
        """Manually switch the voice loop into command-listening mode.

        Intended to be triggered by the sidebar voice button.

        Side effects:
            Sets `self.voice_mode` to "CMD" so the unified voice loop will
            capture a full command on its next iteration.
        """
        self.voice_mode = "CMD"

    def speak(self, text):
        """Provide assistant feedback output.

        Currently implemented as a console print placeholder.

        Args:
            text: Message to output.
        """
        print(f"JARVIS: {text}")

    def export_csv(self):
        """Export all stored sensor readings to a timestamped CSV file.

        Reads all rows from SQLite table `sensor_data` and writes them to a file
        in the current working directory.

        Side effects:
            - Opens the SQLite database configured by `DB_NAME`.
            - Writes a CSV file named `sensor_log_HHMMSS.csv`.
            - Updates the export button text/color on success.

        Error handling:
            Uses a broad `try/except` to avoid crashing the UI if the database
            is missing/locked; failures are silently ignored.
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

    def run_ai_prediction(self):
        """Compute a temperature forecast using an SVR model.

        Steps:
            - Pull the most recent temperature samples from SQLite.
            - Fit a simple SVR regression pipeline (StandardScaler + linear SVR).
            - Predict a future point (offset by 60 steps).

        Returns:
            - "Gathering..." if not enough data exists to train.
            - "Error" if DB/model operations fail.
            - Otherwise a formatted string like "28.4 °C".

        Notes:
            This method is called from the serial background thread.
        """
        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT temp, humid FROM sensor_data ORDER BY id DESC LIMIT 60")
            data = cursor.fetchall()
            conn.close()

            if len(data) < 10: return "Gathering..."
            # Optional/experimental: compute heat index list (not currently used in model training).
            heat_indices = []
            for t, h in data:
                hi = t + 0.55 * (1 - (h/100)) * (t - 14.4)
                heat_indices.append(hi)
            # Prepare supervised training arrays.
            y = np.array([row[0] for row in data][::-1]).reshape(-1, 1) 
            x = np.array(range(len(y))).reshape(-1, 1)
            
            model = make_pipeline(StandardScaler(), SVR(kernel='linear', C=1.0, epsilon=0.1))
            model.fit(x, y.ravel())
            return f"{model.predict([[len(y)+60]])[0]:.1f} °C"
        except: return "Error"

    def serial_loop(self):
        """Background loop: read serial sensor values, store, forecast, control.

        Responsibilities:
            - Ensure `sensor_data` table exists in SQLite.
            - Connect to serial port (`SERIAL_PORT`, `BAUD_RATE`).
            - Parse incoming CSV lines: `temp,humid,light`.
            - Insert readings into the database.
            - Run AI forecast and send control bytes to Arduino:
                - `P` = proactive cooling
                - `N` = normal
            - Trigger UI updates via `self.after(...)`.

        Threading:
            Runs as a daemon thread started from `__init__()`.
        """
        # Ensure the database schema exists.
        conn = sqlite3.connect(DB_NAME)
        conn.execute('CREATE TABLE IF NOT EXISTS sensor_data (id INTEGER PRIMARY KEY, timestamp DATETIME, temp REAL, humid REAL, light INTEGER)')
        conn.close()

        try:
            # Connect to the serial gateway.
            self.ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
            time.sleep(2) 
            self.status_label.configure(text="● SYSTEM ONLINE", text_color="#2ECC71")
        except: return

        while self.running:
            # Only read when data is available.
            if self.ser.in_waiting:
                try:
                    line = self.ser.readline().decode().strip()
                    parts = line.split(',')
                    if len(parts) == 3:
                        t, h, l = parts
                        ts = datetime.now().strftime('%H:%M:%S')
                        # Store the new sample.
                        conn = sqlite3.connect(DB_NAME)
                        conn.execute("INSERT INTO sensor_data (timestamp, temp, humid, light) VALUES (?,?,?,?)", (ts, t, h, l))
                        conn.commit()
                        conn.close()

                        # Run AI forecast.
                        ai_res = self.run_ai_prediction()

                        if self.ai_enabled:
                            try:
                                pred = float(ai_res.split(' ')[0])
                                if pred > AI_THRESHOLD:
                                    # Proactive cooling command.
                                    self.ser.write(b'P')
                                else:
                                    # Normal mode command.
                                    self.ser.write(b'N')
                            except: pass
                        else:
                            if self.manual_override_status == "ON":
                                # Force proactive cooling while in manual override.
                                self.ser.write(b'P') 
                        
                        # Schedule a UI update on the main thread.
                        self.after(0, self.update_dashboard, t, h, l, ai_res)
                except: pass

    def update_dashboard(self, t, h, l, ai):
        """Update KPI cards, append to buffers, and refresh plots.

        Args:
            t: Temperature value (string convertible to float).
            h: Humidity value (string convertible to float).
            l: Light level value (string convertible to int).
            ai: AI forecast display string.

        Side effects:
            - Updates the four KPI labels.
            - Appends to plot data buffers.
            - Trims buffers to a max history length.
            - Redraws all three plots.
        """
        # Update KPI card text.
        self.card_temp.configure(text=f"{t} °C")
        self.card_hum.configure(text=f"{h} %")
        self.card_light.configure(text=f"{l}")
        self.card_ai.configure(text=ai)
        
        # Append new point into graph buffers.
        self.x_data.append(datetime.now().strftime('%H:%M:%S'))
        self.y_temp.append(float(t))
        self.y_hum.append(float(h))
        self.y_light.append(int(l))
        
        # Keep only the latest 60 points for performance and readability.
        if len(self.x_data) > 60:
            self.x_data.pop(0); self.y_temp.pop(0); self.y_hum.pop(0); self.y_light.pop(0)

        # Redraw each plot.
        self.update_single_graph(self.ax_temp, self.canvas_temp, self.y_temp, '#FF5733')
        self.update_single_graph(self.ax_hum, self.canvas_hum, self.y_hum, '#3498DB')
        self.update_single_graph(self.ax_light, self.canvas_light, self.y_light, '#F1C40F')

    def update_single_graph(self, ax, canvas, y, c):
        """Redraw one matplotlib graph using the latest buffered values.

        Args:
            ax: Matplotlib Axes to clear and redraw.
            canvas: TkAgg canvas wrapper to refresh.
            y: Y-series values list.
            c: Line color.

        Notes:
            X-axis uses the index of `self.x_data` and shows timestamps.
            Tick labels are decimated to reduce clutter.
        """
        # Reset axes and plot current window.
        ax.clear(); ax.set_facecolor('#242424'); ax.grid(True, linestyle='--', linewidth=0.5)
        ax.plot(range(len(self.x_data)), y, color=c, linewidth=2)
        step = 10
        if len(self.x_data) > step:
            # Decimate x tick labels for readability.
            idx = list(range(0, len(self.x_data), step))
            ax.set_xticks(idx); ax.set_xticklabels([self.x_data[i] for i in idx], rotation=30, ha='right', color='white')
        else:
            ax.set_xticks(range(len(self.x_data))); ax.set_xticklabels(self.x_data, rotation=30, ha='right', color='white')
        ax.tick_params(colors='white')
        canvas.draw()

if __name__ == "__main__":
    app = SmartHomeApp()
    app.mainloop()