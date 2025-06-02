import csv
import serial
import time
import serial.tools.list_ports
import platform
from datetime import datetime
import re # Import regex for more robust cleaning

CSV_FILE = 'testdb.csv'
RATE_PER_MINUTE = 5  # Amount charged per minute


def detect_arduino_port():
    ports = list(serial.tools.list_ports.comports())
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
            if "COM15" in port.device: # Assuming COM14 is the dedicated port for Arduino payment
                return port.device
    return None


def parse_arduino_data(line):
    try:
        # First, remove any null bytes (\x00) from the entire line
        cleaned_line = line.replace('\x00', '').strip()
        
        parts = cleaned_line.split(',')
        print(f"[ARDUINO] Parsed parts (cleaned): {parts}") # Updated print

        if len(parts) != 2:
            print(f"[ERROR] Invalid number of parts ({len(parts)}) after cleaning: '{cleaned_line}'")
            return None, None

        # Clean plate: remove any non-alphanumeric or non-dash/space characters, then strip whitespace
        # This regex keeps letters, numbers, and common plate characters. Adjust if your plates have other symbols.
        plate = re.sub(r'[^a-zA-Z0-9- ]', '', parts[0]).strip()
        print(f"[ARDUINO] Cleaned plate: '{plate}'") # Added print for cleaned plate

        # Clean the balance string by removing non-digit characters and then stripping
        balance_str = ''.join(c for c in parts[1] if c.isdigit()).strip()
        print(f"[ARDUINO] Cleaned balance: '{balance_str}'") # Updated print

        if balance_str:
            balance = int(balance_str)
            return plate, balance
        else:
            print("[ERROR] Balance string is empty after cleaning.")
            return None, None
    except ValueError as e:
        print(f"[ERROR] Value error in parsing: {e}")
        return None, None
    except IndexError as e:
        print(f"[ERROR] IndexError during parsing (likely missing comma): {e} - Line: '{line}'")
        return None, None


def process_payment(plate, balance, ser):
    try:
        with open(CSV_FILE, 'r') as f:
            rows = list(csv.reader(f))

        header = rows[0]
        entries = rows[1:]

        # --- Find the latest unpaid record for the plate ---
        latest_unpaid_index = -1
        # It's important to iterate backwards to find the *latest* entry if a car enters multiple times
        for i in range(len(entries) - 1, -1, -1):
            row = entries[i]
            # Ensure row has enough columns and check if plate matches and status is '0'
            if len(row) > 5 and row[3].strip() == plate and row[5].strip() == '0': # Added .strip() for robustness
                latest_unpaid_index = i
                break # Found the latest unpaid entry, stop searching

        if latest_unpaid_index == -1:
            print(f"[PAYMENT] Car '{plate}' not found with an outstanding payment or already paid.")
            # Optionally, send a signal to Arduino that no payment is needed (e.g., 'A' for Already Paid)
            # ser.write(b'A\n')
            return # Exit the function, no payment needed or found

        # Process the found latest unpaid record
        row_to_update = entries[latest_unpaid_index]
        entry_time_str = row_to_update[1]
        entry_time = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S')
        exit_time = datetime.now()
        minutes_spent = int((exit_time - entry_time).total_seconds() / 60) + 1
        amount_due = minutes_spent * RATE_PER_MINUTE

        row_to_update[2] = exit_time.strftime('%Y-%m-%d %H:%M:%S')
        row_to_update[4] = str(amount_due)

        if balance < amount_due:
            print(f"[PAYMENT] Insufficient balance. Car: {plate}, Due: {amount_due}, Provided: {balance}")
            ser.write(b'I\n') # Send 'I' for Insufficient
            return
        else:
            new_balance = balance - amount_due
            row_to_update[5] = '1' # Mark as paid

            # Wait for Arduino to send "READY"
            print("[WAIT] Waiting for Arduino to be READY...")
            start_time = time.time()
            while True:
                if ser.in_waiting:
                    arduino_response = ser.readline().decode('utf-8', errors='ignore').strip() # Added error handling
                    print(f"[ARDUINO] {arduino_response}")
                    if arduino_response == "READY":
                        break
                if time.time() - start_time > 5:
                    print("[ERROR] Timeout waiting for Arduino READY")
                    # Consider reverting payment status if communication fails here, or handling failure
                    row_to_update[5] = '0' # Revert to unpaid if communication fails
                    return

            # Send new balance
            ser.write(f"{new_balance}\r\n".encode())
            print(f"[PAYMENT] Sent new balance {new_balance}")

            # Wait for confirmation with timeout
            start_time = time.time()
            print("[WAIT] Waiting for Arduino confirmation...")
            while True:
                if ser.in_waiting:
                    confirm = ser.readline().decode('utf-8', errors='ignore').strip() # Added error handling
                    print(f"[ARDUINO] {confirm}")
                    if "DONE" in confirm:
                        print("[ARDUINO] Write confirmed")
                        break # Confirmation received

                # Add timeout condition
                if time.time() - start_time > 10:
                    print("[ERROR] Timeout waiting for confirmation from Arduino.")
                    # IMPORTANT: If confirmation not received, it's safer to revert payment status
                    # This ensures the car remains 'unpaid' in the DB if the Arduino didn't confirm the write.
                    row_to_update[5] = '0'
                    break # Break loop but payment status remains unpaid

                # Small delay to avoid CPU spinning
                time.sleep(0.05) # Slightly reduced delay for faster response

        # Write the updated entries back to the CSV
        with open(CSV_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(entries)
        print(f"[PAYMENT] Payment successful for {plate}. Amount due: {amount_due}, New balance: {new_balance}")

    except Exception as e:
        print(f"[ERROR] Payment processing failed: {e}")


def main():
    port = detect_arduino_port()
    if not port:
        print("[ERROR] Arduino not found")
        # Log to UI if this is a separate process or write to a status file
        try:
            with open('parking_system_log.txt', 'a') as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - [PROCESS_PAYMENT] ERROR: Arduino not found.\n")
        except Exception as log_e:
            print(f"Error writing to log file: {log_e}")
        return

    try:
        ser = serial.Serial(port, 9600, timeout=1)
        print(f"[CONNECTED] Listening on {port}")
        # Log connection status
        try:
            with open('parking_system_log.txt', 'a') as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - [PROCESS_PAYMENT] CONNECTED to Arduino on {port}.\n")
        except Exception as log_e:
            print(f"Error writing to log file: {log_e}")

        time.sleep(2)

        # Flush any previous data
        ser.reset_input_buffer()

        while True:
            if ser.in_waiting:
                # Use errors='ignore' here as well, as this is the first point of decoding
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                print(f"[SERIAL] Received: {line}")
                
                # Check if the line is empty after stripping (e.g., if only null bytes were sent)
                if not line:
                    print("[SERIAL] Received empty line after cleaning. Skipping.")
                    continue

                plate, balance = parse_arduino_data(line)
                if plate and balance is not None:
                    process_payment(plate, balance, ser)
                else:
                    print(f"[PAYMENT] Skipping invalid data: '{line}'")

    except KeyboardInterrupt:
        print("[EXIT] Program terminated by user")
        # Log exit
        try:
            with open('parking_system_log.txt', 'a') as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - [PROCESS_PAYMENT] Program terminated by user.\n")
        except Exception as log_e:
            print(f"Error writing to log file: {log_e}")
    except serial.SerialException as e:
        print(f"[ERROR] Serial communication error: {e}")
        # Log serial error
        try:
            with open('parking_system_log.txt', 'a') as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - [PROCESS_PAYMENT] SERIAL ERROR: {e}.\n")
        except Exception as log_e:
            print(f"Error writing to log file: {log_e}")
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred: {e}")
        # Log unexpected error
        try:
            with open('parking_system_log.txt', 'a') as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - [PROCESS_PAYMENT] UNEXPECTED ERROR: {e}.\n")
        except Exception as log_e:
            print(f"Error writing to log file: {log_e}")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print("[DISCONNECTED] Serial port closed.")
            # Log disconnection
            try:
                with open('parking_system_log.txt', 'a') as f:
                    f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - [PROCESS_PAYMENT] Serial port closed.\n")
            except Exception as log_e:
                print(f"Error writing to log file: {log_e}")

if __name__ == "__main__":
    main()