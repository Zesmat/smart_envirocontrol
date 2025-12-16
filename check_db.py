import sqlite3
import os

# Configuration
DB_NAME = 'smart_home_data.db'

def inspect_database():
    # Check if file exists first
    if not os.path.exists(DB_NAME):
        print(f"❌ ERROR: Database file '{DB_NAME}' not found.")
        print("   (Did you run the dashboard.py script yet?)")
        return

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    print("="*60)
    print(f"📂 DATABASE: {DB_NAME}")
    print("="*60)

    # --- PART 1: DATABASE DESIGN (Requirement for Report Section 7) ---
    print("\n[1] TABLE DESIGN (Schema):")
    print(f"{'Column ID':<10} {'Name':<15} {'Type':<10} {'NotNull'}")
    print("-" * 50)
    
    # Get table info
    c.execute("PRAGMA table_info(readings)")
    columns = c.fetchall()
    for col in columns:
        # col format: (cid, name, type, notnull, dflt_value, pk)
        print(f"{col[0]:<10} {col[1]:<15} {col[2]:<10} {col[3]}")

    # --- PART 2: LOGGED DATA (Requirement for Logging Standard) ---
    print("\n" + "="*60)
    print("[2] LOGGED DATA (Latest 10 readings):")
    print(f"{'ID':<5} | {'TIMESTAMP':<20} | {'SENSOR NAME':<15} | {'VALUE':<10}")
    print("-" * 60)

    c.execute("SELECT * FROM readings ORDER BY id DESC LIMIT 10")
    rows = c.fetchall()
    
    if not rows:
        print("   (No data found yet. Connect Arduino to generate logs!)")
    else:
        for row in rows:
            # row format: (id, timestamp, type, value)
            print(f"{row[0]:<5} | {row[1]:<20} | {row[2]:<15} | {row[3]:<10}")

    print("\n" + "="*60)
    conn.close()

if __name__ == "__main__":
    inspect_database()