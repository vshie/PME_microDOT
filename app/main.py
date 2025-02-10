#!/usr/bin/env python3
import threading
import time
import datetime
import serial
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__)

# Global list to store the latest 60 measurements.
# Each measurement is a dict: {timestamp, temperature, do, q}
data = []
DATA_LOCK = threading.Lock()

# Serial port configuration
SERIAL_PORT = "/dev/ttyUSB0"
BAUD_RATE = 9600

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
            timeout=1  # read timeout in seconds
        )
    except serial.SerialException as e:
        print(f"Error opening serial port: {e}")
        return

    print("Serial port opened successfully.")
    
    while True:
        # Send the command with carriage return and newline.
        command = "MDOT\r\n"
        try:
            ser.write(command.encode('utf-8'))
            print(f"Sent command: {command.strip()}")
        except Exception as e:
            print("Error writing to serial port:", e)
            time.sleep(5)
            continue
        
        # Allow sensor time to reply.
        time.sleep(0.5)
        try:
            raw_response = ser.read_all().decode('utf-8')
        except Exception as e:
            print("Error reading from serial port:", e)
            raw_response = ""
        
        print("Raw response:", raw_response)
        
            
        # Expected response example: "0,+0.00,+20.276,+8.997,+0.931"
        parts = [p.strip() for p in raw_response.split(',')]
        if len(parts) < 5:
            print("Invalid response received, skipping.")
        else:
            try:
                # parts[0]: time (ignored), parts[1]: Battery V (ignored)
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
                    data.append(measurement)
                    if len(data) > 60:
                        data = data[-60:]
                print("Stored measurement:", measurement)
            except Exception as e:
                print("Error parsing measurement:", e)
        
        # Wait for the remainder of the 5-second cycle.
        time.sleep(5)

# Start the sensor polling thread (daemonized so it stops with the main app)
sensor_thread = threading.Thread(target=read_sensor_loop, daemon=True)
sensor_thread.start()

@app.route('/api/data')
def get_data():
    """Return the latest 60 measurements as JSON."""
    with DATA_LOCK:
        return jsonify(data)

@app.route('/api/serial')
def get_serial():
    """Return the serial port configuration."""
    return jsonify({"serial_port": SERIAL_PORT, "baud_rate": BAUD_RATE})

# Serve the Vue2 frontend (assumes index.html is in the "static" directory)
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

if __name__ == '__main__':
    # Run Flask on port 6423
    app.run(host='0.0.0.0', port=6423)
