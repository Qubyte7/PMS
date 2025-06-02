import cv2
from ultralytics import YOLO
import pytesseract
import os
import time
import serial
import serial.tools.list_ports
import csv
from collections import Counter
from datetime import datetime # Import datetime for proper time handling

# --- NEW: Log File for Unauthorized Attempts ---
UNAUTHORIZED_ATTEMPTS_LOG_FILE = 'unauthorized_attempts_log.csv'

# Configure Tesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Users\user\AppData\Local\Programs\Tesseract-OCR\tesseract.exe'

# Load YOLOv8 model
model = YOLO('./brain/best3.pt')

# Plate save directory (not used in current script, but defined)
save_dir = 'plates'
os.makedirs(save_dir, exist_ok=True)

# CSV log file for main parking data
csv_file = 'testdb.csv'
if not os.path.exists(csv_file):
    with open(csv_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['no', 'entry_time', 'exit_time', 'car_plate', 'due_payment', 'payment_status'])

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


# ===== Auto-detect Arduino Serial Port =====
def detect_arduino_port():
    ports = list(serial.tools.list_ports.comports())
    for port in ports:
        if "COM17" in port.device or "USB" in port.hwid or "UART" in port.hwid:
            return port.device
    return None

arduino_port = detect_arduino_port()
if arduino_port:
    print(f"[CONNECTED] Arduino on {arduino_port}")
    arduino = serial.Serial(arduino_port, 9600, timeout=1)
    time.sleep(2)
else:
    print("[ERROR] Arduino not detected.")
    arduino = None

# ===== Function to check if car is already in parking (updated to check latest record) =====
def is_car_already_in_parking(plate_number):
    if not os.path.exists(csv_file):
        print(f"[WARNING] CSV file not found: {csv_file}. Cannot check parking status.")
        return False

    with open(csv_file, 'r', newline='') as f:
        reader = csv.DictReader(f)
        entries = list(reader)

        for row in reversed(entries):
            if 'car_plate' not in row or 'payment_status' not in row or 'exit_time' not in row:
                continue

            if row['car_plate'] == plate_number:
                if row['payment_status'] == '0' and row['exit_time'] == '':
                    return True
                elif row['payment_status'] == '1' and row['exit_time'] != '':
                    return False
    return False

# ===== CORRECTED read_distance FUNCTION =====
def read_distance(arduino):
    if arduino and arduino.in_waiting > 0:
        try:
            line = arduino.readline().decode('utf-8').strip()
            if line.startswith("DIST:"):
                distance_str = line.replace("DIST:", "")
                return float(distance_str)
            else:
                if line.startswith("MSG:"):
                    print(f"[ARDUINO MSG] {line.replace('MSG:', '')}")
                return None
        except ValueError:
            print(f"[ERROR] Could not convert '{distance_str}' to float.")
            return None
        except UnicodeDecodeError:
            print("[ERROR] UnicodeDecodeError: Could not decode serial data.")
            return None
    return None

# Initialize webcam
cap = cv2.VideoCapture(0)
plate_buffer = []
entry_cooldown = 300  # 5 minutes in seconds
last_saved_plate = None
last_entry_time = 0

print("[SYSTEM] Ready. Press 'q' to exit.")

# Count existing entries to get the next 'no'
entry_count = 0
if os.path.exists(csv_file):
    with open(csv_file, 'r') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        entry_count = sum(1 for row in reader)


while True:
    ret, frame = cap.read()
    if not ret:
        break

    distance = read_distance(arduino)
    # print(f"[SENSOR] Distance: {distance} cm") # Uncomment for verbose sensor debugging

    if distance is not None and distance <= 50:
        results = model(frame)

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
                            print(f"[VALID] Plate Detected: {plate_candidate}")
                            plate_buffer.append(plate_candidate)

                            if len(plate_buffer) >= 3:
                                most_common = Counter(plate_buffer).most_common(1)[0][0]
                                current_time = time.time()

                                if is_car_already_in_parking(most_common):
                                    print(f"[DENIED] Car {most_common} is already in parking (active session).")
                                    # --- NEW: Log unauthorized entry attempt ---
                                    log_unauthorized_attempt(most_common, "ENTRY_DENIED", "Car already in parking")
                                    if arduino:
                                        arduino.write(b'3') # Send '3' for PAYMENT_PENDING/DENIED ENTRY
                                        print("[ALERT] Denied entry, triggering warning buzzer (sent '3')")
                                        time.sleep(10) # buzzer beeping
                                        arduino.write(b'S') # Send 'S' to stop buzzer
                                    plate_buffer.clear() # Clear buffer immediately after denial

                                elif (most_common != last_saved_plate or
                                      (current_time - last_entry_time) > entry_cooldown):
                                    with open(csv_file, 'a', newline='') as f:
                                        writer = csv.writer(f)
                                        entry_count += 1
                                        writer.writerow([
                                            entry_count,
                                            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                            '', most_common, '', 0
                                        ])
                                    print(f"[SAVED] {most_common} logged to CSV.")

                                    if arduino:
                                        arduino.write(b'1') # Send '1' to open gate
                                        print("[GATE] Opening gate (sent '1')")
                                        time.sleep(15)
                                        arduino.write(b'0') # Send '0' to close gate
                                        print("[GATE] Closing gate (sent '0')")
                                    last_saved_plate = most_common
                                    last_entry_time = current_time
                                else:
                                    print(f"[SKIPPED] Duplicate plate {most_common} within {entry_cooldown/60} min cooldown period.")

                                plate_buffer.clear()
                                time.sleep(1)

                cv2.imshow("Plate", plate_img)
                cv2.imshow("Processed", thresh)
                time.sleep(0.1)

    annotated_frame = frame
    if distance is not None and distance <= 50 and 'results' in locals():
        annotated_frame = results[0].plot()

    cv2.imshow('Webcam Feed', annotated_frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
if arduino:
    arduino.close()
cv2.destroyAllWindows()
print("[SYSTEM] Shutting down.")