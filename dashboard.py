import customtkinter as ctk
import serial
import threading
import time
import sqlite3
import numpy as np
import csv 
import speech_recognition as sr # <--- NEW IMPORT
from sklearn.svm import SVR
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from datetime import datetime
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# --- SYSTEM CONFIGURATION ---
SERIAL_PORT = 'COM5'  # <--- CHECK THIS
BAUD_RATE = 9600
DB_NAME = 'smart_home_data.db'
AI_EMERGENCY_TEMP_C = 27.0  # Fixed AI trigger temperature (no slider)

# --- THEME ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue") 

class SmartHomeApp(ctk.CTk):
    def __init__(self):
        """Initialize the main application window and runtime state.

        Sets up the CustomTkinter window, initializes voice recognition,
        creates the sidebar + main dashboard UI, allocates in-memory series
        buffers for plotting, and starts the background serial thread.

        Side effects:
            - Spawns a daemon thread running `serial_loop()`.
            - Initializes GUI widgets and plot canvases.
        """
        super().__init__()

        # Window Setup
        self.title("Smart Home AI - Ultimate Edition")
        self.geometry("1280x850")
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Voice & Control State
        self.recognizer = sr.Recognizer()
        self.ai_enabled = True # Default: AI is in charge
        self.manual_override_status = "None"

        # UI Setup
        self.setup_sidebar()
        self.setup_main_area()

        # Data Lists
        self.x_data = []    
        self.y_temp = []    
        self.y_hum = []     
        self.y_light = []   
        self.running = True 

        # Start Thread
        threading.Thread(target=self.serial_loop, daemon=True).start()

    def setup_sidebar(self):
        """Build the left sidebar UI.

        Creates and places:
            - App title/logo label
            - Connection status label
            - Control mode status label
            - Voice command button
            - Export button
            - Fixed AI trigger temperature label (uses `AI_EMERGENCY_TEMP_C`)

        Notes:
            The AI trigger temperature is intentionally fixed (no slider) per
            project requirement.
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

        # --- NEW: VOICE BUTTON ---
        self.btn_voice = ctk.CTkButton(self.sidebar, text="🎙️ Voice Command", command=self.listen_to_voice, fg_color="#8E44AD", hover_color="#9B59B6")
        self.btn_voice.grid(row=4, column=0, padx=20, pady=(30, 10))

        # Export Button
        self.btn_export = ctk.CTkButton(self.sidebar, text="💾 Export Data", command=self.export_csv, fg_color="#27AE60")
        self.btn_export.grid(row=5, column=0, padx=20, pady=10)

        # Fixed AI trigger temperature (no slider)
        ctk.CTkLabel(self.sidebar, text="AI Trigger Temp:", anchor="w").grid(row=6, column=0, padx=20, pady=(20, 0))
        ctk.CTkLabel(self.sidebar, text=f"{AI_EMERGENCY_TEMP_C:.1f} °C (fixed)", text_color="#3498DB").grid(row=7, column=0, padx=20, pady=(5, 10))

    def setup_main_area(self):
        """Build the main dashboard area (cards + tabbed plots).

        Creates:
            - Four KPI cards (temperature, humidity, light, AI forecast)
            - A tab view with three matplotlib plots (temp/humidity/light)

        Side effects:
            - Initializes matplotlib axes/canvases for later redraw.
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
        """Create a KPI card for the top row.

        Args:
            col: Grid column index within the main_frame.
            title: Card title string.
            value: Initial value text displayed.
            color: Text color for the value label.

        Returns:
            The value label widget, so the caller can update it later.
        """
        frame = ctk.CTkFrame(self.main_frame, fg_color="#2b2b2b", corner_radius=15)
        frame.grid(row=0, column=col, padx=10, pady=10, sticky="ew")
        ctk.CTkLabel(frame, text=title, font=("Roboto Medium", 14), text_color="#aaaaaa").pack(pady=(15,5))
        lbl = ctk.CTkLabel(frame, text=value, font=("Roboto", 32, "bold"), text_color=color)
        lbl.pack(pady=(0,20))
        return lbl

    def create_graph(self, parent, title, color):
        """Create a matplotlib line plot embedded into a Tk container.

        Args:
            parent: The tab/frame to host the plot canvas.
            title: Plot title (currently not shown, kept for extensibility).
            color: Line color for the series.

        Returns:
            (ax, canvas) tuple for future updates.
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

    # --- VOICE ASSISTANT LOGIC ---
    def listen_to_voice(self):
        """Start a background voice-recognition session.

        Runs microphone capture + speech-to-text in a daemon thread to avoid
        blocking the GUI event loop.

        Recognized commands (simple keyword matching):
            - "fan on": disables AI mode and forces fan ON
            - "auto" or "reset": re-enables AI automatic control

        Side effects:
            - Updates UI button text/color while listening.
            - Modifies `self.ai_enabled` and `self.manual_override_status`.
        """
        def _listen():
            self.btn_voice.configure(text="Listening...", fg_color="red")
            try:
                with sr.Microphone() as source:
                    self.recognizer.adjust_for_ambient_noise(source)
                    audio = self.recognizer.listen(source, timeout=3)
                    command = self.recognizer.recognize_google(audio).lower()
                    print(f"Voice Heard: {command}")
                    
                    if "fan" in command and "on" in command:
                        self.ai_enabled = False
                        self.manual_override_status = "ON"
                        self.mode_label.configure(text="VOICE OVERRIDE", text_color="#F39C12")
                        self.speak("Fan turned on.")
                    
                    elif "auto" in command or "reset" in command:
                        self.ai_enabled = True
                        self.manual_override_status = "None"
                        self.mode_label.configure(text="AI AUTOMATIC", text_color="#2ECC71")
                        self.speak("AI mode engaged.")

            except Exception as e:
                print(f"Voice Error: {e}")
            
            self.btn_voice.configure(text="🎙️ Voice Command", fg_color="#8E44AD")

        threading.Thread(target=_listen, daemon=True).start()

    def speak(self, text):
        """Output assistant speech.

        Currently implemented as a console print placeholder.

        Args:
            text: Text to 'speak'.
        """
        # Placeholder for TTS if you add pyttsx3 later
        print(f"JARVIS: {text}")

    def export_csv(self):
        """Export all rows from the SQLite sensor table to a CSV file.

        Writes a CSV file named like `sensor_log_HHMMSS.csv` in the current
        working directory.

        Side effects:
            - Reads from SQLite `sensor_data`.
            - Writes a CSV file.
            - Updates the export button UI on success.
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
        """Train a lightweight SVR model and forecast a future temperature.

        Pulls the latest 60 temperature samples from SQLite and fits a simple
        linear-kernel SVR pipeline (with standardization). Returns a formatted
        string containing the predicted temperature.

        Returns:
            A string like "28.3 °C", or "Gathering..." when insufficient data,
            or "Error" on failure.
        """
        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT temp FROM sensor_data ORDER BY id DESC LIMIT 60")
            data = cursor.fetchall()
            conn.close()
            if len(data) < 10: return "Gathering..."
            y = np.array([row[0] for row in data][::-1]).reshape(-1, 1) 
            x = np.array(range(len(y))).reshape(-1, 1)
            model = make_pipeline(StandardScaler(), SVR(kernel='linear', C=1.0, epsilon=0.1))
            model.fit(x, y.ravel())
            return f"{model.predict([[len(y)+60]])[0]:.1f} °C"
        except: return "Error"

    def serial_loop(self):
        """Background loop: read serial sensor data, persist, predict, control.

        Responsibilities:
            - Ensure SQLite table exists.
            - Open the configured serial port and keep reading CSV lines.
            - Insert each reading into SQLite.
            - Run AI forecast and decide whether to send control bytes.
            - Schedule GUI updates via `self.after()`.

        Threading:
            Runs on a daemon thread started from `__init__()`.
        """
        conn = sqlite3.connect(DB_NAME)
        conn.execute('CREATE TABLE IF NOT EXISTS sensor_data (id INTEGER PRIMARY KEY, timestamp DATETIME, temp REAL, humid REAL, light INTEGER)')
        conn.close()

        try:
            self.ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
            time.sleep(2) 
            self.status_label.configure(text="● SYSTEM ONLINE", text_color="#2ECC71")
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

                        # --- CONTROL LOGIC (The Smart Brain) ---
                        if self.ai_enabled:
                            # 1. AI MODE
                            try:
                                pred = float(ai_res.split(' ')[0])
                                thresh = AI_EMERGENCY_TEMP_C
                                if pred > thresh:
                                    self.ser.write(b'P') # Proactive Cool
                                else:
                                    self.ser.write(b'N') # Normal
                            except: pass
                        else:
                            # 2. VOICE OVERRIDE MODE
                            if self.manual_override_status == "ON":
                                self.ser.write(b'P') # Force ON
                        
                        # Update GUI
                        self.after(0, self.update_dashboard, t, h, l, ai_res)
                except: pass

    def update_dashboard(self, t, h, l, ai):
        """Update KPI cards and append points to plot series.

        Args:
            t: Temperature value (string convertible to float).
            h: Humidity value (string convertible to float).
            l: Light level value (string convertible to int).
            ai: AI forecast string (already formatted).

        Side effects:
            - Updates the four KPI labels.
            - Appends to time-series buffers and trims to last 60 samples.
            - Triggers redraw of all three graphs.
        """
        self.card_temp.configure(text=f"{t} °C")
        self.card_hum.configure(text=f"{h} %")
        self.card_light.configure(text=f"{l}")
        self.card_ai.configure(text=ai)
        
        self.x_data.append(datetime.now().strftime('%H:%M:%S'))
        self.y_temp.append(float(t))
        self.y_hum.append(float(h))
        self.y_light.append(int(l))
        
        if len(self.x_data) > 60:
            self.x_data.pop(0); self.y_temp.pop(0); self.y_hum.pop(0); self.y_light.pop(0)

        self.update_single_graph(self.ax_temp, self.canvas_temp, self.y_temp, '#FF5733')
        self.update_single_graph(self.ax_hum, self.canvas_hum, self.y_hum, '#3498DB')
        self.update_single_graph(self.ax_light, self.canvas_light, self.y_light, '#F1C40F')

    def update_single_graph(self, ax, canvas, y, c):
        """Redraw a single matplotlib axes with the latest buffered values.

        Args:
            ax: The matplotlib axes to draw into.
            canvas: The TkAgg canvas wrapper to refresh.
            y: The y-series values list.
            c: Line color string.

        Notes:
            Uses `self.x_data` for x-axis labels and decimates tick labels
            to avoid clutter.
        """
        ax.clear(); ax.set_facecolor('#242424'); ax.grid(True, linestyle='--', linewidth=0.5)
        ax.plot(range(len(self.x_data)), y, color=c, linewidth=2)
        step = 10
        if len(self.x_data) > step:
            idx = list(range(0, len(self.x_data), step))
            ax.set_xticks(idx); ax.set_xticklabels([self.x_data[i] for i in idx], rotation=30, ha='right', color='white')
        else:
            ax.set_xticks(range(len(self.x_data))); ax.set_xticklabels(self.x_data, rotation=30, ha='right', color='white')
        ax.tick_params(colors='white')
        canvas.draw()

if __name__ == "__main__":
    app = SmartHomeApp()
    app.mainloop()