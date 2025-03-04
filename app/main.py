#!/usr/bin/env python3
import threading
import time
from datetime import datetime, timedelta
import serial
from flask import Flask, jsonify, send_from_directory, Response, request
import os
import csv
from pathlib import Path
import requests  # Add this import at the top
import numpy as np  # Add this import

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
    """Write measurement to CSV file."""
    file_exists = LOG_FILE.exists()
    
    with open(LOG_FILE, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(measurement)

def send_to_mavlink(name, value):
    """Send a named value float to Mavlink2Rest."""
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
    
    try:
        response = requests.post('http://blueos.local:6040/v1/mavlink', json=payload)
        if response.status_code != 200:
            print(f"Failed to send {name} to Mavlink2Rest: {response.status_code}")
    except Exception as e:
        print(f"Error sending {name} to Mavlink2Rest: {e}")

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
    
    cutoff_time = datetime.now() - timedelta(minutes=duration)
    
    if duration <= 5:
        # Use in-memory data for short durations
        with DATA_LOCK:
            if duration <= 0:
                return jsonify(list(data))
            
            filtered_data = [
                measurement for measurement in data
                if datetime.fromisoformat(measurement['timestamp']) > cutoff_time
            ]
            return jsonify(filtered_data)
    else:
        # Read from CSV for longer durations using built-in csv module
        try:
            if not LOG_FILE.exists():
                return jsonify([])
            
            filtered_data = []
            with open(LOG_FILE, 'r') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    # Parse the timestamp and check if it's within the requested duration
                    timestamp = datetime.fromisoformat(row['timestamp'])
                    if duration <= 0 or timestamp > cutoff_time:
                        # Convert string values to proper types
                        processed_row = {
                            'timestamp': row['timestamp'],
                            'temperature': float(row['temperature']),
                            'do': float(row['do']),
                            'q': float(row['q'])
                        }
                        filtered_data.append(processed_row)
            
            return jsonify(filtered_data)
            
        except Exception as e:
            print(f"Error reading from CSV: {e}")
            return jsonify([])

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
