import customtkinter as ctk
import serial
import threading
import time
import sqlite3
import os
from datetime import datetime
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# --- CONFIGURATION ---
SERIAL_PORT = 'COM5'  # Update this to match your Node B COM port
BAUD_RATE = 9600
DB_NAME = 'smart_home_data.db'

# --- THEME SETUP ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class SmartHomeApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Window Setup
        self.title("Smart Home EnviroControl - Professional Edition")
        self.geometry("1000x700")
        
        # Grid Layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- LEFT SIDEBAR ---
        self.sidebar = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        
        self.logo_label = ctk.CTkLabel(self.sidebar, text="EnviroControl", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))
        
        self.status_label = ctk.CTkLabel(self.sidebar, text="System: DISCONNECTED", text_color="#E74C3C")
        self.status_label.grid(row=1, column=0, padx=20, pady=10)

        self.info_label = ctk.CTkLabel(self.sidebar, text="Logging Active to SQLite", font=("Arial", 10))
        self.info_label.grid(row=2, column=0, padx=20, pady=5)

        # --- MAIN DASHBOARD AREA ---
        self.main_frame = ctk.CTkFrame(self, corner_radius=10)
        self.main_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.main_frame.grid_columnconfigure((0, 1, 2), weight=1)

        # 1. Sensor Cards (Top Row)
        self.card_temp = self.create_sensor_card(0, "Temperature", "00.0 °C", "#FF5733")
        self.card_hum = self.create_sensor_card(1, "Humidity", "00.0 %", "#3498DB")
        self.card_light = self.create_sensor_card(2, "Light Level", "000", "#F1C40F")

        # 2. Graph Area (Middle)
        self.graph_frame = ctk.CTkFrame(self.main_frame)
        self.graph_frame.grid(row=1, column=0, columnspan=3, padx=10, pady=20, sticky="nsew")
        
        # Setup Matplotlib Graph
        self.fig = Figure(figsize=(5, 3), dpi=100)
        self.fig.patch.set_facecolor('#2b2b2b') 
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor('#2b2b2b')
        self.ax.set_title("Live Temperature Trend", color="white", fontsize=12)
        self.ax.tick_params(colors='white', labelsize=8)
        
        self.x_data = []
        self.y_data = []
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.graph_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Data Management
        self.running = True
        self.ser = None
        
        # Start the Serial & Database Thread
        threading.Thread(target=self.serial_loop, daemon=True).start()

    def create_sensor_card(self, col, title, value, color):
        frame = ctk.CTkFrame(self.main_frame, fg_color="#1e1e1e", border_width=1, border_color="#444444")
        frame.grid(row=0, column=col, padx=10, pady=10, sticky="ew")
        
        lbl_title = ctk.CTkLabel(frame, text=title, font=("Arial", 14, "bold"))
        lbl_title.pack(pady=(15,0))
        
        lbl_val = ctk.CTkLabel(frame, text=value, font=("Arial", 32, "bold"), text_color=color)
        lbl_val.pack(pady=(5,15))
        return lbl_val

    def update_dashboard(self, temp, hum, light):
        # Update UI Text
        self.card_temp.configure(text=f"{temp} °C")
        self.card_hum.configure(text=f"{hum} %")
        self.card_light.configure(text=f"{light}")
        
        # Update Graph
        current_time = datetime.now().strftime('%H:%M:%S')
        self.x_data.append(current_time)
        self.y_data.append(float(temp))
        
        if len(self.x_data) > 15: # Keep last 15 points for clarity
            self.x_data.pop(0)
            self.y_data.pop(0)
            
        self.ax.clear()
        self.ax.set_facecolor('#2b2b2b')
        self.ax.plot(self.x_data, self.y_data, color='#FF5733', marker='o', linewidth=2)
        self.ax.tick_params(colors='white', axis='x', rotation=45)
        self.ax.tick_params(colors='white', axis='y')
        self.canvas.draw()

    def serial_loop(self):
        # 1. Initialize Database Schema
        try:
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS readings
                         (id INTEGER PRIMARY KEY, timestamp DATETIME, type TEXT, value REAL)''')
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Database Init Error: {e}")

        # 2. Establish Serial Connection
        try:
            self.ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
            time.sleep(2) # Wait for Arduino reboot
            self.status_label.configure(text="System: ONLINE", text_color="#2ECC71")
        except Exception as e:
            self.status_label.configure(text="System: ERROR", text_color="#E74C3C")
            print(f"Connection Error: {e}")
            return

        # 3. Continuous Data Reading and Logging
        while self.running:
            try:
                if self.ser.in_waiting:
                    # Read the comma-separated line (Temp, Hum, Light)
                    line = self.ser.readline().decode('utf-8').strip()
                    parts = line.split(',')
                    
                    if len(parts) == 3:
                        t, h, l = parts
                        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        
                        # Save to Database
                        # We save 3 separate entries so the inspector script shows all logs
                        db_conn = sqlite3.connect(DB_NAME)
                        db_conn.execute("INSERT INTO readings (timestamp, type, value) VALUES (?, ?, ?)", (ts, 'TEMP', float(t)))
                        db_conn.execute("INSERT INTO readings (timestamp, type, value) VALUES (?, ?, ?)", (ts, 'HUMID', float(h)))
                        db_conn.execute("INSERT INTO readings (timestamp, type, value) VALUES (?, ?, ?)", (ts, 'LIGHT', float(l)))
                        db_conn.commit()
                        db_conn.close()

                        # Update GUI on the main thread
                        self.after(0, self.update_dashboard, t, h, l)
            except Exception as e:
                # Handle unexpected disconnects
                print(f"Runtime Error: {e}")
                time.sleep(1)

if __name__ == "__main__":
    app = SmartHomeApp()
    app.mainloop()