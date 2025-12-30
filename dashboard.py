import customtkinter as ctk
import serial
import threading
import time
import sqlite3
import numpy as np
import csv 
import speech_recognition as sr 
import pygame
import asyncio
import edge_tts
import os
import random 
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

# --- CACHED PHRASES (Zero Latency) ---
AUDIO_CACHE = {
    "wake": [
        "Yes, sir?",
        "I am here.",
        "Online.",
        "Ready."
    ],
    "fan_on": [
        "Fan activated.",
        "Cooling systems engaged.",
        "Fan is ON."
    ],
    "fan_off": [
        "Fan deactivated.",
        "Powering down cooling.",
        "Fan is OFF."
    ],
    "light_on": [
        "Lights ON.",
        "Illuminating."
    ],
    "light_off": [
        "Lights OFF.",
        "Going dark."
    ],
    "auto": [
        "Auto mode engaged.",
        "AI taking control."
    ],
    # --- INTERACTIVE PERSONALITY ---
    "greeting": [
        "Hello, sir. Systems operational.",
        "Greetings.",
        "Welcome back, sir."
    ],
    "thanks": [
        "You are welcome, sir.",
        "My pleasure.",
        "Anytime."
    ],
    "identity": [
        "I am Jarvis, your environmental control AI.",
        "I am a Python-based intelligent assistant."
    ]
}

# --- THEME COLORS ---
COLOR_BG = "#0F172A"       
COLOR_SIDEBAR = "#1E293B"  
COLOR_CARD = "#334155"     
COLOR_PRIMARY = "#3B82F6"  
COLOR_SUCCESS = "#10B981"  
COLOR_WARNING = "#F59E0B"  
COLOR_DANGER = "#EF4444"   
COLOR_ACCENT = "#8B5CF6"   
COLOR_TEXT = "#F8FAFC"     
COLOR_SUBTEXT = "#94A3B8"  

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue") 

class SmartHomeApp(ctk.CTk):
    def __init__(self):
        """Initialize the EnviroControl (Jarvis Edition) dashboard application.

        Responsibilities:
        - Configure the main window (title, size, theme).
        - Initialize runtime state used by:
            - Serial I/O (Arduino gateway) + DB logging
            - AI prediction + auto-control thresholding
            - Voice recognition (wake word + command mode)
            - Audio playback (cached phrases + dynamic TTS)
        - Initialize audio subsystem (`pygame.mixer`).
        - Build UI (sidebar + main area).
        - Start background threads:
            - `serial_loop`: reads serial, logs to SQLite, triggers AI control, updates UI.
            - `unified_voice_loop`: microphone loop with WAKE/CMD modes.
            - `preload_audio_cache`: pre-generates cached MP3 responses for low latency.

        Notes:
        - Threads are daemon threads so the app can exit cleanly.
        - Cached audio files are stored under the local `cache/` directory.
        """
        super().__init__()

        # Window Setup
        self.title("EnviroControl AI | JARVIS Edition")
        self.geometry("1400x900")
        self.configure(fg_color=COLOR_BG) 
        
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # State Variables
        self.recognizer = sr.Recognizer()
        self.ai_enabled = True 
        self.manual_override_status = "None"
        self.voice_mode = "WAKE" 
        self.running = True 
        self.latest_ai_pred = 0.0 
        
        # Audio Cache Storage
        self.cached_files = {} 

        # Initialize Audio
        pygame.mixer.init()

        # Data Lists
        self.x_data = []    
        self.y_temp = []    
        self.y_hum = []     
        self.y_light = []   

        # UI Setup
        self.setup_sidebar()
        self.setup_main_area()

        # Start Background Threads
        threading.Thread(target=self.serial_loop, daemon=True).start()
        threading.Thread(target=self.unified_voice_loop, daemon=True).start()
        threading.Thread(target=self.preload_audio_cache, daemon=True).start()

    def setup_sidebar(self):
        """Build and lay out the left sidebar UI.

        The sidebar includes:
        - App/logo title
        - Connection status indicator (offline/online)
        - Current operating mode label (AI automatic vs voice override)
        - Voice interface button + hint label
        - AI threshold display
        - Export button to save the database log to CSV

        This method only creates and places widgets; it does not start threads.
        """
        self.sidebar = ctk.CTkFrame(self, width=280, corner_radius=0, fg_color=COLOR_SIDEBAR)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(8, weight=1) 
        
        self.logo_label = ctk.CTkLabel(self.sidebar, text="JARVIS\nSYSTEMS", font=("Segoe UI", 28, "bold"), text_color=COLOR_PRIMARY)
        self.logo_label.grid(row=0, column=0, padx=20, pady=(50, 10))
        
        self.status_frame = ctk.CTkFrame(self.sidebar, fg_color=COLOR_BG, corner_radius=20)
        self.status_frame.grid(row=1, column=0, padx=20, pady=(0, 30))
        self.status_label = ctk.CTkLabel(self.status_frame, text="● SYSTEM OFFLINE", font=("Segoe UI", 12, "bold"), text_color=COLOR_DANGER)
        self.status_label.pack(padx=15, pady=5)

        self.lbl_mode_title = ctk.CTkLabel(self.sidebar, text="OPERATING MODE", font=("Segoe UI", 12, "bold"), text_color=COLOR_SUBTEXT)
        self.lbl_mode_title.grid(row=2, column=0, padx=20, pady=(10, 0), sticky="w")
        
        self.mode_card = ctk.CTkFrame(self.sidebar, fg_color=COLOR_CARD, corner_radius=10)
        self.mode_card.grid(row=3, column=0, padx=20, pady=(5, 20), sticky="ew")
        self.mode_label = ctk.CTkLabel(self.mode_card, text="🤖 AI AUTOMATIC", font=("Segoe UI", 16, "bold"), text_color=COLOR_SUCCESS)
        self.mode_label.pack(pady=15)

        self.lbl_voice_title = ctk.CTkLabel(self.sidebar, text="VOICE INTERFACE", font=("Segoe UI", 12, "bold"), text_color=COLOR_SUBTEXT)
        self.lbl_voice_title.grid(row=4, column=0, padx=20, pady=(10, 0), sticky="w")

        self.btn_voice = ctk.CTkButton(self.sidebar, text="🎙️ INITIALIZING...", command=self.force_wake, font=("Segoe UI", 16, "bold"), fg_color=COLOR_ACCENT, hover_color="#7C3AED", height=60, corner_radius=12)
        self.btn_voice.grid(row=5, column=0, padx=20, pady=(10, 5), sticky="ew")
        
        self.lbl_voice_hint = ctk.CTkLabel(self.sidebar, text="Say 'Jarvis' to wake", font=("Segoe UI", 12), text_color=COLOR_SUBTEXT)
        self.lbl_voice_hint.grid(row=6, column=0, padx=20, pady=(0, 20))

        self.lbl_thresh = ctk.CTkLabel(self.sidebar, text=f"AI TRIGGER: > {AI_THRESHOLD}°C", font=("Segoe UI", 14, "bold"), text_color=COLOR_SUBTEXT)
        self.lbl_thresh.grid(row=7, column=0, padx=20, pady=20)

        self.btn_export = ctk.CTkButton(self.sidebar, text="💾 SAVE DATA LOG", command=self.export_csv, fg_color=COLOR_CARD, hover_color=COLOR_PRIMARY, text_color="white", height=40)
        self.btn_export.grid(row=9, column=0, padx=20, pady=30, sticky="ew")

    def setup_main_area(self):
        """Build and lay out the main dashboard content area.

                Creates:
                - Four KPI cards (temperature, humidity, light level, AI prediction)
                - A tabbed chart area (Matplotlib embedded in Tk) with three trends:
                    temperature, humidity, and light.

                The plots and KPI values are updated by `update_dashboard`, which is scheduled
                from the serial thread using `after(...)` to keep UI updates thread-safe.
        """
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, padx=30, pady=30, sticky="nsew")
        self.main_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.main_frame.grid_rowconfigure(1, weight=1)

        self.card_temp = self.create_hero_card(0, "TEMPERATURE", "00.0 °C", "🌡️", COLOR_DANGER) 
        self.card_hum = self.create_hero_card(1, "HUMIDITY", "00.0 %", "💧", COLOR_PRIMARY)     
        self.card_light = self.create_hero_card(2, "LIGHT LEVEL", "000", "☀️", COLOR_WARNING)   
        self.card_ai = self.create_hero_card(3, "AI PREDICTION", "--.- °C", "🧠", COLOR_ACCENT) 

        self.tab_view = ctk.CTkTabview(self.main_frame, fg_color=COLOR_SIDEBAR, segmented_button_fg_color=COLOR_BG, segmented_button_selected_color=COLOR_PRIMARY, segmented_button_selected_hover_color=COLOR_PRIMARY, corner_radius=15, height=500)
        self.tab_view.grid(row=1, column=0, columnspan=4, padx=0, pady=30, sticky="nsew")
        
        self.ax_temp, self.canvas_temp = self.create_graph(self.tab_view.add("  TEMPERATURE TREND  "), COLOR_DANGER)
        self.ax_hum, self.canvas_hum = self.create_graph(self.tab_view.add("  HUMIDITY TREND  "), COLOR_PRIMARY)
        self.ax_light, self.canvas_light = self.create_graph(self.tab_view.add("  LIGHT TREND  "), COLOR_WARNING)

    def create_hero_card(self, col, title, value, icon, color):
        """Create one KPI “hero card” and return its value label.

        Args:
            col: Column index in the top KPI row.
            title: Card title text (e.g., "TEMPERATURE").
            value: Initial value text displayed on the card.
            icon: Small icon/emoji displayed next to the title.
            color: Text color for the value label.

        Returns:
            The `CTkLabel` used to display the card's value so callers can update it
            later via `.configure(text=...)`.
        """
        card = ctk.CTkFrame(self.main_frame, fg_color=COLOR_SIDEBAR, corner_radius=15)
        card.grid(row=0, column=col, padx=10, pady=0, sticky="ew")
        title_lbl = ctk.CTkLabel(card, text=f"{icon}  {title}", font=("Segoe UI", 12, "bold"), text_color=COLOR_SUBTEXT)
        title_lbl.pack(pady=(20, 5), padx=20, anchor="w")
        value_lbl = ctk.CTkLabel(card, text=value, font=("Segoe UI", 36, "bold"), text_color=color)
        value_lbl.pack(pady=(0, 20), padx=20, anchor="w")
        return value_lbl

    def create_graph(self, parent, color):
        """Create a themed Matplotlib graph embedded into a Tk widget.

        Args:
            parent: The tab/frame container where the graph will be placed.
            color: Line color for the plotted series.

        Returns:
            `(ax, canvas)`:
            - `ax`: Matplotlib axes used for drawing.
            - `canvas`: TkAgg canvas widget used to render the figure.

        Notes:
            The figure/axes styling is matched to the app's dark theme.
        """
        fig = Figure(figsize=(5, 3), dpi=100)
        fig.patch.set_facecolor(COLOR_SIDEBAR) 
        ax = fig.add_subplot(111)
        ax.set_facecolor(COLOR_SIDEBAR) 
        ax.tick_params(colors=COLOR_SUBTEXT, labelsize=9)
        ax.spines['bottom'].set_color(COLOR_SUBTEXT)
        ax.spines['left'].set_color(COLOR_SUBTEXT)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(True, color=COLOR_CARD, linestyle='-', linewidth=1, alpha=0.5)
        ax.plot([], [], color=color, linewidth=3, marker='o', markersize=0) 
        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)
        return ax, canvas

    # --- AUDIO CACHING SYSTEM (The Speed Fix) ---
    def preload_audio_cache(self):
        """Pre-generate and register cached MP3 phrases for low-latency responses.

        This method:
        - Ensures a local `cache/` directory exists.
        - Iterates `AUDIO_CACHE` categories and phrases.
        - Uses `edge_tts` to generate MP3 files (if they are missing).
        - Populates `self.cached_files` with the filenames for each category.
        - Plays a quick "wake" response once caching is complete.

        Threading/event loop:
        - Creates its own asyncio event loop because it typically runs in a
        background thread.

        Failure behavior:
        - Exceptions during individual file generation are swallowed so caching can
        continue for other phrases.
        """
        if not os.path.exists("cache"):
            os.makedirs("cache")

        voice = "en-GB-RyanNeural"
        print("--- CACHING AUDIO FILES ---")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        for category, phrases in AUDIO_CACHE.items():
            self.cached_files[category] = []
            for i, text in enumerate(phrases):
                filename = f"cache/{category}_{i}.mp3"
                if not os.path.exists(filename):
                    try:
                        communicate = edge_tts.Communicate(text, voice)
                        loop.run_until_complete(communicate.save(filename))
                    except: pass
                self.cached_files[category].append(filename)
        
        print("--- AUDIO CACHE COMPLETE ---")
        self.speak_quick("wake") 

    def speak_quick(self, category):
        """Play a cached audio response for near-zero latency.

        Args:
            category: Key in `AUDIO_CACHE` / `self.cached_files` (e.g. "wake",
                "fan_on", "greeting").

        Behavior:
        - Randomly selects a cached MP3 from the requested category.
        - Plays it via `pygame.mixer.music`.
        - Blocks until playback completes (keeps voice feedback crisp).

        Failure behavior:
        - Prints an error if playback fails.
        """
        try:
            if category in self.cached_files and self.cached_files[category]:
                file_to_play = random.choice(self.cached_files[category])
                pygame.mixer.music.load(file_to_play)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    pygame.time.Clock().tick(10)
        except Exception as e:
            print(f"Quick Speak Error: {e}")

    def speak(self, text):
        """Generate dynamic speech audio (slower, but supports arbitrary text).

        Use this when the response contains dynamic content (numbers, sensor values,
        AI predictions) that cannot be fully pre-cached.

        Args:
            text: The text to speak.

        Behavior:
        - Generates an MP3 using `edge_tts` (neural voice) into a temporary file.
        - Plays the file using `pygame`.
        - Deletes the temporary file after playback.
        - Runs the TTS generation/playback in a daemon thread to avoid freezing the UI.

        Failure behavior:
        - Prints a message if neural TTS fails.
        """
        print(f"JARVIS: {text}")
        def _speak_thread():
            try:
                voice = "en-GB-RyanNeural" 
                output_file = f"temp_voice_{int(time.time())}.mp3"
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                communicate = edge_tts.Communicate(text, voice)
                loop.run_until_complete(communicate.save(output_file))
                
                pygame.mixer.music.load(output_file)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    pygame.time.Clock().tick(10)
                pygame.mixer.music.unload()
                os.remove(output_file)
            except Exception as e:
                print(f"Neural Voice Error: {e}")
        threading.Thread(target=_speak_thread, daemon=True).start()

    # --- VOICE HELPERS ---
    def voice_status_report(self):
        """Speak a short system status report using the latest buffered sensor data.

        Reads the most recent values from `self.y_temp` and `self.y_hum`.

        Notes:
        - Uses `self.speak(...)` (dynamic TTS) because the response includes numbers.
        - If buffers are empty, reports that the system is still initializing.
        """
        try:
            if len(self.y_temp) > 0:
                t = self.y_temp[-1]
                h = self.y_hum[-1]
                # Dynamic text -> Must use self.speak()
                self.speak(f"Current temperature is {t} degrees. Humidity is {h} percent. Systems nominal.")
            else:
                self.speak("System is initializing.")
        except:
            self.speak("Sensors unreachable.")

    def voice_explain_decision(self):
        """Explain the current control decision (AI/override) in natural language.

        Behavior:
        - If AI is disabled, explains that Manual Override mode is active.
        - Otherwise, computes a simplified “current heat index” estimate from the
            latest temperature/humidity and compares it with `self.latest_ai_pred`.
        - Speaks why the fan is expected to be on/off based on prediction/threshold.

        Failure behavior:
        - Falls back to a short response if data is missing or an exception occurs.
        """
        try:
            if not self.ai_enabled:
                self.speak("I am in Manual Override mode.")
                return

            if len(self.y_temp) > 0:
                t = self.y_temp[-1]
                h = self.y_hum[-1]
                current_hi = t + 0.55 * (1 - (h/100)) * (t - 14.4)
                
                if self.latest_ai_pred > AI_THRESHOLD:
                    self.speak(f"Fan is ON. Heat index is {current_hi:.1f}, but AI predicts {self.latest_ai_pred:.1f}, which is high.")
                else:
                    self.speak(f"Fan is OFF. AI predicts a safe {self.latest_ai_pred:.1f} degrees.")
            else:
                self.speak("Gathering data.")
        except:
            self.speak("Calculating.")
            
    def voice_shutdown(self):
        """Trigger an emergency shutdown state and send safe-off commands to hardware.

        This method:
        - Speaks a shutdown message (dynamic TTS).
        - Sends serial commands:
            - `b'N'` to ensure the fan is OFF
            - `b'l'` to ensure lights are OFF
        - Disables AI mode locally.
        - Updates the voice button UI to reflect shutdown state.

        Important:
        - This does not stop threads or exit the application; it changes operating mode.
        """
        self.speak("Emergency shutdown.")
        self.ser.write(b'N') 
        time.sleep(0.5)
        self.ser.write(b'l') 
        self.ai_enabled = False 
        self.manual_override_status = "None"
        self.btn_voice.configure(text="⚠️ SHUTDOWN", fg_color=COLOR_CARD, text_color=COLOR_DANGER)

    # --- UNIFIED VOICE LOOP ---
    def unified_voice_loop(self):
        """Run the microphone loop implementing WAKE and COMMAND voice modes.

        Intended to run in its own daemon thread.

        Modes:
        - WAKE: listens briefly for the wake word "jarvis".
        - CMD: listens for a command and executes actions, then returns to WAKE.

        Commands handled (keyword-based):
        - Interactive: "hello", "thank...", "who are you"
        - Fan: "fan on", "fan off"
        - Auto: "auto" / "reset"
        - Light: "light on" / "light off" (serial `b'L'` / `b'l'`)
        - Info: "status" / "report", "why" / "reason"
        - Safety: "shut down" / "goodbye"

        Error handling:
        - `WaitTimeoutError`: returns to WAKE when in CMD mode.
        - `UnknownValueError`: ignored (noise/unrecognized speech).
        - Other exceptions: printed and cause the inner loop to restart.
        """
        time.sleep(3) 
        self.btn_voice.configure(text="🎙️ WAITING FOR 'JARVIS'", fg_color=COLOR_ACCENT)
        
        while self.running:
            try:
                with sr.Microphone(device_index=1) as source:
                    self.recognizer.energy_threshold = 150  
                    self.recognizer.dynamic_energy_threshold = True 
                    self.recognizer.pause_threshold = 0.5 
                    
                    while self.running:
                        try:
                            # --- WAKE MODE ---
                            if self.voice_mode == "WAKE":
                                self.btn_voice.configure(text="🎙️ WAITING FOR 'JARVIS'", fg_color=COLOR_ACCENT)
                                self.lbl_voice_hint.configure(text="Say 'Jarvis' to wake", text_color=COLOR_SUBTEXT)
                                
                                audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=2)
                                phrase = self.recognizer.recognize_google(audio).lower()
                                
                                if "jarvis" in phrase:
                                    print("✅ JARVIS HEARD!")
                                    self.speak_quick("wake") # Cached = Fast
                                    self.voice_mode = "CMD" 
                                    
                            # --- COMMAND MODE ---
                            elif self.voice_mode == "CMD":
                                self.btn_voice.configure(text="🔴 LISTENING...", fg_color=COLOR_DANGER)
                                self.lbl_voice_hint.configure(text="Say: 'Hello', 'Status', 'Fan On'...", text_color=COLOR_DANGER)
                                
                                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=5)
                                self.btn_voice.configure(text="⏳ PROCESSING...", fg_color=COLOR_WARNING)
                                
                                command = self.recognizer.recognize_google(audio).lower()
                                print(f"Command: {command}")
                                
                                # --- INTERACTIVE CHAT (RESTORED!) ---
                                if "hello" in command:
                                    self.speak_quick("greeting")
                                    self.btn_voice.configure(text="💬 GREETING", fg_color=COLOR_PRIMARY)

                                elif "thank" in command: # Matches "thank you", "thanks"
                                    self.speak_quick("thanks")
                                    self.btn_voice.configure(text="💬 POLITE", fg_color=COLOR_PRIMARY)

                                elif "who are you" in command:
                                    self.speak_quick("identity")
                                    self.btn_voice.configure(text="💬 IDENTITY", fg_color=COLOR_PRIMARY)

                                # --- HARDWARE COMMANDS ---
                                elif "on" in command and "fan" in command:
                                    self.ai_enabled = False
                                    self.manual_override_status = "ON"
                                    self.mode_label.configure(text="⚡ VOICE OVERRIDE", text_color=COLOR_WARNING)
                                    self.speak_quick("fan_on")
                                    self.btn_voice.configure(text="✅ COMMAND EXECUTED", fg_color=COLOR_SUCCESS)
                                    
                                elif "off" in command and "fan" in command:
                                    self.ai_enabled = True
                                    self.manual_override_status = "None"
                                    self.mode_label.configure(text="🤖 AI AUTOMATIC", text_color=COLOR_SUCCESS)
                                    self.speak_quick("fan_off")
                                    self.btn_voice.configure(text="✅ COMMAND EXECUTED", fg_color=COLOR_SUCCESS)

                                elif "auto" in command or "reset" in command:
                                    self.ai_enabled = True
                                    self.manual_override_status = "None"
                                    self.mode_label.configure(text="🤖 AI AUTOMATIC", text_color=COLOR_SUCCESS)
                                    self.speak_quick("auto")
                                    self.btn_voice.configure(text="✅ COMMAND EXECUTED", fg_color=COLOR_SUCCESS)
                                
                                elif "light" in command:
                                    if "on" in command:
                                        self.ser.write(b'L')
                                        self.speak_quick("light_on")
                                        self.btn_voice.configure(text="✅ LIGHTS ON", fg_color=COLOR_SUCCESS)
                                    elif "off" in command:
                                        self.ser.write(b'l')
                                        self.speak_quick("light_off")
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
                                    self.btn_voice.configure(text="❓ UNKNOWN", fg_color=COLOR_CARD)

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

        This is bound to the UI voice button so the user can manually trigger CMD mode
        without speaking the wake word.
        """
        self.voice_mode = "CMD"

    def export_csv(self):
        """Export all rows from the `sensor_data` table into a timestamped CSV file.

        Output file name format:
            `sensor_log_HHMMSS.csv`

        UI behavior:
        - Temporarily changes the export button state to indicate success.

        Failure behavior:
        - Exceptions are swallowed to avoid interrupting the UI.
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
        """Compute a heat-index-based forecast using a simple SVR model.

        Steps:
        - Loads up to 60 recent `(temp, humid)` rows from SQLite.
        - Converts them to a heat-index-like value per sample.
        - Fits a linear SVR pipeline (`StandardScaler` + `SVR`).
        - Predicts a future value (offset into the future) and returns a UI string.

        Returns:
        - A formatted string like `"28.4 °C (Feels Like)"`
        - `"GATHERING..."` if there is not enough history.
        - `"Error"` on failure.
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
        """Read serial sensor data, log to SQLite, run AI logic, and update the UI.

        Intended to run in a dedicated daemon thread.

        Responsibilities:
        - Ensure the SQLite table exists.
        - Connect to the configured serial port.
        - Parse incoming lines formatted as CSV: `temp,humid,light`.
        - Insert readings into SQLite with a timestamp.
        - Call `run_ai_prediction` and (if AI is enabled) send control bytes:
            - `b'P'` when prediction > `AI_THRESHOLD`
            - `b'N'` otherwise
        - When manual override is ON, force `b'P'`.
        - Schedule UI updates via `self.after(0, self.update_dashboard, ...)`.

        Failure behavior:
        - Most exceptions are swallowed to keep the loop running.
        - If serial connection fails initially, the method returns.
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
        """Update KPI cards, buffer arrays, and refresh charts with the latest reading.

        Args:
            t: Temperature value (string or numeric).
            h: Humidity value (string or numeric).
            l: Light level value (string or numeric).
            ai: AI prediction string for the KPI card.

        Behavior:
        - Updates the top KPI labels.
        - Appends the new values to rolling buffers (max 60 samples).
        - Triggers redraw of the temperature/humidity/light graphs.

        Threading:
        - Called on the Tk main thread (scheduled by `serial_loop` via `after`).
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
        """Redraw one Matplotlib trend graph using the current buffered data.

        Args:
            ax: Matplotlib axes object to clear and re-draw.
            canvas: TkAgg canvas used to render the figure.
            y: The Y-series to plot.
            c: Color for the line/fill.

        Behavior:
        - Clears axes and reapplies dark theme styling.
        - Plots a line plus a subtle fill for readability.
        - Decimates x-axis tick labels to avoid overcrowding.
        - Calls `canvas.draw()` to render the update.
        """
        ax.clear()
        ax.set_facecolor(COLOR_SIDEBAR) 
        ax.grid(True, color=COLOR_CARD, linestyle='-', linewidth=1, alpha=0.3)
        ax.plot(range(len(self.x_data)), y, color=c, linewidth=2.5)
        ax.fill_between(range(len(self.x_data)), y, color=c, alpha=0.1)
        ax.spines['bottom'].set_color(COLOR_SUBTEXT)
        ax.spines['left'].set_color(COLOR_SUBTEXT)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.tick_params(colors=COLOR_SUBTEXT)
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