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

# CSV log file
csv_file = 'testdb.csv'
MAX_DISTANCE = 50   # cm - Max distance to trigger car detection
MIN_DISTANCE = 5    # cm - Min distance to avoid false positives from sensor too close

# --- Auto-detect Arduino Serial Port ---
def detect_arduino_port():
    """
    Attempts to auto-detect the Arduino's serial port.
    Looks for specific identifiers like "COM" on Windows or common USB serial patterns.
    """
    ports = list(serial.tools.list_ports.comports())
    for port in ports:
        # Use a broader search for common Arduino/ESP serial chips and COM ports
        # 'COM17' is specific, but 'USB' or 'UART' in hwid are more general
        if "COM" in port.device and platform.system() == 'Windows': # For Windows COM ports
            if "USB-SERIAL CH340" in port.description or "Arduino" in port.description or "COM17" in port.device:
                return port.device
        elif platform.system() != 'Windows': # For Linux/macOS
            if "ttyUSB" in port.device or "ttyACM" in port.device or "wchusbserial" in port.device:
                return port.device
    print("[WARN] No typical Arduino/ESP serial port found.")
    return None

# --- Read distance from Arduino (Parses "DIST:XX.YY" format) ---
def read_distance(arduino_serial):
    """
    Reads a distance (float) value from the Arduino via serial.
    Parses lines starting with "DIST:".
    Returns the float if valid, or None if invalid/empty/not a distance reading.
    """
    if arduino_serial and arduino_serial.in_waiting > 0:
        try:
            line = arduino_serial.readline().decode('utf-8').strip()
            if line.startswith("DIST:"):
                try:
                    distance_str = line.replace("DIST:", "")
                    return float(distance_str)
                except ValueError:
                    # print(f"[ERROR] Failed to convert distance string '{distance_str}' to float.")
                    return None
            elif line.startswith("MSG:"):
                # print(f"[ARDUINO MSG] {line.replace('MSG:', '')}") # Suppress for cleaner output unless debugging Arduino messages
                pass
            return None # Not a distance reading or unhandled message
        except UnicodeDecodeError:
            # print("[ERROR] UnicodeDecodeError: Could not decode serial data.")
            return None
        except serial.SerialException as e:
            # print(f"[ERROR] Serial communication error: {e}")
            return None
    return None

# Initialize Arduino serial communication
arduino_port = detect_arduino_port()
if arduino_port:
    print(f"[CONNECTED] Attempting to connect to Arduino on {arduino_port}")
    try:
        arduino = serial.Serial(arduino_port, 9600, timeout=1)
        time.sleep(2) # Give Arduino time to reset
        print(f"[SUCCESS] Arduino connected on {arduino_port}")
    except serial.SerialException as e:
        print(f"[ERROR] Could not open serial port {arduino_port}: {e}")
        arduino = None
else:
    print("[ERROR] Arduino serial port not detected. Check connections and port name.")
    arduino = None

# --- Check and update exit record ---
def handle_exit(plate_number, arduino_serial):
    """
    Checks the CSV for the car's entry status and payment.
    - If 'payment_status' is '0' (unpaid) and 'exit_time' is empty, triggers buzzer.
    - If 'payment_status' is '1' (paid) and 'exit_time' is within 5 minutes, grants exit.
    """
    if not os.path.exists(csv_file):
        print("[ERROR] CSV file not found. Cannot process exit.")
        return False

    rows = []
    # Read all rows and find the most recent entry for the plate
    with open(csv_file, 'r', newline='') as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    # Find the most recent entry for the plate_number
    # Iterate in reverse to find the latest relevant entry
    latest_entry_for_plate = None
    for row in reversed(rows):
        if row['car_plate'] == plate_number:
            latest_entry_for_plate = row
            break

    if latest_entry_for_plate:
        # Scenario 1: Car is currently in parking and UNPAID
        if latest_entry_for_plate['payment_status'] == '0' and latest_entry_for_plate['exit_time'] == '':
            print(f"[ACCESS DENIED] Car {plate_number} has not paid. Triggering alert.")
            if arduino_serial:
                arduino_serial.write(b'2') # Send '2' to trigger PAYMENT_PENDING alert on Arduino
                print("[ALERT] Sent '2' to Arduino (Payment Pending/Denied Exit).")
                # Arduino handles the alert duration, no need for long sleep here
                time.sleep(3) # Give time for initial alert burst
                arduino_serial.write(b'S') # Send 'S' to stop alert after a short while if needed
                print("[ALERT] Sent 'S' to Arduino to stop alert after initial burst.")
            return False # Access Denied

        # Scenario 2: Car has paid and is attempting to exit (check if it's the valid paid entry)
        elif latest_entry_for_plate['payment_status'] == '1' and latest_entry_for_plate['exit_time'] != '':
            try:
                # Check if the 'exit_time' in the CSV (which was recorded upon payment) is recent
                csv_exit_time = datetime.strptime(latest_entry_for_plate['exit_time'], '%Y-%m-%d %H:%M:%S')
                time_diff_since_payment = (datetime.now() - csv_exit_time).total_seconds() / 60 # in minutes

                if time_diff_since_payment <= 5: # Must be within 5 minutes of payment/marked exit
                    print(f"[ACCESS GRANTED] Latest paid exit found for {plate_number}. Time since payment: {time_diff_since_payment:.2f} min.")
                    # At this point, you might want to update the 'exit_time' in the CSV again
                    # with the actual current time to mark the final exit, or add a 'final_exit_time' column.
                    # For now, we just return True for access granted.
                    return True # Access Granted
                else:
                    print(f"[ACCESS DENIED] Paid record for {plate_number} is too old ({time_diff_since_payment:.2f} min ago). Triggering alert.")
                    if arduino_serial:
                        arduino_serial.write(b'3') # Trigger alert for old payment
                        print("[ALERT] Sent '3' to Arduino (Old Payment / Denied Exit).")
                        time.sleep(5)
                        arduino_serial.write(b'S')
                    return False # Access Denied
            except ValueError:
                print(f"[ERROR] Invalid 'exit_time' format in CSV for {plate_number}: {latest_entry_for_plate['exit_time']}. Triggering alert.")
                if arduino_serial:
                    arduino_serial.write(b'2')
                    time.sleep(5)
                    arduino_serial.write(b'S')
                return False # Access Denied
        # Scenario 3: Car is in parking but in an unhandled state (e.g., payment_status not 0 or 1)
        else:
            print(f"[ACCESS DENIED] Unhandled status for {plate_number}: Payment_status={latest_entry_for_plate['payment_status']}, Exit_time='{latest_entry_for_plate['exit_time']}'. Triggering alert.")
            if arduino_serial:
                arduino_serial.write(b'3')
                time.sleep(5)
                arduino_serial.write(b'S')
            return False # Access Denied
    else:
        print(f"[ACCESS DENIED] No entry record found for {plate_number}. Triggering alert.")
        if arduino_serial:
            arduino_serial.write(b'2')
            time.sleep(5)
            arduino_serial.write(b'S')
        return False # Access Denied


# --- Webcam and Main Loop ---
cap = cv2.VideoCapture(0) # 0 for default webcam

plate_buffer = [] # Stores recent plate readings for stability
last_plate_detection_time = 0 # To track time since last plate was seen for buffer clearing

print("[EXIT SYSTEM] Ready. Press 'q' to quit.")

# Variable to track if gate is currently open due to this script
is_gate_controlled_open = False
gate_open_time = 0

while True:
    ret, frame = cap.read()
    if not ret:
        print("[ERROR] Failed to grab frame from webcam. Exiting.")
        break

    # --- Read Distance from Ultrasonic Sensor ---
    distance = read_distance(arduino)
    # If distance is None (e.g., parsing error or no data), use a value outside active range
    if distance is None:
        distance_for_check = MAX_DISTANCE + 1 # Effectively makes it "out of range"
    else:
        distance_for_check = distance
    # print(f"[SENSOR] Current Distance: {distance_for_check:.2f} cm") # Uncomment for detailed sensor debugging

    # --- Gate Logic: Close gate if it was opened by script and enough time has passed ---
    if is_gate_controlled_open and (time.time() - gate_open_time) > 15: # 15 seconds open duration
        if arduino:
            arduino.write(b'0') # Close gate
            print("[GATE] Auto-closing gate (sent '0').")
        is_gate_controlled_open = False # Reset flag

    # --- Car Detection and Plate Recognition ---
    plates_detected_in_frame = False # Flag for current frame
    annotated_frame = frame # Default to original frame for display

    if MIN_DISTANCE <= distance_for_check <= MAX_DISTANCE:
        results = model(frame) # Run YOLO detection
        annotated_frame = results[0].plot() # For display

        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                plate_img = frame[y1:y2, x1:x2]

                # Preprocess plate image for OCR
                gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
                blur = cv2.GaussianBlur(gray, (5, 5), 0)
                thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

                # Perform OCR
                plate_text = pytesseract.image_to_string(
                    thresh, config='--psm 8 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
                ).strip().replace(" ", "")

                # Validate plate format (e.g., "RA" prefix, 3 digits, 1 letter)
                if "RA" in plate_text:
                    start_idx = plate_text.find("RA")
                    plate_candidate = plate_text[start_idx:]
                    if len(plate_candidate) >= 7:
                        plate_candidate = plate_candidate[:7] # Ensure it's exactly 7 chars
                        prefix, digits, suffix = plate_candidate[:3], plate_candidate[3:6], plate_candidate[6]
                        if (prefix.isalpha() and prefix.isupper() and
                            digits.isdigit() and suffix.isalpha() and suffix.isupper()):
                            print(f"[VALID] Plate detected: {plate_candidate}")
                            plate_buffer.append(plate_candidate)
                            plates_detected_in_frame = True
                            last_plate_detection_time = time.time() # Update time of last valid plate detection

                            # Decision after 3 consistent captures
                            if len(plate_buffer) >= 3:
                                most_common_plate = Counter(plate_buffer).most_common(1)[0][0]
                                plate_buffer.clear() # Clear buffer after a decision attempt

                                # If gate is not already controlled open by this script
                                if not is_gate_controlled_open: # Prevent re-triggering while gate is active
                                    if handle_exit(most_common_plate, arduino):
                                        print(f"[ACCESS GRANTED] Opening gate for {most_common_plate}")
                                        if arduino:
                                            arduino.write(b'1') # Open gate
                                            print("[GATE] Sent '1' to Arduino (Open Gate).")
                                            is_gate_controlled_open = True
                                            gate_open_time = time.time() # Record time gate was opened
                                        else:
                                            print("[GATE] Gate opening skipped: Arduino not connected.")
                                    # else: handle_exit already prints DENIED message and triggers alert
                                else:
                                    print(f"[INFO] Gate already open, skipping re-check for {most_common_plate}.")

                            # Display processed plate images
                            cv2.imshow("Plate", plate_img)
                            cv2.imshow("Processed", thresh)
                            # Add a small delay after processing a plate to prevent rapid re-detections
                            time.sleep(0.1) # Shorter delay for UI updates

        # Clear plate buffer if no plates have been consistently detected for a short period
        if not plates_detected_in_frame and len(plate_buffer) > 0:
            if time.time() - last_plate_detection_time > 2: # No new plate seen for 2 seconds
                plate_buffer.clear()
                print("[INFO] Plate buffer cleared due to no recent detections.")

    else: # Distance is out of range, clear plate buffer
        if len(plate_buffer) > 0:
            # print("[INFO] Distance out of range, clearing plate buffer.") # Uncomment for detailed sensor debugging
            plate_buffer.clear()

    # --- Display Webcam Feed ---
    # Show annotated frame if results were processed and within distance, else original frame
    cv2.imshow("Exit Webcam Feed", annotated_frame)

    # Exit condition
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# --- Cleanup ---
cap.release()
if arduino:
    arduino.close()
    print("[INFO] Arduino serial connection closed.")
cv2.destroyAllWindows()
print("[EXIT SYSTEM] Shutting down.")