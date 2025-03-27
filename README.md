# PME microDOT Extension for BlueOS

This extension provides real-time monitoring and logging of dissolved oxygen (DO) and temperature data from the PME microDOT sensor in BlueOS. It features a modern web interface for data visualization and includes integration with Mavlink2Rest for vehicle data logging.

## Features

- Real-time monitoring of dissolved oxygen (DO) and temperature
- Vehicle temperature integration via Mavlink2Rest
- GPS position logging (latitude/longitude) with each measurement
- Interactive web interface with configurable time windows
- Automatic data logging to CSV files
- Serial port configuration management
- Data export functionality
- Responsive design that works on both desktop and mobile

## Hardware Requirements

1. PME microDOT sensor
2. RS232 to USB adapter (required for serial communication)
   - Recommended: [FTDI USB-RS232-WE-1800-BT-0-0](https://www.digikey.com/en/products/detail/ftdi-future-technology-devices-international-ltd/USB-RS232-WE-1800-BT-0-0/2402469)
   - This adapter provides reliable RS232 to USB conversion for the microDOT sensor

## Installation

1. Install the extension through the BlueOS extension manager
2. Connect the microDOT sensor to the RS232 to USB adapter
3. Connect the USB adapter to your BlueOS system
4. The extension will automatically detect available serial ports

## Usage

1. Access the extension through the BlueOS interface
2. Select the appropriate serial port in the Settings tab
3. The graph will automatically begin displaying data once connected
4. Use the time window selector to view different ranges of data:
   - Last Minute
   - Last 5 Minutes
   - Last 10 Minutes
   - Last 30 Minutes
   - All Data

## Data Logging

- All measurements are automatically logged to CSV files
- Logs include:
  - Timestamp
  - Temperature (°C)
  - Dissolved Oxygen (mg/l)
  - Quality indicator (Q)
  - Vehicle temperature (°C)
  - GPS coordinates (latitude/longitude)
- Logs can be downloaded or deleted through the web interface
- Automatic log rotation when file size exceeds 10MB

## Mavlink2Rest Integration

The extension automatically sends sensor data to Mavlink2Rest for vehicle logging:
- DO_T: Temperature measurements
- DO_O: Dissolved oxygen measurements

## Troubleshooting

1. If the sensor is not detected:
   - Check the USB connection
   - Verify the correct serial port is selected
   - Ensure the RS232 to USB adapter is properly connected

2. If data is not displaying:
   - Check the serial port settings
   - Verify the sensor is powered and connected
   - Check the browser console for error messages

## Support

For issues or questions, please refer to the BlueOS documentation or contact support.
