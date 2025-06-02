import csv
import serial
import time
import serial.tools.list_ports
import platform
from datetime import datetime
import os # Import os for file existence check

CSV_FILE = 'testdb.csv'
RATE_PER_MINUTE = 5  # Amount charged per minute
LOG_FILE = 'parking_system_log.txt' # Shared log file for UI communication

def log_message(message):
    """
    Logs messages to a shared log file for UI display.
    """
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - PAYMENT: {message}\n")
    except IOError as e:
        print(f"Error writing to {LOG_FILE}: {e}")

def detect_arduino_port():
    """
    Detects the Arduino serial port for payment processing.
    """
    ports = list(serial.tools.list_list_ports.comports())
    system = platform.system()
    print(system)
    for port in ports:
        if system == "Linux":
            if "ttyUSB" in port.device or "ttyACM" in port.device:
                return port.device
        elif system == "Darwin":
            if "usbmodem" in port.device or "usbserial" in port.device:
                return port.device
        elif system == "Windows":
            if "COM14" in port.device: # Adjust to your payment Arduino COM port
                return port.device
    return None


def parse_arduino_data(line):
    """
    Parses plate number and balance from Arduino serial data.
    """
    try:
        parts = line.strip().split(',')
        print(f"[ARDUINO] Parsed parts: {parts}")
        if len(parts) != 2:
            log_message(f"Invalid Arduino data format: {line}")
            return None, None
        plate = parts[0].strip()

        # Clean the balance string by removing non-digit characters
        balance_str = ''.join(c for c in parts[1] if c.isdigit())
        print(f"[ARDUINO] Cleaned balance: {balance_str}")

        if balance_str:
            balance = int(balance_str)
            return plate, balance
        else:
            log_message(f"Invalid balance received: {parts[1]}")
            return None, None
    except ValueError as e:
        log_message(f"Value error in parsing: {e} - Line: {line}")
        return None, None


def process_payment(plate, balance, ser):
    """
    Processes payment for a given car plate, updates CSV, and communicates with Arduino.
    Ensures only the latest unpaid entry is processed.
    """
    try:
        if not os.path.exists(CSV_FILE):
            log_message(f"CSV file not found: {CSV_FILE}")
            print(f"[ERROR] CSV file not found: {CSV_FILE}")
            return

        with open(CSV_FILE, 'r', newline='') as f:
            rows = list(csv.reader(f))

        if not rows:
            log_message("CSV file is empty.")
            print("[ERROR] CSV file is empty.")
            return

        header = rows[0]
        entries = rows[1:]
        
        # --- Find the latest unpaid entry for the given plate ---
        target_entry_index = -1
        # Iterate backwards to find the most recent record for the plate
        for i in range(len(entries) - 1, -1, -1): 
            row = entries[i]
            # Basic check for row integrity (ensure enough columns exist)
            if len(row) < 6: 
                continue

            if row[3] == plate: # Found a record for this plate
                if row[5] == '0' and row[2] == '': # This is an active, unpaid session
                    target_entry_index = i
                    break # Found the latest active unpaid session, stop searching
                elif row[5] == '1': # Found a paid record for this plate
                    # If the most recent record for this plate is already paid,
                    # it implies there's no current outstanding payment for this car.
                    # We should not process payment for this car at this time.
                    print(f"[PAYMENT] Plate {plate} has already paid for its latest session or has no outstanding payment.")
                    log_message(f"Plate {plate} has already paid for its latest session or has no outstanding payment.")
                    # Optionally, send a signal to Arduino if already paid/no outstanding (e.g., 'A' for Already Paid)
                    # ser.write(b'A\n') 
                    return # Exit the function as no payment is needed/possible for this car

        if target_entry_index == -1:
            # If loop finishes and no active unpaid entry was found
            print(f"[PAYMENT] Plate {plate} not found with an outstanding payment record.")
            log_message(f"Plate {plate} not found with an outstanding payment record.")
            # Optionally send a signal to Arduino if plate not found (e.g., 'N' for Not Found / No Outstanding)
            # ser.write(b'N\n')
            return

        # If we reached here, target_entry_index holds the index of the latest unpaid entry
        row_to_update = entries[target_entry_index]

        entry_time_str = row_to_update[1]
        try:
            entry_time = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            log_message(f"Invalid entry time format for plate {plate}: {entry_time_str}")
            print(f"[ERROR] Invalid entry time format for plate {plate}: {entry_time_str}")
            return

        exit_time = datetime.now()
        minutes_spent = int((exit_time - entry_time).total_seconds() / 60) + 1
        amount_due = minutes_spent * RATE_PER_MINUTE

        row_to_update[2] = exit_time.strftime('%Y-%m-%d %H:%M:%S') # Update exit_time
        row_to_update[4] = str(amount_due) # Update due_payment

        log_message(f"Plate {plate} needs to pay {amount_due}. Balance: {balance}")
        print(f"[PAYMENT] Plate {plate} needs to pay {amount_due}. Current balance: {balance}")

        if balance < amount_due:
            print("[PAYMENT] Insufficient balance")
            log_message(f"Insufficient balance for {plate}. Due: {amount_due}, Had: {balance}")
            ser.write(b'I\n') # Signal insufficient balance
            return
        else:
            new_balance = balance - amount_due
            log_message(f"Payment successful for {plate}. New balance: {new_balance}")

            # Wait for Arduino to send "READY"
            print("[WAIT] Waiting for Arduino to be READY...")
            log_message("Waiting for Arduino 'READY' signal.")
            start_time = time.time()
            while True:
                if ser.in_waiting:
                    arduino_response = ser.readline().decode().strip()
                    print(f"[ARDUINO] {arduino_response}")
                    if arduino_response == "READY":
                        log_message("Arduino is READY.")
                        break
                if time.time() - start_time > 5:
                    log_message("[ERROR] Timeout waiting for Arduino READY")
                    print("[ERROR] Timeout waiting for Arduino READY")
                    return
                time.sleep(0.01) # Small delay

            # Send new balance
            ser.write(f"{new_balance}\r\n".encode())
            print(f"[PAYMENT] Sent new balance {new_balance} to Arduino.")
            log_message(f"Sent new balance {new_balance} to Arduino for plate {plate}.")

            # Wait for confirmation with timeout
            start_time = time.time()
            print("[WAIT] Waiting for Arduino confirmation...")
            log_message("Waiting for Arduino confirmation 'DONE'.")
            while True:
                if ser.in_waiting:
                    confirm = ser.readline().decode().strip()
                    print(f"[ARDUINO] {confirm}")
                    if "DONE" in confirm:
                        print("[ARDUINO] Write confirmed")
                        log_message("Arduino write confirmed.")
                        entries[target_entry_index][5] = '1' # Mark as paid in the identified row
                        break

                if time.time() - start_time > 10:
                    print("[ERROR] Timeout waiting for confirmation")
                    log_message("[ERROR] Timeout waiting for Arduino confirmation")
                    break

                time.sleep(0.1)

        # Write updated data back to CSV
        with open(CSV_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(entries)
        log_message(f"CSV file updated for plate {plate}.")

    except Exception as e:
        log_message(f"[ERROR] Payment processing failed for plate {plate}: {e}")
        print(f"[ERROR] Payment processing failed: {e}")


def main():
    log_message("Payment system started.")
    port = detect_arduino_port()
    if not port:
        print("[ERROR] Arduino for payment not found")
        log_message("Arduino for payment NOT found!")
        return

    try:
        ser = serial.Serial(port, 9600, timeout=1)
        print(f"[CONNECTED] Listening on {port} for payment data.")
        log_message(f"Connected to Arduino for payment on {port}.")
        time.sleep(2)

        ser.reset_input_buffer()

        while True:
            if ser.in_waiting:
                line = ser.readline().decode().strip()
                print(f"[SERIAL] Received: {line}")
                log_message(f"Received from Arduino: {line}")
                plate, balance = parse_arduino_data(line)
                if plate and balance is not None:
                    process_payment(plate, balance, ser)

    except KeyboardInterrupt:
        print("[EXIT] Program terminated by user.")
        log_message("Payment system terminated by user.")
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred: {e}")
        log_message(f"[ERROR] An unexpected error occurred in payment main loop: {e}")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
            log_message("Payment Arduino serial port closed.")
        log_message("Payment system shut down.")
