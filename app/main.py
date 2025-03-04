#!/usr/bin/env python3
import threading
import time
import datetime
import serial
from flask import Flask, jsonify, send_from_directory, Response

app = Flask(__name__)

# Global list to store the latest 60 measurements.
# Each measurement is a dict: {timestamp, temperature, do, q}
data = []
DATA_LOCK = threading.Lock()

# Serial port configuration
SERIAL_PORT = "/dev/ttyUSB0"
BAUD_RATE = 9600

def clean_response(response):
    """Clean and validate the sensor response string."""
    # Remove leading/trailing whitespace and any extra linebreaks
    lines = [line.strip() for line in response.split('\n') if line.strip()]
    if not lines:
        return None
    
    # Take only the last complete response if multiple are received
    return lines[-1]

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
                    "timestamp": datetime.datetime.now().isoformat(),
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
    """Return the latest 60 measurements as JSON."""
    with DATA_LOCK:
        # Return a copy of the data to prevent race conditions
        return jsonify(list(data))

@app.route('/api/serial')
def get_serial():
    """Return the serial port configuration."""
    return jsonify({"serial_port": SERIAL_PORT, "baud_rate": BAUD_RATE})

@app.route('/register_service')
def register_service():
    """Register the extension as a service in BlueOS."""
    return Response(
        response=jsonify({
            # Unique name for the service
            "name": "DO Sensor",
            # User-friendly name that appears in the menu
            "description": "Dissolved Oxygen Sensor Monitor",
            # Icon from Material Design Icons
            "icon": "mdi-water",
            # The company/developer name
            "company": "Blue Robotics",
            # Path to the webpage
            "webpage": "/",
            # Enable/disable status
            "enabled": True
        }).get_data(),
        status=200,
        mimetype='application/json'
    )

# Serve the Vue2 frontend (assumes index.html is in the "static" directory)
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

if __name__ == '__main__':
    # Run Flask on port 6423
    app.run(host='0.0.0.0', port=6423)
