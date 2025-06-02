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

# ===== Auto-detect Arduino Serial Port =====
def detect_arduino_port():
    ports = list(serial.tools.list_ports.comports())
    for port in ports:
        # Check for specific identifiers if "COM17" or "wchusbmodem" might vary
        # On Windows, it's often COMx. On Linux/macOS, it's usually /dev/ttyUSBx or /dev/tty.wchusbserialx
        if "COM17" in port.device or "USB" in port.hwid or "UART" in port.hwid: # Broader search for common Arduino/ESP serial chips
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
    """
    Checks the CSV file to see if a car with the given plate number
    is currently marked as 'in parking' (latest record has payment_status '0' and empty exit_time).
    """
    if not os.path.exists(csv_file):
        print(f"[WARNING] CSV file not found: {csv_file}. Cannot check parking status.")
        return False # Assume not in parking if file doesn't exist

    with open(csv_file, 'r', newline='') as f:
        reader = csv.DictReader(f)
        entries = list(reader)

        for row in reversed(entries): # Iterate backwards to find the most recent record
            if 'car_plate' not in row or 'payment_status' not in row or 'exit_time' not in row:
                continue # Skip malformed rows

            if row['car_plate'] == plate_number:
                # Car is considered "in parking" if the latest record for it
                # has 'payment_status' 0 and 'exit_time' is empty.
                if row['payment_status'] == '0' and row['exit_time'] == '':
                    return True # Car is currently in parking
                elif row['payment_status'] == '1' and row['exit_time'] != '':
                    # If the latest record is paid and has an exit time,
                    # it means the car has completed its previous session.
                    return False # Car is not currently in parking
    return False # No relevant record found, or all records indicate car has exited


# ===== CORRECTED read_distance FUNCTION =====
def read_distance(arduino):
    """
    Reads a distance (float) value from the Arduino via serial.
    Parses lines starting with "DIST:".
    Returns the float if valid, or None if invalid/empty/not a distance reading.
    """
    if arduino and arduino.in_waiting > 0:
        try:
            line = arduino.readline().decode('utf-8').strip()
            # Check if the line contains the "DIST:" prefix
            if line.startswith("DIST:"):
                distance_str = line.replace("DIST:", "") # Remove the prefix
                return float(distance_str) # Convert the remaining string to float
            else:
                # Optionally print other messages from Arduino for debugging
                if line.startswith("MSG:"):
                    print(f"[ARDUINO MSG] {line.replace('MSG:', '')}")
                return None # Not a distance reading
        except ValueError:
            # This will catch errors if distance_str cannot be converted to float
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
        header = next(reader, None) # Skip header
        entry_count = sum(1 for row in reader)


while True:
    ret, frame = cap.read()
    if not ret:
        break

    distance = read_distance(arduino) # Now this should correctly parse "DIST:XX.YY"
    print(f"[SENSOR] Distance: {distance} cm")

    # Only process if a valid distance is received AND it's within range
    if distance is not None and distance <= 50: # Assuming 50cm is your trigger distance
        results = model(frame)

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

                # Plate Validation (RA followed by 3 digits and 1 letter)
                if "RA" in plate_text:
                    start_idx = plate_text.find("RA")
                    plate_candidate = plate_text[start_idx:]
                    if len(plate_candidate) >= 7:
                        plate_candidate = plate_candidate[:7] # Ensure it's exactly 7 chars
                        prefix, digits, suffix = plate_candidate[:3], plate_candidate[3:6], plate_candidate[6]
                        if (prefix.isalpha() and prefix.isupper() and
                            digits.isdigit() and suffix.isalpha() and suffix.isupper()):
                            print(f"[VALID] Plate Detected: {plate_candidate}")
                            plate_buffer.append(plate_candidate)

                            # Decision after 3 captures
                            if len(plate_buffer) >= 3:
                                most_common = Counter(plate_buffer).most_common(1)[0][0]
                                current_time = time.time()

                                if is_car_already_in_parking(most_common):
                                    print(f"[DENIED] Car {most_common} is already in parking (active session).")
                                    if arduino:
                                        arduino.write(b'3') # Send '3' for PAYMENT_PENDING/DENIED ENTRY
                                        print("[ALERT] Denied entry, triggering warning buzzer (sent '2')")
                                        time.sleep(5) # buzzer beeping 
                                        arduino.write(b'S') # Send '0' to stop buzzer
                                        # The Arduino will handle the buzzer pattern and light state for the alert
                                    # Optional: clear buffer immediately after denial to prevent rapid re-denial
                                    plate_buffer.clear()

                                elif (most_common != last_saved_plate or
                                      (current_time - last_entry_time) > entry_cooldown):
                                    # If not a duplicate within cooldown and not already in parking
                                    with open(csv_file, 'a', newline='') as f:
                                        writer = csv.writer(f)
                                        entry_count += 1
                                        writer.writerow([
                                            entry_count,
                                            datetime.now().strftime('%Y-%m-%d %H:%M:%S'), # Use datetime for current time
                                            '', most_common, '', 0 # due_payment empty, payment_status 0 (unpaid)
                                        ])
                                    print(f"[SAVED] {most_common} logged to CSV.")

                                    if arduino:
                                        arduino.write(b'1') # Send '1' to open gate
                                        print("[GATE] Opening gate (sent '1')")
                                        # The Arduino will handle the buzzer for gate opening and light changes.
                                        # The 15-second delay here means the gate stays open for 15s in Arduino.
                                        # The Arduino will also handle the buzzer during this time.
                                        time.sleep(15) # Gate open duration
                                        arduino.write(b'0') # Send '0' to close gate
                                        print("[GATE] Closing gate (sent '0')")
                                    last_saved_plate = most_common
                                    last_entry_time = current_time
                                else:
                                    print(f"[SKIPPED] Duplicate plate {most_common} within {entry_cooldown/60} min cooldown period.")

                                plate_buffer.clear() # Clear buffer after processing
                                # Delay after processing a plate to avoid rapid re-detections
                                time.sleep(1) # Small delay to give sensor/camera time to reset

                cv2.imshow("Plate", plate_img)
                cv2.imshow("Processed", thresh)
                time.sleep(0.1) # Small delay for UI updates

    # Display annotated frame
    # Make sure 'results' is defined if distance is not None
    annotated_frame = frame # Default to original frame
    if distance is not None and distance <= 50 and 'results' in locals():
        annotated_frame = results[0].plot()

    cv2.imshow('Webcam Feed', annotated_frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
if arduino:
    arduino.close()
cv2.destroyAllWindows()