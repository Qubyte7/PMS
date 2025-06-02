import platform
import cv2
from ultralytics import YOLO
import pytesseract
import os
import time
import serial
import serial.tools.list_ports
import csv
from collections import Counter
from datetime import datetime

# Configure Tesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Users\user\AppData\Local\Programs\Tesseract-OCR\tesseract.exe'

# Load YOLOv8 model
model = YOLO('./brain/best3.pt')

# CSV log file for main parking data
csv_file = 'testdb.csv'
MAX_DISTANCE = 50  # cm - Max distance to trigger car detection
MIN_DISTANCE = 5  # cm - Min distance to avoid false positives from sensor too close

# --- NEW: Log File for Unauthorized Attempts ---
UNAUTHORIZED_ATTEMPTS_LOG_FILE = 'unauthorized_attempts_log.csv'

# ===== Helper function to log unauthorized attempts =====
def log_unauthorized_attempt(plate, attempt_type, reason, details=""):
    """
    Logs an unauthorized attempt to a separate CSV file.
    """
    header = ['timestamp', 'car_plate', 'attempt_type', 'reason', 'details']
    
    # Check if file exists and has a header, if not, create it
    if not os.path.exists(UNAUTHORIZED_ATTEMPTS_LOG_FILE) or os.path.getsize(UNAUTHORIZED_ATTEMPTS_LOG_FILE) == 0:
        with open(UNAUTHORIZED_ATTEMPTS_LOG_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(header)

    with open(UNAUTHORIZED_ATTEMPTS_LOG_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        writer.writerow([timestamp, plate, attempt_type, reason, details])
    print(f"[LOG] Unauthorized attempt logged: Plate={plate}, Type={attempt_type}, Reason='{reason}'")


# --- Auto-detect Arduino Serial Port ---
def detect_arduino_port():
    ports = list(serial.tools.list_ports.comports())
    for port in ports:
        if "COM" in port.device and platform.system() == 'Windows':
            if "USB-SERIAL CH340" in port.description or "Arduino" in port.description or "COM17" in port.device:
                return port.device
        elif platform.system() != 'Windows':
            if "ttyUSB" in port.device or "ttyACM" in port.device or "wchusbserial" in port.device:
                return port.device
    print("[WARN] No typical Arduino/ESP serial port found.")
    return None

# --- Read distance from Arduino (Parses "DIST:XX.YY" format) ---
def read_distance(arduino_serial):
    if arduino_serial and arduino_serial.in_waiting > 0:
        try:
            line = arduino_serial.readline().decode('utf-8').strip()
            if line.startswith("DIST:"):
                try:
                    distance_str = line.replace("DIST:", "")
                    return float(distance_str)
                except ValueError:
                    return None
            elif line.startswith("MSG:"):
                pass
            return None
        except UnicodeDecodeError:
            return None
        except serial.SerialException as e:
            return None
    return None

# Initialize Arduino serial communication
arduino_port = detect_arduino_port()
if arduino_port:
    print(f"[CONNECTED] Attempting to connect to Arduino on {arduino_port}")
    try:
        arduino = serial.Serial(arduino_port, 9600, timeout=1)
        time.sleep(2)
        print(f"[SUCCESS] Arduino connected on {arduino_port}")
    except serial.SerialException as e:
        print(f"[ERROR] Could not open serial port {arduino_port}: {e}")
        arduino = None
else:
    print("[ERROR] Arduino serial port not detected. Check connections and port name.")
    arduino = None

# --- Check and update exit record ---
def handle_exit(plate_number, arduino_serial):
    if not os.path.exists(csv_file):
        print("[ERROR] CSV file not found. Cannot process exit.")
        return False

    rows = []
    with open(csv_file, 'r', newline='') as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    latest_entry_for_plate = None
    for row in reversed(rows):
        if row['car_plate'] == plate_number:
            latest_entry_for_plate = row
            break

    if latest_entry_for_plate:
        # Scenario 1: Car is currently in parking and UNPAID
        if latest_entry_for_plate['payment_status'] == '0' and latest_entry_for_plate['exit_time'] == '':
            print(f"[ACCESS DENIED] Car {plate_number} has not paid. Triggering alert.")
            # --- NEW: Log unauthorized exit attempt (unpaid) ---
            log_unauthorized_attempt(plate_number, "EXIT_DENIED", "Payment not made", f"Due: {latest_entry_for_plate['due_payment']}")
            if arduino_serial:
                arduino_serial.write(b'2')
                print("[ALERT] Sent '2' to Arduino (Payment Pending/Denied Exit).")
                time.sleep(10)
                arduino_serial.write(b'S')
                print("[ALERT] Sent 'S' to Arduino to stop alert after initial burst.")
            return False

        # Scenario 2: Car has paid and is attempting to exit (check if it's the valid paid entry)
        elif latest_entry_for_plate['payment_status'] == '1' and latest_entry_for_plate['exit_time'] != '':
            try:
                csv_exit_time = datetime.strptime(latest_entry_for_plate['exit_time'], '%Y-%m-%d %H:%M:%S')
                time_diff_since_payment = (datetime.now() - csv_exit_time).total_seconds() / 60

                if time_diff_since_payment <= 5:
                    print(f"[ACCESS GRANTED] Latest paid exit found for {plate_number}. Time since payment: {time_diff_since_payment:.2f} min.")
                    return True
                else:
                    print(f"[ACCESS DENIED] Paid record for {plate_number} is too old ({time_diff_since_payment:.2f} min ago). Triggering alert.")
                    # --- NEW: Log unauthorized exit attempt (old payment) ---
                    log_unauthorized_attempt(plate_number, "EXIT_DENIED", "Previous payment too old", f"Paid {time_diff_since_payment:.2f} min ago")
                    if arduino_serial:
                        arduino_serial.write(b'3')
                        print("[ALERT] Sent '3' to Arduino (Old Payment / Denied Exit).")
                        time.sleep(3)
                        arduino_serial.write(b'S')
                    return False
            except ValueError:
                print(f"[ERROR] Invalid 'exit_time' format in CSV for {plate_number}: {latest_entry_for_plate['exit_time']}. Triggering alert.")
                # --- NEW: Log unauthorized exit attempt (invalid data) ---
                log_unauthorized_attempt(plate_number, "EXIT_DENIED", "Invalid record data", f"Invalid exit_time format: {latest_entry_for_plate['exit_time']}")
                if arduino_serial:
                    arduino_serial.write(b'2')
                    time.sleep(10)
                    arduino_serial.write(b'S')
                return False
        # Scenario 3: Car is in parking but in an unhandled state
        else:
            print(f"[ACCESS DENIED] Unhandled status for {plate_number}: Payment_status={latest_entry_for_plate['payment_status']}, Exit_time='{latest_entry_for_plate['exit_time']}'. Triggering alert.")
            # --- NEW: Log unauthorized exit attempt (unhandled status) ---
            log_unauthorized_attempt(plate_number, "EXIT_DENIED", "Unhandled status", f"Status: {latest_entry_for_plate['payment_status']}, Exit Time: '{latest_entry_for_plate['exit_time']}'")
            if arduino_serial:
                arduino_serial.write(b'3')
                time.sleep(5)
                arduino_serial.write(b'S')
            return False
    else:
        print(f"[ACCESS DENIED] No entry record found for {plate_number}. Triggering alert.")
        # --- NEW: Log unauthorized exit attempt (no record) ---
        log_unauthorized_attempt(plate_number, "EXIT_DENIED", "No entry record found")
        if arduino_serial:
            arduino_serial.write(b'2')
            time.sleep(10)
            arduino_serial.write(b'S')
        return False

# --- Webcam and Main Loop ---
cap = cv2.VideoCapture(0)

plate_buffer = []
last_plate_detection_time = 0

print("[EXIT SYSTEM] Ready. Press 'q' to quit.")

is_gate_controlled_open = False
gate_open_time = 0

while True:
    ret, frame = cap.read()
    if not ret:
        print("[ERROR] Failed to grab frame from webcam. Exiting.")
        break

    distance = read_distance(arduino)
    if distance is None:
        distance_for_check = MAX_DISTANCE + 1
    else:
        distance_for_check = distance

    if is_gate_controlled_open and (time.time() - gate_open_time) > 15:
        if arduino:
            arduino.write(b'0')
            print("[GATE] Auto-closing gate (sent '0').")
        is_gate_controlled_open = False

    plates_detected_in_frame = False
    annotated_frame = frame

    if MIN_DISTANCE <= distance_for_check <= MAX_DISTANCE:
        results = model(frame)
        annotated_frame = results[0].plot()

        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                plate_img = frame[y1:y2, x1:x2]

                gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
                blur = cv2.GaussianBlur(gray, (5, 5), 0)
                thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

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
                            print(f"[VALID] Plate detected: {plate_candidate}")
                            plate_buffer.append(plate_candidate)
                            plates_detected_in_frame = True
                            last_plate_detection_time = time.time()

                            if len(plate_buffer) >= 3:
                                most_common_plate = Counter(plate_buffer).most_common(1)[0][0]
                                plate_buffer.clear()

                                if not is_gate_controlled_open:
                                    if handle_exit(most_common_plate, arduino):
                                        print(f"[ACCESS GRANTED] Opening gate for {most_common_plate}")
                                        if arduino:
                                            arduino.write(b'1')
                                            print("[GATE] Sent '1' to Arduino (Open Gate).")
                                            is_gate_controlled_open = True
                                            gate_open_time = time.time()
                                        else:
                                            print("[GATE] Gate opening skipped: Arduino not connected.")
                                else:
                                    print(f"[INFO] Gate already open, skipping re-check for {most_common_plate}.")

                                cv2.imshow("Plate", plate_img)
                                cv2.imshow("Processed", thresh)
                                time.sleep(0.1)

        if not plates_detected_in_frame and len(plate_buffer) > 0:
            if time.time() - last_plate_detection_time > 2:
                plate_buffer.clear()
                print("[INFO] Plate buffer cleared due to no recent detections.")
    else:
        if len(plate_buffer) > 0:
            plate_buffer.clear()

    cv2.imshow("Exit Webcam Feed", annotated_frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
if arduino:
    arduino.close()
    print("[INFO] Arduino serial connection closed.")
cv2.destroyAllWindows()
print("[EXIT SYSTEM] Shutting down.")