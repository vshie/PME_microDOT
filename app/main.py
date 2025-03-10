#!/usr/bin/env python3
import threading
import time
from datetime import datetime, timedelta
import serial
from flask import Flask, jsonify, send_from_directory, Response, request, send_file
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

# IMPORTANT: In Docker with a volume mount from host to /app/logs,
# we should ALWAYS use the /app/logs path directly, as this is what's
# mounted to the host directory.
LOG_DIR = Path("/app/logs")
LOG_FILE = LOG_DIR / "sensor_data.csv"
CSV_HEADERS = ["timestamp", "temperature", "do", "q"]
MAX_CSV_SIZE_MB = 10  # Limit file size to 10MB before rotation

# Create logs directory if it doesn't exist (for safety)
try:
    os.makedirs(str(LOG_DIR), exist_ok=True)
    print(f"Using log directory: {LOG_DIR}")
    print(f"Log directory exists: {LOG_DIR.exists()}")
    print(f"Log directory is writable: {os.access(str(LOG_DIR), os.W_OK)}")
    print(f"Log file will be stored at: {LOG_FILE}")
except Exception as e:
    print(f"Error creating log directory: {e}")

# List all directories in /app to help diagnose
try:
    print("Contents of /app directory:")
    for item in os.listdir("/app"):
        item_path = os.path.join("/app", item)
        if os.path.isdir(item_path):
            print(f"  - {item}/ (directory)")
        else:
            print(f"  - {item} (file)")
except Exception as e:
    print(f"Error listing /app directory: {e}")

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
    try:
        log_file_path = str(LOG_FILE)
        log_dir = os.path.dirname(log_file_path)
        
        # Debug info
        print(f"Writing to log file: {log_file_path}")
        print(f"Log directory: {log_dir}")
        print(f"Directory exists: {os.path.exists(log_dir)}")
        print(f"Directory writable: {os.access(log_dir, os.W_OK)}")
        
        # Ensure the log directory exists
        os.makedirs(log_dir, exist_ok=True)
        
        file_exists = os.path.exists(log_file_path)
        print(f"Log file exists before write: {file_exists}")
        
        # Check if we need to rotate the file based on size (only if it exists)
        if file_exists:
            try:
                file_size_mb = os.path.getsize(log_file_path) / (1024 * 1024)  # Convert to MB
                print(f"Current log file size: {file_size_mb:.2f} MB")
                
                # If file is too big, rotate it
                if file_size_mb >= MAX_CSV_SIZE_MB:
                    print(f"Rotating CSV file (current size: {file_size_mb:.2f} MB)")
                    
                    # Create a backup filename with timestamp
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_file = os.path.join(log_dir, f"sensor_data_backup_{timestamp}.csv")
                    
                    # Rename the current file as backup
                    os.rename(log_file_path, backup_file)
                    print(f"Previous data backed up to {backup_file}")
                    
                    # File no longer exists after rename, so update flag
                    file_exists = False
            except Exception as rotate_error:
                print(f"Error rotating CSV file: {rotate_error}")
                # If rotation fails, just continue with append
        
        # Append the new measurement (or create new file if needed)
        with open(log_file_path, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            if not file_exists:
                writer.writeheader()
            writer.writerow(measurement)
            # Flush to ensure data is written immediately
            f.flush()
            os.fsync(f.fileno())
        
        # Verify file was written
        print(f"Log file exists after write: {os.path.exists(log_file_path)}")
        if os.path.exists(log_file_path):
            print(f"Log file size after write: {os.path.getsize(log_file_path)} bytes")
            
    except Exception as e:
        print(f"Error writing to CSV: {e}")

def send_to_mavlink(name, value):
    """Send a named value float to Mavlink2Rest."""
    # Try multiple possible endpoints
    endpoints = [
        'http://host.docker.internal:6040/v1/mavlink',
        'http://localhost:6040/v1/mavlink',
        'http://127.0.0.1:6040/v1/mavlink',
        'http://192.168.2.2:6040/v1/mavlink',
        'http://blueos.local:6040/v1/mavlink'
    ]
    
    # Create name array exactly as shown in the documentation
    name_array = []
    for i in range(10):
        if i < len(name):
            name_array.append(name[i])
        else:
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
    
    # Try each endpoint
    for endpoint in endpoints:
        try:
            response = requests.post(endpoint, json=payload, timeout=2.0)
            if response.status_code == 200:
                print(f"Successfully sent {name}={value} to Mavlink2Rest via {endpoint}")
                return True
            else:
                continue  # Try next endpoint
        except Exception:
            continue  # Try next endpoint
    
    # Only print one error message if all endpoints fail
    print(f"Could not send {name}={value} to any Mavlink2Rest endpoint")
    return False

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
                        
                        # Send values to Mavlink2Rest with sensor names matching BlueRobotics convention
                        # The exact sensor name is critical for proper logging in BlueOS
                        send_success = send_to_mavlink("DO_T", temperature)  # DO_T for DO Temperature
                        if send_success:
                            # Only try sending the next value if the first one succeeded
                            send_to_mavlink("DO_O", do)  # DO_O for Dissolved Oxygen
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
        max_points = int(request.args.get('max_points', 1000))  # Default to max 1000 points
    except (TypeError, ValueError):
        duration = 0
        max_points = 1000
    
    # For "All Data" selection, use duration=-1 to indicate we want everything
    all_data_requested = duration <= 0
    
    # Only calculate cutoff time if we're not requesting all data
    cutoff_time = datetime.now() - timedelta(minutes=duration) if not all_data_requested else None
    
    print(f"Data request: duration={duration}, all_data={all_data_requested}, max_points={max_points}")
    
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
                    
                    # Count rows and collect matching data
                    all_matching_rows = []
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
                                    all_matching_rows.append(processed_row)
                            else:
                                error_count += 1
                                if error_count < 5:  # Limit the number of error messages
                                    missing = [field for field in CSV_HEADERS if field not in row]
                                    print(f"Row {row_count} missing fields: {missing}")
                        except (ValueError, KeyError) as e:
                            error_count += 1
                            if error_count < 5:  # Limit the number of error messages
                                print(f"Error processing row {row_count}: {e}")
                except Exception as file_error:
                    print(f"Error reading CSV file: {file_error}")
                    with DATA_LOCK:
                        return jsonify(list(data))
            
            # If we have more points than max_points, we need to downsample
            total_points = len(all_matching_rows)
            if total_points > max_points and max_points > 0:
                # Simple downsampling - take evenly spaced points
                step = total_points // max_points
                filtered_data = all_matching_rows[::step]
                if len(filtered_data) > max_points:  # Ensure we don't exceed max_points
                    filtered_data = filtered_data[:max_points]
                print(f"Downsampled from {total_points} to {len(filtered_data)} points")
            else:
                filtered_data = all_matching_rows
            
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
    log_file_path = str(LOG_FILE)
    
    # Print debug info
    print(f"Download requested for log file: {log_file_path}")
    print(f"File exists: {os.path.exists(log_file_path)}")
    if os.path.exists(log_file_path):
        print(f"File size: {os.path.getsize(log_file_path)} bytes")
    
    # List all files in the logs directory
    log_dir = os.path.dirname(log_file_path)
    print(f"Contents of log directory ({log_dir}):")
    if os.path.exists(log_dir):
        for item in os.listdir(log_dir):
            item_path = os.path.join(log_dir, item)
            if os.path.isfile(item_path):
                print(f"  - {item} ({os.path.getsize(item_path)} bytes)")
            else:
                print(f"  - {item}/ (directory)")
    
    try:
        if os.path.exists(log_file_path):
            response = send_file(
                log_file_path,
                mimetype='text/csv',
                as_attachment=True,
                download_name='do_sensor_logs.csv'
            )
            return response
        else:
            return "No log file found", 404
    except Exception as e:
        return f"Error accessing log file: {e}", 500

@app.route('/api/logs/delete', methods=['POST'])
def delete_logs():
    """Delete the log file."""
    log_file_path = str(LOG_FILE)
    
    # Print debug info
    print(f"Delete requested for log file: {log_file_path}")
    print(f"File exists before delete: {os.path.exists(log_file_path)}")
    
    try:
        if os.path.exists(log_file_path):
            # List backup files in the directory
            log_dir = os.path.dirname(log_file_path)
            backup_files = [f for f in os.listdir(log_dir) if f.startswith("sensor_data_backup_")]
            
            # Delete the main log file
            os.remove(log_file_path)
            print(f"Main log file deleted: {log_file_path}")
            
            # Delete any backup files
            for backup in backup_files:
                backup_path = os.path.join(log_dir, backup)
                os.remove(backup_path)
                print(f"Backup file deleted: {backup_path}")
            
            return jsonify({"success": True, "message": f"Deleted log file and {len(backup_files)} backup files"})
        
        return jsonify({"success": True, "message": "No log file to delete"})
    except Exception as e:
        print(f"Error deleting log file: {e}")
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
