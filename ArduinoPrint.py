import re
import time
import serial
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from gspread_formatting import set_column_width
import statistics

# ============== CONFIGURATION ==============
SERIAL_PORT = '/dev/ttyACM0'  # Adjust to your serial port (e.g., 'COM3' on Windows)
BAUD_RATE = 9600              # Match your Arduino's baud rate
SPREADSHEET_NAME = 'PyTest'   # Name of your Google Sheet
CREDENTIALS_FILE = '/home/ldneuman/arduino/credentials.json'  # Path to your service account credentials
COLLECTION_DURATION = 45      # Duration to collect data (seconds)
MAX_ROWS = 10000              # Maximum rows in the Google Sheet

# ============== PARSING FUNCTION ==============
def parse_arduino_line(line: str):
    """Parse the Arduino output line into sensor, reading, units, and timestamp."""
    match = re.search(
        r'FORWARD\s+(.*?)\s+(Reading:|Distance:)\s*(.*?)\s+at\s+(\d{4}/\d{1,2}/\d{1,2}\s+\d{1,2}:\d{1,2}:\d{1,2})',
        line
    )
    if not match:
        return None

    sensor_part = match.group(1).strip()
    reading_part = match.group(3).strip()
    arduino_timestamp = match.group(4).strip()

    sensor_type = ""
    reading_value = ""
    units = ""

    if "PIR" in sensor_part:
        sensor_type = "PIR Motion"
        reading_value = reading_part
        units = ""
    elif "HC-SR04" in sensor_part:
        sensor_type = "Ultrasonic"
        dist_match = re.search(r'([\d,\.]+)\s*(cm|mm)?', reading_part)
        if dist_match:
            reading_value = dist_match.group(1).replace(',', '.')
            units = dist_match.group(2) or 'cm'
        else:
            reading_value = reading_part
            units = ""
    elif "RQ-S003" in sensor_part:
        sensor_type = "Flame"
        reading_value = reading_part
        units = ""
    elif "HW-201" in sensor_part:
        sensor_type = "Vibration"
        reading_value = reading_part
        units = ""
    else:
        sensor_type = sensor_part
        reading_value = reading_part
        units = ""

    return {
        'sensor': sensor_type,
        'reading_value': reading_value,
        'units': units,
        'arduino_timestamp': arduino_timestamp
    }

# ============== GOOGLE SHEETS SETUP ==============
print("Initializing Google Sheets...")
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scope)
client = gspread.authorize(creds)

sheet = client.open(SPREADSHEET_NAME).sheet1
sheet.clear()
sheet.resize(rows=MAX_ROWS)  # Set to 10,000 rows

headers = ["Local Timestamp", "Arduino Timestamp", "Sensor", "Reading", "Units", "Raw Line"]
sheet.append_row(headers)

# Set column widths for readability
set_column_width(sheet, 'A', 140)
set_column_width(sheet, 'B', 160)
set_column_width(sheet, 'C', 120)
set_column_width(sheet, 'D', 100)
set_column_width(sheet, 'E', 60)
set_column_width(sheet, 'F', 260)

print(f"Cleared old data and set up headers in '{SPREADSHEET_NAME}'.")

# ============== SERIAL SETUP ==============
print(f"Opening serial port {SERIAL_PORT} at {BAUD_RATE} baud...")
ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
ser.reset_input_buffer()
time.sleep(2)  # Stabilize connection
print("Serial port opened. Starting data collection...")

# ============== DATA COLLECTION ==============
print(f"Starting {COLLECTION_DURATION}-second data collection...")
start_time = time.time()
data = {}  # Store numerical readings for statistics

while time.time() - start_time < COLLECTION_DURATION:
    if ser.in_waiting > 0:  # Check if data is available
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line:
            parsed = parse_arduino_line(line)
            if parsed:
                local_ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                row_values = [
                    local_ts,
                    parsed['arduino_timestamp'],
                    parsed['sensor'],
                    parsed['reading_value'],
                    parsed['units'],
                    line
                ]
                sheet.append_row(row_values)
                print(f"Appended row: {row_values}")

                # Collect numerical data for statistics
                try:
                    value = float(parsed['reading_value'])
                    sensor = parsed['sensor']
                    if sensor not in data:
                        data[sensor] = []
                    data[sensor].append(value)
                except ValueError:
                    pass  # Skip non-numerical readings
    time.sleep(0.1)  # Small delay to prevent CPU overuse

# ============== CALCULATE AND WRITE STATISTICS ==============
print("\nData collection complete. Calculating and writing statistics...")
sheet.append_row([""] * len(headers))  # Blank row for separation
sheet.append_row(["STATISTICS:"])      # Statistics section header
stats_headers = ["Sensor", "Count", "Mean", "Median", "Min", "Max", "Std Dev", "Calculation Time"]
sheet.append_row(stats_headers)

for sensor, values in data.items():
    if len(values) > 0:
        try:
            # Calculate statistics
            mean = round(statistics.mean(values), 2)
            median = round(statistics.median(values), 2)
            min_val = round(min(values), 2)
            max_val = round(max(values), 2)
            count = len(values)
            std_dev = round(statistics.stdev(values), 2) if len(values) > 1 else "N/A"

            # Append statistics to sheet
            stats_row = [
                sensor,
                count,
                mean,
                median,
                min_val,
                max_val,
                std_dev,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ]
            sheet.append_row(stats_row)
            time.sleep(1)  # Avoid hitting API rate limits

            # Print to console
            print(f"\nSensor: {sensor}")
            print(f"  Count: {count}")
            print(f"  Mean: {mean}")
            print(f"  Median: {median}")
            print(f"  Min: {min_val}")
            print(f"  Max: {max_val}")
            print(f"  Std Dev: {std_dev}")
        except Exception as e:
            print(f"Error processing {sensor}: {str(e)}")
    else:
        print(f"No numerical data for sensor: {sensor}")

# Add an empty row after statistics
sheet.append_row([""] * len(stats_headers))

# ============== CLEANUP ==============
ser.close()
print("Serial connection closed.")
