import customtkinter as ctk
import serial
import threading
import time
import sqlite3
from datetime import datetime
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates

# --- CONFIGURATION ---
SERIAL_PORT = 'COM3'  # <--- CHECK THIS
BAUD_RATE = 9600
DB_NAME = 'smart_home_data.db'

# --- THEME SETUP ---
ctk.set_appearance_mode("Dark")  # Modes: "System", "Dark", "Light"
ctk.set_default_color_theme("blue")  # Themes: "blue", "green", "dark-blue"

class SmartHomeApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Window Setup
        self.title("Smart Home EnviroControl - Professional Edition")
        self.geometry("900x600")
        
        # Grid Layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- LEFT SIDEBAR ---
        self.sidebar = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        
        self.logo_label = ctk.CTkLabel(self.sidebar, text="EnviroControl", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))
        
        self.status_label = ctk.CTkLabel(self.sidebar, text="System: DISCONNECTED", text_color="red")
        self.status_label.grid(row=1, column=0, padx=20, pady=10)

        # Manual Fan Control
        self.fan_switch = ctk.CTkSwitch(self.sidebar, text="Manual Fan Override", command=self.toggle_fan)
        self.fan_switch.grid(row=2, column=0, padx=20, pady=20)

        # --- MAIN DASHBOARD AREA ---
        self.main_frame = ctk.CTkFrame(self, corner_radius=10)
        self.main_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.main_frame.grid_columnconfigure((0, 1, 2), weight=1)

        # 1. Sensor Cards (Top Row)
        self.card_temp = self.create_sensor_card(0, "Temperature", "00.0 °C", "orange")
        self.card_hum = self.create_sensor_card(1, "Humidity", "00.0 %", "blue")
        self.card_light = self.create_sensor_card(2, "Light Level", "000", "yellow")

        # 2. Graph Area (Middle)
        self.graph_frame = ctk.CTkFrame(self.main_frame)
        self.graph_frame.grid(row=1, column=0, columnspan=3, padx=10, pady=20, sticky="nsew")
        
        # Setup Matplotlib Graph
        self.fig = Figure(figsize=(5, 3), dpi=100)
        self.fig.patch.set_facecolor('#2b2b2b') # Dark background
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor('#2b2b2b')
        self.ax.tick_params(colors='white')
        self.ax.spines['bottom'].set_color('white')
        self.ax.spines['left'].set_color('white')
        
        self.x_data = []
        self.y_data = []
        self.line, = self.ax.plot([], [], 'r-', linewidth=2)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.graph_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Data Threads
        self.running = True
        self.ser = None
        threading.Thread(target=self.serial_loop, daemon=True).start()

    def create_sensor_card(self, col, title, value, color):
        frame = ctk.CTkFrame(self.main_frame, fg_color="#333333")
        frame.grid(row=0, column=col, padx=10, pady=10, sticky="ew")
        
        lbl_title = ctk.CTkLabel(frame, text=title, font=("Arial", 14))
        lbl_title.pack(pady=(10,0))
        
        lbl_val = ctk.CTkLabel(frame, text=value, font=("Arial", 28, "bold"), text_color=color)
        lbl_val.pack(pady=(0,10))
        return lbl_val

    def toggle_fan(self):
        # Optional: Send command back to Arduino if you implement RX on Node B
        pass

    def update_dashboard(self, temp, hum, light):
        self.card_temp.configure(text=f"{temp} °C")
        self.card_hum.configure(text=f"{hum} %")
        self.card_light.configure(text=f"{light}")
        
        # Update Graph
        self.x_data.append(datetime.now())
        self.y_data.append(float(temp))
        if len(self.x_data) > 20: # Keep last 20 points
            self.x_data.pop(0)
            self.y_data.pop(0)
            
        self.ax.clear()
        self.ax.plot(self.x_data, self.y_data, color='#ff7f0e', linewidth=2) # Orange line
        self.ax.set_facecolor('#2b2b2b')
        self.ax.tick_params(colors='gray')
        self.canvas.draw()

    def serial_loop(self):
        # Database Init
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS readings
                     (id INTEGER PRIMARY KEY, timestamp DATETIME, type TEXT, value REAL)''')
        conn.commit()
        conn.close()

        # Serial Connect
        try:
            self.ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
            time.sleep(2)
            self.status_label.configure(text="System: ONLINE", text_color="green")
        except:
            return

        while self.running:
            try:
                if self.ser.in_waiting:
                    line = self.ser.readline().decode().strip()
                    parts = line.split(',')
                    if len(parts) == 3:
                        t, h, l = parts
                        
                        # Save to DB
                        conn = sqlite3.connect(DB_NAME)
                        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        conn.execute("INSERT INTO readings (timestamp, type, value) VALUES (?, ?, ?)", (ts, 'TEMP', t))
                        conn.commit()
                        conn.close()

                        # Update GUI
                        self.after(0, self.update_dashboard, t, h, l)
            except:
                pass

if __name__ == "__main__":
    app = SmartHomeApp()
    app.mainloop()