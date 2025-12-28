import customtkinter as ctk
import serial
import threading
import time
import sqlite3
import numpy as np
import csv # Added for Export Feature
from sklearn.svm import SVR
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from datetime import datetime
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.ticker as ticker

# --- SYSTEM CONFIGURATION ---
SERIAL_PORT = 'COM5'  # <--- CHECK THIS
BAUD_RATE = 9600
DB_NAME = 'smart_home_data.db'

# --- UI THEME CONFIGURATION ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue") 

class SmartHomeApp(ctk.CTk):
    """
    Main Application Class for the Smart Home AI Dashboard.
    """
    
    def __init__(self):
        super().__init__()

        # 1. Window Configuration
        self.title("Smart Home AI - Ultimate Edition")
        self.geometry("1280x850")
        
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # 2. UI Initialization
        self.setup_sidebar()
        self.setup_main_area()

        # 3. Data Structures
        self.x_data = []    
        self.y_temp = []    
        self.y_hum = []     
        self.y_light = []   
        self.running = True 

        # 4. Start Background Thread
        threading.Thread(target=self.serial_loop, daemon=True).start()

    def setup_sidebar(self):
        """
        Builds the left-hand navigation, status, and Export Button.
        """
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        
        # Logo
        self.logo_label = ctk.CTkLabel(self.sidebar, text="EnviroControl AI", 
                                     font=ctk.CTkFont(size=24, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(40, 20))
        
        # Status Indicators
        self.lbl_status_title = ctk.CTkLabel(self.sidebar, text="CONNECTION STATUS:", 
                                           font=ctk.CTkFont(size=12, weight="bold"))
        self.lbl_status_title.grid(row=1, column=0, padx=20, pady=(20, 5), sticky="w")

        self.status_label = ctk.CTkLabel(self.sidebar, text="● DISCONNECTED", 
                                       text_color="#E74C3C", font=ctk.CTkFont(size=14))
        self.status_label.grid(row=2, column=0, padx=20, pady=5, sticky="w")

        # Actuator Status
        self.lbl_fan_title = ctk.CTkLabel(self.sidebar, text="ACTIVE CONTROL:", 
                                        font=ctk.CTkFont(size=12, weight="bold"))
        self.lbl_fan_title.grid(row=3, column=0, padx=20, pady=(20, 5), sticky="w")

        self.fan_status_label = ctk.CTkLabel(self.sidebar, text="Standby", 
                                           text_color="gray", font=ctk.CTkFont(size=14))
        self.fan_status_label.grid(row=4, column=0, padx=20, pady=5, sticky="w")

        # --- NEW FEATURE: EXPORT BUTTON ---
        self.btn_export = ctk.CTkButton(self.sidebar, text="💾 Export Data (CSV)", 
                                      command=self.export_csv, 
                                      fg_color="#27AE60", hover_color="#2ECC71")
        self.btn_export.grid(row=5, column=0, padx=20, pady=(40, 10))

        # Footer
        self.footer_label = ctk.CTkLabel(self.sidebar, text="v3.1 Final\nSVR Model Active", 
                                       font=ctk.CTkFont(size=10), text_color="gray")
        self.footer_label.grid(row=6, column=0, padx=20, pady=20, sticky="s")

    def setup_main_area(self):
        """
        Builds the main dashboard content.
        UPDATED: Titles now include professional Unicode Icons.
        """
        self.main_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.main_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.main_frame.grid_rowconfigure(1, weight=1)

        # --- Top Row: Sensor Cards (Updated Icons) ---
        self.card_temp = self.create_card(0, "🌡️ Temp (Live)", "00.0 °C", "#FF5733") 
        self.card_hum = self.create_card(1, "💧 Humidity", "00.0 %", "#3498DB")     
        self.card_light = self.create_card(2, "☀️ Light Level", "000", "#F1C40F")   
        self.card_ai = self.create_card(3, "🧠 AI Forecast (1m)", "--.- °C", "#9B59B6") 

        # --- Middle Row: Tabbed Graphs ---
        self.tab_view = ctk.CTkTabview(self.main_frame, width=800, height=500)
        self.tab_view.grid(row=1, column=0, columnspan=4, padx=5, pady=20, sticky="nsew")
        
        # Add Tabs
        self.tab_temp = self.tab_view.add("Temperature")
        self.tab_hum = self.tab_view.add("Humidity")
        self.tab_light = self.tab_view.add("Light")

        # Initialize Graphs in Tabs (Updated Titles)
        self.ax_temp, self.canvas_temp = self.create_graph(self.tab_temp, "🌡️ Temperature Trend", "#FF5733")
        self.ax_hum, self.canvas_hum = self.create_graph(self.tab_hum, "💧 Humidity Trend", "#3498DB")
        self.ax_light, self.canvas_light = self.create_graph(self.tab_light, "☀️ Light Level Trend", "#F1C40F")

    def create_card(self, col, title, value, color):
        frame = ctk.CTkFrame(self.main_frame, fg_color="#2b2b2b", corner_radius=15, border_width=1, border_color="#3a3a3a")
        frame.grid(row=0, column=col, padx=10, pady=10, sticky="ew")
        
        ctk.CTkLabel(frame, text=title, font=("Roboto Medium", 14), text_color="#aaaaaa").pack(pady=(15,5))
        lbl = ctk.CTkLabel(frame, text=value, font=("Roboto", 32, "bold"), text_color=color)
        lbl.pack(pady=(0,20))
        return lbl

    def create_graph(self, parent, title, line_color):
        fig = Figure(figsize=(5, 3), dpi=100)
        fig.patch.set_facecolor('#242424') 
        
        ax = fig.add_subplot(111)
        ax.set_facecolor('#242424')
        ax.tick_params(colors='white', labelsize=8)
        ax.spines['bottom'].set_color('white')
        ax.spines['left'].set_color('white')
        ax.spines['top'].set_color('#242424')
        ax.spines['right'].set_color('#242424')
        ax.set_title(title, color='white', fontsize=10, pad=10)
        
        ax.grid(True, color='#404040', linestyle='--', linewidth=0.5)
        ax.plot([], [], color=line_color, linewidth=2)
        
        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        return ax, canvas

    def export_csv(self):
        """
        NEW FEATURE: Exports the database content to a CSV file.
        Useful for "Research Data Analysis" sections.
        """
        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sensor_data")
            rows = cursor.fetchall()
            conn.close()
            
            # Generate Filename with Timestamp
            filename = f"sensor_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
            with open(filename, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['ID', 'Timestamp', 'Temp', 'Humid', 'Light'])
                writer.writerows(rows)
            
            print(f"✅ Success: Data exported to {filename}")
            # Optional: Visual feedback on button
            self.btn_export.configure(text="✅ Exported!", fg_color="#2ECC71")
            self.after(2000, lambda: self.btn_export.configure(text="💾 Export Data (CSV)", fg_color="#27AE60"))
            
        except Exception as e:
            print(f"❌ Export Error: {e}")
            self.btn_export.configure(text="❌ Error", fg_color="red")

    def run_ai_prediction(self):
        """
        The Brain 3.0: Uses SVR (Support Vector Regression).
        Epsilon set to 0.1 based on data analysis.
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

            # SVR with Epsilon=0.1 (Optimized for your clean data)
            model = make_pipeline(StandardScaler(), SVR(kernel='linear', C=1.0, epsilon=0.1))
            model.fit(x, y.ravel())

            future_x = np.array([[len(y) + 60]]) 
            prediction = model.predict(future_x)
            
            return f"{prediction[0]:.1f} °C"
        except Exception as e:
            print(f"AI Error: {e}")
            return "Error"

    def update_dashboard(self, t, h, l, ai_pred):
        # Update Cards
        self.card_temp.configure(text=f"{t} °C")
        self.card_hum.configure(text=f"{h} %")
        self.card_light.configure(text=f"{l}")
        self.card_ai.configure(text=ai_pred)

        # Update Lists
        ts = datetime.now().strftime('%H:%M:%S')
        self.x_data.append(ts)
        self.y_temp.append(float(t))
        self.y_hum.append(float(h))
        self.y_light.append(int(l))

        if len(self.x_data) > 60:
            self.x_data.pop(0)
            self.y_temp.pop(0)
            self.y_hum.pop(0)
            self.y_light.pop(0)

        self.update_single_graph(self.ax_temp, self.canvas_temp, self.y_temp, '#FF5733')
        self.update_single_graph(self.ax_hum, self.canvas_hum, self.y_hum, '#3498DB')
        self.update_single_graph(self.ax_light, self.canvas_light, self.y_light, '#F1C40F')

    def update_single_graph(self, ax, canvas, y_data, color):
        ax.clear()
        ax.set_facecolor('#242424')
        ax.grid(True, color='#404040', linestyle='--', linewidth=0.5)
        
        ax.plot(range(len(self.x_data)), y_data, color=color, linewidth=2, marker='o', markersize=3)
        
        step = 10
        if len(self.x_data) > step:
            indices = list(range(0, len(self.x_data), step))
            labels = [self.x_data[i] for i in indices]
            ax.set_xticks(indices)
            ax.set_xticklabels(labels, rotation=30, ha='right', color='white')
        else:
            ax.set_xticks(range(len(self.x_data)))
            ax.set_xticklabels(self.x_data, rotation=30, ha='right', color='white')

        ax.tick_params(colors='white')
        canvas.draw()

    def serial_loop(self):
        conn = sqlite3.connect(DB_NAME)
        conn.execute('''CREATE TABLE IF NOT EXISTS sensor_data
                     (id INTEGER PRIMARY KEY, timestamp DATETIME, temp REAL, humid REAL, light INTEGER)''')
        conn.commit()
        conn.close()

        try:
            self.ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
            time.sleep(2) 
            self.status_label.configure(text="● SYSTEM ONLINE", text_color="#2ECC71")
        except Exception as e:
            self.status_label.configure(text=f"● ERROR: {SERIAL_PORT}", text_color="#E74C3C")
            print(f"Serial Error: {e}")
            return

        while self.running:
            if self.ser.in_waiting:
                try:
                    line = self.ser.readline().decode().strip()
                    parts = line.split(',')
                    
                    if len(parts) == 3:
                        t, h, l = parts
                        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        
                        conn = sqlite3.connect(DB_NAME)
                        conn.execute("INSERT INTO sensor_data (timestamp, temp, humid, light) VALUES (?,?,?,?)", 
                                     (ts, float(t), float(h), int(l)))
                        conn.commit()
                        conn.close()

                        ai_result = self.run_ai_prediction()

                        # --- ACTUATOR LOGIC ---
                        try:
                            pred_val = float(ai_result.split(' ')[0])
                            # Trigger Fan if AI predicts > 27.0°C
                            if pred_val > 27.0:
                                self.ser.write(b'P') 
                                self.fan_status_label.configure(text="AI COOLING ENGAGED", text_color="#3498DB")
                            else:
                                self.ser.write(b'N') 
                                self.fan_status_label.configure(text="Standby / Normal", text_color="gray")
                        except:
                            pass

                        self.after(0, self.update_dashboard, t, h, l, ai_result)
                except Exception as e:
                    print(f"Loop Error: {e}")
                    time.sleep(1)

if __name__ == "__main__":
    app = SmartHomeApp()
    app.mainloop()