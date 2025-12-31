import customtkinter as ctk
import serial
import threading
import time
import sqlite3
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

# --- ALFRED PERSONALITY DATABASE ---
AUDIO_CACHE = {
    "wake": ["At your service, sir.", "Yes, sir?", "Awaiting instructions.", "Ready."],
    "fan_on": ["Cooling systems engaged.", "Fan activated, sir."],
    "fan_off": ["Fan deactivated.", "Stopping the fan."],
    "light_on": ["Illuminating the room.", "Lights activated."],
    "light_off": ["Going dark.", "Lights deactivated."],
    "auto": ["Automatic control engaged.", "I shall manage the environment."],
    "greeting": ["Good day, sir.", "Systems nominal.", "Welcome back, sir."],
    "thanks": ["My pleasure, sir.", "You are most welcome."],
    "identity": ["I am Jarvis, your digital butler."],
    "confirm": ["Very good, sir.", "Consider it done.", "As you wish."],
    "adjust_cool": ["Understood. Lowering temperature threshold.", "Making it cooler, sir."],
    "adjust_warm": ["Understood. Raising temperature threshold.", "Conserving heat, sir."],
    "error": ["I'm afraid I cannot do that.", "Command invalid."],
    # Scenes
    "scene_study": ["Study Protocol initiated.", "Concentration mode engaged."],
    "scene_cinema": ["Cinema Mode activated.", "Setting the scene."],
    "scene_sleep": ["Sleep Protocol initiated. Goodnight, sir."]
}

# --- COLORS ---
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
        """Initialize the main application window and core runtime state.

        This constructor is responsible for:
            - Configuring the main CTk window (title, size, theme colors, grid).
            - Initializing app-wide flags used by worker threads:
                - `ai_enabled`: automatic fan control enabled/disabled.
                - `manual_override_status`: indicates manual fan override intent.
                - `voice_mode`: "WAKE" (wake word) vs "CMD" (command capture).
                - `running`: global loop flag to stop threads on exit.
            - Initializing “adaptive” control parameters:
                - `current_threshold`: learned temperature setpoint used by the
                  hysteresis controller in `serial_loop`.
                - `hysteresis`: deadband to reduce frequent fan toggling.
            - Initializing audio (pygame) and local TTS cache storage.
            - Building the UI via `setup_sidebar` and `setup_main_area`.
            - Starting background threads for serial I/O, voice, and TTS caching.

        Threading notes:
            Tkinter widgets should be updated on the UI thread. This app uses
            `self.after(...)` for safe UI updates from background threads.
        """
        super().__init__()
        self.title("EnviroControl AI | Adaptive Edition")
        self.geometry("1400x900")
        self.configure(fg_color=COLOR_BG) 
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.recognizer = sr.Recognizer()
        self.ai_enabled = True 
        self.manual_override_status = "None"
        self.voice_mode = "WAKE" 
        self.running = True 
        
        # --- ADAPTIVE BRAIN SETTINGS ---
        self.current_threshold = 27.0 
        self.last_temp = 0.0
        self.hysteresis = 0.5  # Safety buffer for fan
        
        self.cached_files = {} 
        pygame.mixer.init()

        self.x_data = []; self.y_temp = []; self.y_hum = []; self.y_light = []   
        self.last_update_time = None
        self.last_heard = "—"
        self.last_action = "—"

        self.setup_sidebar()
        self.setup_main_area()

        # Start Threads
        threading.Thread(target=self.serial_loop, daemon=True).start()
        threading.Thread(target=self.unified_voice_loop, daemon=True).start()
        threading.Thread(target=self.preload_audio_cache, daemon=True).start()

    def setup_sidebar(self):
        """Create the left sidebar (status, mode, voice, threshold, export).

        Sidebar sections:
            - Branding header
            - System status pill (offline/online)
            - Operating mode card
            - Voice interface button (manual wake)
            - JARVIS FEED (last heard + last action)
            - Learned threshold display
            - CSV export button

        Side effects:
            Defines widget attributes used later for live updates:
                - `status_label`, `mode_label`, `btn_voice`
                - `lbl_heard`, `lbl_action`, `lbl_threshold`
        """
        self.sidebar = ctk.CTkFrame(self, width=280, corner_radius=0, fg_color=COLOR_SIDEBAR)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(10, weight=1) 
        
        ctk.CTkLabel(self.sidebar, text="EnviroControl\nSYSTEMS", font=("Segoe UI", 28, "bold"), text_color=COLOR_PRIMARY).grid(row=0, column=0, padx=20, pady=(50, 10))
        
        self.status_frame = ctk.CTkFrame(self.sidebar, fg_color=COLOR_BG, corner_radius=20)
        self.status_frame.grid(row=1, column=0, padx=20, pady=(0, 30))
        self.status_label = ctk.CTkLabel(self.status_frame, text="● SYSTEM OFFLINE", font=("Segoe UI", 12, "bold"), text_color=COLOR_DANGER)
        self.status_label.pack(padx=15, pady=5)

        ctk.CTkLabel(self.sidebar, text="OPERATING MODE", font=("Segoe UI", 12, "bold"), text_color=COLOR_SUBTEXT).grid(row=2, column=0, padx=20, pady=(10, 0), sticky="w")
        self.mode_card = ctk.CTkFrame(self.sidebar, fg_color=COLOR_CARD, corner_radius=10)
        self.mode_card.grid(row=3, column=0, padx=20, pady=(5, 20), sticky="ew")
        self.mode_label = ctk.CTkLabel(self.mode_card, text="🤖 AI AUTOMATIC", font=("Segoe UI", 16, "bold"), text_color=COLOR_SUCCESS)
        self.mode_label.pack(pady=15)

        ctk.CTkLabel(self.sidebar, text="VOICE INTERFACE", font=("Segoe UI", 12, "bold"), text_color=COLOR_SUBTEXT).grid(row=4, column=0, padx=20, pady=(10, 0), sticky="w")
        self.btn_voice = ctk.CTkButton(self.sidebar, text="🎙️ STANDBY...", command=self.force_wake, font=("Segoe UI", 16, "bold"), fg_color=COLOR_ACCENT, hover_color="#7C3AED", height=60, corner_radius=12)
        self.btn_voice.grid(row=5, column=0, padx=20, pady=(10, 5), sticky="ew")

        ctk.CTkLabel(self.sidebar, text="JARVIS FEED", font=("Segoe UI", 12, "bold"), text_color=COLOR_SUBTEXT).grid(row=6, column=0, padx=20, pady=(18, 0), sticky="w")
        self.feed_card = ctk.CTkFrame(self.sidebar, fg_color=COLOR_CARD, corner_radius=10)
        self.feed_card.grid(row=7, column=0, padx=20, pady=(5, 10), sticky="ew")
        self.lbl_heard = ctk.CTkLabel(self.feed_card, text="Heard: —", font=("Segoe UI", 12, "bold"), text_color=COLOR_TEXT, wraplength=220, justify="left")
        self.lbl_heard.pack(padx=14, pady=(12, 2), anchor="w")
        self.lbl_action = ctk.CTkLabel(self.feed_card, text="Action: —", font=("Segoe UI", 12, "bold"), text_color=COLOR_SUBTEXT, wraplength=220, justify="left")
        self.lbl_action.pack(padx=14, pady=(0, 12), anchor="w")
        
        ctk.CTkLabel(self.sidebar, text="LEARNED THRESHOLD", font=("Segoe UI", 12, "bold"), text_color=COLOR_SUBTEXT).grid(row=8, column=0, padx=20, pady=(20, 0), sticky="w")
        self.threshold_card = ctk.CTkFrame(self.sidebar, fg_color=COLOR_CARD, corner_radius=10)
        self.threshold_card.grid(row=9, column=0, padx=20, pady=(5, 20), sticky="ew")
        self.lbl_threshold = ctk.CTkLabel(self.threshold_card, text=f"{self.current_threshold:.1f} °C", font=("Segoe UI", 24, "bold"), text_color=COLOR_WARNING)
        self.lbl_threshold.pack(pady=10)

        self.btn_export = ctk.CTkButton(self.sidebar, text="💾 SAVE DATA", command=self.export_csv, fg_color=COLOR_CARD, hover_color=COLOR_PRIMARY, text_color="white", height=40)
        self.btn_export.grid(row=11, column=0, padx=20, pady=30, sticky="ew")

    def update_jarvis_feed(self, heard=None, action=None):
        """Update the sidebar JARVIS FEED labels in a thread-safe way.

        Args:
            heard: Optional phrase text to show as the last recognized speech.
            action: Optional action text describing what the system just did.

        Threading:
            Safe to call from any thread. Updates are scheduled onto the Tk
            event loop using `self.after(0, ...)`.
        """
        def _do():
            if heard is not None:
                if hasattr(self, "lbl_heard"): self.lbl_heard.configure(text=f"Heard: {heard}")
            if action is not None:
                if hasattr(self, "lbl_action"): self.lbl_action.configure(text=f"Action: {action}")
        try: self.after(0, _do)
        except: pass

    def safe_ser_write(self, data: bytes):
        """Safely write a command byte to the Arduino serial port.

        Args:
            data: Raw bytes to send (expected one of `b'P'`, `b'N'`, `b'L'`,
                `b'l'`, `b'A'`).

        Returns:
            bool: True if the write was attempted successfully, else False.

        Notes:
            This is best-effort and intentionally swallows exceptions so voice
            and UI flows don't crash when serial isn't connected.
        """
        try:
            if hasattr(self, "ser") and self.ser is not None:
                self.ser.write(data)
                return True
        except: pass
        return False

    def setup_main_area(self):
        """Create and lay out the main dashboard area.

        Builds:
            - Hero cards row (Temp, Humidity, Light, Fan state)
            - Insights strip (rolling averages + system meta)
            - Tabbed charts (Temperature/Humidity/Light)

        Side effects:
            Creates widget attributes updated by `update_dashboard`:
                - `card_temp`, `card_hum`, `card_light`, `card_fan`
                - `mini_*` labels/bars, `lbl_last_update`, `lbl_points`
                - `ax_*`, `canvas_*`
        """
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, padx=30, pady=30, sticky="nsew")
        self.main_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.main_frame.grid_rowconfigure(2, weight=1)

        self.card_temp = self.create_hero_card(0, "TEMP", "00.0 °C", "🌡️", COLOR_DANGER) 
        self.card_hum = self.create_hero_card(1, "HUMIDITY", "00.0 %", "💧", COLOR_PRIMARY)     
        self.card_light = self.create_hero_card(2, "LIGHT", "000", "☀️", COLOR_WARNING)   
        self.card_fan = self.create_hero_card(3, "FAN", "AUTO", "🌀", COLOR_SUCCESS)

        self.insights_frame = ctk.CTkFrame(self.main_frame, fg_color=COLOR_SIDEBAR, corner_radius=15)
        self.insights_frame.grid(row=1, column=0, columnspan=4, padx=10, pady=(20, 0), sticky="nsew")
        self.insights_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.mini_temp_lbl, self.mini_temp_bar = self.create_mini_stat(self.insights_frame, 0, "AVG TEMP (60)", "🌡️", COLOR_DANGER)
        self.mini_hum_lbl, self.mini_hum_bar = self.create_mini_stat(self.insights_frame, 1, "AVG HUM (60)", "💧", COLOR_PRIMARY)
        self.mini_light_lbl, self.mini_light_bar = self.create_mini_stat(self.insights_frame, 2, "AVG LIGHT (60)", "☀️", COLOR_WARNING)

        self.mini_meta_card = ctk.CTkFrame(self.insights_frame, fg_color=COLOR_BG, corner_radius=12)
        self.mini_meta_card.grid(row=0, column=3, padx=10, pady=10, sticky="nsew")
        ctk.CTkLabel(self.mini_meta_card, text="🛰️ SYSTEM", font=("Segoe UI", 12, "bold"), text_color=COLOR_SUBTEXT).pack(pady=(14, 2), padx=16, anchor="w")
        self.lbl_last_update = ctk.CTkLabel(self.mini_meta_card, text="Last: --:--:--", font=("Segoe UI", 14, "bold"), text_color=COLOR_TEXT)
        self.lbl_last_update.pack(pady=(0, 2), padx=16, anchor="w")
        self.lbl_points = ctk.CTkLabel(self.mini_meta_card, text="Points: 0", font=("Segoe UI", 12, "bold"), text_color=COLOR_SUBTEXT)
        self.lbl_points.pack(pady=(0, 14), padx=16, anchor="w")

        self.tab_view = ctk.CTkTabview(self.main_frame, fg_color=COLOR_SIDEBAR, segmented_button_fg_color=COLOR_BG, segmented_button_selected_color=COLOR_PRIMARY, segmented_button_selected_hover_color=COLOR_PRIMARY, corner_radius=15, height=500)
        self.tab_view.grid(row=2, column=0, columnspan=4, padx=0, pady=30, sticky="nsew")
        
        self.ax_temp, self.canvas_temp = self.create_graph(self.tab_view.add(" TEMPERATURE "), COLOR_DANGER)
        self.ax_hum, self.canvas_hum = self.create_graph(self.tab_view.add(" HUMIDITY "), COLOR_PRIMARY)
        self.ax_light, self.canvas_light = self.create_graph(self.tab_view.add(" LIGHT "), COLOR_WARNING)

    def create_hero_card(self, col, title, value, icon, color):
        """Create a hero metric card (large value + label).

        Args:
            col: Column index in the hero row.
            title: Metric title.
            value: Initial value text.
            icon: Emoji/icon prefix.
            color: Value label color.

        Returns:
            CTkLabel for the value field, which callers update later.
        """
        card = ctk.CTkFrame(self.main_frame, fg_color=COLOR_SIDEBAR, corner_radius=15)
        card.grid(row=0, column=col, padx=10, pady=0, sticky="ew")
        ctk.CTkLabel(card, text=f"{icon} {title}", font=("Segoe UI", 12, "bold"), text_color=COLOR_SUBTEXT).pack(pady=(20, 5), padx=20, anchor="w")
        lbl = ctk.CTkLabel(card, text=value, font=("Segoe UI", 36, "bold"), text_color=color)
        lbl.pack(pady=(0, 20), padx=20, anchor="w")
        return lbl

    def create_mini_stat(self, parent, col, title, icon, color):
        """Create a compact insight tile with a numeric label and progress bar.

        Args:
            parent: The frame that will contain the tile.
            col: Grid column index within the parent.
            title: Title text.
            icon: Emoji/icon prefix.
            color: Color for value label + bar.

        Returns:
            (value_label, progress_bar) so the caller can update both.
        """
        card = ctk.CTkFrame(parent, fg_color=COLOR_BG, corner_radius=12)
        card.grid(row=0, column=col, padx=10, pady=10, sticky="nsew")
        ctk.CTkLabel(card, text=f"{icon} {title}", font=("Segoe UI", 12, "bold"), text_color=COLOR_SUBTEXT).pack(pady=(14, 2), padx=16, anchor="w")
        value_lbl = ctk.CTkLabel(card, text="--", font=("Segoe UI", 18, "bold"), text_color=color)
        value_lbl.pack(pady=(0, 8), padx=16, anchor="w")
        bar = ctk.CTkProgressBar(card, height=10, corner_radius=10, fg_color=COLOR_CARD, progress_color=color)
        bar.set(0)
        bar.pack(pady=(0, 14), padx=16, fill="x")
        return value_lbl, bar

    def create_graph(self, parent, color):
        """Create a Matplotlib graph embedded in a CustomTkinter tab.

        Args:
            parent: Tab/frame to host the graph widget.
            color: Series line color.

        Returns:
            Tuple (ax, canvas) used by `update_single_graph` to redraw.
        """
        fig = Figure(figsize=(5, 3), dpi=100)
        fig.patch.set_facecolor(COLOR_SIDEBAR) 
        ax = fig.add_subplot(111)
        ax.set_facecolor(COLOR_SIDEBAR) 
        ax.tick_params(colors=COLOR_SUBTEXT, labelsize=9)
        ax.spines['bottom'].set_color(COLOR_SUBTEXT); ax.spines['left'].set_color(COLOR_SUBTEXT)
        ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
        ax.grid(True, color=COLOR_CARD, linestyle='-', linewidth=1, alpha=0.5)
        ax.plot([], [], color=color, linewidth=3) 
        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)
        return ax, canvas

    def preload_audio_cache(self):
        """Preload TTS audio responses into local MP3 files.

        This converts each phrase in `AUDIO_CACHE` to an MP3 using `edge_tts`
        and stores the result under the `cache/` directory.

        Side effects:
            - Creates `cache/` folder if missing.
            - Populates `self.cached_files[category]` with MP3 paths.

        Threading:
            Intended to run as a daemon thread.
        """
        if not os.path.exists("cache"): os.makedirs("cache")
        voice = "en-GB-RyanNeural"
        print("--- CACHING ALFRED ---")
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
        self.speak_quick("wake") 

    def speak_quick(self, category):
        """Play a random cached response for a given category.

        Args:
            category: Category name in `self.cached_files`.

        Notes:
            - Best-effort: playback failures are silently ignored.
        """
        try:
            if category in self.cached_files:
                pygame.mixer.music.load(random.choice(self.cached_files[category]))
                pygame.mixer.music.play()
        except: pass

    def speak(self, text):
        """Synthesize and speak a custom sentence (non-cached).

        Args:
            text: Text to synthesize using `edge_tts`.

        Threading:
            Runs synthesis/playback on a daemon thread to keep the UI responsive.

        Side effects:
            Creates a temporary `temp.mp3` file and deletes it after playback.
        """
        def _speak():
            try:
                loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
                communicate = edge_tts.Communicate(text, "en-GB-RyanNeural")
                loop.run_until_complete(communicate.save("temp.mp3"))
                pygame.mixer.music.load("temp.mp3"); pygame.mixer.music.play()
                while pygame.mixer.music.get_busy(): time.sleep(0.1)
                pygame.mixer.music.unload(); os.remove("temp.mp3")
            except: pass
        threading.Thread(target=_speak, daemon=True).start()

    def update_threshold_ui(self):
        """Update the sidebar threshold label from `self.current_threshold`."""
        self.lbl_threshold.configure(text=f"{self.current_threshold:.1f} °C")

    # --- VOICE LOOP (VALIDATED + ADAPTIVE) ---
    def unified_voice_loop(self):
        """Continuously listen for wake word and handle voice commands.

        Modes:
            - WAKE: listens briefly for the word "jarvis".
            - CMD: listens longer and parses a command.

        Command handling (current implementation):
            - Preference adjustment:
                - "hot"/"warm": decrease threshold (cooler target)
                - "cold"/"freezing": increase threshold (warmer target)
            - Scene presets:
                - study: lights on + threshold set to 24°C
                - cinema/movie: lights off + fan on (manual override)
                - sleep: lights off + threshold set to 26°C
            - Direct control:
                - fan on/off, auto
                - light/lamp on/off
            - Info:
                - status
            - Safety:
                - shut down

        Threading:
            Runs in a daemon thread. UI updates are performed indirectly via
            `update_jarvis_feed` and widget configuration calls.

        Reliability:
            The loop uses broad exception handling to stay alive even if the
            microphone or recognition service intermittently fails.
        """
        time.sleep(3) 
        while self.running:
            try:
                with sr.Microphone(device_index=1) as source:
                    self.recognizer.energy_threshold = 200  
                    self.recognizer.dynamic_energy_threshold = False 
                    self.recognizer.pause_threshold = 0.5 
                    
                    while self.running:
                        try:
                            if self.voice_mode == "WAKE":
                                self.btn_voice.configure(text="🎙️ STANDBY...", fg_color=COLOR_ACCENT)
                                audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=2)
                                phrase = self.recognizer.recognize_google(audio).lower()
                                self.update_jarvis_feed(heard=phrase)
                                if "jarvis" in phrase:
                                    self.speak_quick("wake")
                                    self.update_jarvis_feed(action="Wake word detected")
                                    self.voice_mode = "CMD" 
                                    
                            elif self.voice_mode == "CMD":
                                self.btn_voice.configure(text="🔴 LISTENING...", fg_color=COLOR_DANGER)
                                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=4)
                                self.btn_voice.configure(text="⚡ EXECUTING...", fg_color=COLOR_WARNING)
                                command = self.recognizer.recognize_google(audio).lower()
                                print(f"Cmd: {command}")
                                self.update_jarvis_feed(heard=command)

                                handled = False

                                # --- 1. DIRECT ADAPTATION (Contextual) ---
                                if "hot" in command or "warm" in command:
                                    self.speak_quick("adjust_cool")
                                    self.current_threshold = max(18.0, self.current_threshold - 1.0) # Limit min 18
                                    self.update_threshold_ui()
                                    self.safe_ser_write(b'P') 
                                    self.update_jarvis_feed(action="Adjusted: Cooler")
                                    handled = True

                                elif "cold" in command or "freezing" in command:
                                    self.speak_quick("adjust_warm")
                                    self.current_threshold = min(32.0, self.current_threshold + 1.0) # Limit max 32
                                    self.update_threshold_ui()
                                    self.safe_ser_write(b'N') 
                                    self.update_jarvis_feed(action="Adjusted: Warmer")
                                    handled = True

                                # --- 2. SCENE MODES ---
                                elif "study" in command:
                                    self.safe_ser_write(b'L') 
                                    self.ai_enabled = True 
                                    self.current_threshold = 24.0 # Focus temp
                                    self.update_threshold_ui()
                                    self.mode_label.configure(text="📚 STUDY", text_color=COLOR_PRIMARY)
                                    self.speak_quick("scene_study")
                                    self.update_jarvis_feed(action="Study mode")
                                    handled = True

                                elif "cinema" in command or "movie" in command:
                                    self.safe_ser_write(b'l'); self.safe_ser_write(b'P') 
                                    self.ai_enabled = False 
                                    self.manual_override_status = "ON"
                                    self.mode_label.configure(text="🎬 CINEMA", text_color=COLOR_WARNING)
                                    self.speak_quick("scene_cinema")
                                    self.update_jarvis_feed(action="Cinema mode")
                                    handled = True

                                elif "sleep" in command:
                                    self.safe_ser_write(b'l')
                                    self.ai_enabled = True 
                                    self.current_threshold = 26.0 # Sleep temp
                                    self.update_threshold_ui()
                                    self.mode_label.configure(text="🌙 SLEEP", text_color=COLOR_ACCENT)
                                    self.speak_quick("scene_sleep")
                                    self.update_jarvis_feed(action="Sleep mode")
                                    handled = True

                                # --- 3. HARDWARE COMMANDS ---
                                elif "fan" in command:
                                    if "on" in command:
                                        self.safe_ser_write(b'P')
                                        self.ai_enabled = False
                                        self.manual_override_status = "ON"
                                        self.mode_label.configure(text="⚡ OVERRIDE", text_color=COLOR_WARNING)
                                        self.speak_quick("fan_on")
                                        self.update_jarvis_feed(action="Fan ON")
                                        handled = True
                                        if self.last_temp < self.current_threshold:
                                            self.current_threshold = max(18.0, self.last_temp - 0.5)
                                            self.update_threshold_ui()

                                    elif "off" in command:
                                        self.safe_ser_write(b'N')
                                        self.ai_enabled = True
                                        self.manual_override_status = "None"
                                        self.mode_label.configure(text="🤖 AUTO", text_color=COLOR_SUCCESS)
                                        self.speak_quick("fan_off")
                                        self.update_jarvis_feed(action="Fan OFF")
                                        handled = True
                                        if self.last_temp > self.current_threshold:
                                            self.current_threshold = min(32.0, self.last_temp + 0.5)
                                            self.update_threshold_ui()

                                elif "auto" in command:
                                    self.safe_ser_write(b'A')
                                    self.ai_enabled = True
                                    self.manual_override_status = "None"
                                    self.mode_label.configure(text="🤖 AUTO", text_color=COLOR_SUCCESS)
                                    self.speak_quick("auto")
                                    self.update_jarvis_feed(action="Auto mode")
                                    handled = True
                                
                                elif "light" in command or "lamp" in command:
                                    if "on" in command:
                                        self.safe_ser_write(b'L')
                                        self.speak_quick("light_on")
                                        self.update_jarvis_feed(action="Lights ON")
                                        handled = True
                                    elif "off" in command:
                                        self.safe_ser_write(b'l')
                                        self.speak_quick("light_off")
                                        self.update_jarvis_feed(action="Lights OFF")
                                        handled = True

                                # --- 4. CHAT ---
                                elif "hello" in command:
                                    self.speak_quick("greeting"); self.update_jarvis_feed(action="Greeting"); handled=True
                                elif "thank" in command:
                                    self.speak_quick("thanks"); self.update_jarvis_feed(action="You're welcome"); handled=True
                                elif "who" in command:
                                    self.speak_quick("identity"); self.update_jarvis_feed(action="Identity"); handled=True
                                elif "status" in command: 
                                    self.speak_quick("confirm")
                                    self.speak(f"Current temp is {self.last_temp} degrees.")
                                    self.update_jarvis_feed(action="Status report")
                                    handled = True
                                elif "shut down" in command:
                                    self.safe_ser_write(b'N'); time.sleep(0.1); self.safe_ser_write(b'l')
                                    self.speak("Shutting down systems.")
                                    self.update_jarvis_feed(action="Shutdown")
                                    handled = True
                                
                                # --- 5. UNKNOWN COMMAND ---
                                else:
                                    self.speak_quick("unknown")
                                    self.update_jarvis_feed(action="Unrecognized command")

                                if not handled: self.btn_voice.configure(text="🎙️ STANDBY...", fg_color=COLOR_ACCENT)
                                time.sleep(0.2)
                                self.voice_mode = "WAKE"

                        except: pass
            except: time.sleep(1)

    def force_wake(self):
        """Manually switch the voice system into command mode.

        This is triggered by the sidebar voice button. It allows issuing a
        command without speaking the wake word.
        """
        self.voice_mode = "CMD"

    def export_csv(self):
        """Export the full `sensor_data` table to a CSV file.

        Output:
            - Writes `log.csv` to the current working directory.

        Data source:
            - Reads all rows from the SQLite database `smart_home_data.db`.

        Failure handling:
            Best-effort: any exception is swallowed to avoid UI disruption.
        """
        try:
            conn = sqlite3.connect(DB_NAME); cursor = conn.cursor()
            cursor.execute("SELECT * FROM sensor_data")
            with open(f"log.csv", 'w', newline='') as f: csv.writer(f).writerows(cursor.fetchall())
            conn.close()
        except: pass

    # --- SERIAL LOOP WITH HYSTERESIS & ADAPTIVE LOGIC ---
    def serial_loop(self):
        """Continuously read serial telemetry, log it to SQLite, and update UI.

        Responsibilities:
            - Ensure the `sensor_data` table exists.
            - Connect to the configured serial port (`SERIAL_PORT`).
            - Parse incoming lines as CSV: temp, humid, light.
            - Persist readings to SQLite with a timestamp.
            - Update connection status indicator.
            - Apply fan control:
                - In AI mode: hysteresis control around `current_threshold`.
                - In manual override: can force fan ON.
            - Schedule UI refresh using `self.after(0, ...)`.

        Threading:
            Runs in a daemon thread.
        """
        conn = sqlite3.connect(DB_NAME)
        conn.execute('CREATE TABLE IF NOT EXISTS sensor_data (id INTEGER PRIMARY KEY, timestamp DATETIME, temp REAL, humid REAL, light INTEGER)')
        conn.close()
        try: self.ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        except: return

        while self.running:
            if self.ser.in_waiting:
                try:
                    line = self.ser.readline().decode().strip()
                    parts = line.split(',')
                    if len(parts) == 3:
                        t, h, l = parts
                        self.last_temp = float(t) 
                        
                        conn = sqlite3.connect(DB_NAME)
                        conn.execute("INSERT INTO sensor_data (timestamp, temp, humid, light) VALUES (?,?,?,?)", (datetime.now().strftime('%H:%M:%S'), t, h, l))
                        conn.commit(); conn.close()
                        
                        self.status_label.configure(text="● SYSTEM ONLINE", text_color=COLOR_SUCCESS)

                        # --- HYSTERESIS PROTECTION (Prevents fan flicker) ---
                        if self.ai_enabled:
                            # Turn ON if significantly hotter than threshold
                            if self.last_temp > (self.current_threshold + self.hysteresis):
                                self.safe_ser_write(b'P')
                            # Turn OFF if significantly cooler than threshold
                            elif self.last_temp < (self.current_threshold - self.hysteresis):
                                self.safe_ser_write(b'N') 
                            # If in between, do NOTHING (keep previous state)
                        else:
                             if self.manual_override_status == "ON": self.safe_ser_write(b'P')
                        
                        self.after(0, self.update_dashboard, t, h, l)
                except: pass

    def update_dashboard(self, t, h, l):
        """Update all dashboard widgets with new sensor readings.

        Args:
            t: Temperature value (string or numeric).
            h: Humidity value (string or numeric).
            l: Light sensor reading (string or numeric).

        Side effects:
            - Updates hero card labels.
            - Updates fan status label based on mode/override.
            - Appends to chart buffers (keeps last 60 points).
            - Updates insight averages and progress bars.
            - Redraws all charts.
        """
        self.card_temp.configure(text=f"{t} °C")
        self.card_hum.configure(text=f"{h} %")
        self.card_light.configure(text=f"{l}")

        if self.ai_enabled:
            self.card_fan.configure(text="AUTO", text_color=COLOR_SUCCESS)
        else:
            if self.manual_override_status == "ON":
                self.card_fan.configure(text="ON", text_color=COLOR_WARNING)
            else:
                self.card_fan.configure(text="MANUAL", text_color=COLOR_WARNING)

        self.x_data.append(datetime.now().strftime('%H:%M:%S'))
        self.y_temp.append(float(t)); self.y_hum.append(float(h)); self.y_light.append(int(l))
        if len(self.x_data) > 60: 
            self.x_data.pop(0); self.y_temp.pop(0); self.y_hum.pop(0); self.y_light.pop(0)

        # Mini insights
        def _clamp01(v):
            try: return max(0.0, min(1.0, float(v)))
            except: return 0.0
        def _avg(values): return (sum(values) / len(values)) if values else 0.0

        avg_t = _avg(self.y_temp); avg_h = _avg(self.y_hum); avg_l = _avg(self.y_light)

        self.mini_temp_lbl.configure(text=f"{avg_t:.1f} °C")
        self.mini_hum_lbl.configure(text=f"{avg_h:.1f} %")
        self.mini_light_lbl.configure(text=f"{avg_l:.0f}")

        self.mini_temp_bar.set(_clamp01(avg_t / 50.0))
        self.mini_hum_bar.set(_clamp01(avg_h / 100.0))
        self.mini_light_bar.set(_clamp01(avg_l / 1023.0))

        self.last_update_time = self.x_data[-1] if self.x_data else None
        self.lbl_last_update.configure(text=f"Last: {self.last_update_time or '--:--:--'}")
        self.lbl_points.configure(text=f"Points: {len(self.x_data)}")

        self.update_single_graph(self.ax_temp, self.canvas_temp, self.y_temp, COLOR_DANGER)
        self.update_single_graph(self.ax_hum, self.canvas_hum, self.y_hum, COLOR_PRIMARY)
        self.update_single_graph(self.ax_light, self.canvas_light, self.y_light, COLOR_WARNING)

    def update_single_graph(self, ax, canvas, y, c):
        """Redraw one chart with downsampled timestamp labels.

        Args:
            ax: Matplotlib Axes to draw into.
            canvas: FigureCanvasTkAgg to redraw.
            y: Sequence of y-values.
            c: Line color.

        Chart details:
            - X values are indices into the ring buffer.
            - Tick labels are taken from `self.x_data` and reduced to ~8 ticks
              to keep the chart readable.
        """
        ax.clear(); ax.set_facecolor(COLOR_SIDEBAR)
        ax.grid(True, color=COLOR_CARD, linestyle='-', linewidth=1, alpha=0.3)
        n = len(self.x_data)
        x = list(range(n))
        ax.plot(x, y, color=c, linewidth=2.5)
        ax.fill_between(x, y, color=c, alpha=0.1)
        if n > 0:
            target_ticks = 8
            if n <= target_ticks: idxs = list(range(n))
            else:
                step = max(1, n // (target_ticks - 1))
                idxs = list(range(0, n, step))
                if idxs[-1] != n - 1: idxs.append(n - 1)
            labels = [self.x_data[i] for i in idxs]
            ax.set_xticks(idxs)
            ax.set_xticklabels(labels, rotation=0, ha='center', fontsize=8, color=COLOR_SUBTEXT)
        ax.spines['bottom'].set_color(COLOR_SUBTEXT); ax.spines['left'].set_color(COLOR_SUBTEXT)
        ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False); ax.tick_params(colors=COLOR_SUBTEXT)
        canvas.draw()

if __name__ == "__main__":
    app = SmartHomeApp()
    app.mainloop()