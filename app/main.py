#!/usr/bin/env python3
import threading
import time
from datetime import datetime, timedelta
import serial
from flask import Flask, jsonify, send_from_directory, Response, request
import os
import csv
from pathlib import Path
import requests

app = Flask(__name__)

# Global list to store the latest 60 measurements.
# Each measurement is a dict: {timestamp, temperature, do, q}
data = []
DATA_LOCK = threading.Lock()

# Serial port configuration
SERIAL_PORT = "/dev/ttyUSB0"
BAUD_RATE = 9600

# Add after the DATA_LOCK definition
LOG_DIR = Path("/app/logs")
LOG_FILE = LOG_DIR / "sensor_data.csv"
CSV_HEADERS = ["timestamp", "temperature", "do", "q"]

# Create logs directory if it doesn't exist
LOG_DIR.mkdir(exist_ok=True)

def clean_response(response):
    """Clean and validate the sensor response string."""
    # Remove leading/trailing whitespace and any extra linebreaks
    lines = [line.strip() for line in response.split('\n') if line.strip()]
    if not lines:
        return None
    
    # Take only the last complete response if multiple are received
    return lines[-1]

def write_to_csv(measurement):
    """Write measurement to CSV file with file rotation to limit size."""
    MAX_CSV_ROWS = 100000  # Limit to ~100K rows (roughly ~140 hours of data at 5s intervals)
    
    try:
        log_file_path = str(LOG_FILE)
        log_dir = os.path.dirname(log_file_path)
        
        # Ensure the log directory exists
        os.makedirs(log_dir, exist_ok=True)
        
        file_exists = os.path.exists(log_file_path)
        
        # Check if we need to rotate the file (only if it exists)
        if file_exists:
            try:
                row_count = 0
                with open(log_file_path, 'r') as f:
                    row_count = sum(1 for _ in f) - 1  # Subtract 1 for header
                
                # If file is too big, rotate it (keep most recent data)
                if row_count >= MAX_CSV_ROWS:
                    print(f"Rotating CSV file (current rows: {row_count})")
                    
                    # Read existing data
                    all_rows = []
                    with open(log_file_path, 'r') as f:
                        reader = csv.DictReader(f)
                        all_rows = list(reader)
                    
                    # Keep the most recent rows (half the maximum)
                    rows_to_keep = all_rows[-int(MAX_CSV_ROWS/2):]
                    
                    # Write back to file
                    with open(log_file_path, 'w', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
                        writer.writeheader()
                        writer.writerows(rows_to_keep)
            except Exception as rotate_error:
                print(f"Error rotating CSV file: {rotate_error}")
                # If rotation fails, just continue with append
        
        # Append the new measurement
        with open(log_file_path, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            if not file_exists:
                writer.writeheader()
            writer.writerow(measurement)
            # Flush to ensure data is written immediately
            f.flush()
            os.fsync(f.fileno())
            
    except Exception as e:
        print(f"Error writing to CSV: {e}")

def send_to_mavlink(name, value):
    """Send a named value float to Mavlink2Rest."""
    # Configure Mavlink settings - use IP address instead of hostname
    # Try both the local Docker host and the standard BlueOS IP
    mavlink_urls = [
        'http://host.docker.internal:6040/v1/mavlink',  # Docker host internal
        'http://192.168.2.2:6040/v1/mavlink',           # Standard BlueOS IP
        'http://localhost:6040/v1/mavlink',             # Local host
        'http://blueos.local:6040/v1/mavlink'           # Original hostname (as fallback)
    ]
    
    # Don't send to Mavlink if we're in debug mode (detected by log date)
    current_year = datetime.now().year
    if current_year > 2024:  # If "future" date like 2025, we're likely in dev/debug mode
        print(f"Debug mode detected (year: {current_year}), skipping Mavlink send")
        return
    
    # Pad the name to 10 characters with null bytes as required
    name_array = list(name[:10])  # Take first 10 chars if name is too long
    while len(name_array) < 10:
        name_array.append('\u0000')
    
    payload = {
        "header": {
            "system_id": 255,
            "component_id": 0,
            "sequence": 0
        },
        "message": {
            "type": "NAMED_VALUE_FLOAT",
            "time_boot_ms": 0,
            "value": value,
            "name": name_array
        }
    }
    
    # Try each URL in order until one succeeds
    for url in mavlink_urls:
        try:
            response = requests.post(url, json=payload, timeout=1.0)  # Short timeout
            if response.status_code == 200:
                # Success, no need to try other URLs
                return
            # If not 200, try the next URL
        except requests.exceptions.RequestException:
            # If request fails, try the next URL
            continue
    
    # If we get here, all URLs failed - log the error once but don't spam logs
    print(f"Could not send {name} to any Mavlink2Rest endpoint - continuing without Mavlink integration")

def read_sensor_loop():
    """Continuously poll the sensor every 5 seconds and update the global data."""
    global data
    try:
        ser = serial.Serial(
            port=SERIAL_PORT,
            baudrate=BAUD_RATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1
        )
    except serial.SerialException as e:
        print(f"Error opening serial port: {e}")
        return

    print("Serial port opened successfully.")
    
    while True:
        start_time = time.time()
        
        # Clear any pending data in the buffer
        ser.reset_input_buffer()
        
        # Send the command
        try:
            ser.write("MDOT\r\n".encode('utf-8'))
        except Exception as e:
            print("Error writing to serial port:", e)
            time.sleep(5)
            continue
        
        # Allow sensor time to reply
        time.sleep(0.5)
        
        try:
            raw_response = ser.read_all().decode('utf-8')
            cleaned_response = clean_response(raw_response)
            if not cleaned_response:
                print("Invalid or empty response received, skipping.")
                continue
                
            parts = [p.strip() for p in cleaned_response.split(',')]
            if len(parts) >= 5:
                temperature = float(parts[2])
                do = float(parts[3])
                q = float(parts[4])
                
                measurement = {
                    "timestamp": datetime.now().isoformat(),
                    "temperature": temperature,
                    "do": do,
                    "q": q
                }
                
                with DATA_LOCK:
                    # Only append if values are reasonable
                    if -10 <= temperature <= 50 and 0 <= do <= 20 and 0 <= q <= 1:
                        data.append(measurement)
                        if len(data) > 60:
                            data = data[-60:]
                        print("Stored measurement:", measurement)
                        write_to_csv(measurement)
                        
                        # Send values to Mavlink2Rest
                        send_to_mavlink("DOT", temperature)  # DOT for DO Temperature
                        send_to_mavlink("DO", do)  # DO for Dissolved Oxygen
                    else:
                        print("Measurement values out of expected range, skipping")
            else:
                print("Invalid response format")
                
        except Exception as e:
            print("Error processing measurement:", e)
        
        # Calculate remaining time in the 5-second cycle
        elapsed = time.time() - start_time
        sleep_time = max(0, 5 - elapsed)
        time.sleep(sleep_time)

# Start the sensor polling thread (daemonized so it stops with the main app)
sensor_thread = threading.Thread(target=read_sensor_loop, daemon=True)
sensor_thread.start()

@app.route('/api/data')
def get_data():
    """Return measurements filtered by duration."""
    try:
        duration = int(request.args.get('duration', 0))
    except (TypeError, ValueError):
        duration = 0
    
    # For "All Data" selection, use duration=-1 to indicate we want everything
    all_data_requested = duration <= 0
    
    # Only calculate cutoff time if we're not requesting all data
    cutoff_time = datetime.now() - timedelta(minutes=duration) if not all_data_requested else None
    
    print(f"Data request: duration={duration}, all_data={all_data_requested}")
    
    # Always return in-memory data for short durations (5 minutes or less)
    if duration <= 5 and not all_data_requested:
        with DATA_LOCK:
            filtered_data = [
                measurement for measurement in data
                if all_data_requested or datetime.fromisoformat(measurement['timestamp']) > cutoff_time
            ]
            print(f"Returning {len(filtered_data)} in-memory records (short duration)")
            return jsonify(filtered_data)
    else:
        # For longer durations or all data, try to read from CSV
        log_file_path = str(LOG_FILE)
        
        # First check if the file exists
        if not os.path.exists(log_file_path):
            print(f"Log file not found: {log_file_path}, falling back to in-memory data")
            with DATA_LOCK:
                return jsonify(list(data))
        
        # Try to read from the CSV file
        try:
            filtered_data = []
            row_count = 0
            error_count = 0
            
            with open(log_file_path, 'r') as csvfile:
                try:
                    reader = csv.DictReader(csvfile)
                    
                    # Verify the headers are correct
                    if not all(header in reader.fieldnames for header in CSV_HEADERS):
                        print(f"CSV headers mismatch. Expected: {CSV_HEADERS}, Found: {reader.fieldnames}")
                        with DATA_LOCK:
                            return jsonify(list(data))
                    
                    for row in reader:
                        row_count += 1
                        try:
                            # Only process if all required fields are present
                            if all(field in row for field in CSV_HEADERS):
                                # Parse the timestamp and check if it's within the requested duration
                                timestamp = datetime.fromisoformat(row['timestamp'])
                                if all_data_requested or timestamp > cutoff_time:
                                    # Convert string values to proper types
                                    processed_row = {
                                        'timestamp': row['timestamp'],
                                        'temperature': float(row['temperature']),
                                        'do': float(row['do']),
                                        'q': float(row['q'])
                                    }
                                    filtered_data.append(processed_row)
                            else:
                                error_count += 1
                                missing = [field for field in CSV_HEADERS if field not in row]
                                if error_count < 5:  # Limit the number of error messages
                                    print(f"Row {row_count} missing fields: {missing}")
                        except (ValueError, KeyError) as e:
                            error_count += 1
                            if error_count < 5:  # Limit the number of error messages
                                print(f"Error processing row {row_count}: {e}")
                except Exception as file_error:
                    print(f"Error reading CSV file: {file_error}")
                    with DATA_LOCK:
                        return jsonify(list(data))
            
            print(f"CSV read: {row_count} total rows, {len(filtered_data)} returned, {error_count} errors")
            
            # If we got data from the CSV, return it
            if filtered_data:
                return jsonify(filtered_data)
            else:
                # Fall back to in-memory data if CSV read returned no data
                print("No data found in CSV matching criteria, falling back to in-memory data")
                with DATA_LOCK:
                    return jsonify(list(data))
                
        except Exception as e:
            print(f"Exception while processing CSV file: {e}")
            # Fall back to in-memory data on any error
            with DATA_LOCK:
                return jsonify(list(data))

@app.route('/api/serial')
def get_serial():
    """Return the serial port configuration."""
    return jsonify({"serial_port": SERIAL_PORT, "baud_rate": BAUD_RATE})

@app.route('/register_service')
def register_service():
    """Register the extension as a service in BlueOS."""
    return send_from_directory('static', 'register_service')

# Serve the Vue2 frontend (assumes index.html is in the "static" directory)
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/logs')
def download_logs():
    """Download the log file."""
    if LOG_FILE.exists():
        return send_from_directory(
            LOG_DIR,
            LOG_FILE.name,
            as_attachment=True,
            download_name="sensor_data.csv"
        )
    return jsonify({"error": "No log file found"}), 404

@app.route('/api/logs/delete', methods=['POST'])
def delete_logs():
    """Delete the log file."""
    try:
        if LOG_FILE.exists():
            LOG_FILE.unlink()
            return jsonify({"success": True, "message": "Log file deleted"})
        return jsonify({"success": True, "message": "No log file to delete"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/widget')
def widget():
    """Serve the widget-optimized version of the dashboard."""
    response = send_from_directory('static', 'widget.html')
    # Add header to prevent BlueOS from wrapping the page
    response.headers['X-Frame-Options'] = 'ALLOWALL'
    return response

if __name__ == '__main__':
    # Run Flask on port 6436
    app.run(host='0.0.0.0', port=6436)
