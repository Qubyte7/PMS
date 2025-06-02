# app.py
from flask import Flask, render_template, jsonify
import csv
from datetime import datetime
import os # Import os for file existence check

app = Flask(__name__)

CSV_FILE = '../../testdb.csv'
UNAUTHORIZED_ATTEMPTS_LOG_FILE = '../../unauthorized_attempts_log.csv' # NEW: Path to the new log file

def read_parking_data():
    """Reads data from testdb.csv and returns a list of dictionaries."""
    data = []
    try:
        with open(CSV_FILE, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append(row)
    except FileNotFoundError:
        print(f"Error: {CSV_FILE} not found.")
    return data

def read_alerts_from_log_csv(): # Renamed function for clarity
    """Reads unauthorized attempts from unauthorized_attempts_log.csv."""
    alerts = []
    try:
        if not os.path.exists(UNAUTHORIZED_ATTEMPTS_LOG_FILE):
            print(f"Warning: {UNAUTHORIZED_ATTEMPTS_LOG_FILE} not found. No alerts will be displayed.")
            return []

        with open(UNAUTHORIZED_ATTEMPTS_LOG_FILE, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Ensure all expected fields exist
                if all(k in row for k in ['timestamp', 'car_plate', 'attempt_type', 'reason', 'details']):
                    alerts.append({
                        'timestamp': row['timestamp'],
                        'plate': row['car_plate'],
                        'message': f"Type: {row['attempt_type']}, Reason: {row['reason']}. Details: {row['details']}",
                        'type': row['attempt_type'] # This can be used for more specific styling in frontend
                    })
                else:
                    print(f"Skipping malformed row in {UNAUTHORIZED_ATTEMPTS_LOG_FILE}: {row}")

    except FileNotFoundError: # This catch is technically redundant due to os.path.exists check, but harmless
        print(f"Error: {UNAUTHORIZED_ATTEMPTS_LOG_FILE} not found. Cannot read alerts.")
    except Exception as e:
        print(f"An error occurred while reading alerts from CSV: {e}")
    return alerts

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/parking_data')
def get_parking_data():
    data = read_parking_data()
    return jsonify(data)

@app.route('/api/alerts')
def get_alerts():
    alerts = read_alerts_from_log_csv() # Call the new function
    return jsonify(alerts)

if __name__ == '__main__':
    app.run(debug=True)