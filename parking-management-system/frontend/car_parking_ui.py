import tkinter as tk
from tkinter import ttk
import os
import time
import subprocess
import threading
from datetime import datetime
import csv

# --- File Paths for UI Communication ---
ENTRY_STATUS_FILE = 'entry_gate_status.txt'
EXIT_STATUS_FILE = 'exit_gate_status.txt'
DETECTED_PLATE_FILE = 'detected_plate.txt'
LOG_FILE = 'parking_system_log.txt'
CSV_FILE = 'testdb.csv' # For displaying parking records

class ParkingSystemUI:
    def __init__(self, master):
        self.master = master
        master.title("Smart Parking System Dashboard")
        master.geometry("1000x700") # Wider window

        # --- Styles ---
        self.style = ttk.Style()
        self.style.configure("TFrame", background="#E0F2F7") # Light blue background
        self.style.configure("TLabel", background="#E0F2F7", font=("Helvetica", 12))
        self.style.configure("TButton", font=("Helvetica", 12, "bold"))
        self.style.configure("Header.TLabel", font=("Helvetica", 16, "bold"), foreground="#00796B") # Teal
        self.style.configure("Status.TLabel", font=("Helvetica", 14, "bold"))
        self.style.configure("Plate.TLabel", font=("Helvetica", 18, "bold"), foreground="#D32F2F") # Red

        # Removed: self.style.tag_configure(...) from here
        # These will be called on self.records_tree directly after its creation.

        # --- Variables to update UI ---
        self.system_status = tk.StringVar(value="Initializing...")
        self.entry_gate_status = tk.StringVar(value="Unknown")
        self.exit_gate_status = tk.StringVar(value="Unknown")
        self.detected_plate = tk.StringVar(value="N/A")
        self.parking_records_data = [] # To store CSV data

        self.create_widgets() # Call create_widgets first to ensure records_tree exists
        self.init_files()
        self.start_backend_processes()
        self.update_ui() # Start periodic UI updates

    def init_files(self):
        # Create empty files if they don't exist
        for f in [ENTRY_STATUS_FILE, EXIT_STATUS_FILE, DETECTED_PLATE_FILE, LOG_FILE]:
            if not os.path.exists(f):
                with open(f, 'w') as temp_f:
                    pass # Create empty file

    def create_widgets(self):
        # --- Header ---
        header_frame = ttk.Frame(self.master, padding="15 15 15 15", relief="raised")
        header_frame.pack(fill=tk.X, pady=10)
        ttk.Label(header_frame, text="Smart Parking System Dashboard", style="Header.TLabel").pack()

        # --- System Status ---
        status_frame = ttk.Frame(self.master, padding="10 10 10 10", relief="groove")
        status_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(status_frame, text="Overall System Status:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        ttk.Label(status_frame, textvariable=self.system_status, style="Status.TLabel", foreground="blue").grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)

        # --- Gate Statuses ---
        gate_status_frame = ttk.Frame(self.master, padding="10 10 10 10", relief="groove")
        gate_status_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(gate_status_frame, text="Entry Gate Status:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.entry_status_label = ttk.Label(gate_status_frame, textvariable=self.entry_gate_status, style="Status.TLabel")
        self.entry_status_label.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)

        ttk.Label(gate_status_frame, text="Exit Gate Status:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.exit_status_label = ttk.Label(gate_status_frame, textvariable=self.exit_gate_status, style="Status.TLabel")
        self.exit_status_label.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)

        # --- Last Detected Plate ---
        plate_frame = ttk.Frame(self.master, padding="10 10 10 10", relief="groove")
        plate_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(plate_frame, text="Last Detected Plate:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        ttk.Label(plate_frame, textvariable=self.detected_plate, style="Plate.TLabel").grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)

        # --- Parking Records (Treeview) ---
        records_frame = ttk.Frame(self.master, padding="10 10 10 10", relief="groove")
        records_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        ttk.Label(records_frame, text="Parking Records:", style="Header.TLabel").pack(anchor=tk.W, pady=5)

        columns = ('no', 'entry_time', 'exit_time', 'car_plate', 'due_payment', 'payment_status')
        self.records_tree = ttk.Treeview(records_frame, columns=columns, show='headings', height=8)
        for col in columns:
            self.records_tree.heading(col, text=col.replace('_', ' ').title())
            self.records_tree.column(col, width=100, anchor=tk.CENTER) # Adjust width as needed

        self.records_tree.column('entry_time', width=150)
        self.records_tree.column('exit_time', width=150)
        self.records_tree.column('car_plate', width=100)
        self.records_tree.column('due_payment', width=100)
        self.records_tree.column('payment_status', width=100)

        self.records_tree.pack(fill=tk.BOTH, expand=True)

        # --- APPLY TREEVIEW TAG CONFIGURATION HERE ---
        # Define tags for Treeview rows based on payment status directly on the treeview object
        self.records_tree_tags = {
            "paid": {"background": "#D4EDDA", "foreground": "#155724"}, # Light green, dark green text
            "unpaid": {"background": "#F8D7DA", "foreground": "#721C24"} # Light red, dark red text
        }
        self.records_tree.tag_configure("paid", **self.records_tree_tags["paid"])
        self.records_tree.tag_configure("unpaid", **self.records_tree_tags["unpaid"])
        # --- END OF TREEVIEW TAG CONFIGURATION ---

        # Scrollbar for Treeview
        scrollbar = ttk.Scrollbar(records_frame, orient=tk.VERTICAL, command=self.records_tree.yview)
        self.records_tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # --- System Log ---
        log_frame = ttk.Frame(self.master, padding="10 10 10 10", relief="groove")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        ttk.Label(log_frame, text="System Log:", style="Header.TLabel").pack(anchor=tk.W, pady=5)

        self.log_text = tk.Text(log_frame, wrap=tk.WORD, height=10, state=tk.DISABLED, font=("Consolas", 10))
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Scrollbar for log
        log_scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def start_backend_processes(self):
        # Function to run a script in a new subprocess
        def run_script(script_name):
            try:
                # Use `start` on Windows to open in a new console window
                if os.name == 'nt': # For Windows
                    subprocess.Popen(f"start python {script_name}", shell=True)
                else: # For Linux/macOS
                    subprocess.Popen(['python3', script_name])
            except Exception as e:
                self.log_to_ui(f"ERROR: Could not start {script_name}: {e}")

        # Start each script in a separate thread/process
        # It's better to manage these as separate processes to avoid GIL issues with CV2 and serial
        # and to ensure if one crashes, it doesn't bring down the UI.
        threading.Thread(target=run_script, args=('car_entry.py',)).start()
        threading.Thread(target=run_script, args=('car_exit.py',)).start()
        threading.Thread(target=run_script, args=('process_payment.py',)).start()
        self.system_status.set("Backend Running")
        self.log_to_ui("All backend scripts launched.")

    def log_to_ui(self, message):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{datetime.now().strftime('%H:%M:%S')} - {message}\n")
        self.log_text.see(tk.END) # Auto-scroll to bottom
        self.log_text.config(state=tk.DISABLED)

    def update_ui(self):
        # Read gate statuses
        try:
            with open(ENTRY_STATUS_FILE, 'r') as f:
                status = f.read().strip()
                self.entry_gate_status.set(status)
                if "Open" in status:
                    self.entry_status_label.config(foreground="green")
                elif "Closed" in status:
                    self.entry_status_label.config(foreground="orange")
                elif "Error" in status: # Catch system errors from entry script
                    self.entry_status_label.config(foreground="red")
                else: # e.g., "Gate Status Unknown", "System Offline"
                    self.entry_status_label.config(foreground="gray")
        except FileNotFoundError:
            self.entry_gate_status.set("Offline")
            self.entry_status_label.config(foreground="gray")

        try:
            with open(EXIT_STATUS_FILE, 'r') as f:
                status = f.read().strip()
                self.exit_gate_status.set(status)
                if "Open" in status:
                    self.exit_status_label.config(foreground="green")
                elif "Closed" in status:
                    self.exit_status_label.config(foreground="orange")
                elif "Denied" in status: # Catches "Access Denied" messages
                    self.exit_status_label.config(foreground="red")
                elif "Error" in status: # Catch system errors from exit script
                    self.exit_status_label.config(foreground="red")
                else:
                    self.exit_status_label.config(foreground="gray")
        except FileNotFoundError:
            self.exit_gate_status.set("Offline")
            self.exit_status_label.config(foreground="gray")

        # Read detected plate
        try:
            with open(DETECTED_PLATE_FILE, 'r') as f:
                self.detected_plate.set(f.read().strip())
        except FileNotFoundError:
            self.detected_plate.set("N/A")

        # Read and update parking records
        self.update_parking_records()

        # Read and update system log
        self.update_system_log()

        # Schedule next update
        self.master.after(1000, self.update_ui) # Update every 1 second

    def update_parking_records(self):
        # Clear existing entries
        for item in self.records_tree.get_children():
            self.records_tree.delete(item)

        try:
            with open(CSV_FILE, 'r', newline='') as f:
                reader = csv.reader(f)
                header = next(reader) # Skip header row
                self.parking_records_data = list(reader)
                # Display rows in reverse order to show latest entries first
                for row in reversed(self.parking_records_data):
                    # Determine tag based on payment_status
                    tag = "unpaid" if len(row) > 5 and row[5] == '0' else "paid"
                    self.records_tree.insert('', 'end', values=row, tags=(tag,))
        except FileNotFoundError:
            self.log_to_ui(f"ERROR: Parking records CSV not found: {CSV_FILE}")
        except Exception as e:
            self.log_to_ui(f"ERROR reading CSV: {e}")

    def update_system_log(self):
        # Read log file and append new lines
        try:
            with open(LOG_FILE, 'r') as f:
                current_log_content = self.log_text.get("1.0", tk.END).strip()
                full_log_content = f.read().strip()

                # Only update if there's new content
                if full_log_content != current_log_content:
                    self.log_text.config(state=tk.NORMAL)
                    self.log_text.delete("1.0", tk.END)
                    self.log_text.insert(tk.END, full_log_content + "\n")
                    self.log_text.see(tk.END)
                    self.log_text.config(state=tk.DISABLED)
        except FileNotFoundError:
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, "Log file not found.\n")
            self.log_text.config(state=tk.DISABLED)


def main():
    root = tk.Tk()
    app = ParkingSystemUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
