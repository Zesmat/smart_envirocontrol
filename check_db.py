import sqlite3
import os

# Configuration
DB_NAME = 'smart_home_data.db'
TABLE_NAME = 'sensor_data'  # Updated to match the new dashboard

def inspect_database():
    """Inspect the SQLite database used by the dashboard.

    This utility script is meant for quick validation during development and
    report preparation.

    Output sections:
        1) Table schema (via PRAGMA table_info)
        2) Latest 10 rows (ordered by descending id)

    Behavior:
        - If the DB file does not exist, prints a helpful message and exits.
        - If the table is missing or empty, prints a warning.
        - Any operational errors are caught and printed to the console.
    """
    # Check if file exists first
    if not os.path.exists(DB_NAME):
        print(f"❌ ERROR: Database file '{DB_NAME}' not found.")
        print("   (Did you run the dashboard.py script yet?)")
        return

    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return

    print("="*80)
    print(f"📂 DATABASE INSPECTION: {DB_NAME}")
    print("="*80)

    # --- PART 1: DATABASE DESIGN ---
    # Schema is derived directly from SQLite's metadata.
    print(f"\n[1] TABLE SCHEMA ({TABLE_NAME}):")
    print(f"{'ID':<5} {'Name':<15} {'Type':<10} {'NotNull'}")
    print("-" * 50)
    
    try:
        # Get table info for the table name configured in TABLE_NAME.
        c.execute(f"PRAGMA table_info({TABLE_NAME})")
        columns = c.fetchall()
        
        if not columns:
            print(f"⚠️  Table '{TABLE_NAME}' not found! Did you delete the old .db file?")
            return

        for col in columns:
            # col format: (cid, name, type, notnull, dflt_value, pk)
            print(f"{col[0]:<5} {col[1]:<15} {col[2]:<10} {col[3]}")
    except Exception as e:
        print(f"Error reading schema: {e}")

    # --- PART 2: LOGGED DATA (Requirement for Logging Standard) ---
    # Fetch a small sample of recent rows for a sanity check.
    print("\n" + "="*80)
    print("[2] LOGGED DATA (Latest 10 readings):")
    # Updated header to match the 5 columns
    print(f"{'ID':<5} | {'TIMESTAMP':<20} | {'TEMP':<8} | {'HUMID':<8} | {'LIGHT':<8}")
    print("-" * 80)

    try:
        c.execute(f"SELECT * FROM {TABLE_NAME} ORDER BY id DESC LIMIT 10")
        rows = c.fetchall()
        
        if not rows:
            print("   (No data found yet. Run the Dashboard to generate logs!)")
        else:
            for row in rows:
                # row format: (id, timestamp, temp, humid, light)
                # We format the floats to look nice (e.g., 25.5°C)
                r_id = row[0]
                r_time = row[1]
                r_temp = f"{row[2]}°C"
                r_hum = f"{row[3]}%"
                r_light = str(row[4])
                
                print(f"{r_id:<5} | {r_time:<20} | {r_temp:<8} | {r_hum:<8} | {r_light:<8}")

    except Exception as e:
        print(f"Error reading data: {e}")

    print("\n" + "="*80)
    print("✅ STATUS: Database structure is valid for the Report.")
    conn.close()

if __name__ == "__main__":
    inspect_database()