import cv2
from ultralytics import YOLO
import pytesseract
import os
import time
import serial
import serial.tools.list_ports
import csv
from collections import Counter
import datetime # Import datetime

pytesseract.pytesseract.tesseract_cmd = r'C:\Users\user\AppData\Local\Programs\Tesseract-OCR\tesseract.exe'

# Load YOLOv8 model
model = YOLO('./brain/best3.pt')

# Plate save directory
save_dir = 'plates'
os.makedirs(save_dir, exist_ok=True)

# CSV log file
csv_file = 'testdb.csv'
if not os.path.exists(csv_file):
    with open(csv_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['no', 'entry_time', 'exit_time', 'car_plate', 'due_payment', 'payment_status'])

# --- UI Communication Files ---
ENTRY_STATUS_FILE = 'entry_gate_status.txt'
DETECTED_PLATE_FILE = 'detected_plate.txt'
LOG_FILE = 'parking_system_log.txt'

def update_ui_status(gate_status, detected_plate=None, log_message=None):
    """
    Updates status files for UI communication.
    """
    try:
        with open(ENTRY_STATUS_FILE, 'w') as f:
            f.write(gate_status)
    except IOError as e:
        print(f"Error writing to {ENTRY_STATUS_FILE}: {e}")

    if detected_plate:
        try:
            with open(DETECTED_PLATE_FILE, 'w') as f:
                f.write(detected_plate)
        except IOError as e:
            print(f"Error writing to {DETECTED_PLATE_FILE}: {e}")

    if log_message:
        try:
            with open(LOG_FILE, 'a') as f:
                f.write(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - ENTRY: {log_message}\n")
        except IOError as e:
            print(f"Error writing to {LOG_FILE}: {e}")


# ===== Auto-detect Arduino Serial Port =====
def detect_arduino_port():
    """
    Detects the Arduino serial port. Adjust 'COM13' or 'wchusbmodem' as per your Arduino setup.
    """
    ports = list(serial.tools.list_ports.comports())
    for port in ports:
        if "COM13" in port.device or "wchusbmodem" in port.device: # Specific to your previous setup
            return port.device
    return None

arduino_port = detect_arduino_port()
if arduino_port:
    print(f"[CONNECTED] Arduino on {arduino_port}")
    arduino = serial.Serial(arduino_port, 9600, timeout=1)
    time.sleep(2) # Allow time for Arduino to initialize
    update_ui_status("Gate Closed", log_message="Arduino connected.")
else:
    print("[ERROR] Arduino not detected.")
    arduino = None
    update_ui_status("Gate Status Unknown", log_message="Arduino NOT connected!")

# ==== Reading distance from ultrasonic sensor =====
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

# ===== Function to check if car is already in parking (updated to check latest record) =====
def is_car_already_in_parking(plate_number):
    """
    Checks the CSV file to see if a car with the given plate number
    is currently marked as 'in parking' (latest record has payment_status '0' and empty exit_time).
    """
    if not os.path.exists(csv_file):
        print(f"[WARNING] CSV file not found: {csv_file}. Cannot check parking status.")
        return False # Assume not in parking if file doesn't exist

    with open(csv_file, 'r', newline='') as f:
        reader = csv.DictReader(f)
        # Convert to list to allow reverse iteration
        entries = list(reader) 
        
        # Iterate backwards to find the most recent record for the plate
        for row in reversed(entries):
            # Basic check for row integrity (ensure enough columns exist)
            if 'car_plate' not in row or 'payment_status' not in row or 'exit_time' not in row:
                continue # Skip malformed rows

            if row['car_plate'] == plate_number: # Found a record for this plate
                if row['payment_status'] == '0' and row['exit_time'] == '': # This is an active, unpaid session
                    return True # Car is already in parking (latest session is active)
                elif row['payment_status'] == '1': # Found a paid record for this plate
                    # If the most recent record for this plate is paid,
                    # it implies the car has exited or completed its previous session.
                    return False # Car is not currently in parking (latest session is closed)
        
    return False # No record found or all records are for exited/paid sessions


# Initialize webcam
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print("[ERROR] Could not open webcam.")
    update_ui_status("System Error", log_message="Webcam NOT detected!")
    exit() # Exit if webcam isn't available

plate_buffer = []
entry_cooldown = 300  # 5 minutes cooldown to prevent rapid re-entry of the same car
last_saved_plate = None
last_entry_time = 0

print("[SYSTEM] Ready. Press 'q' to exit.")
update_ui_status("Gate Closed", log_message="Entry system ready.")

# Get initial entry count for 'no' column in CSV
# Subtract 1 for the header row
try:
    with open(csv_file, 'r') as f:
        entry_count = sum(1 for _ in f) - 1
        if entry_count < 0: # Handle case of empty or only header file
            entry_count = 0
except FileNotFoundError:
    entry_count = 0 # If file doesn't exist, start count from 0

while True:
    ret, frame = cap.read()
    if not ret:
        update_ui_status("System Error", log_message="Failed to read frame from webcam!")
        break

    distance = read_distance(arduino)
    # print(f"[SENSOR] Distance: {distance} cm") # Uncomment for debugging distance

    if distance is not None and distance <= 50: # Car detected by ultrasonic sensor
        results = model(frame) # Perform YOLO detection

        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                plate_img = frame[y1:y2, x1:x2]

                # Plate Image Processing
                gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
                blur = cv2.GaussianBlur(gray, (5, 5), 0)
                thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

                # OCR Extraction
                plate_text = pytesseract.image_to_string(
                    thresh, config='--psm 8 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
                ).strip().replace(" ", "")

                # Plate Validation
                if "RA" in plate_text: # Assuming "RA" is a common prefix for valid plates
                    start_idx = plate_text.find("RA")
                    plate_candidate = plate_text[start_idx:]
                    if len(plate_candidate) >= 7: # Check for minimum length
                        plate_candidate = plate_candidate[:7] # Take first 7 characters
                        prefix, digits, suffix = plate_candidate[:3], plate_candidate[3:6], plate_candidate[6]
                        if (prefix.isalpha() and prefix.isupper() and # Validate format
                            digits.isdigit() and suffix.isalpha() and suffix.isupper()):
                            print(f"[VALID] Plate Detected: {plate_candidate}")
                            update_ui_status("Gate Closed", detected_plate=plate_candidate, log_message=f"Plate detected: {plate_candidate}")
                            plate_buffer.append(plate_candidate)

                            # Decision after 3 consistent captures
                            if len(plate_buffer) >= 3:
                                most_common = Counter(plate_buffer).most_common(1)[0][0]
                                current_time = time.time()

                                # Check for duplicate entry within cooldown or if car is already in parking
                                if (most_common == last_saved_plate and (current_time - last_entry_time) < entry_cooldown):
                                    print("[SKIPPED] Duplicate within 5 min window.")
                                    update_ui_status("Gate Closed", log_message=f"Plate {most_common} skipped (duplicate/cooldown).")
                                elif is_car_already_in_parking(most_common): # Check if car is already marked as in parking
                                    print(f"[DENIED] Car {most_common} is already in parking.")
                                    update_ui_status("Gate Closed", log_message=f"Car {most_common} denied entry: already in parking.")
                                    if arduino:
                                        # Optionally send a signal to Arduino for "denied entry" (e.g., buzzer)
                                        # arduino.write(b'2') # Assuming '2' triggers a buzzer
                                        # time.sleep(2) # Buzzer duration
                                        # arduino.write(b'0') # Turn off buzzer
                                        pass
                                else:
                                    # Log new entry to CSV
                                    with open(csv_file, 'a', newline='') as f:
                                        writer = csv.writer(f)
                                        entry_count += 1
                                        writer.writerow([
                                            entry_count,
                                            time.strftime('%Y-%m-%d %H:%M:%S'),
                                            '', most_common, '', 0 # Empty exit_time, 0 for unpaid
                                        ])
                                    print(f"[SAVED] {most_common} logged to CSV.")
                                    update_ui_status("Gate Closed", log_message=f"Car {most_common} recorded for entry.")

                                    # Open gate if Arduino is connected
                                    if arduino:
                                        arduino.write(b'1') # Signal to open gate
                                        print("[GATE] Opening gate (sent '1')")
                                        update_ui_status("Gate Open", log_message="Entry gate opening...")
                                        time.sleep(15) # Gate open duration
                                        arduino.write(b'0') # Signal to close gate
                                        print("[GATE] Closing gate (sent '0')")
                                        update_ui_status("Gate Closed", log_message="Entry gate closed.")

                                    last_saved_plate = most_common
                                    last_entry_time = current_time

                                plate_buffer.clear() # Clear buffer after decision

                cv2.imshow("Plate", plate_img)
                cv2.imshow("Processed", thresh)
                # time.sleep(0.1) # Small delay to allow UI to update if needed

    annotated_frame = results[0].plot() if distance is not None and distance <= 50 else frame
    cv2.imshow('Webcam Feed', annotated_frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
if arduino:
    arduino.close()
cv2.destroyAllWindows()
update_ui_status("System Offline", log_message="Entry system shut down.")
