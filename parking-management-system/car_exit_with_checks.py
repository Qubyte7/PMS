import cv2
from ultralytics import YOLO
import pytesseract
import os
import time
import serial
import serial.tools.list_ports
import csv
from collections import Counter
import datetime # Import datetime for logging

# Load YOLOv8 model (same model as entry)
model = YOLO('./brain/best.pt')

# CSV log file
csv_file = 'testdb.csv'

# --- UI Communication Files ---
EXIT_STATUS_FILE = 'exit_gate_status.txt'
DETECTED_PLATE_FILE = 'detected_plate.txt' # Shared with entry for overall last detected
LOG_FILE = 'parking_system_log.txt' # Shared log file

def update_ui_status(gate_status, detected_plate=None, log_message=None):
    """
    Updates status files for UI communication.
    """
    try:
        with open(EXIT_STATUS_FILE, 'w') as f:
            f.write(gate_status)
    except IOError as e:
        print(f"Error writing to {EXIT_STATUS_FILE}: {e}")

    if detected_plate:
        try:
            with open(DETECTED_PLATE_FILE, 'w') as f:
                f.write(detected_plate)
        except IOError as e:
            print(f"Error writing to {DETECTED_PLATE_FILE}: {e}")

    if log_message:
        try:
            with open(LOG_FILE, 'a') as f:
                f.write(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - EXIT: {log_message}\n")
        except IOError as e:
            print(f"Error writing to {LOG_FILE}: {e}")

# ===== Auto-detect Arduino Serial Port =====
def detect_arduino_port():
    """
    Detects the Arduino serial port for the exit gate.
    """
    ports = list(serial.tools.list_ports.comports())
    for port in ports:
        if "COM" in port.device: # Refine this if you have specific COM ports for exit
            return port.device
    return None

arduino_port = detect_arduino_port()
if arduino_port:
    print(f"[CONNECTED] Arduino on {arduino_port}")
    arduino = serial.Serial(arduino_port, 9600, timeout=1)
    time.sleep(2)
    update_ui_status("Gate Closed", log_message="Arduino connected.")
else:
    print("[ERROR] Arduino not detected.")
    arduino = None
    update_ui_status("Gate Status Unknown", log_message="Arduino NOT connected!")

# reading distance from ultrasonic sensor
def read_distance(arduino):
    """
    Reads a distance (float) value from the Arduino via serial.
    Returns the float if valid, or None if invalid/empty.
    """
    if arduino and arduino.in_waiting > 0:
        try:
            line = arduino.readline().decode('utf-8').strip()
            return float(line)
        except ValueError:
            return None
    return None

# ===== Check payment status in CSV (Updated to check latest record) =====
def is_payment_complete(plate_number):
    """
    Checks the CSV file to see if the latest entry for a given plate number
    has a payment_status of '1' (paid) and an exit_time recorded.
    Returns True if paid and exited, False if unpaid or not found as entered.
    """
    if not os.path.exists(csv_file):
        update_ui_status("System Error", log_message=f"CSV file not found: {csv_file}. Cannot check payment status.")
        return False

    with open(csv_file, 'r', newline='') as f:
        reader = csv.DictReader(f)
        entries = list(reader) # Convert to list to allow reverse iteration

        # Iterate backwards to find the most recent record for the plate
        for row in reversed(entries):
            # Basic check for row integrity
            if 'car_plate' not in row or 'payment_status' not in row or 'exit_time' not in row:
                continue # Skip malformed rows

            if row['car_plate'] == plate_number: # Found a record for this plate
                if row['payment_status'] == '1': # This session is paid
                    return True # Car has paid for its latest session
                elif row['payment_status'] == '0' and row['exit_time'] == '':
                    # This is an active, unpaid session for the latest entry
                    return False # Car has entered but not paid for current session
                # If it's an unpaid record with an exit_time, it's a previous session that might have been manually closed
                # or an anomaly, but for exit, we care about the *latest* active session.
        
    # If no record found for the plate, or all found records are for already exited/paid older sessions
    return False


# ===== Webcam and Main Loop =====
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print("[ERROR] Could not open webcam.")
    update_ui_status("System Error", log_message="Webcam NOT detected!")
    exit()

plate_buffer = []

print("[EXIT SYSTEM] Ready. Press 'q' to quit.")
update_ui_status("Gate Closed", log_message="Exit system ready.")

while True:
    ret, frame = cap.read()
    if not ret:
        update_ui_status("System Error", log_message="Failed to read frame from webcam!")
        break

    distance = read_distance(arduino)
    # print(f"[SENSOR] Distance: {distance} cm") # Uncomment for debugging

    if distance is not None and distance <= 50: # Car detected by ultrasonic sensor
        results = model(frame) # Perform YOLO detection

        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                plate_img = frame[y1:y2, x1:x2]

                # Preprocessing
                gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
                blur = cv2.GaussianBlur(gray, (5, 5), 0)
                thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

                # OCR
                plate_text = pytesseract.image_to_string(
                    thresh, config='--psm 8 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
                ).strip().replace(" ", "")

                if "RA" in plate_text:
                    start_idx = plate_text.find("RA")
                    plate_candidate = plate_text[start_idx:]
                    if len(plate_candidate) >= 7:
                        plate_candidate = plate_candidate[:7]
                        prefix, digits, suffix = plate_candidate[:3], plate_candidate[3:6], plate_candidate[6]
                        if (prefix.isalpha() and prefix.isupper() and
                            digits.isdigit() and suffix.isalpha() and suffix.isupper()):
                            print(f"[VALID] Plate Detected: {plate_candidate}")
                            update_ui_status("Gate Closed", detected_plate=plate_candidate, log_message=f"Plate detected: {plate_candidate}")
                            plate_buffer.append(plate_candidate)

                            if len(plate_buffer) >= 3:
                                most_common = Counter(plate_buffer).most_common(1)[0][0]
                                plate_buffer.clear()

                                # --- NEW CHECK: Verify if car has entered and paid for its latest session ---
                                if is_payment_complete(most_common): # This function now checks for the latest paid entry
                                    print(f"[ACCESS GRANTED] Payment complete for {most_common}. Opening exit gate.")
                                    update_ui_status("Gate Open", log_message=f"Access granted for {most_common}. Exit gate opening...")
                                    if arduino:
                                        arduino.write(b'1')  # Open gate
                                        print("[GATE] Opening gate (sent '1')")
                                        time.sleep(15)
                                        arduino.write(b'0')  # Close gate
                                        print("[GATE] Closing gate (sent '0')")
                                        update_ui_status("Gate Closed", log_message="Exit gate closed.")
                                else:
                                    # If is_payment_complete returns False, it means either:
                                    # 1. The car never entered (no record found).
                                    # 2. The car entered but its latest session is unpaid.
                                    print(f"[ACCESS DENIED] Car {most_common} has not paid for its current session or has no entry record.")
                                    update_ui_status("Access Denied", log_message=f"Access DENIED for {most_common}. Not paid or no entry.")
                                    if arduino:
                                        arduino.write(b'2')  # Trigger warning buzzer
                                        print("[ALERT] Buzzer triggered (sent '2')")
                                        # Optionally, let buzzer buzz for a short duration
                                        # time.sleep(2)
                                        # arduino.write(b'0') # Turn off buzzer if '0' does that

                cv2.imshow("Plate", plate_img)
                cv2.imshow("Processed", thresh)
                # time.sleep(0.1) # Reduce this if performance is an issue for UI

    annotated_frame = results[0].plot() if distance is not None and distance <= 50 else frame
    cv2.imshow("Exit Webcam Feed", annotated_frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
if arduino:
    arduino.close()
cv2.destroyAllWindows()
update_ui_status("System Offline", log_message="Exit system shut down.")
